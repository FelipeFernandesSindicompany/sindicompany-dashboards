"""
Auditoria de integridade dos dashboards: re-extrai cada mês a partir dos
PDFs/XLSXs originais (pasta_prestacao no OneDrive) e compara com os valores
do var BAL em cada HTML.

Campos comparados: tAnt, tCred, tDeb, tAtual, inad, inadProc, prev, real, tDesp

Tolerância: R$ 1,00 por campo (arredondamentos de centavos são esperados).

Resultado gravado em output/audit_dashboards_YYYYMMDD.txt
"""

import sys
import os
import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from conciliacao.bal_reader import listar_meses_disponiveis, ler_bal_mes, MESES_NUM
from conciliacao.demonstrativo_reader import localizar_arquivo_mes
from adapters import get_adapter

PROJECTS_DIR = None   # Determinado em runtime (pasta_prestacao.py)
TOLERANCIA = 1.0      # R$ 1,00
SKIP_ZERO   = True    # Ignorar entradas do BAL onde tAtual == 0 (meses vazios/placeholder)

# Campos CRÍTICOS: comparados sempre (erros aqui = dado errado no dashboard)
CAMPOS_CRITICOS = [
    ("tAnt",   "Saldo Anterior"),
    ("tCred",  "Total Créditos"),
    ("tDeb",   "Total Débitos"),
    ("tAtual", "Saldo Atual"),
]

# Campos SECUNDÁRIOS: só reportados quando o HTML já tinha valor não-zero
# (metodologia pode diferir entre épocas, não são erros automáticos)
CAMPOS_SECUNDARIOS = [
    ("inad",     "Inadimplência"),
    ("inadProc", "Inad. Recebida"),
    ("prev",     "Previsto"),
    ("real",     "Realizado"),
]

MESES_ABREV = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]


def _chave_para_mes_ano(chave: str) -> tuple[int, int]:
    """'jul26' -> (7, 2026)"""
    abrev = chave[:3]
    ano_2d = int(chave[3:])
    mes = MESES_NUM[abrev]
    ano = 2000 + ano_2d
    return mes, ano


def _mes_ano_para_str(mes: int, ano: int) -> str:
    """(7, 2026) -> '2026-07'"""
    return f"{ano}-{mes:02d}"


def raiz_prestacoes() -> Path | None:
    """Encontra a raiz das pastas de prestação de contas (igual ao pasta_prestacao.py)."""
    candidatos: list[Path] = []
    if os.environ.get("SINDICOMPANY_PRESTACOES_RAIZ"):
        candidatos.append(Path(os.environ["SINDICOMPANY_PRESTACOES_RAIZ"]))
    config_local = ROOT / "data" / "config_local.json"
    try:
        valor = json.loads(config_local.read_text(encoding="utf-8")).get("pasta_prestacoes_raiz")
        if valor:
            candidatos.append(Path(valor))
    except (OSError, ValueError):
        pass
    candidatos += sorted(Path.home().glob("OneDrive*/Documentos/Claude/Projects"))
    return next((c for c in candidatos if c.is_dir()), None)


def carregar_config_validacao() -> dict:
    """Lê config/validacao_balancetes.json e devolve {condo_id: {...}}."""
    path = ROOT / "config" / "validacao_balancetes.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("condominios", {})
    return {}


def obter_dados_adapter(condo: dict, arquivo: Path, mes_str: str) -> dict | None:
    """Executa o adapter e converte DadosFinanceiros -> dict (mesma lógica de dados_para_bal)."""
    try:
        adapter = get_adapter(condo["empresa_gestora"], condo)
        ext = arquivo.suffix.lower()
        if ext in (".pdf", ".PDF"):
            dados = adapter.ler_pdf(arquivo, mes_str)
        else:
            dados = adapter.ler_xlsx(arquivo, mes_str)

        # prev / real: mesma lógica de dados_para_bal em injetar_mes.py
        prev = dados.receita_prevista if dados.receita_prevista > 0 else dados.receita_realizada
        receita_cotas = getattr(dados, "receita_cotas", 0.0)
        real = receita_cotas if receita_cotas > 0 else dados.receita_realizada
        # inadProc usa inadimplencia_recebida (campo que grava o inad já quitado)
        inad_proc = getattr(dados, "inadimplencia_recebida", 0.0)

        return {
            "tAnt":     dados.saldo_anterior,
            "tCred":    dados.receita_realizada,
            "tDeb":     dados.despesa_total,
            "tAtual":   dados.saldo_atual,
            "inad":     dados.inadimplencia_valor,
            "inadProc": inad_proc,
            "prev":     prev,
            "real":     real,
        }
    except Exception as e:
        return {"_erro": str(e)}


