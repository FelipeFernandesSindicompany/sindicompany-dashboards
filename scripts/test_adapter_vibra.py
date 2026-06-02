"""
Testa o adapter Lirba para todos os meses do Vibra Butantã.
Exibe categorias de despesa extraídas vs. dashboard atual.
"""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from adapters.lirba_pdf import AdapterLirbaPDF

PDF_DIR = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Vibra Butantã"
DASH = os.path.join(os.path.dirname(__file__), '..', 'docs', 'Dashboard_Financeiro_VibraButanta.html')

MESES_MAP = {
    '04.2025': ('abr25','2025-04'), '05.2025': ('mai25','2025-05'),
    '06.2025': ('jun25','2025-06'), '07.2025': ('jul25','2025-07'),
    '08.2025': ('ago25','2025-08'), '09.2025': ('set25','2025-09'),
    '10.2025': ('out25','2025-10'), '11.2025': ('nov25','2025-11'),
    '12.2025': ('dez25','2025-12'), '01.2026': ('jan26','2026-01'),
    '02.2026': ('fev26','2026-02'), '03.2026': ('mar26','2026-03'),
    '04.2026': ('abr26','2026-04'),
}

adapter = AdapterLirbaPDF({'id': 'vibra_butanta', 'nome': 'Vibra Butanta'})

for mes_str, (chave, mes_fmt) in sorted(MESES_MAP.items()):
    pdf = os.path.join(PDF_DIR, f'Prestação de Contas {mes_str}.PDF')
    if not os.path.exists(pdf):
        print(f'{chave}: PDF não encontrado')
        continue
    dados = adapter.ler_pdf(pdf, mes_fmt)
    cats = sorted(dados.categorias_despesa.items(), key=lambda x: -x[1])
    total = sum(v for _,v in cats)
    print(f'\n{chave} ({len(cats)} cats, soma={total:,.2f}, tDesp={dados.despesa_total:,.2f}):')
    for c,v in cats:
        print(f'  {c}: {v:,.2f}')
