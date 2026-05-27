"""Debug: mostra as tabelas HTML do XLS Lello."""
import sys, pandas as pd
from io import StringIO

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Barra Viva I - Alegria\prestacaocontas_1878_2026_04.xls"

with open(path, "r", encoding="latin-1", errors="replace") as f:
    content = f.read()

tabelas = pd.read_html(StringIO(content), thousands=".", decimal=",")
print(f"Total de tabelas: {len(tabelas)}")

for i, df in enumerate(tabelas[:5]):
    print(f"\n=== TABELA {i} ({df.shape[0]} linhas x {df.shape[1]} colunas) ===")
    print("Colunas:", list(df.columns))
    print(df.head(10).to_string())
    if len(df) > 10:
        print("...")
        print(df.tail(3).to_string())