def formatar_dif(campo, val_html, val_adp):
    dif = abs(val_html - val_adp)
    if dif <= TOLERANCIA:
        return None  # OK
    sinal = "↑" if val_adp > val_html else "↓"
    return f"  {campo:12s}: HTML={val_html:>12,.2f}  ADP={val_adp:>12,.2f}  Δ={sinal}{dif:,.2f}"


def auditar_condo(cond: dict, cfg_val: dict, raiz: Path, linhas: list,
                  desde: tuple[int, int] | None = None) -> dict:
    """Audita todos os meses de um condomínio. Retorna stats."""
    cid = cond["id"]
    nome = cond["nome"]
    html_path = ROOT / "docs" / cond.get("html_file", "")

    cfg_este = cfg_val.get(cid, {})
    pasta_nome = cfg_este.get("pasta_prestacao") or cond.get("pasta_prestacao", "")

    linhas.append(f"\n{'='*70}")
    linhas.append(f"  {nome}  [{cid}]  —  {cond.get('empresa_gestora','?')}")
    linhas.append(f"{'='*70}")

    if not html_path.exists():
        linhas.append(f"  [SKIP] HTML não encontrado: {html_path.name}")
        return {"ok": 0, "dif": 0, "skip": 0, "sem_arq": 0, "avs": 0}

    meses = listar_meses_disponiveis(html_path)
    if not meses:
        linhas.append("  [SKIP] Nenhum mês no BAL.")
        return {"ok": 0, "dif": 0, "skip": 0, "sem_arq": 0, "avs": 0}

    pasta = raiz / pasta_nome if pasta_nome else None
    if pasta and not pasta.is_dir():
        pasta = None

    stats = {"ok": 0, "dif": 0, "skip": 0, "sem_arq": 0, "avs": 0}

    for chave in sorted(meses, key=lambda k: (int(k[3:]), MESES_NUM[k[:3]])):
        # Filtro de data mínima (--desde)
        if desde is not None:
            mes_c, ano_c = _chave_para_mes_ano(chave)
            desde_mes, desde_ano = desde
            if (ano_c, mes_c) < (desde_ano, desde_mes):
                stats["skip"] += 1
                continue

        try:
            bal = ler_bal_mes(html_path, chave)
        except Exception as e:
            linhas.append(f"  {chave}  [PARSE ERR] {str(e)[:80]}")
            stats["skip"] += 1
            continue
        if bal is None:
            continue

        # Pula meses totalmente zerados (placeholder)
        if SKIP_ZERO and bal.get("tAtual", 0) == 0 and bal.get("tCred", 0) == 0:
            linhas.append(f"  {chave}  [SKIP] Entrada zerada no BAL")
            stats["skip"] += 1
            continue

        mes, ano = _chave_para_mes_ano(chave)
        mes_str = _mes_ano_para_str(mes, ano)

        # Localizar arquivo fonte
        arquivo = None
        if pasta:
            arquivo = localizar_arquivo_mes(pasta, mes, ano)

        if arquivo is None:
            linhas.append(f"  {chave}  [SEM ARQUIVO] Não encontrado em {pasta.name if pasta else '(pasta não configurada)'}")
            stats["sem_arq"] += 1
            continue

        # Re-extrair via adapter
        adp = obter_dados_adapter(cond, arquivo, mes_str)
        if "_erro" in adp:
            linhas.append(f"  {chave}  [ERRO ADAPTER] {adp['_erro'][:120]}")
            stats["dif"] += 1
            continue

        # Comparar campos críticos (sempre)
        diferencas = []
        avisos = []
        for campo, _label in CAMPOS_CRITICOS:
            val_html = bal.get(campo, 0) or 0
            val_adp  = adp.get(campo, 0) or 0
            d = formatar_dif(campo, val_html, val_adp)
            if d:
                diferencas.append(d)

        # Campos secundários: só reportar quando HTML tinha valor != 0
        for campo, _label in CAMPOS_SECUNDARIOS:
            val_html = bal.get(campo, 0) or 0
            val_adp  = adp.get(campo, 0) or 0
            if val_html == 0:
                continue  # Campo não foi preenchido na época, pula
            d = formatar_dif(campo, val_html, val_adp)
            if d:
                avisos.append(f"  [AVS] {d.strip()}")

        # Verificação de consistência interna (BAL): tAnt + tCred - tDeb ≈ tAtual
        tAnt = bal.get("tAnt", 0) or 0
        tCred = bal.get("tCred", 0) or 0
        tDeb  = bal.get("tDeb", 0) or 0
        tAtual = bal.get("tAtual", 0) or 0
        consistencia = abs(tAnt + tCred - tDeb - tAtual)
        if consistencia > TOLERANCIA:
            diferencas.append(f"  {'[CONSISTÊNCIA]':12s}: tAnt+tCred-tDeb={tAnt+tCred-tDeb:,.2f} ≠ tAtual={tAtual:,.2f}  Δ={consistencia:,.2f}")

        if diferencas:
            linhas.append(f"  {chave}  [DIV]  {arquivo.name}")
            linhas.extend(diferencas)
            if avisos:
                linhas.extend(avisos)
            stats["dif"] += 1
        elif avisos:
            linhas.append(f"  {chave}  [AVS]  {arquivo.name}")
            linhas.extend(avisos)
            stats["avs"] += 1
        else:
            linhas.append(f"  {chave}  [OK]   {arquivo.name}")
            stats["ok"] += 1

    return stats


