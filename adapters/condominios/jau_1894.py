"""
Adapter específico para Jaú 1894.
Empresa gestora: lello_pdf — sem implementação Python.
"""
from adapters.base import AdapterBase, DadosFinanceiros
from pathlib import Path


class Adapter(AdapterBase):
    """Stub para Jaú 1894: 'lello_pdf' não implementado."""

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Jaú 1894: adapter 'lello_pdf' não implementado — injeção manual.")
