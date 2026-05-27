"""Debug: mostra linhas 88-165 do XLSX para entender estrutura das categorias."""
import sys, openpyxl
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Alvorada\prestacao_contas_4_2026.xlsx")
wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
ws = wb.active
linhas = list(ws.iter_rows(values_only=True))

print("=== Linhas 85-165 (0-indexed) ===")
for i, row in enumerate(linhas[84:165], start=85):
    # Mostra apenas colunas não-None
    vals = [(j, v) for j, v in enumerate(row) if v is not None]
    if vals:
        print(f"L{i:3d}: {vals}")

wb.close()
