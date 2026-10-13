"""
Auditoria de INTEGRIDADE da Validação de Balancetes, condomínio a condomínio (só lê arquivos; não altera nada).

Parte A — a leitura fecha com o que o próprio arquivo imprime? (principal causa de "nenhum achado" falso)
  A1 avisos de verificar_extracao (soma dos lançamentos da conta x débito impresso no Resumo)
  A2 identidade de cada conta: saldo anterior + créditos - débitos = saldo final
  A3 cobertura: o que o formato permite verificar e o que não
  A4 leitura vazia (sem contas/lançamentos/receitas quando a cobertura diz que deveria haver)
Parte B — as regras pegam um defeito conhecido? (falso negativo): injeta defeitos sintéticos nos dados reais do mês e confere
  que o achado correspondente aparece (e que o mês real, sem defeito, não os tem por engano).
  B1 receita negativa   B2 pagamento sem identificação   B3 duas parcelas no mesmo mês
  B4 lançamento duplicado (checklist de gestor)   B5 compra em marketplace (checklist de gestor)

Uso: python scripts/auditoria_integridade_validacao.py [id1 id2 ...] [--meses N]
Saída: data/auditoria_integridade/resultado.jsonl (um registro por condomínio/mês) e resumo no terminal.
"""
import copy
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from conciliacao import config_validacao, pasta_prestacao  # noqa: E402
from conciliacao.demonstrativo_reader import _extrair_mes_ano  # noqa: E402
from conciliacao.regras_gerais.extratores import get_extrator  # noqa: E402
from conciliacao.regras_gerais.modelo import LancamentoDespesa, LinhaReceita  # noqa: E402
from conciliacao.regras_gerais.regras import aplicar_regras, verificar_extracao  # noqa: E402

TOL = 0.02


def _arquivos(pasta: Path) -> dict:
    arqs = {}
    for a in pasta.rglob("*"):
        if a.is_file() and a.suffix.lower() in (".pdf", ".xlsx", ".xls") and not a.name.lower().startswith(("valida", "logo")):
            ma = _extrair_mes_ano(a.name)
            if ma and (ma not in arqs or a.parent == pasta):
                arqs[ma] = a
    return arqs


def parte_a(d) -> list[str]:
    problemas = []
    for av in verificar_extracao(d):
        problemas.append("A1 " + av)
    for c in d.contas:
        if c.nome.upper().startswith("CONSOLIDADO"):
            continue
        if abs(c.saldo_anterior + c.creditos - c.debitos - c.saldo_atual) > TOL and any((c.saldo_anterior, c.creditos, c.debitos, c.saldo_atual)):
            problemas.append(f"A2 conta {c.nome}: saldo anterior {c.saldo_anterior:.2f} + créditos {c.creditos:.2f} - débitos {c.debitos:.2f} "
                             f"!= saldo final {c.saldo_atual:.2f} (diferença {c.saldo_anterior + c.creditos - c.debitos - c.saldo_atual:.2f})")
    cob = d.cobertura
    if cob.get("lancamentos") and not d.lancamentos:
        problemas.append("A4 cobertura diz que há lançamentos, mas nenhum foi lido")
    if cob.get("receitas") and not d.receitas:
        problemas.append("A4 cobertura diz que há receitas, mas nenhuma foi lida")
    if (cob.get("lancamentos") or cob.get("rendimentos")) and not d.contas:
        problemas.append("A4 nenhuma conta (Resumo/Posição Financeira) foi lida")
    return problemas


def _tipos(achados) -> dict:
    t: dict = {}
    for a in achados:
        t[a.tipo] = t.get(a.tipo, 0) + 1
    return t


