"""
Adapter específico para Elo & Elo Duo.
Empresa gestora: habitacional_xlsx
"""
from adapters.habitacional_xlsx import AdapterHabitacionalXLSX


class Adapter(AdapterHabitacionalXLSX):
    """Adapter de Elo & Elo Duo — herda do genérico; override aqui quando necessário."""
    pass
