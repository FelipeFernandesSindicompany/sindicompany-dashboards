"""
Motor de injeção mensal.

Lê o XLSX/PDF de um condomínio, converte para o bloco BAL e injeta no HTML existente.

Uso:
  python scripts/injetar_mes.py --condominio alvorada --mes 2026-05 --xlsx caminho/arquivo.xlsx
  python scripts/injetar_mes.py --todos --mes 2026-05  (processa todos com arquivo na pasta data/)
"""
import argparse, json, re, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

HTML_DIR = ROOT / "docs"

# Garante UTF-8 no terminal Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── Helpers de mês ─────────────────────────────────────────────────────────

MESES_ABREV = {
    1:"jan", 2:"fev", 3:"mar", 4:"abr", 5:"mai", 6:"jun",
    7:"jul", 8:"ago", 9:"set", 10:"out", 11:"nov", 12:"dez",
}
MESES_FULL = {
    1:"Janeiro", 2:"Fevereiro", 3:"Março", 4:"Abril",
    5:"Maio", 6:"Junho", 7:"Julho", 8:"Agosto",
    9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro",
}

def mes_chave(mes_str: str) -> str:
    """'2026-05' → 'mai26'"""
    dt = datetime.strptime(mes_str, "%Y-%m")
    return f"{MESES_ABREV[dt.month]}{str(dt.year)[2:]}"

def mes_titulo(mes_str: str) -> str:
    """'2026-05' → 'Maio / 2026'"""
    dt = datetime.strptime(mes_str, "%Y-%m")
    return f"{MESES_FULL[dt.month]} / {dt.year}"

def mes_periodo(mes_str: str) -> str:
    """'2026-05' → '01/05/2026 a 31/05/2026'"""
    import calendar
    dt = datetime.strptime(mes_str, "%Y-%m")
    ultimo = calendar.monthrange(dt.year, dt.month)[1]
    return f"01/{dt.month:02d}/{dt.year} a {ultimo}/{dt.month:02d}/{dt.year}"

def mes_evo_label(mes_str: str) -> str:
    """'2026-05' → 'Mai/26'"""
    dt = datetime.strptime(mes_str, "%Y-%m")
    return f"{MESES_FULL[dt.month][:3]}/{str(dt.year)[2:]}"


# ── Conversão DadosFinanceiros → bloco BAL ─────────────────────────────────

def dados_para_bal(dados, mes_str: str) -> dict:
    """
    Converte DadosFinanceiros (do adapter) para o dict no formato BAL
    que os HTMLs reais esperam.
    """
    from adapters.base import DadosFinanceiros

    # tDesp = total usado para % nas despesas (soma das categorias, == total ordinária)
    t_desp = round(sum(dados.categorias_despesa.values()), 2) or round(dados.despesa_total, 2)

    bloco = {
        "tit":    mes_titulo(mes_str),
        "per":    mes_periodo(mes_str),
        "tAnt":   round(dados.saldo_anterior, 2),
        "tCred":  round(dados.receita_realizada, 2),
        "tDeb":   round(dados.despesa_total, 2),
        "tAtual": round(dados.saldo_atual, 2),
        "tDesp":  t_desp,
        "inad":   round(dados.inadimplencia_valor, 2),
        "inadProc": 0,
        "banco":  {"cc": round(dados.saldo_atual, 2), "cdb": 0.0, "priv": 0.0},
        "contas": [{"n": "ORDINÁRIA", "a": round(dados.saldo_anterior, 2),
                    "c": round(dados.receita_realizada, 2),
                    "d": round(dados.despesa_total, 2),
                    "s": round(dados.saldo_atual, 2)}],
        "desp": [
            {"c": cat.upper(), "v": round(val, 2)}
            for cat, val in sorted(
                dados.categorias_despesa.items(),
                key=lambda x: x[1], reverse=True
            )
        ],
    }
    return bloco


# ── Injeção no HTML ────────────────────────────────────────────────────────

