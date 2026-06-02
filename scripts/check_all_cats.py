import sys, re, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.join(os.path.dirname(__file__), '..')
with open(os.path.join(ROOT, 'docs', 'Dashboard_Financeiro_VibraButanta.html'), encoding='utf-8') as f:
    c = f.read()
bal_start = c.find('var BAL = {')
bal_end = c.find('};', bal_start) + 2
bal = c[bal_start:bal_end]
MESES = ['abr25','mai25','jun25','jul25','ago25','set25','out25','nov25','dez25','jan26','fev26','mar26','abr26']
for key in MESES:
    m = re.search(r'\b' + key + r'\s*:\s*\{', bal)
    if not m:
        print(f'{key}: nao encontrado')
        continue
    brace = bal.find('{', m.start()+len(key))
    depth, j = 0, brace
    while j < len(bal):
        if bal[j] == '{': depth += 1
        elif bal[j] == '}':
            depth -= 1
            if depth == 0: j += 1; break
        j += 1
    seg = bal[m.start():j]
    dm = re.search(r'desp:\s*\[([^\]]+)\]', seg)
    if dm:
        cats = re.findall(r'c:"([^"]+)",\s*v:([\d.]+)', dm.group(1))
        total = sum(float(v) for _,v in cats)
        names = [cat for cat,v in cats]
        print(f'{key}: {len(cats)} cats = {total:,.2f}  | {names}')
    else:
        print(f'{key}: sem desp')
