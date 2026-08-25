"""
Adapter específico para Baturité.
Empresa gestora: habitacional_xlsx
"""
from adapters.habitacional_xlsx import AdapterHabitacionalXLSX


class Adapter(AdapterHabitacionalXLSX):
    """Adapter de Baturité — herda do genérico; override aqui quando necessário."""
    pass
