"""
Conciliador específico — Maison Patrícia (Auxiliadora Predial).

Planilha .xls (até ago/2026) -> conciliador Auxiliadora, como sempre.
PDF "Demonstrativo de Contas" de 8 páginas (set/2026: posição por conta, despesas e receitas, SEM comprovantes) -> nenhum registro de comprovante;
a validação segue só pelas regras gerais, lidas do próprio PDF, e o relatório avisa o escopo.
"""
from pathlib import Path

from conciliacao.auxiliadora_xls import ConciliadorAuxiliadoraXLS


class Conciliador(ConciliadorAuxiliadoraXLS):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if Path(caminho).suffix.lower() == ".pdf":
            return []
        return super().extrair_comprovantes(caminho)
