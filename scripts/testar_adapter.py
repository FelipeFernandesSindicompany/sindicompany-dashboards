"""
Testa um adapter com o arquivo real e mostra os dados extraídos.
Uso: python scripts/testar_adapter.py --condominio alvorada --arquivo "caminho/arquivo.xlsx"
"""
import sys, argparse, json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from adapters import get_adapter

with open(ROOT / "config" / "condominios.json", encoding="utf-8") as f:
    config = json.load(f)

parser = argparse.ArgumentParser()
parser.add_argument("--condominio", required=True)
parser.add_argument("--arquivo", required=True)
parser.add_argument("--mes", default="2026-04")
args = parser.parse_args()

cond = next((c for c in config["condominios"] if c["id"] == args.condominio), None)
if not cond:
    print(f"[ERRO] Condomínio '{args.condominio}' não encontrado"); sys.exit(1)

adapter = get_adapter(cond["empresa_gestora"], cond)
arquivo = Path(args.arquivo)

print(f"\n=== Testando: {cond['nome']} ({cond['empresa_gestora']}) ===")
print(f"Arquivo: {arquivo.name}\n")

if arquivo.suffix.lower() in (".pdf",):
    dados = adapter.ler_pdf(arquivo, args.mes)
else:
    dados = adapter.ler_xlsx(arquivo, args.mes)

print(f"Saldo Anterior:       R$ {dados.saldo_anterior:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
print(f"Receita Realizada:    R$ {dados.receita_realizada:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
print(f"Total Despesas:       R$ {dados.despesa_total:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
print(f"Saldo Atual:          R$ {dados.saldo_atual:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
print(f"Inadimplencia:        R$ {dados.inadimplencia_valor:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
print(f"  ({dados.inadimplencia_percentual:.1f}%)")
print(f"\nDespesas por categoria ({len(dados.categorias_despesa)}):")
for cat, val in sorted(dados.categorias_despesa.items(), key=lambda x: x[1], reverse=True):
    print(f"  {cat:<35} R$ {val:>10,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
