"""Debug: mostra todas as tabelas Lello para encontrar categorias de despesa."""
import sys, pandas as pd
from io import StringIO

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Barra Viva I - Alegria\prestacaocontas_1878_2026_04.xls"

with open(path, "r", encoding="latin-1", errors="replace") as f:
    content = f.read()

tabelas = pd.read_html(StringIO(content), thousands=".", decimal=",")
print(f"Total de tabelas: {len(tabelas)}\n")

for i, df in enumerate(tabelas):
    # Filtra tabelas com palavras-chave de despesa
    texto = df.to_string().lower()
    if any(k in texto for k in ["pessoal", "terceiriz", "manut", "total", "administr"]):
        print(f"\n=== TABELA {i} ({df.shape[0]}x{df.shape[1]}) ===")
        print("Colunas:", list(df.columns))
        print(df.to_string())
        print()