def bal_para_js(bloco: dict, chave: str, indent: int = 4) -> str:
    """Serializa o bloco como JavaScript formatado."""
    pad = " " * indent
    linhas = [f"{pad}{chave}: {{"]
    linhas.append(f"{pad}  tit: {json.dumps(bloco['tit'], ensure_ascii=False)},")
    linhas.append(f"{pad}  per: {json.dumps(bloco['per'], ensure_ascii=False)},")
    linhas.append(f"{pad}  tAnt: {bloco['tAnt']},")
    linhas.append(f"{pad}  tCred: {bloco['tCred']},")
    linhas.append(f"{pad}  tDeb: {bloco['tDeb']},")
    linhas.append(f"{pad}  tAtual: {bloco['tAtual']},")
    linhas.append(f"{pad}  tDesp: {bloco['tDesp']},")
    linhas.append(f"{pad}  inad: {bloco['inad']},")
    linhas.append(f"{pad}  inadProc: {bloco['inadProc']},")

    # contas
    contas_js = ", ".join(
        "{{n:{n}, a:{a}, c:{c}, d:{d}, s:{s}}}".format(
            n=json.dumps(c["n"], ensure_ascii=False),
            a=c["a"], c=c["c"], d=c["d"], s=c["s"]
        ) for c in bloco["contas"]
    )
    linhas.append(f"{pad}  contas: [{contas_js}],")

    # desp
    desp_js = ", ".join(
        "{{c:{c}, v:{v}}}".format(
            c=json.dumps(d["c"], ensure_ascii=False), v=d["v"]
        ) for d in bloco["desp"]
    )
    linhas.append(f"{pad}  desp: [{desp_js}],")

    # banco
    b = bloco["banco"]
    linhas.append(f"{pad}  banco: {{cc:{b['cc']}, cdb:{b['cdb']}, priv:{b['priv']}}}")
    linhas.append(f"{pad}}}")
    return "\n".join(linhas)


def injetar_no_html(html_path: Path, chave: str, bloco_js: str,
                    evo_label: str, saldo_atual: float) -> bool:
    """
    Injeta novo mês no HTML:
    1. Adiciona entrada no objeto BAL
    2. Atualiza EVO_L (labels) e EVO_V (valores de saldo)
    Retorna True se modificou o arquivo.
    """
    texto = html_path.read_text(encoding="utf-8", errors="ignore")

    # ── 1. Verifica se o mês já existe ──
    if re.search(rf'\b{re.escape(chave)}\s*:', texto):
        print(f"  [AVISO] Mês '{chave}' já existe em {html_path.name}. Pulando.")
        return False

    # ── 2. Injeta no BAL ──
    # Encontra o último mês dentro do objeto BAL e adiciona depois
    # Padrão: última chave de mês (ex: mar26: { ... })
    bal_entry_pattern = r'((\s{2,4}[a-z]{3}\d{2}\s*:\s*\{[^}]*(?:\{[^}]*\}[^}]*)?\})\s*\n)(\s*\})'

    # Estratégia mais robusta: acha o fechamento do var BAL = { ... }
    # e insere antes do fechamento
    bal_close = re.search(r'(var\s+BAL\s*=\s*\{.*?)(\n\s*\};)', texto, re.DOTALL)
    if not bal_close:
        print(f"  [ERRO] Não encontrou var BAL em {html_path.name}")
        return False

    # Insere novo mês antes do fechamento do BAL
    # Evita vírgula dupla se a última entrada já termina com ","
    conteudo_bal = bal_close.group(1)
    if conteudo_bal.rstrip().endswith(','):
        separador = "\n"
    else:
        separador = ",\n"
    novo_bal = conteudo_bal + separador + bloco_js + bal_close.group(2)
    texto = texto[:bal_close.start()] + novo_bal + texto[bal_close.end():]

    # ── 3. Atualiza EVO_L ──
    # EVO_L pode ser declarada como "var EVO_L=[...]" ou junto com outra var "..., EVO_L=[...]"
    evo_l_m = re.search(r'(\bEVO_L\s*=\s*\[)([^\]]*?)(\])', texto)
    if evo_l_m:
        labels_atuais = evo_l_m.group(2)
        novo_label = f"'{evo_label}'"
        if novo_label not in labels_atuais:
            nova_lista = labels_atuais.rstrip() + (", " if labels_atuais.strip() else "") + novo_label
            texto = texto[:evo_l_m.start()] + evo_l_m.group(1) + nova_lista + evo_l_m.group(3) + texto[evo_l_m.end():]

    # ── 4. Atualiza EVO_V ──
    # EVO_V pode ser declarada sem "var" separado (ex: "var EVO_L=[...], EVO_V=[...]")
    evo_v_m = re.search(r'(\bEVO_V\s*=\s*\[)([^\]]*?)(\])', texto, re.DOTALL)
    if evo_v_m:
        valores_atuais = evo_v_m.group(2)
        novo_valor = str(round(saldo_atual, 2))
        nova_lista = valores_atuais.rstrip() + (", " if valores_atuais.strip() else "") + novo_valor
        texto = texto[:evo_v_m.start()] + evo_v_m.group(1) + nova_lista + evo_v_m.group(3) + texto[evo_v_m.end():]

    html_path.write_text(texto, encoding="utf-8")
    return True


