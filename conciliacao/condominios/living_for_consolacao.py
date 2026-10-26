"""
Conciliador específico — Living For Consolação.

Cadastrado como "habitacional_xlsx" (planilhas até jul/2026), mas em ago/set/2026 o arquivo passou a ser o PDF "Prestação de Contas" completo
(ContasData/desti.net.br: "Comprovante de Despesa NNNN" embutidos). O formato é escolhido pela extensão: .xlsx/.xls -> leitor de planilha
Habitacional; PDF -> leitor ContasData (Lirba). Mesmo desenho do Port Saint Tropez.
"""
from pathlib import Path

from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        return super().extrair_comprovantes(caminho)
