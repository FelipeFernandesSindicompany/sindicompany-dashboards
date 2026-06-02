import sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def brace_end(text, start):
    d, j = 0, start
    while j < len(text):
        if text[j] == '{': d += 1
        elif text[j] == '}':
            d -= 1
            if d == 0: return j+1
        j += 1
    return j

with open('docs/Dashboard_Financeiro_VistaVerde.html', encoding='utf-8', errors='replace') as f:
    c = f.read()

bal_m = re.search(r'var\s+BAL\s*=\s*\{', c)
bal_end = brace_end(c, c.index('{', bal_m.start()))
bal = c[bal_m.start():bal_end]
keys = re.findall(r'\b([a-z]{3}\d{2})\s*:', bal)
print(f'BAL meses ({len(keys)}): {keys}')

evo_l = re.search(r'EVO_L\s*=\s*\[([^\]]+)\]', c)
evo_v = re.search(r'EVO_V\s*=\s*\[([^\]]+)\]', c)
l = [x.strip() for x in evo_l.group(1).split(',') if x.strip()]
v = [x.strip() for x in evo_v.group(1).split(',') if x.strip()]
print(f'EVO_L: {len(l)} | EVO_V: {len(v)} -> Match: {len(l)==len(v)}')

# abr26 values
abr_m = re.search(r'\babr26\s*:\s*\{', bal)
if abr_m:
    seg = bal[abr_m.start():abr_m.start()+400]
    vals = {k: re.search(rf'{k}:\s*([\d.]+)', seg) for k in ['tAtual','tDesp','inad','tCred','tDeb']}
    for k, m in vals.items():
        print(f'  abr26.{k} = {m.group(1) if m else "?"}')

# DESP_COLORS check
dc = re.search(r'var\s+DESP_COLORS\s*=\s*\{', c)
if dc:
    dc_end = brace_end(c, c.index('{', dc.start()))
    dc_body = c[dc.start():dc_end]
    if 'abr26' in dc_body:
        print("ERRO: abr26 ainda em DESP_COLORS!")
    else:
        print("DESP_COLORS: OK (sem abr26)")

print("\nVerificacao concluida!")
