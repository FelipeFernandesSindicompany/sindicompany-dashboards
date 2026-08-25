"""
Adapter específico para Vera Cruz.
Empresa gestora: convivium_pdf — sem implementação Python.
"""
from adapters.base import AdapterBase, DadosFinanceiros
from pathlib import Path


class Adapter(AdapterBase):
    """Stub para Vera Cruz: 'convivium_pdf' não implementado."""

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Vera Cruz: adapter 'convivium_pdf' não implementado — injeção manual.")
