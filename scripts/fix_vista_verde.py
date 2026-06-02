"""
Corrige o Dashboard Vista Verde:
1. Remove abr26 que foi injetado no objeto DESP_COLORS (errado)
2. Injeta abr26 corretamente no BAL usando brace tracking
3. Corrige EVO_V (13 valores → 9)
"""
import sys, re, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.join(os.path.dirname(__file__), '..')
DASH = os.path.join(ROOT, 'docs', 'Dashboard_Financeiro_VistaVerde.html')

with open(DASH, encoding='utf-8', errors='replace') as f:
    c = f.read()


def brace_end(text, start):
    """Retorna índice após o '}' de fechamento usando tracking de profundidade."""
    depth, j = 0, start
    while j < len(text):
        if text[j] == '{': depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return j


# ── 1. Extrai o entry abr26 do local errado (DESP_COLORS) ──────────────────
m = re.search(r'(\s*abr26\s*:\s*)\{', c)
assert m, "abr26 não encontrado!"
brace_pos = m.end() - 1  # posição do '{'
entry_end = brace_end(c, brace_pos)
abr26_full = c[m.start():entry_end]  # inclui whitespace + key + value

print("=== abr26 extraído do DESP_COLORS ===")
# Get key values
tAtual_val = float(re.search(r'tAtual:\s*([\d.]+)', abr26_full).group(1))
print(f"  tAtual: {tAtual_val}")
print(f"  chars: {len(abr26_full)}")

# ── 2. Remove abr26 do DESP_COLORS ─────────────────────────────────────────
entry_start = m.start()

# Consume trailing comma + newline after the closing brace
tail = c[entry_end:]
if tail.lstrip('\n').startswith(','):
    entry_end = entry_end + len(tail) - len(tail.lstrip('\n')) + 1
    tail2 = c[entry_end:]
    if tail2.startswith('\n'):
        entry_end += 1

# Also trim leading whitespace/newline from entry_start
# (the comma+newline from the PREVIOUS color entry should remain)
c_removed = c[:entry_start] + c[entry_end:]
print(f"\nRemovido de DESP_COLORS: {len(c) - len(c_removed)} chars")

# Verify
remaining = list(re.finditer(r'\babr26\b', c_removed, re.IGNORECASE))
print(f"abr26 após remoção: {len(remaining)} ocorrências")


# ── 3. Localiza o fim do var BAL usando brace tracking ─────────────────────
bal_m = re.search(r'var\s+BAL\s*=\s*\{', c_removed)
assert bal_m, "var BAL não encontrado!"
bal_open = bal_m.end() - 1  # posição do '{'
bal_end_pos = brace_end(c_removed, bal_open)
print(f"\nBAL: pos {bal_m.start()} → {bal_end_pos}")

bal_body = c_removed[bal_m.start():bal_end_pos]
bal_keys = re.findall(r'\b([a-z]{3}\d{2})\s*:', bal_body)
print(f"BAL meses antes da inserção: {bal_keys}")


# ── 4. Monta o entry abr26 limpo para inserir no BAL ───────────────────────
# Extrai apenas o objeto {…} sem key
obj_start = abr26_full.index('{')
abr26_obj = abr26_full[obj_start:]  # just the { ... }

entry_js = f"  abr26: {abr26_obj}"

# Insere antes do '}' final do BAL
# O conteúdo atual termina em ...  mar26: { ... }\n}
# Precisamos adicionar vírgula após mar26 se não tiver
insert_at = bal_end_pos - 1  # posição do '}' final do BAL

# Texto antes do '}' final
before_close = c_removed[:insert_at].rstrip()
if not before_close.endswith(','):
    separator = ',\n'
else:
    separator = '\n'

c_new = before_close + separator + entry_js + '\n' + c_removed[insert_at:]

# ── 5. Corrige EVO_L / EVO_V ───────────────────────────────────────────────
evo_l = re.search(r'(EVO_L\s*=\s*\[)([^\]]+)(\])', c_new)
evo_v = re.search(r'(EVO_V\s*=\s*\[)([^\]]+)(\])', c_new)

l_vals = [x.strip() for x in evo_l.group(2).split(',') if x.strip()] if evo_l else []
v_vals = [x.strip() for x in evo_v.group(2).split(',') if x.strip()] if evo_v else []

print(f"\nEVO_L: {len(l_vals)} labels")
print(f"EVO_V: {len(v_vals)} valores (antes)")

if evo_v and len(v_vals) != len(l_vals):
    # Manter apenas os N primeiros valores que correspondem às labels
    # A última label é 'Abr/26' → último valor deve ser tAtual de abr26
    if len(v_vals) >= len(l_vals):
        v_fixed = v_vals[:len(l_vals) - 1] + [str(tAtual_val)]
    else:
        v_fixed = v_vals + [str(tAtual_val)]
        v_fixed = v_fixed[:len(l_vals)]
    new_evo_v = ', '.join(v_fixed)
    c_new = c_new[:evo_v.start()] + evo_v.group(1) + new_evo_v + evo_v.group(3) + c_new[evo_v.end():]
    print(f"EVO_V corrigido: {len(v_fixed)} valores")

# ── 6. Verificação final ────────────────────────────────────────────────────
print("\n=== VERIFICAÇÃO FINAL ===")
bal_m2 = re.search(r'var\s+BAL\s*=\s*\{', c_new)
bal_end2 = brace_end(c_new, c_new.index('{', bal_m2.end()-1))
bal_body2 = c_new[bal_m2.start():bal_end2]
bal_keys2 = re.findall(r'\b([a-z]{3}\d{2})\s*:', bal_body2)
print(f"BAL meses: {bal_keys2}")

evo_v2 = re.search(r'EVO_V\s*=\s*\[([^\]]+)\]', c_new)
v_final = [x.strip() for x in evo_v2.group(1).split(',') if x.strip()] if evo_v2 else []
print(f"EVO_V final: {len(v_final)} valores, último={v_final[-1] if v_final else '?'}")

abr_final = list(re.finditer(r'\babr26\b', c_new, re.IGNORECASE))
print(f"abr26 ocorrências: {len(abr_final)}")
for mm in abr_final:
    ctx = c_new[max(0,mm.start()-60):mm.end()+60].replace('\n',' ')
    print(f"  pos {mm.start()}: {ctx[:120]}")

# ── 7. Salva ────────────────────────────────────────────────────────────────
if len(bal_keys2) == 9 and 'abr26' in bal_keys2:
    print("\nTudo correto! Salvando...")
    with open(DASH, 'w', encoding='utf-8') as f:
        f.write(c_new)
    print("Dashboard salvo!")

    # JS syntax check
    import subprocess
    node = r"C:\Program Files\nodejs\node.exe"
    r = subprocess.run([node, '--check', DASH], capture_output=True, text=True)
    if r.returncode == 0:
        print("JS syntax: OK")
    else:
        print(f"JS syntax ERROR: {r.stderr[:200]}")
else:
    print(f"\nERRO: BAL tem {len(bal_keys2)} meses (esperado 9) ou abr26 ausente")
    print("NÃO salvo - verifique manualmente")
