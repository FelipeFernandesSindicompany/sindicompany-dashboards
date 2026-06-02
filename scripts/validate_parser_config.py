"""
Valida que o sistema de parser_config funciona corretamente.
Lê o condominios.json, instancia o adapter com o parser_config do condomínio
e testa a extração de categorias.
"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

with open(os.path.join(os.path.dirname(__file__), '..', 'config', 'condominios.json'),
          encoding='utf-8') as f:
    cfg = json.load(f)

# Vibra Butantã - verificação completa
vib = next(c for c in cfg['condominios'] if c['id'] == 'vibra_butanta')
print("=== Vibra Butantã parser_config ===")
print(json.dumps(vib['parser_config'], ensure_ascii=False, indent=2))

from adapters.lirba_pdf import AdapterLirbaPDF

adapter = AdapterLirbaPDF(vib)
print(f"\nextract_cats  = {adapter.parser_config.get('extract_cats')}")
print(f"consumo_name  = {adapter.parser_config.get('consumo_name')}")
print(f"iptu_name     = {adapter.parser_config.get('iptu_name')}")
print(f"cat_map       = {len(adapter.parser_config.get('cat_map', {}))} entradas")

PDF_DIR = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Vibra Butantã"

print("\n=== Teste abr26 (Posição Financeira) ===")
dados = adapter.ler_pdf(os.path.join(PDF_DIR, 'Prestação de Contas 04.2026.PDF'), '2026-04')
cats = sorted(dados.categorias_despesa.items(), key=lambda x: -x[1])
total = sum(v for _,v in cats)
print(f"Categorias ({len(cats)}), soma={total:,.2f}, tDesp={dados.despesa_total:,.2f}")
for c,v in cats:
    print(f"  {c}: {v:,.2f}")

print("\n=== Teste mar26 ===")
dados2 = adapter.ler_pdf(os.path.join(PDF_DIR, 'Prestação de Contas 03.2026.PDF'), '2026-03')
cats2 = sorted(dados2.categorias_despesa.items(), key=lambda x: -x[1])
total2 = sum(v for _,v in cats2)
print(f"Categorias ({len(cats2)}), soma={total2:,.2f}, tDesp={dados2.despesa_total:,.2f}")
for c,v in cats2:
    print(f"  {c}: {v:,.2f}")

# Verificar que Blue Sky e Gravura usam total_da_conta
print("\n=== Blue Sky / Gravura — extract_cats ===")
for cid in ['residencial_blue_sky', 'gravura_residencial', 'gravura_studio']:
    c = next(x for x in cfg['condominios'] if x['id'] == cid)
    print(f"  {c['nome']}: {c.get('parser_config', {}).get('extract_cats', 'auto')}")

# Verificar NYC
nyc = next(x for x in cfg['condominios'] if x['id'] == 'nyc')
print(f"  {nyc['nome']}: {nyc.get('parser_config', {}).get('extract_cats', 'auto')}")

# Contar por método
from collections import Counter
lirba_conds = [c for c in cfg['condominios'] if c['empresa_gestora'] == 'lirba_pdf']
metodos = Counter(c.get('parser_config', {}).get('extract_cats', 'auto') for c in lirba_conds)
print(f"\n=== Distribuição de extract_cats (lirba_pdf) ===")
for m, n in sorted(metodos.items()):
    print(f"  {m}: {n} condomínios")
