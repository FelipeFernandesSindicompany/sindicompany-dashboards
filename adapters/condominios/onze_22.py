"""
Adapter específico para Onze 22.
Empresa gestora: habitacional_xlsx
"""
from adapters.habitacional_xlsx import AdapterHabitacionalXLSX


class Adapter(AdapterHabitacionalXLSX):
    """Adapter de Onze 22 — herda do genérico; override aqui quando necessário."""
    pass
