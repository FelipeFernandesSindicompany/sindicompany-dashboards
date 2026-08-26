"""
Adapter específico para NYC Berrini.
Empresa gestora: lirba_pdf (Lirba/Webware)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRAS EXCLUSIVAS DESTE CONDOMÍNIO — NÃO COMPARTILHAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CATEGORIAS DE DESPESA (nomes exibidos no dashboard):
  • Pessoal          ← PDF: PESSOAL
  • Consumo          ← PDF: CONSUMOS / CONSUMO
  • Contratos        ← PDF: CONTRATOS
  • Manutenção       ← PDF: MANUTENCAO / MANUTENÇÃO / MANUT/CONSERV. CONTRAT. / MANUT/CONSERV. ESPORÁD.
  • Impostos e Taxas ← PDF: IMPOSTOS E TAXAS
  • Outros           ← PDF: OUTROS / AQUISICOES / AQUISIÇÕES
  • ADMINISTRATIVO   ← permanece como ADMINISTRATIVO (categoria separada)
  • ENCARGOS SOCIAIS ← PDF: ENCARGOS / ENCARGOS SOCIAIS

O mapeamento cat_map está configurado em config/condominios.json.
"""
from adapters.lirba_pdf import AdapterLirbaPDF


class Adapter(AdapterLirbaPDF):
    """Adapter de NYC Berrini — herda do genérico lirba_pdf."""
    pass
