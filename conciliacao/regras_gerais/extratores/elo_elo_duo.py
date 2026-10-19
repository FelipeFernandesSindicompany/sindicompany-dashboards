"""
Extrator das regras gerais — Elo & Elo Duo Caminhos da Lapa (Habitacional).

Entrega normal: planilha .xlsx ("Demonstrações Por Conta", prestacao_contas_N_2026.xlsx) -> extrator Habitacional. Em ago/2026 a administradora
passou a enviar também/apenas um PDF de 4 páginas (Resumo Financeiro Contábil + Demonstrativo de Despesas + Posição de Devedores, sem receitas
nem comprovantes): o formato é escolhido pela EXTENSÃO do arquivo; o PDF é lido pelo leitor ContasData (mesmas telas).
"""
from pathlib import Path

from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ContasData
from conciliacao.regras_gerais.modelo import DadosRegras


class Extrator(_ContasData):
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        if Path(caminho).suffix.lower() in (".xlsx", ".xlsm"):
            from conciliacao.regras_gerais.extratores.habitacional_xlsx import Extrator as _Planilha
            return _Planilha(self.condo).extrair(caminho, mes)
        dados = super().extrair(caminho, mes)
        dados.avisos.append("arquivo em PDF resumido (Resumo Financeiro + Demonstrativo de Despesas): sem demonstrativo de receitas, rendimentos "
                            "nem comprovantes")
        return dados
