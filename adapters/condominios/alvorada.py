"""
Adapter específico para Alvorada.
Empresa gestora: habitacional_xlsx
"""
from adapters.habitacional_xlsx import AdapterHabitacionalXLSX


class Adapter(AdapterHabitacionalXLSX):
    """Adapter de Alvorada — herda do genérico; override aqui quando necessário."""
    pass
