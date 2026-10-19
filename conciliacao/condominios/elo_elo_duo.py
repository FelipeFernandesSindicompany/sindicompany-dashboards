"""
Conciliador específico — Elo & Elo Duo Caminhos da Lapa.

Planilha .xlsx (Habitacional, com hyperlink "Link" por lançamento) -> conciliador Habitacional, como sempre.
PDF resumido (4 págs, só Resumo Financeiro + Demonstrativo de Despesas, ago/2026) -> não traz comprovantes: nenhum registro de comprovante; a
validação segue só pelas regras gerais (lidas do próprio PDF) e o relatório avisa o escopo.
"""
from pathlib import Path

from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX


class Conciliador(ConciliadorHabitacionalXLSX):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if Path(caminho).suffix.lower() == ".pdf":
            return []
        return super().extrair_comprovantes(caminho)
