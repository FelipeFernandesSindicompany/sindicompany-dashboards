"""
Extrator das regras gerais — Serra da Mantiqueira (Edifício Serra da Mantiqueira; administradora FL Condomínios,
sistema Consvicta "W0xx"). Cadastrado como datadigitus_pdf no condominios.json, mas o PDF é da FL Condomínios (família
Consvicta, ~21-26 páginas, texto extraível) — NÃO é DataDigitus.

Telas usadas (14 meses, mai/2025-jun/2026; nenhum PDF anterior a mai/2025):
  W020A  "Demonstrativo Analítico "<GRUPO DE SALDO>"" — um bloco por grupo de saldo (ORDINÁRIO, FUNDO DE RESERVA, PROVISÃO 13º SALÁRIO
         E FÉRIAS, FUNDO DE OBRAS, DESPESAS TRABALHISTAS, CONCILIAÇÃO BANCÁRIA), cada um com:
           Receitas  (Competência | Liquidação | Valor): OPERACIONAIS/EMERGENCIAIS... > CONDOMINIO, JUROS, MULTAS... > linhas
                     "N cobranças [histórico] competência liquidação % valor" (agrupadas por data de liquidação); valor com sinal.
           Despesas  (Liquidação | Documento | Forma de Pgto. | Valor): DESPESAS OPERACIONAIS > PESSOAL ORGANICO > SALARIO > FOLHA LIQUIDA >
                     linhas "FORNECEDOR histórico  liquidação  NF-xxx  forma  % valor"; linhas que quebram continuam na margem.
         Cada grupo de saldo é uma CONTA das regras (`conta`).
  Resumo "Grupos de saldo" (pág. 13): Saldo ant., Créditos*, Débitos*, Saldo final por grupo ("(*) inclui transferência entre grupos").
`categoria` do lançamento = "<nível 2> > <subconta folha>" (ex.: "PESSOAL ORGANICO > FOLHA LIQUIDA"; quando a folha é o próprio nível 2, só ele).
Conferências (viram `avisos`): Σ lançamentos e Σ receitas de cada grupo == "Total de DESPESAS"/"Total de RECEITAS" do bloco == Débitos/Créditos
do grupo no resumo.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.extratores.top_nine import (_CENT, _linhas, _marca_parcela, _norm, _num, _texto,
                                                           aplicar_config_receitas_negativas)
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_RE_PCT_TITULO = re.compile(r"\(\s*\d+,\d+\s*%\s*\)")


def _tipo_receita(nome2: str, nome1: str = "") -> str:
    n = _norm(nome2 + " " + nome1)
    if "RENDIMENTO" in n:
        return "rendimento"
    if "JUROS" in n or "MULTA" in n or "ATUALIZACAO" in n:
        return "multa_juros"
    if "CONDOMINIO" in n or "FUNDO DE" in n or "GAS" in n or "AGUA" in n or "RATEIO" in n:
        return "cota"
    return "outra"


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        doc = fitz.open(str(caminho))
        totais: dict = {}
        try:
            contas = self._resumo(doc)
            self._blocos(doc, dados, totais)
        finally:
            doc.close()
        por_nome = {_norm(c.nome): c for c in contas}
        for r in dados.receitas:
            if r.tipo == "rendimento":
                c = por_nome.get(_norm(r.conta))
                if c is not None:
                    c.rendimento = round(c.rendimento + r.valor, 2)
        dados.contas = contas
        self._conferir(dados, contas, totais)
        com_rend = [c for c in contas if abs(c.rendimento) > _CENT]
        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": len(com_rend) >= 2, "lancamentos": bool(dados.lancamentos)}
        if not dados.receitas:
            dados.motivos_nao_cobertos["receitas"] = "nenhum bloco 'Demonstrativo Analítico' (W020A) com receitas encontrado neste PDF"
        if not dados.lancamentos:
            dados.motivos_nao_cobertos["lancamentos"] = "nenhum bloco 'Demonstrativo Analítico' (W020A) com despesas encontrado neste PDF"
        if not dados.cobertura["rendimentos"]:
            quais = ", ".join(f"{c.nome} {c.rendimento:,.2f}" for c in com_rend) or "nenhum"
            dados.motivos_nao_cobertos["rendimentos"] = (
                f"o rendimento de aplicação ('RENDIMENTO DE APLICACAO', centavos) é creditado apenas em um grupo de saldo ({quais}); os demais "
                "grupos (fundos de reserva/obras, provisão de 13º) não recebem rendimento no arquivo — não há distribuição a conferir")
        aplicar_config_receitas_negativas(dados, self.condo)
        return dados

    # ── resumo "Grupos de saldo" ─────────────────────────────────────────────
    def _resumo(self, doc) -> list:
        contas: list[ContaMes] = []
        for i in range(len(doc)):
            txt = doc[i].get_text()
            if "Grupos de saldo" not in txt:
                continue
            em = False
            for yc, ws in _linhas(doc[i]):
                tn = _norm(_texto(ws))
                if tn.startswith("GRUPOS DE SALDO"):
                    em = True
                    continue
                if not em:
                    continue
                if tn.startswith("SALDO FINAL"):
                    break
                nums = [_num(w[4]) for w in ws if _num(w[4]) is not None]
                nome = " ".join(w[4] for w in ws if _num(w[4]) is None).strip()
                if len(nums) == 4 and nome:
                    contas.append(ContaMes(nome=nome, saldo_anterior=nums[0], creditos=nums[1], debitos=abs(nums[2]),
                                           saldo_atual=nums[3], pagina=i + 1))
            break
        return contas

    # ── blocos W020A ─────────────────────────────────────────────────────────
    def _blocos(self, doc, dados, totais):
        conta = None
        secao = None            # "receitas" | "despesas"
        nivel1 = nivel2 = folha = ""
        cur = None
        for i in range(len(doc)):
            txt = doc[i].get_text()
            m = re.search(r'Demonstrativo Anal[íi]tico\s+"([^"]+)"', txt)
            if m:
                conta = m.group(1).strip()
                secao, nivel1, nivel2, folha, cur = None, "", "", "", None
            if conta is None:
                continue
            # os blocos W020A terminam no "Resumo Financeiro"/"Grupos de saldo" (sem código W0xx no topo) ou numa tela W020I/W037/W002C...
            if not m and (re.search(r"\bW0\d\d[B-Z]\b|\bW020[B-Z]\b", txt[:200]) or re.search(r"Resumo Financeiro|Grupos de saldo", txt[:700])):
                break
            for yc, ws in _linhas(doc[i]):
                if yc < 18 or yc > 770:
                    continue
                t = _texto(ws)
                tn = _norm(t)
                x0 = ws[0][0]
                valor_tok = next((w for w in reversed(ws) if _num(w[4]) is not None and w[0] > 470), None)
                if tn.startswith("MOV LIQUIDO"):
                    secao, cur = None, None                      # acabou o demonstrativo do grupo
                    continue
                if tn.startswith("TRANSFERENCIAS ENTRE GRUPOS"):
                    secao, cur = "transferencias", None          # "De X para Y"/"Para X de Y": movimento entre grupos, não é receita nem despesa
                    continue
                if tn.startswith(("EMITIDO EM", "W020A", "DEMONSTRATIVO ANALITICO", "ENTRE ", "DESPESA COM", "SALDO EM")):
                    if tn.startswith("SALDO EM"):
                        secao = None
                    continue
                if secao == "transferencias":
                    if valor_tok is not None:
                        totais.setdefault("transferencias", []).append((conta, _num(valor_tok[4])))
                    continue
                if tn.startswith("RECEITAS COMPETENCIA"):
                    secao, nivel1, nivel2, folha, cur = "receitas", "", "", "", None
                    continue
                if tn.startswith("DESPESAS LIQUIDACAO"):
                    secao, nivel1, nivel2, folha, cur = "despesas", "", "", "", None
                    continue
                sem_valores = _norm(" ".join(w[4] for w in ws if _num(w[4]) is None and not w[4].endswith("%")))
                if sem_valores == "TOTAL DE RECEITAS" and valor_tok is not None:
                    # "Total de RECEITAS 100,00% <período> <acumulado>": o 1º valor é o do período
                    vals = [_num(w[4]) for w in ws if _num(w[4]) is not None]
                    totais.setdefault("receitas_conta", {})[_norm(conta)] = vals[0] if vals else None
                    cur = None
                    continue
                if sem_valores == "TOTAL DE DESPESAS" and valor_tok is not None:
                    totais.setdefault("despesas_conta", {})[_norm(conta)] = _num(valor_tok[4])
                    cur = None
                    continue
                if tn.startswith("TOTAL DE"):
                    cur = None
                    continue
                if secao is None:
                    continue
                if valor_tok is not None:
                    cur = self._linha(ws, valor_tok, secao, conta, nivel1, nivel2, folha, i + 1, dados)
                    continue
                if (x0 < 36 or x0 >= 100) and cur is not None:    # continuação de linha que quebrou (margem, ou resto de coluna: "...-51")
                    cur["tokens"].extend(w[4] for w in ws)
                    self._atualiza(cur)
                    continue
                cur = None
                if _RE_PCT_TITULO.search(t):
                    nivel1, nivel2, folha = re.sub(_RE_PCT_TITULO, "", t).strip(), "", ""
                elif 42 <= x0 < 50:
                    nivel2, folha = t.strip(), t.strip()
                else:
                    folha = t.strip()

    def _linha(self, ws, vt, secao, conta, nivel1, nivel2, folha, pagina, dados):
        # colunas (x0): histórico < 235/275 | [receitas: competência 280, liquidação 345] [despesas: liquidação 240, documento 293, forma 355] | % | valor
        lim = 275 if secao == "receitas" else 235
        corpo = [w for w in ws if w is not vt and not w[4].endswith("%")]
        desc = [w[4] for w in corpo if w[0] < lim]
        extra = [w for w in corpo if w[0] >= lim]
        categoria = nivel2 if (not folha or _norm(folha) == _norm(nivel2)) else (f"{nivel2} > {folha}" if nivel2 else folha)
        categoria = categoria or nivel1
        bbox = (ws[0][0], min(w[1] for w in ws), vt[2], max(w[3] for w in ws))
        cur = {"tokens": desc, "secao": secao, "valor": _num(vt[4]), "cat": categoria, "nivel1": nivel1, "doc": "", "data": None, "comp": None}
        datas = [w[4] for w in extra if re.fullmatch(r"\d{2}/\d{2}/\d{4}", w[4])]
        if secao == "receitas":
            cur["data"] = datas[0] if datas else None
            cur["comp"] = next((w[4] for w in extra if re.fullmatch(r"\d{2}/\d{4}", w[4]) or w[4].lower() == "acordo"), None)
            cur["obj"] = LinhaReceita(conta=conta, descricao="", valor=cur["valor"], tipo=_tipo_receita(nivel2 or folha, nivel1),
                                      data=cur["data"], pagina=pagina, bbox=bbox)
            dados.receitas.append(cur["obj"])
        else:
            cur["data"] = datas[0] if datas else None
            cur["doc"] = " ".join(w[4] for w in extra if 280 <= w[0] < 350 and w[4] not in datas)
            cur["obj"] = LancamentoDespesa(descricao="", valor=cur["valor"], categoria=categoria, conta=conta, data=cur["data"],
                                           pagina=pagina, bbox=bbox)
            dados.lancamentos.append(cur["obj"])
        self._atualiza(cur)
        return cur

    @staticmethod
    def _atualiza(cur):
        texto = re.sub(r"\s+", " ", " ".join(cur["tokens"])).strip()
        if cur["secao"] == "receitas":
            sufixo = f" (comp. {cur['comp']})" if cur["comp"] else ""
            cur["obj"].descricao = f"{cur['cat']}: {texto}{sufixo}".strip()
        else:
            cur["obj"].descricao = _marca_parcela(f"{texto} {cur['doc']}".strip())

    # ── conferências ─────────────────────────────────────────────────────────
    def _conferir(self, dados, contas, totais):
        transf = totais.get("transferencias", [])
        if transf:
            dados.avisos.append(f"{len(transf)} transferência(s) entre grupos de saldo (R$ {sum(abs(v) for _, v in transf) / 2:,.2f} movimentados) "
                                "estão no demonstrativo e foram ignoradas: não são receita nem despesa")
        for c in contas:
            s_l = round(sum(l.valor for l in dados.lancamentos if _norm(l.conta) == _norm(c.nome)), 2)
            s_r = round(sum(r.valor for r in dados.receitas if _norm(r.conta) == _norm(c.nome)), 2)
            td = totais.get("despesas_conta", {}).get(_norm(c.nome))
            tr = totais.get("receitas_conta", {}).get(_norm(c.nome))
            if (td is not None and abs(s_l - td) > _CENT) or (td is None and s_l > _CENT):
                dados.avisos.append(f"grupo {c.nome}: Σ lançamentos lidos ({s_l:,.2f}) difere do 'Total de DESPESAS' do bloco ({td if td is None else f'{td:,.2f}'})")
            if (tr is not None and abs(s_r - tr) > _CENT) or (tr is None and abs(s_r) > _CENT):
                dados.avisos.append(f"grupo {c.nome}: Σ receitas lidas ({s_r:,.2f}) difere do 'Total de RECEITAS' do bloco ({tr if tr is None else f'{tr:,.2f}'})")
            # o resumo "(*) inclui transferência entre grupos": entradas somam nos Créditos*, saídas nos Débitos*
            t_in = round(sum(v for g, v in transf if _norm(g) == _norm(c.nome) and v > 0), 2)
            t_out = round(sum(-v for g, v in transf if _norm(g) == _norm(c.nome) and v < 0), 2)
            if abs(s_l + t_out - c.debitos) > _CENT:
                dados.avisos.append(f"grupo {c.nome}: Σ lançamentos ({s_l:,.2f}) + transferências de saída ({t_out:,.2f}) difere dos Débitos* do resumo ({c.debitos:,.2f})")
            if abs(s_r + t_in - c.creditos) > _CENT:
                dados.avisos.append(f"grupo {c.nome}: Σ receitas ({s_r:,.2f}) + transferências de entrada ({t_in:,.2f}) difere dos Créditos* do resumo ({c.creditos:,.2f})")