def parte_b(d, regras_condo: dict) -> dict:
    """{teste: 'ok' | 'FALHOU: ...' | 'n/a: motivo'}"""
    cfg = {**(regras_condo or {}), "gestor": {}}
    base_ach, _ = aplicar_regras(d, None, cfg, historico=[])
    base = _tipos(base_ach)
    def _soma_itens(achados) -> dict:
        t: dict = {}
        for a in achados:
            if a.tipo == "observacao_gestor":
                t[a.detalhes.get("verificacao")] = t.get(a.detalhes.get("verificacao"), 0) + a.detalhes.get("total_itens", 0)
        return t

    base_g = _soma_itens(base_ach)
    res = {}
    conta = (d.contas[0].nome if d.contas else "ORDINÁRIA")
    cat = (d.lancamentos[0].categoria if d.lancamentos else "TESTE")
    cob = d.cobertura

    def rodar(mut, expect_tipo, nome, verif=None):
        x = copy.deepcopy(d)
        mut(x)
        ach, _ = aplicar_regras(x, None, cfg, historico=[])
        if verif:
            novo = _soma_itens(ach)
            res[nome] = "ok" if novo.get(verif, 0) > base_g.get(verif, 0) else f"FALHOU: '{verif}' não detectado"
        else:
            res[nome] = "ok" if _tipos(ach).get(expect_tipo, 0) > base.get(expect_tipo, 0) else f"FALHOU: '{expect_tipo}' não detectado"

    if cob.get("receitas"):
        rodar(lambda x: x.receitas.append(LinhaReceita(conta=conta, descricao="MUTACAO RECEITA DE TESTE", valor=-123.45, tipo="outra")),
              "receita_negativa", "B1_receita_negativa")
    else:
        res["B1_receita_negativa"] = "n/a: formato sem linhas de receita"
    if cob.get("lancamentos"):
        rodar(lambda x: x.lancamentos.append(LancamentoDespesa(descricao="", valor=500.0, categoria=cat, conta=conta, data="10/01/2026")),
              "pagamento_sem_identificacao", "B2_sem_identificacao")
        rodar(lambda x: x.lancamentos.extend([
            LancamentoDespesa(descricao="MUTACAO FORNECEDOR TESTE LTDA NF 91 PARC 01/03", valor=300.0, categoria=cat, conta=conta, data="10/01/2026"),
            LancamentoDespesa(descricao="MUTACAO FORNECEDOR TESTE LTDA NF 91 PARC 02/03", valor=300.0, categoria=cat, conta=conta, data="11/01/2026")]),
            "parcelas_mesmo_mes", "B3_parcelas_mesmo_mes")
        rodar(lambda x: x.lancamentos.extend([
            LancamentoDespesa(descricao="MUTACAO MANUTENCAO PREDIAL NF 7777 TESTE", valor=777.77, categoria=cat, conta=conta, data="12/01/2026"),
            LancamentoDespesa(descricao="MUTACAO MANUTENCAO PREDIAL NF 7777 TESTE", valor=777.77, categoria=cat, conta=conta, data="12/01/2026")]),
            None, "B4_duplicidade_no_mes", verif="duplicidade_no_mes")
        rodar(lambda x: x.lancamentos.append(LancamentoDespesa(descricao="MERCADO PAGO COMPRA TESTE", valor=250.0, categoria=cat, conta=conta, data="12/01/2026")),
              None, "B5_marketplace", verif="compra_marketplace")
    else:
        for k in ("B2_sem_identificacao", "B3_parcelas_mesmo_mes", "B4_duplicidade_no_mes", "B5_marketplace"):
            res[k] = "n/a: formato não lista lançamentos individuais"
    return res


def main():
    args = sys.argv[1:]
    n_meses = 3
    if "--meses" in args:
        i = args.index("--meses")
        n_meses = int(args[i + 1])
        del args[i:i + 2]
    saida = RAIZ / "data" / "auditoria_integridade"
    saida.mkdir(parents=True, exist_ok=True)
    arq_saida = saida / "resultado.jsonl"
    feitos = set()
    if arq_saida.exists() and not args:
        for linha in arq_saida.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(linha)
                feitos.add((r["id"], r["mes"]))
            except Exception:
                pass
    with open(arq_saida, "a", encoding="utf-8") as fo:
        for c in json.load(open(RAIZ / "config/condominios.json", encoding="utf-8"))["condominios"]:
            if not c.get("ativo", True) or c["id"] == "demonstracao" or (args and c["id"] not in args):
                continue
            condo = config_validacao.aplicar(c)
            ex = get_extrator(condo)
            pasta = pasta_prestacao.pasta_do_condominio(condo)
            if ex is None or pasta is None:
                fo.write(json.dumps({"id": c["id"], "mes": None, "erro": "sem leitor das regras gerais ou sem pasta do projeto"}, ensure_ascii=False) + "\n")
                fo.flush()
                print(c["id"], "SEM LEITOR/PASTA", flush=True)
                continue
            arqs = _arquivos(pasta)
            for (m, a) in sorted(arqs, key=lambda k: (k[1], k[0]), reverse=True)[:n_meses]:
                mes = f"{a}-{m:02d}"
                if (c["id"], mes) in feitos:
                    continue
                t0 = time.time()
                reg = {"id": c["id"], "mes": mes, "arquivo": arqs[(m, a)].name, "formato": arqs[(m, a)].suffix.lower()}
                try:
                    d = ex.extrair(arqs[(m, a)], mes)
                    reg.update(cobertura=d.cobertura, n_contas=len(d.contas), n_lancamentos=len(d.lancamentos), n_receitas=len(d.receitas),
                               problemas_leitura=parte_a(d), mutacoes=parte_b(d, condo.get("regras")))
                except Exception as e:
                    reg["erro"] = f"{type(e).__name__}: {str(e)[:200]}"
                reg["seg"] = round(time.time() - t0)
                fo.write(json.dumps(reg, ensure_ascii=False) + "\n")
                fo.flush()
                falhas = [k for k, v in (reg.get("mutacoes") or {}).items() if str(v).startswith("FALHOU")]
                print(f"{c['id']:30s} {mes} leitura={len(reg.get('problemas_leitura') or [])} mutacoes_falhas={falhas} {reg.get('erro', '')} {reg['seg']}s", flush=True)


if __name__ == "__main__":
    main()
