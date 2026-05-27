"""
Script principal de processamento.
Uso:
  python scripts/processar.py --mes 2026-05
  python scripts/processar.py --mes 2026-05 --condominio edificio_exemplo
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Garante UTF-8 no terminal Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Adiciona raiz do projeto ao path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from jinja2 import Environment, FileSystemLoader
from adapters import get_adapter


def carregar_config() -> dict:
    with open(ROOT / "config" / "condominios.json", encoding="utf-8") as f:
        return json.load(f)


MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def mes_label_pt(mes: str) -> str:
    dt = datetime.strptime(mes, "%Y-%m")
    return f"{MESES_PT[dt.month]} de {dt.year}"


def moeda_filter(valor) -> str:
    try:
        v = float(valor)
        inteiro, decimal = f"{v:,.2f}".split(".")
        inteiro = inteiro.replace(",", ".")
        return f"R$ {inteiro},{decimal}"
    except Exception:
        return "R$ 0,00"


def processar_condominio(cond: dict, mes: str, config_global: dict) -> bool:
    empresa_id = cond["empresa_gestora"]
    empresa_cfg = config_global["empresas"].get(empresa_id, {})
    adapter = get_adapter(empresa_id, cond)

    pasta = ROOT / cond["pasta_dados"] / mes
    if not pasta.exists():
        print(f"  [AVISO] Pasta de dados não encontrada: {pasta}")
        return False

    # Detecta arquivos disponíveis
    xlsx_files = list(pasta.glob("*.xlsx")) + list(pasta.glob("*.xls"))
    pdf_files  = list(pasta.glob("*.pdf"))

    if not xlsx_files and not pdf_files:
        print(f"  [AVISO] Nenhum arquivo encontrado em {pasta}")
        return False

    dados = None
    if xlsx_files:
        print(f"  Lendo XLSX: {xlsx_files[0].name}")
        dados = adapter.ler_xlsx(xlsx_files[0], mes)

    if pdf_files and hasattr(adapter, "ler_pdf"):
        print(f"  Lendo PDF:  {pdf_files[0].name}")
        dados_pdf = adapter.ler_pdf(pdf_files[0], mes)
        if dados:
            # Complementa dados do XLSX com info do PDF (saldo anterior, inadimplência)
            if dados_pdf.saldo_anterior:
                dados.saldo_anterior = dados_pdf.saldo_anterior
            if dados_pdf.inadimplencia_valor:
                dados.inadimplencia_valor     = dados_pdf.inadimplencia_valor
                dados.inadimplencia_percentual = dados_pdf.inadimplencia_percentual
        else:
            dados = dados_pdf

    if not dados:
        print(f"  [ERRO] Não foi possível extrair dados para {cond['nome']}")
        return False

    # Recalcula saldo com saldo_anterior atualizado
    dados.saldo_atual = adapter.calcular_saldo(dados)

    # Renderiza dashboard HTML
    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    env.filters["moeda"] = moeda_filter

    mes_label = mes_label_pt(mes)

    template = env.get_template("dashboard.html")
    html = template.render(
        condominio=cond,
        dados=dados,
        mes_label=mes_label,
        gerado_em=datetime.now().strftime("%d/%m/%Y %H:%M"),
        historico_json=json.dumps(dados.historico_meses, ensure_ascii=False),
        despesas_json=json.dumps(dados.categorias_despesa, ensure_ascii=False),
    )

    saida_dir = ROOT / "output" / cond["id"] / mes
    saida_dir.mkdir(parents=True, exist_ok=True)
    saida_path = saida_dir / "index.html"
    saida_path.write_text(html, encoding="utf-8")
    print(f"  [OK] Dashboard gerado: {saida_path.relative_to(ROOT)}")
    return True


def gerar_indice(config: dict, mes: str):
    """Gera página índice com todos os condomínios."""
    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    env.filters["moeda"] = moeda_filter

    # Coleta resumos
    resumos = []
    for cond in config["condominios"]:
        if not cond.get("ativo", True):
            continue
        saida = ROOT / "output" / cond["id"] / mes / "index.html"
        resumos.append({
            "cond": cond,
            "gerado": saida.exists(),
            "link": f"{cond['id']}/{mes}/index.html",
        })

    mes_label = mes_label_pt(mes)

    template = env.get_template("indice.html")
    html = template.render(
        resumos=resumos,
        mes_label=mes_label,
        gerado_em=datetime.now().strftime("%d/%m/%Y %H:%M"),
        total=len(resumos),
        processados=sum(1 for r in resumos if r["gerado"]),
    )

    indice_path = ROOT / "output" / "index.html"
    indice_path.write_text(html, encoding="utf-8")
    print(f"\n[OK] Índice gerado: output/index.html ({sum(1 for r in resumos if r['gerado'])}/{len(resumos)} condomínios)")


def main():
    parser = argparse.ArgumentParser(description="Gera dashboards financeiros por condomínio")
    parser.add_argument("--mes", required=True, help="Mês de referência (formato YYYY-MM)")
    parser.add_argument("--condominio", default=None, help="ID do condomínio (opcional, processa todos se omitido)")
    args = parser.parse_args()

    # Valida formato do mês
    try:
        datetime.strptime(args.mes, "%Y-%m")
    except ValueError:
        print("[ERRO] Formato de mês inválido. Use YYYY-MM (ex: 2026-05)")
        sys.exit(1)

    config = carregar_config()
    condominios = [c for c in config["condominios"] if c.get("ativo", True)]

    if args.condominio:
        condominios = [c for c in condominios if c["id"] == args.condominio]
        if not condominios:
            print(f"[ERRO] Condomínio '{args.condominio}' não encontrado na config.")
            sys.exit(1)

    print(f"\n=== Processando {len(condominios)} condomínio(s) — {args.mes} ===\n")
    ok = 0
    for cond in condominios:
        print(f"> {cond['nome']} [{cond['empresa_gestora']}]")
        if processar_condominio(cond, args.mes, config):
            ok += 1
        print()

    gerar_indice(config, args.mes)
    print(f"\nConcluído: {ok}/{len(condominios)} dashboards gerados com sucesso.")


if __name__ == "__main__":
    main()
