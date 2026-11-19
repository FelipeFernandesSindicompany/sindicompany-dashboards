"""
Conciliador específico — Vibra Butantã (administradora Oma, sistema GK/GoControleDocumentos, ContasData).

  PDF "Pasta Digital" completo (centenas de páginas, até jul/2026) -> ConciliadorLirbaPDF (conciliador de listagem ContasData), como sempre
  PDF resumido COM LINKS (3 a 14 págs, ago/2026 em diante)        -> cada linha do "Demonstrativo de Despesas" traz o Nº do lançamento (8 dígitos) e um link
                                                                     para o portal GoControleDocumentos (sistemas.gk.com.br; mesmo protocolo do Cores/Highlights,
                                                                     conciliacao/gocontroledocumentos.py): cada linha com link vira `despesa_listada` +
                                                                     `comprovante_anexado`. Reaproveita a leitura do Cores (mesmo layout com "Nº lancto." e %).
"""
from pathlib import Path

from conciliacao.condominios.cores import Conciliador as _ConciliadorCores
from conciliacao.condominios.patricia import _links_de_despesa
from conciliacao.lirba_pdf import ConciliadorLirbaPDF

_PAGINAS_PASTA_DIGITAL = 30        # acima disso é a Pasta Digital completa; o resumo mensal tem poucas páginas


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        caminho = Path(caminho)
        import fitz
        with fitz.open(str(caminho)) as doc:
            paginas = len(doc)
        if paginas <= _PAGINAS_PASTA_DIGITAL and _links_de_despesa(caminho):
            return _ConciliadorCores._extrair_pdf_com_links(self, caminho)
        return super().extrair_comprovantes(caminho)
