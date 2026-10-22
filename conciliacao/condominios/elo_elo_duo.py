"""
Conciliador específico — Elo & Elo Duo Caminhos da Lapa.

Planilha .xlsx (Habitacional, com hyperlink "Link" por lançamento) -> conciliador Habitacional, como sempre.
PDF "Pasta Digital" completo (ContasData, "Voltar ao índice", ~545 págs com o Demonstrativo e os comprovantes — jul/2026) -> leitor ContasData
(Lirba), igual ao Onze 22/Baturité/Port Saint Tropez.
PDF resumido (4 págs, só Resumo Financeiro + Demonstrativo de Despesas, ago/2026) -> não traz comprovantes: nenhum registro de comprovante; a
validação segue só pelas regras gerais (lidas do próprio PDF) e o relatório avisa o escopo.
"""
from pathlib import Path

from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF

_PAGINAS_PASTA_DIGITAL = 30        # acima disso o PDF é a Pasta Digital com comprovantes; o resumo mensal tem 4 páginas


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        import fitz
        with fitz.open(str(caminho)) as doc:
            paginas = len(doc)
        if paginas <= _PAGINAS_PASTA_DIGITAL:
            return []
        return super().extrair_comprovantes(caminho)
