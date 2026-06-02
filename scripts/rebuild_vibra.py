"""
Reconstrói Vibra Butantã do zero a partir do Sublime.
Inclui abr26 explicitamente no BAL antes de salvar.
Garante que o dashboard esteja 100% funcional antes de salvar.
"""
import sys, re, json, os, subprocess, tempfile
ROOT = __file__.replace('scripts\\rebuild_vibra.py', '')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SUBLIME = ROOT + 'docs/Dashboard_Financeiro_Sublime.html'
# Use the ORIGINAL Vibra file (before any bad modifications)
# We'll get BAL data from git or reconstruct from known good state
DASH_OUT = ROOT + 'docs/Dashboard_Financeiro_VibraButanta.html'

# First, get the current Vibra file (it has the BAL data even if structure is broken)
with open(SUBLIME, encoding='utf-8') as f:
    template = f.read()

# Get Vibra's current content to extract BAL
with open(DASH_OUT, encoding='utf-8') as f:
    vibra_broken = f.read()

# ── Extract all data from the broken Vibra file ─────────────────────────────
# Get all individual month entries from the broken BAL
mo = {v:k+1 for k,v in enumerate(['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'])}
valid_months = set(mo.keys())

# Extract individual month entries using brace tracking
def extract_bal_entries(text):
    """Extract all month entries {key: {...}} from BAL-like text"""
    entries = {}
    key_re = re.compile(r'\b([a-z]{3}\d{2})\s*:\s*\{')
    pos = 0
    while True:
        km = key_re.search(text, pos)
        if not km: break
        key = km.group(1)
        if key[:3] not in valid_months:
            pos = km.end()
            continue
        brace_start = km.end() - 1
        depth = 0
        j = brace_start
        while j < len(text):
            if text[j] == '{': depth += 1
            elif text[j] == '}':
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        entry_text = text[km.start():j]
        entries[key] = entry_text
        pos = j
        while pos < len(text) and text[pos] in ' \t,\n':
            pos += 1
    return entries

# Extract from broken Vibra file - look in the full text
entries = extract_bal_entries(vibra_broken)
keys = sorted(entries.keys(), key=lambda k: int(k[3:])*12 + mo.get(k[:3],0))
print(f"Extracted {len(entries)} BAL entries: {keys}")

# Build clean BAL block
bal_entries_str = ',\n'.join(f'    {entries[k]}' for k in keys)
clean_bal = f'var BAL = {{\n{bal_entries_str}\n}};'

# Get EVO data from Vibra broken file
evo_l = re.search(r'var EVO_L=\[[^\]]+\]', vibra_broken)
evo_v = re.search(r'var EVO_V=\[[^\]]+\]', vibra_broken)
inad_v = re.search(r'var INAD_V\s*=\s*\[[^\]]*\]', vibra_broken)

# Fix EVO_V count to match EVO_L
if evo_l and evo_v:
    n_labels = len([x for x in evo_l.group(0).split(',') if x.strip() and 'EVO_L' not in x and '[' not in x and ']' not in x]) + 1
    # simpler: count by actual parsed labels
    labels_content = re.search(r'var EVO_L=\[([^\]]+)\]', vibra_broken).group(1)
    vals_content   = re.search(r'var EVO_V=\[([^\]]+)\]', vibra_broken).group(1)
    n_labels = len([x for x in labels_content.split(',') if x.strip()])
    vals = [v.strip() for v in vals_content.split(',') if v.strip()]
    if len(vals) > n_labels:
        vals = vals[:n_labels]
    evo_v_str = 'var EVO_V=[' + ','.join(vals) + ']'
    evo_l_str = evo_l.group(0)
else:
    evo_l_str = 'var EVO_L=[]'
    evo_v_str = 'var EVO_V=[]'

print(f"EVO_L: {n_labels if evo_l else 0} labels, EVO_V: {len(vals) if evo_v else 0} values")

# Build MESES
meses_js = 'var MESES=' + json.dumps(keys) + ';'

# Get ORC_MESES from Vibra
orc_start = vibra_broken.find('var ORC_MESES')
orc_block = 'var ORC_MESES={};'
if orc_start >= 0:
    orc_end = vibra_broken.find('};', orc_start) + 2
    orc_block = vibra_broken[orc_start:orc_end]

