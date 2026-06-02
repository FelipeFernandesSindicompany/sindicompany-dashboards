"""
Atualiza abr26 no dashboard com os valores corretos extraídos da Posição Financeira do PDF.
Valores corretos (do PDF pág. 3, conta ORDINÁRIA):
  - Manutenção: 35.828,75 (dashboard estava errado: 46.083,51)
  - Mat. de Consumo: 10.254,76 (dashboard estava errado: 652,60)
Também renomeia 'Consumos' para manter consistência (já correto como 'Consumos').
"""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)

from adapters.lirba_pdf import AdapterLirbaPDF

PDF = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Vibra Butantã\Prestação de Contas 04.2026.PDF"
DASH = os.path.join(ROOT, 'docs', 'Dashboard_Financeiro_VibraButanta.html')

adapter = AdapterLirbaPDF({'id': 'vibra_butanta', 'nome': 'Vibra Butanta'})
dados = adapter.ler_pdf(PDF, '2026-04')

cats = sorted(dados.categorias_despesa.items(), key=lambda x: -x[1])
total = sum(v for _,v in cats)
print(f"Adapter abr26 ({len(cats)} cats, soma={total:,.2f}, tDesp={dados.despesa_total:,.2f}):")
for c,v in cats:
    print(f"  {c}: {v:,.2f}")

print("\nAtualizando dashboard...")
with open(DASH, encoding='utf-8') as f:
    c = f.read()

bal_start = c.find('var BAL = {')
if bal_start < 0: bal_start = c.find('var BAL={')
bal_end = c.find('};', bal_start) + 2
bal = c[bal_start:bal_end]

m = re.search(r'\babr26\s*:\s*\{', bal)
if not m:
    print("abr26 NOT FOUND!"); sys.exit(1)

brace = bal.find('{', m.start()+5)
depth, j = 0, brace
while j < len(bal):
    if bal[j] == '{': depth += 1
    elif bal[j] == '}':
        depth -= 1
        if depth == 0: j += 1; break
    j += 1
entry = bal[m.start():j]
entry_len = j - m.start()

# Build new desp array from adapter
desp_str = ', '.join(
    '{' + f'c:"{cat}", v:{round(v,2)}' + '}'
    for cat, v in cats
)

open_b = entry.find('[', entry.find('desp:'))
close_b = entry.find(']', open_b)
new_entry = entry[:open_b+1] + desp_str + entry[close_b:]
# Keep tDesp = 183497.74 (actual net total from PDF, not sum of categories)
# because DÉBITO/CRÉDITO NÃO IDENTIFICAD (-11.797,25) reduces the net
# tDesp already set to 183497.74 from previous fix, keep it
print(f"\nCategoria total = {total:,.2f}  tDesp = {dados.despesa_total:,.2f}")
print("(diferença = DÉBITO/CRÉDITO NÃO IDENTIFICAD no PDF)")

bal = bal[:m.start()] + new_entry + bal[m.start()+entry_len:]
c = c[:bal_start] + bal + c[bal_end:]
with open(DASH, 'w', encoding='utf-8') as f:
    f.write(c)
print("\nDashboard atualizado!")
