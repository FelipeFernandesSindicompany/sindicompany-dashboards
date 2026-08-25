"""
Adapter específico para Port Saint Tropez.
Empresa gestora: habitacional_xlsx
"""
from adapters.habitacional_xlsx import AdapterHabitacionalXLSX


class Adapter(AdapterHabitacionalXLSX):
    """Adapter de Port Saint Tropez — herda do genérico; override aqui quando necessário."""
    pass
