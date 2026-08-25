"""
Adapter específico para Saint Simon.
Empresa gestora: ucondo_pdf — sem implementação Python.
"""
from adapters.base import AdapterBase, DadosFinanceiros
from pathlib import Path


class Adapter(AdapterBase):
    """Stub para Saint Simon: 'ucondo_pdf' não implementado."""

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Saint Simon: adapter 'ucondo_pdf' não implementado — injeção manual.")