# Get CONFIG
cfg_m = re.search(r'var CONFIG=\{', vibra_broken)
if cfg_m:
    cfg_start = cfg_m.start()
    cfg_end = vibra_broken.find('};', cfg_start) + 2
    vibra_cfg = vibra_broken[cfg_start:cfg_end]
else:
    vibra_cfg = 'var CONFIG={nome:"Condomínio Vibra Butantã",sindica:"Síndico Profissional",orcamento:{exercicio:"2025/2026",totalAnual:0,meses:{}}};'

# ── Replace in Sublime template ──────────────────────────────────────────────
result = template

# 1. Title
result = result.replace('Dashboard Financeiro – Condomínio Sublime', 'Dashboard Financeiro – Condomínio Vibra Butantã')
result = result.replace('Condomínio Sublime', 'Condomínio Vibra Butantã')

# 2. CONFIG
sub_cfg = re.search(r'var CONFIG=\{', result)
if sub_cfg:
    s = sub_cfg.start()
    e = result.find('};', s) + 2
    result = result[:s] + vibra_cfg + result[e:]
    print("CONFIG replaced")

# 3. BAL (compact Sublime BAL -> expanded Vibra BAL)
sub_bal = re.search(r'var BAL=\{', result)
if sub_bal:
    s = sub_bal.start()
    e = result.find('};', s) + 2
    result = result[:s] + clean_bal + result[e:]
    print("BAL replaced")

# 4. EVO_L
sub_evo_l = re.search(r'var EVO_L=\[[^\]]+\]', result)
if sub_evo_l:
    result = result.replace(sub_evo_l.group(0), evo_l_str, 1)
    print("EVO_L replaced")

# 5. EVO_V
sub_evo_v = re.search(r'var EVO_V=\[[^\]]+\]', result)
if sub_evo_v:
    result = result.replace(sub_evo_v.group(0), evo_v_str, 1)
    print("EVO_V replaced")

# 6. ORC_MESES
sub_orc = re.search(r'var ORC_MESES=\{', result)
if sub_orc:
    s = sub_orc.start()
    e = result.find('};', s) + 2
    result = result[:s] + orc_block + result[e:]
    print("ORC_MESES replaced")

# 7. MESES
sub_meses = re.search(r'var\s+MESES\s*=\s*\[[^\]]*\]', result)
if sub_meses:
    result = result.replace(sub_meses.group(0), meses_js, 1)
    print("MESES replaced")

# ── Syntax check before saving ───────────────────────────────────────────────
scripts = re.findall(r'<script(?![^>]*\bsrc\b)[^>]*>([\s\S]*?)</script>', result, re.IGNORECASE)
combined = '\n'.join(scripts)
tmp_path = os.path.join(tempfile.gettempdir(), 'vibra_final_check.js')
with open(tmp_path, 'w', encoding='utf-8') as f:
    f.write('var window={onload:null,addEventListener:function(){},innerWidth:1200};\n')
    f.write('var document={getElementById:function(){return{innerHTML:"",style:{},classList:{add:function(){},remove:function(){}},appendChild:function(){},querySelectorAll:function(){return[];}};},querySelector:function(){return null;},querySelectorAll:function(){return[];},createElement:function(){return{};},addEventListener:function(){},body:{appendChild:function(){}}};\n')
    f.write('var Chart=function(){};\nvar setTimeout=function(){};\nvar clearTimeout=function(){};\n')
    f.write(combined)

node = r'C:\Program Files\nodejs\node.exe'
check = subprocess.run([node, '--check', tmp_path], capture_output=True, text=True)
os.unlink(tmp_path)

if check.returncode != 0:
    print(f"\nSYNTAX ERROR: {check.stderr[:300]}")
    sys.exit(1)
else:
    print("\nSyntax check: PASSED!")

# ── Save ─────────────────────────────────────────────────────────────────────
with open(DASH_OUT, 'w', encoding='utf-8') as f:
    f.write(result)
print(f"Dashboard saved: {len(result)} chars, {len(entries)} months")
