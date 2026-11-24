"""
Conciliador específico — Hub Home Club Tatuapé.

Planilha .xls (Lello/HTML) -> conciliador Lello, como sempre. PDF "Demonstrativo de Contas" (out/2026, 6 páginas: Resumo Financeiro + Demonstrativo de Despesas
com "Nº lancto." e um link do portal GoControleDocumentos da Graiche por lançamento) -> o mesmo conciliador do Elo & Elo Duo (cada linha com link vira
`despesa_listada` + `comprovante_anexado`).
"""
from pathlib import Path

from conciliacao.condominios.elo_elo_duo import Conciliador as _ConciliadorElo
from conciliacao.lello_xls import ConciliadorLelloXLS


class Conciliador(_ConciliadorElo):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xls", ".xlsx", ".xlsm")):
            return ConciliadorLelloXLS(self.config).extrair_comprovantes(caminho)
        return super().extrair_comprovantes(caminho)
