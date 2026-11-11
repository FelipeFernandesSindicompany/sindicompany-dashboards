"""
Conciliador específico — Residencial Villa Park Osasco (Lello).

  .xls (planilha HTML da Lello, até ago/2026)            -> ConciliadorLelloXLS, como sempre
  PDF "Pasta Digital" completo (~400 págs, set/2026)      -> ConciliadorLirbaPDF, como sempre (conciliador de listagem ContasData)
  PDF resumido COM LINKS (6 págs, out/2026 em diante)    -> cada linha do "Demonstrativo de Despesas" traz um link para o portal
                                                            GoControleDocumentos (mesmo protocolo do Elo/Cores/Patrícia, conciliacao/
                                                            gocontroledocumentos.py): cada linha com link vira `despesa_listada` +
                                                            `comprovante_anexado`. Reaproveita a leitura do Elo (mesmo layout "Demonstrativo
                                                            de Contas" da BBZ: data, histórico, valor, total e %, sem Nº de lançamento).
"""
from pathlib import Path

from conciliacao.condominios.elo_elo_duo import _PAGINAS_PASTA_DIGITAL, Conciliador as _ConciliadorElo
from conciliacao.condominios.patricia import _links_de_despesa
from conciliacao.lello_xls import ConciliadorLelloXLS
from conciliacao.lirba_pdf import ConciliadorLirbaPDF


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        caminho = Path(caminho)
        if caminho.suffix.lower() != ".pdf":
            return ConciliadorLelloXLS(self.config).extrair_comprovantes(caminho)
        import fitz
        with fitz.open(str(caminho)) as doc:
            paginas = len(doc)
        if paginas <= _PAGINAS_PASTA_DIGITAL and _links_de_despesa(caminho):
            return _ConciliadorElo._extrair_pdf_com_links(self, caminho)
        return super().extrair_comprovantes(caminho)
