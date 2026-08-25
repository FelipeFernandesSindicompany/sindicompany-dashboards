"""
Adapter específico para Demonstração.
Empresa gestora: demo — sem implementação Python.
"""
from adapters.base import AdapterBase, DadosFinanceiros
from pathlib import Path


class Adapter(AdapterBase):
    """Stub para Demonstração: 'demo' não implementado."""

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Demonstração: adapter 'demo' não implementado — injeção manual.")
