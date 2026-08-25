"""
Adapter específico para Victoria.
Empresa gestora: habitacional_xlsx
"""
from adapters.habitacional_xlsx import AdapterHabitacionalXLSX


class Adapter(AdapterHabitacionalXLSX):
    """Adapter de Victoria — herda do genérico; override aqui quando necessário."""
    pass
