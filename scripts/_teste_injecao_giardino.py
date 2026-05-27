"""Teste de injeção para Giardino (Iello PDF)."""
import sys, json, re
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.injetar_mes import (
    mes_chave, mes_evo_label, dados_para_bal, bal_para_js, injetar_no_html
)
from adapters import get_adapter

MES = "2026-04"
ARQUIVO = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Giardino D'Itália\Prestação de Contas 04.2026.pdf")
HTML_TESTE = ROOT / "test_giardino.html"

with open(ROOT / "config" / "condominios.json", encoding="utf-8") as f:
    config = json.load(f)
cond = next(c for c in config["condominios"] if c["id"] == "giardino_d_italia")

adapter = get_adapter(cond["empresa_gestora"], cond)
dados = adapter.ler_pdf(ARQUIVO, MES)

print(f"Saldo Anterior:  R$ {dados.saldo_anterior:>12,.2f}")
print(f"Receita:         R$ {dados.receita_realizada:>12,.2f}")
print(f"Despesas:        R$ {dados.despesa_total:>12,.2f}")
print(f"Saldo Atual:     R$ {dados.saldo_atual:>12,.2f}")
print(f"Inadimplência:   R$ {dados.inadimplencia_valor:>12,.2f}")

chave = mes_chave(MES)
bloco = dados_para_bal(dados, MES)
bloco_js = bal_para_js(bloco, chave)
evo_label = mes_evo_label(MES)

print(f"\n=== Bloco JS (chave={chave}) ===")
print(bloco_js[:300], "...")

ok = injetar_no_html(HTML_TESTE, chave, bloco_js, evo_label, dados.saldo_atual)
print(f"\nInjeção: {'OK' if ok else 'FALHOU'}")

if ok:
    html = HTML_TESTE.read_text(encoding="utf-8", errors="ignore")
    evo_l = re.search(r"var\s+EVO_L\s*=\s*\[([^\]]*)\]", html)
    evo_v = re.search(r"var\s+EVO_V\s*=\s*\[([^\]]*)\]", html)
    if evo_l: print(f"EVO_L: [{evo_l.group(1)[-100:]}]")
    if evo_v: print(f"EVO_V: [{evo_v.group(1)[-60:]}]")
