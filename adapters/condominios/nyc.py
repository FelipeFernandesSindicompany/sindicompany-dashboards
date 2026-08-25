"""
Adapter específico para NYC.
Empresa gestora: lirba_pdf
"""
from adapters.lirba_pdf import AdapterLirbaPDF


class Adapter(AdapterLirbaPDF):
    """Adapter de NYC — herda do genérico; override aqui quando necessário."""
    pass
