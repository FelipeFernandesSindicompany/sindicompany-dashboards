"""
Conciliador específico — Baturité.

Empresa gestora mudou de "habitacional_xlsx" (planilha) para o sistema
ContasData (PDF) a partir de 2026 — confirmado em dados reais: a pasta de
projeto só tem arquivos ".xlsx" até 2025 e só ".pdf" a partir de 2026 (ver
também adapters/condominios/baturite.py, mesmo motivo). A estrutura do
"Demonstrativo de Despesas" é a mesma família ContasData/Lirba, só sem
coluna de data por lançamento — já suportado por
conciliacao/lirba_pdf.py::ConciliadorLirbaPDF após tornar o cabeçalho
"Data Histórico Valor Total" tolerante à ausência de "Data".

Os meses em planilha (até 2025) continuam existindo na pasta: o formato é escolhido pela extensão do arquivo
(.xlsx/.xls → leitor de planilha Habitacional; PDF → ContasData), para não quebrar com "No /Root object!"
ao receber uma planilha (mesmo caso de port_saint_tropez.py).
"""
from pathlib import Path

from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        return super().extrair_comprovantes(caminho)
