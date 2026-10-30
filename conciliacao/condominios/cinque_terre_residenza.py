"""
Conciliador específico — Cinque Terre Residenza.

Cadastrado como empresa_gestora="habitacional_xlsx" (planilha "prestacao_contas_M_AAAA.xlsx", com os links dos anexos). Em set/2026 a
administradora enviou um PDF ESCANEADO de 5 páginas (Demonstrativo de Despesas, Posição Financeira, Conciliação Bancária e Resumo Financeiro
Contábil), sem comprovantes: não há o que conferir por comprovante — as regras gerais (extrator por OCR em
regras_gerais/extratores/cinque_terre_residenza.py) é que leem o arquivo, e o relatório traz o aviso de escopo. O formato é escolhido pela extensão.
"""
from pathlib import Path

from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX


class Conciliador(ConciliadorHabitacionalXLSX):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith(".pdf"):
            return []
        return super().extrair_comprovantes(caminho)
