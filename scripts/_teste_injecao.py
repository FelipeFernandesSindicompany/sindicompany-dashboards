"""
Teste end-to-end de injeção:
1. Lê o XLSX de Alvorada (Habitacional)
2. Converte para bloco BAL
3. Injeta em uma cópia do HTML
4. Verifica resultado
"""
import sys, json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Importa o motor de injeção
from scripts.injetar_mes import (
    mes_chave, mes_titulo, mes_evo_label, dados_para_bal, bal_para_js, injetar_no_html
)
from adapters import get_adapter

MES = "2026-05"
ARQUIVO_XLSX = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Alvorada\prestacao_contas_4_2026.xlsx")
HTML_ORIGEM  = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\HTML\Dashboard_Financeiro_Alvorada.html")
HTML_TESTE   = ROOT / "test_alvorada.html"

# 1. Lê config
with open(ROOT / "config" / "condominios.json", encoding="utf-8") as f:
    config = json.load(f)
cond = next(c for c in config["condominios"] if c["id"] == "alvorada")

# 2. Cria adapter e lê dados
adapter = get_adapter(cond["empresa_gestora"], cond)
dados = adapter.ler_xlsx(ARQUIVO_XLSX, MES)

print("=== Dados lidos ===")
print(f"Saldo Anterior:  R$ {dados.saldo_anterior:>12,.2f}")
print(f"Receita:         R$ {dados.receita_realizada:>12,.2f}")
print(f"Despesas:        R$ {dados.despesa_total:>12,.2f}")
print(f"Saldo Atual:     R$ {dados.saldo_atual:>12,.2f}")
print(f"Inadimplência:   R$ {dados.inadimplencia_valor:>12,.2f}")
print(f"Categorias:      {list(dados.categorias_despesa.keys())}")

# 3. Gera bloco BAL
chave = mes_chave(MES)
bloco = dados_para_bal(dados, MES)
bloco_js = bal_para_js(bloco, chave)
evo_label = mes_evo_label(MES)

print(f"\n=== Bloco JS (chave={chave}) ===")
print(bloco_js)

# 4. Injeta no HTML de teste
ok = injetar_no_html(HTML_TESTE, chave, bloco_js, evo_label, dados.saldo_atual)
print(f"\n=== Injeção: {'OK' if ok else 'FALHOU'} ===")

if ok:
    # 5. Verifica resultado
    html = HTML_TESTE.read_text(encoding="utf-8", errors="ignore")
    if chave in html:
        print(f"Chave '{chave}' encontrada no HTML. ✓")
        # Mostra trecho ao redor da nova chave
        idx = html.index(chave)
        print("\nTrecho injetado:")
        print(html[max(0,idx-50):idx+500])
    else:
        print(f"[ERRO] Chave '{chave}' NÃO encontrada!")

    # Verifica EVO_L
    import re
    evo_l = re.search(r"var\s+EVO_L\s*=\s*\[([^\]]*)\]", html)
    if evo_l:
        print(f"\nEVO_L (últimos 80 chars): ...{evo_l.group(1)[-80:]}")
    evo_v = re.search(r"var\s+EVO_V\s*=\s*\[([^\]]*)\]", html)
    if evo_v:
        print(f"EVO_V (últimos 80 chars): ...{evo_v.group(1)[-80:]}")
