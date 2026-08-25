"""
Adapter específico para Gardens Living Club I.
Empresa gestora: ucondo_pdf — sem implementação Python.
"""
from adapters.base import AdapterBase, DadosFinanceiros
from pathlib import Path


class Adapter(AdapterBase):
    """Stub para Gardens Living Club I: 'ucondo_pdf' não implementado."""

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Gardens Living Club I: adapter 'ucondo_pdf' não implementado — injeção manual.")
