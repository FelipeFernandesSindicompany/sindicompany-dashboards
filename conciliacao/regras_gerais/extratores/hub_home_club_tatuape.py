"""
Extrator das regras gerais — Hub Home Club Tatuapé (Lello/Graiche).

Entrega normal: planilha .xls (HTML/MHTML da Lello) -> extrator lello_mhtml. Em out/2026 veio o PDF "Demonstrativo de Contas" (mesmas telas do Elo & Elo
Duo: Resumo Financeiro Contábil, Posição Financeira por conta e Demonstrativo de Despesas): o PDF é lido pelo leitor ContasData.
"""
from pathlib import Path

from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ContasData
from conciliacao.regras_gerais.modelo import DadosRegras


class Extrator(_ContasData):
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        if Path(caminho).suffix.lower() in (".xls", ".xlsx", ".xlsm", ".htm", ".html", ".mhtml"):
            from conciliacao.regras_gerais.extratores.lello_mhtml import Extrator as _Lello
            return _Lello(self.condo).extrair(caminho, mes)
        return super().extrair(caminho, mes)
