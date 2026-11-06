"""
Conciliador específico — Alvorada.

Cadastrado como empresa_gestora="habitacional_xlsx" (planilha "prestacao_contas_M_AAAA.xlsx", usada até jul/2026), mas a
administradora também entrega a "Pasta Digital" em PDF (ContasData, "Voltar ao índice", Demonstrativo + comprovantes) — mesma
migração do Onze 22. O formato é escolhido pela extensão do arquivo recebido: .xlsx/.xlsm/.xls → leitor de planilha Habitacional;
PDF → ContasData (Lirba).
"""
from pathlib import Path

from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        return super().extrair_comprovantes(caminho)
