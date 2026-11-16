"""
Conciliador específico — Splendor Square (Lello).

  .xls (planilha HTML da Lello, até jul/2026)             -> ConciliadorLelloXLS
  PDF "Pasta Digital" completo (~500 págs, ago-set/2026)   -> ConciliadorLirbaPDF (conciliador de listagem ContasData/GK)
  PDF resumido COM LINKS (7 págs, out/2026 em diante)      -> cada linha do "Demonstrativo de Despesas" traz o Nº do lançamento (8 dígitos) e um link
                                                              para o portal GoControleDocumentos (GK ADM; mesmo protocolo do Cores/Ciudad Real,
                                                              conciliacao/gocontroledocumentos.py): cada linha com link vira `despesa_listada` +
                                                              `comprovante_anexado`. Reaproveita a leitura do Cores (mesmo layout "Demonstrativo de
                                                              Contas" com "Nº lancto." e %).
"""
from pathlib import Path

from conciliacao.condominios.cores import Conciliador as _ConciliadorCores
from conciliacao.condominios.patricia import _links_de_despesa
from conciliacao.lello_xls import ConciliadorLelloXLS
from conciliacao.lirba_pdf import ConciliadorLirbaPDF

_PAGINAS_PASTA_DIGITAL = 30        # acima disso é a Pasta Digital completa; o resumo mensal tem ~7 páginas


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        caminho = Path(caminho)
        if caminho.suffix.lower() != ".pdf":
            return ConciliadorLelloXLS(self.config).extrair_comprovantes(caminho)
        import fitz
        with fitz.open(str(caminho)) as doc:
            paginas = len(doc)
        if paginas <= _PAGINAS_PASTA_DIGITAL and _links_de_despesa(caminho):
            return _ConciliadorCores._extrair_pdf_com_links(self, caminho)
        return super().extrair_comprovantes(caminho)