# ── Processamento principal ────────────────────────────────────────────────

def processar_um(cond: dict, mes_str: str, arquivo: Path, config_global: dict) -> bool:
    from adapters import get_adapter

    empresa_id = cond["empresa_gestora"]
    adapter = get_adapter(empresa_id, cond)

    ext = arquivo.suffix.lower()
    if ext in (".pdf",):
        print(f"  Lendo PDF:  {arquivo.name}")
        dados = adapter.ler_pdf(arquivo, mes_str)
    else:
        print(f"  Lendo XLSX: {arquivo.name}")
        dados = adapter.ler_xlsx(arquivo, mes_str)

    chave = mes_chave(mes_str)
    bloco = dados_para_bal(dados, mes_str)
    bloco_js = bal_para_js(bloco, chave)
    evo_label = mes_evo_label(mes_str)

    html_path = HTML_DIR / cond["html_file"]
    if not html_path.exists():
        print(f"  [ERRO] HTML não encontrado: {html_path}")
        return False

    ok = injetar_no_html(html_path, chave, bloco_js, evo_label, dados.saldo_atual)
    if ok:
        print(f"  [OK] Mês '{chave}' injetado em {html_path.name}")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mes", required=True, help="Mês YYYY-MM")
    parser.add_argument("--condominio", help="ID do condomínio")
    parser.add_argument("--arquivo", "--xlsx", dest="arquivo",
                        help="Caminho para o arquivo XLSX ou PDF (opcional)")
    parser.add_argument("--todos", action="store_true")
    args = parser.parse_args()

    try:
        datetime.strptime(args.mes, "%Y-%m")
    except ValueError:
        print("[ERRO] Use formato YYYY-MM"); sys.exit(1)

    with open(ROOT / "config" / "condominios.json", encoding="utf-8") as f:
        config = json.load(f)

    condominios = [c for c in config["condominios"] if c.get("ativo", True)]
    if args.condominio:
        condominios = [c for c in condominios if c["id"] == args.condominio]
    elif not args.todos:
        print("[ERRO] Informe --condominio <id> ou --todos"); sys.exit(1)

    ok = 0
    for cond in condominios:
        print(f"\n> {cond['nome']} [{cond['empresa_gestora']}]")

        if args.arquivo:
            arquivo_path = Path(args.arquivo)
        else:
            pasta = ROOT / cond["pasta_dados"] / args.mes
            arquivos = (list(pasta.glob("*.xlsx")) + list(pasta.glob("*.xls"))
                        + list(pasta.glob("*.pdf")) + list(pasta.glob("*.PDF")))
            if not arquivos:
                print(f"  [AVISO] Nenhum arquivo em {pasta}"); continue
            arquivo_path = arquivos[0]

        if processar_um(cond, args.mes, arquivo_path, config):
            ok += 1

    print(f"\nConcluído: {ok}/{len(condominios)} condomínios atualizados.")


if __name__ == "__main__":
    main()