def main():
    raiz = raiz_prestacoes()
    if raiz is None:
        print("[ERRO] Pasta de prestações de contas não encontrada.")
        sys.exit(1)
    print(f"Raiz das prestações: {raiz}")

    cfg_val = carregar_config_validacao()

    with open(ROOT / "config" / "condominios.json", encoding="utf-8") as f:
        config = json.load(f)
    condos = [c for c in config["condominios"] if c.get("ativo", True)]

    # Filtros via argumentos: [condo_filtro] [--desde YYYY-MM]
    filtro = None
    desde = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--desde" and i + 1 < len(args):
            partes = args[i + 1].split("-")
            desde = (int(partes[1]), int(partes[0]))  # (mes, ano)
            i += 2
        elif not args[i].startswith("--"):
            filtro = args[i].lower()
            i += 1
        else:
            i += 1
    if filtro:
        condos = [c for c in condos if filtro in c["id"].lower() or filtro in c["nome"].lower()]
    if desde:
        print(f"Filtrando a partir de {desde[1]:04d}-{desde[0]:02d}")

    linhas = []
    linhas.append(f"AUDITORIA DE DASHBOARDS — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    linhas.append(f"Raiz: {raiz}")
    linhas.append(f"Total condomínios: {len(condos)}")

    total = {"ok": 0, "avs": 0, "dif": 0, "skip": 0, "sem_arq": 0}

    for i, cond in enumerate(condos, 1):
        print(f"[{i}/{len(condos)}] {cond['nome']}...", end="  ", flush=True)
        s = auditar_condo(cond, cfg_val, raiz, linhas, desde=desde)
        for k in total:
            total[k] += s[k]
        print(f"OK={s['ok']} AVS={s['avs']} DIV={s['dif']} SEM={s['sem_arq']} skip={s['skip']}")

    linhas.append(f"\n{'='*70}")
    linhas.append("RESUMO FINAL")
    linhas.append(f"{'='*70}")
    linhas.append(f"  OK (sem divergência):      {total['ok']}")
    linhas.append(f"  AVISO (campo secundario):  {total['avs']}")
    linhas.append(f"  COM DIVERGENCIA CRITICA:   {total['dif']}")
    linhas.append(f"  SEM ARQUIVO FONTE:         {total['sem_arq']}")
    linhas.append(f"  PULADOS (zeros):           {total['skip']}")

    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    dt = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"audit_dashboards_{dt}.txt"
    out_path.write_text("\n".join(linhas), encoding="utf-8")
    print(f"\nRelatorio gravado: {out_path}")
    print(f"OK={total['ok']}  AVS={total['avs']}  DIV={total['dif']}  SEM_ARQ={total['sem_arq']}  SKIP={total['skip']}")


if __name__ == "__main__":
    main()
