"""Debug: mostra a tabela de despesas Lello completa."""
import sys, pandas as pd, re
from io import StringIO

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Barra Viva I - Alegria\prestacaocontas_1878_2026_04.xls"

with open(path, "r", encoding="latin-1", errors="replace") as f:
    content = f.read()

tabelas = pd.read_html(StringIO(content), thousands=".", decimal=",")

# Encontra a tabela grande de despesas
for i, df in enumerate(tabelas):
    texto = df.to_string().lower()
    if "total pessoal" in texto or "pessoal total" in texto or ("pessoal" in texto and "terceiriz" in texto):
        print(f"\n=== TABELA {i} ({df.shape[0]}x{df.shape[1]}) - DESPESAS ===")
        # Mostra apenas linhas com "Total" (subtotais de categoria)
        for idx, row in df.iterrows():
            linha = " | ".join(str(v) for v in row.values)
            if re.search(r"Total\b", linha, re.IGNORECASE):
                print(f"  L{idx:3d}: {linha[:200]}")
        break
