"""
Adapter específico para Go Liberdade.
Empresa gestora: habitacional_xlsx
"""
from adapters.habitacional_xlsx import AdapterHabitacionalXLSX


class Adapter(AdapterHabitacionalXLSX):
    """Adapter de Go Liberdade — herda do genérico; override aqui quando necessário."""
    pass
