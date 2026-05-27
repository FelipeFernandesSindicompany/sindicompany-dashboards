"""Debug: lista todas as tabelas e mostra resumo + linhas com Total."""
import sys, pandas as pd, re
from io import StringIO

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Barra Viva I - Alegria\prestacaocontas_1878_2026_04.xls"

with open(path, "r", encoding="latin-1", errors="replace") as f:
    content = f.read()

tabelas = pd.read_html(StringIO(content), thousands=".", decimal=",")

for i, df in enumerate(tabelas):
    print(f"Tab {i:2d}: {df.shape[0]:3d}x{df.shape[1]} | cols[0]={str(df.columns[0])[:40]}")

# Mostra tabelas grandes (> 30 linhas)
for i, df in enumerate(tabelas):
    if df.shape[0] > 30:
        print(f"\n=== TABELA {i} ({df.shape[0]}x{df.shape[1]}) ===")
        # Mostra primeiras 5 e últimas 5 linhas
        for idx, row in df.head(5).iterrows():
            print(f"  L{idx:3d}: {' | '.join(str(v)[:30] for v in row.values)}")
        print("  ...")
        for idx, row in df.tail(5).iterrows():
            print(f"  L{idx:3d}: {' | '.join(str(v)[:30] for v in row.values)}")
        # Linhas com Total
        print("  --- Linhas com 'Total': ---")
        for idx, row in df.iterrows():
            linha = " | ".join(str(v) for v in row.values)
            if re.search(r"\bTotal\b", linha, re.IGNORECASE):
                print(f"  T{idx:3d}: {linha[:180]}")
