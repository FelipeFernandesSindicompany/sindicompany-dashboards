"""Fix Gravura HTML: remove double comma in BAL and add missing EVO_V value for mai26."""
import sys, re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

html_path = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\HTML\Dashboard_Financeiro_GravuraResidencial.html")
texto = html_path.read_text(encoding="utf-8", errors="ignore")

# 1. Fix double comma: "},,\n    mai26:" → "},\n    mai26:"
before = texto.count("},,")
texto = texto.replace("},,\n    mai26:", "},\n    mai26:")
after_fix = texto.count("},,")
print(f"Double commas fixed: {before - after_fix} (from {before} to {after_fix})")

# 2. Add missing EVO_V value for mai26
# Find the mai26 saldo_atual from the BAL entry
m_saldo = re.search(r'mai26:\s*\{[^}]*tAtual:\s*([\d.]+)', texto)
if m_saldo:
    saldo_mai26 = float(m_saldo.group(1))
    print(f"Found mai26 saldo_atual: {saldo_mai26}")

    # Find EVO_V and check if it already has the value
    evo_v_m = re.search(r'(\bEVO_V\s*=\s*\[)([^\]]*?)(\])', texto)
    if evo_v_m:
        valores = evo_v_m.group(2)
        print(f"Current EVO_V count: {len([v for v in valores.split(',') if v.strip()])}")
        evo_l_m = re.search(r'(\bEVO_L\s*=\s*\[)([^\]]*?)(\])', texto)
        evo_l_count = len([v for v in evo_l_m.group(2).split(',') if v.strip()]) if evo_l_m else 0
        print(f"EVO_L count: {evo_l_count}")

        evo_v_count = len([v for v in valores.split(',') if v.strip()])
        if evo_v_count < evo_l_count:
            # Add missing value
            novo_valor = str(round(saldo_mai26, 2))
            nova_lista = valores.rstrip() + (", " if valores.strip() else "") + novo_valor
            texto = texto[:evo_v_m.start()] + evo_v_m.group(1) + nova_lista + evo_v_m.group(3) + texto[evo_v_m.end():]
            print(f"Added EVO_V value: {novo_valor}")
        else:
            print("EVO_V already has correct count")

html_path.write_text(texto, encoding="utf-8")
print("File saved.")

# Verify
texto2 = html_path.read_text(encoding="utf-8", errors="ignore")
evo_v2 = re.search(r'\bEVO_V\s*=\s*\[([^\]]*)\]', texto2)
evo_l2 = re.search(r'\bEVO_L\s*=\s*\[([^\]]*)\]', texto2)
print(f"\nEVO_L: ...{evo_l2.group(1)[-50:] if evo_l2 else 'NOT FOUND'}")
print(f"EVO_V: ...{evo_v2.group(1)[-50:] if evo_v2 else 'NOT FOUND'}")
dbl = texto2.count("},,")
print(f"Double commas remaining: {dbl}")
