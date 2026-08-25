"""
Adapter específico para Fatto Morumbi.
Empresa gestora: manager_adm_pdf
"""
from adapters.manager_adm_pdf import AdapterManagerAdmPDF


class Adapter(AdapterManagerAdmPDF):
    """Adapter de Fatto Morumbi — herda do genérico; override aqui quando necessário."""
    pass
