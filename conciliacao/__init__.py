"""
Registry de conciliadores por administradora — espelha adapters/__init__.py::get_adapter.

Prioridade:
  1. Conciliador específico em conciliacao/condominios/{condo_id}.py (classe `Conciliador`)
  2. Conciliador genérico por empresa_gestora (dict CONCILIADORES)
"""
import importlib
from pathlib import Path

from conciliacao.addomus_pdf import ConciliadorAddomusPDF
from conciliacao.lirba_pdf import ConciliadorLirbaPDF
from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.datadigitus_pdf import ConciliadorDatadigitusPDF
from conciliacao.consvicta_pdf import ConciliadorConsvictaPDF
from conciliacao.lello_xls import ConciliadorLelloXLS
from conciliacao.alliz_pdf import ConciliadorAllizPDF
from conciliacao.auxiliadora_xls import ConciliadorAuxiliadoraXLS

CONCILIADORES = {
    "addomus_pdf": ConciliadorAddomusPDF,
    "lirba_pdf": ConciliadorLirbaPDF,
    "habitacional_xlsx": ConciliadorHabitacionalXLSX,
    # "lfc_xlsx" (ex.: Guaratambé) é a mesma estrutura de planilha do
    # Habitacional (Nº Lançto./Data/Anexo/Histórico/Valor/Total, hyperlink
    # "Link" na coluna Anexo) — confirmado em dados reais. Reaproveita.
    "lfc_xlsx": ConciliadorHabitacionalXLSX,
    "datadigitus_pdf": ConciliadorDatadigitusPDF,
    "consvicta_pdf": ConciliadorConsvictaPDF,
    "lello_xls": ConciliadorLelloXLS,
    "alliz_pdf": ConciliadorAllizPDF,
    "auxiliadora_xls": ConciliadorAuxiliadoraXLS,
    # "gk_pdf" (administradora GK ADM, ex.: Ciudad Real) usa o MESMO software
    # de exportação ContasData do Lirba — mesmíssima estrutura de
    # "Demonstrativo de Despesas"/"Comprovante de Despesa" (confirmado em
    # dados reais), só o adapter de demonstrativo tem regras próprias
    # (ver adapters/gk_pdf.py). Reaproveita a classe sem duplicar.
    "gk_pdf": ConciliadorLirbaPDF,
    # "manager_adm_pdf" (ex.: Dueto Morumbi, Fatto Morumbi) também é
    # ContasData — só tem uma coluna extra "Nº lancto." antes da data (ver
    # conciliacao/lirba_pdf.py::_RE_DATA_INICIO).
    "manager_adm_pdf": ConciliadorLirbaPDF,
}

_CONDO_CACHE: dict | None = None


def _condo_conciliadores() -> dict:
    global _CONDO_CACHE
    if _CONDO_CACHE is not None:
        return _CONDO_CACHE
    _CONDO_CACHE = {}
    condominios_dir = Path(__file__).parent / "condominios"
    if not condominios_dir.exists():
        return _CONDO_CACHE
    for py in sorted(condominios_dir.glob("[!_]*.py")):
        mod_name = f"conciliacao.condominios.{py.stem}"
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "Conciliador"):
                _CONDO_CACHE[py.stem] = mod.Conciliador
        except Exception as exc:
            print(f"[AVISO] conciliador específico {py.name}: {exc}")
    return _CONDO_CACHE


def get_conciliador(empresa_id: str, config: dict):
    """Retorna a instância de conciliador correta para o condomínio."""
    condo_id = config.get("id", "")

    if condo_id:
        condo_cls = _condo_conciliadores().get(condo_id)
        if condo_cls:
            return condo_cls(config)

    cls = CONCILIADORES.get(empresa_id)
    if not cls:
        raise ValueError(
            f"Conciliador não encontrado para '{empresa_id}'. "
            f"Disponíveis: {list(CONCILIADORES.keys())}"
        )
    return cls(config)
