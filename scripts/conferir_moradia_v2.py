"""
Conferencia completa Praca Saude - Moradia
Usa o adapter oficial para extrair todos os valores e compara com o dashboard
Inclui verificacao de FAC (juros + multas recebidos)
"""
import sys, os, re
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
# UTF-8 output
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from adapters.lirba_pdf import AdapterLirbaPDF

PDF_DIR = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Analise de Balancete Praca Saude - Moradia"
DASH = os.path.join(ROOT, 'docs', 'Dashboard_Praca_Saude_Moradia.html')

# Try both path variants
if not os.path.exists(PDF_DIR):
    PDF_DIR = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Praça Saúde - Moradia"

DASH_VARIANTS = [
    os.path.join(ROOT, 'docs', 'Dashboard_Praça_Saúde_Moradia.html'),
    os.path.join(ROOT, 'docs', 'Dashboard_Praca_Saude_Moradia.html'),
]
for d in DASH_VARIANTS:
    if os.path.exists(d):
        DASH = d
        break

print(f"PDF_DIR: {PDF_DIR}")
print(f"DASHBOARD: {DASH}")
try:
    n_pdfs = len([f for f in os.listdir(PDF_DIR) if f.endswith('.PDF')])
    print(f"PDFs encontrados: {n_pdfs}")
except FileNotFoundError:
    print(f"[ERRO] PDF_DIR nao encontrado: {PDF_DIR}")
print()

MESES_MAP = {
    '04.2025': ('abr25','2025-04'), '05.2025': ('mai25','2025-05'), '06.2025': ('jun25','2025-06'),
    '07.2025': ('jul25','2025-07'), '08.2025': ('ago25','2025-08'), '09.2025': ('set25','2025-09'),
    '10.2025': ('out25','2025-10'), '11.2025': ('nov25','2025-11'), '12.2025': ('dez25','2025-12'),
    '01.2026': ('jan26','2026-01'), '02.2026': ('fev26','2026-02'), '03.2026': ('mar26','2026-03'),
    '04.2026': ('abr26','2026-04'),
}

def get_dashboard_values(chave):
    with open(DASH, encoding='utf-8', errors='replace') as f:
        content = f.read()
    idx = content.find(f'{chave}:')
    if idx < 0: return None
    segment = content[idx:idx+1000]
    def num(pattern):
        m = re.search(pattern, segment)
        return float(m.group(1)) if m else 0.0
    tAtual = num(r'tAtual:\s*([\d.]+)')
    inad   = num(r'\binad:\s*([\d.]+)')
    fac    = num(r'\bfac:\s*([\d.]+)')
    banco_m = re.search(r'banco:\s*\{cc:([\d.-]+),\s*cdb:([\d.-]+),\s*priv:([\d.-]+)\}', segment)
    cc  = float(banco_m.group(1)) if banco_m else 0.0
    cdb = float(banco_m.group(2)) if banco_m else 0.0
    prv = float(banco_m.group(3)) if banco_m else 0.0
    return {'tAtual': tAtual, 'inad': inad, 'fac': fac, 'cc': cc, 'cdb': cdb, 'priv': prv}

adapter = AdapterLirbaPDF({'id': 'praca_saude_moradia', 'nome': 'PS Moradia'})

header = f"{'MES':<7} | {'tAtual PDF':>12} | {'tAtual Dash':>12} | {'Inad PDF':>10} | {'Inad Dash':>10} | {'FAC PDF':>8} | {'CC':>10} | {'CDB':>10} | STATUS"
print(header)
print("-" * len(header))

corrections = {}

try:
    pdfs = sorted([f for f in os.listdir(PDF_DIR) if f.endswith('.PDF') and 'Presta' in f])
except FileNotFoundError:
    print(f"[ERRO] Diretorio nao encontrado: {PDF_DIR}")
    sys.exit(1)

for pdf_file in pdfs:
    m = re.search(r'(\d{2}\.\d{4})', pdf_file)
    if not m: continue
    mes_str = m.group(1)
    if mes_str not in MESES_MAP: continue
    chave, mes_fmt = MESES_MAP[mes_str]

    pdf_path = os.path.join(PDF_DIR, pdf_file)
    try:
        dados = adapter.ler_pdf(pdf_path, mes_fmt)
    except Exception as e:
        print(f"{chave:<7} | ERRO: {e}")
        continue

    dash = get_dashboard_values(chave)
    if not dash:
        print(f"{chave:<7} | NAO ENCONTRADO NO DASHBOARD")
        continue

    banco_total_dash = dash['cc'] + dash['cdb'] + dash['priv']

    # Compare
    inad_match  = abs(dados.inadimplencia_valor - dash['inad']) < 1
    total_match = abs(dados.saldo_atual - dash['tAtual']) < 1

    issues = []
    if not inad_match: issues.append(f"INAD: PDF={dados.inadimplencia_valor:.2f} vs DASH={dash['inad']:.2f}")
    if not total_match: issues.append(f"TOTAL: PDF={dados.saldo_atual:.2f} vs DASH={dash['tAtual']:.2f}")

    status = "OK" if not issues else " | ".join(issues)

    fac_val = getattr(dados, 'fac', 0.0)
    print(f"{chave:<7} | {dados.saldo_atual:>12,.2f} | {dash['tAtual']:>12,.2f} | {dados.inadimplencia_valor:>10,.2f} | {dash['inad']:>10,.2f} | {fac_val:>8,.2f} | {dados.banco_cc:>10,.2f} | {dados.banco_cdb:>10,.2f} | {status}")

    if issues:
        corrections[chave] = {
            'saldo_atual': dados.saldo_atual,
            'inad': dados.inadimplencia_valor,
            'fac': fac_val,
            'banco_cc': dados.banco_cc,
            'banco_cdb': dados.banco_cdb,
            'banco_priv': dados.banco_priv,
            'dash': dash,
            'issues': issues
        }

print()
print(f"Meses com discrepancias: {len(corrections)}")
for k, v in sorted(corrections.items()):
    print(f"\n  {k}: {'; '.join(v['issues'])}")
    print(f"    PDF extrai  -> inad={v['inad']:.2f}  fac={v['fac']:.2f}  banco_cc={v['banco_cc']:.2f}  banco_cdb={v['banco_cdb']:.2f}  banco_priv={v['banco_priv']:.2f}")
    print(f"    Dashboard   -> inad={v['dash']['inad']:.2f}  fac={v['dash']['fac']:.2f}  cc={v['dash']['cc']:.2f}  cdb={v['dash']['cdb']:.2f}  priv={v['dash']['priv']:.2f}")
