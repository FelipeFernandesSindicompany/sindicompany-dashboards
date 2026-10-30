"""
Adapter específico para Splendor Square.
Empresa gestora: habitacional_xlsx (PDF ContasData desde 2026)
"""
from adapters.habitacional_xlsx import AdapterHabitacionalXLSX


class Adapter(AdapterHabitacionalXLSX):
    """Adapter de Splendor Square — herda do genérico; override aqui quando necessário."""
    pass
