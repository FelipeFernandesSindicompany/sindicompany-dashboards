"""
Adapter específico para Sublime.
Empresa gestora: habitacional_xlsx
"""
from adapters.habitacional_xlsx import AdapterHabitacionalXLSX


class Adapter(AdapterHabitacionalXLSX):
    """Adapter de Sublime — herda do genérico; override aqui quando necessário."""
    pass
