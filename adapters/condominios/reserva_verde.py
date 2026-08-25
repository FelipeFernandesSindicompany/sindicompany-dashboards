"""
Adapter específico para Reserva Verde.
Empresa gestora: sk_condominios_pdf
"""
from adapters.sk_condominios_pdf import AdapterSKCondominiosPDF


class Adapter(AdapterSKCondominiosPDF):
    """Adapter de Reserva Verde — herda do genérico; override aqui quando necessário."""
    pass
