"""
Conciliador específico — Alvorada.

Cadastrado como empresa_gestora="habitacional_xlsx" (planilha "prestacao_contas_M_AAAA.xlsx", usada até jul/2026), mas a
administradora também entrega a "Pasta Digital" em PDF (ContasData, "Voltar ao índice", Demonstrativo + comprovantes) — mesma
migração do Onze 22. O formato é escolhido pela extensão do arquivo recebido: .xlsx/.xlsm/.xls → leitor de planilha Habitacional;
PDF → ContasData (Lirba).

PDF RESUMIDO COM LINKS (set/2026 em diante, ~9 páginas): cada linha do Demonstrativo de Despesas traz o Nº do lançamento e um link do portal
GoControleDocumentos; cada linha com link vira `despesa_listada` + `comprovante_anexado` (mesmo tratamento do Highlights Dr. Nelson Moretti).
"""
from pathlib import Path

from conciliacao.condominios.cores import Conciliador as _ConciliadorCores
from conciliacao.condominios.patricia import _links_de_despesa
from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        import fitz
        with fitz.open(str(caminho)) as doc:
            paginas = len(doc)
        if paginas <= 30 and _links_de_despesa(Path(caminho)):
            return _ConciliadorCores._extrair_pdf_com_links(self, Path(caminho))
        return super().extrair_comprovantes(caminho)
