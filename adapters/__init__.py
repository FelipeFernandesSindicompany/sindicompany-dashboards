import importlib
from pathlib import Path

from adapters.habitacional_xlsx import AdapterHabitacionalXLSX
from adapters.lello_mhtml import AdapterLelloMHTML
from adapters.lirba_pdf import AdapterLirbaPDF
from adapters.datadigitus_pdf import AdapterDatadigitusPDF
from adapters.iello_pdf import AdapterIelloPDF
from adapters.lfc_xlsx import AdapterLFCXLSX
from adapters.manager_adm_pdf import AdapterManagerAdmPDF
from adapters.auxiliadora_xls import AdapterAuxiliadoraXLS
from adapters.sk_condominios_pdf import AdapterSKCondominiosPDF
from adapters.alliz_pdf import AdapterAllizPDF

# Mantidos para compatibilidade com o condomínio de exemplo
from adapters.empresa_a import AdapterEmpresaA
from adapters.empresa_b import AdapterEmpresaB

ADAPTERS = {
    # Formatos reais
    "habitacional_xlsx":  AdapterHabitacionalXLSX,
    "lfc_xlsx":           AdapterLFCXLSX,
    "lello_xls":          AdapterLelloMHTML,      # XLS Lello = MHTML disfarçado
    "auxiliadora_xls":    AdapterAuxiliadoraXLS,  # XLS Auxiliadora Predial = OLE2 binário
    "lirba_pdf":          AdapterLirbaPDF,
    "datadigitus_pdf":    AdapterDatadigitusPDF,
    "iello_pdf":          AdapterIelloPDF,
    "manager_adm_pdf":    AdapterManagerAdmPDF,
    "sk_condominios_pdf": AdapterSKCondominiosPDF,
    "alliz_pdf":          AdapterAllizPDF,
    # Legado / exemplos
    "empresa_a": AdapterEmpresaA,
    "empresa_b": AdapterEmpresaB,
}

_CONDO_CACHE: dict | None = None


def _condo_adapters() -> dict:
    """
    Carrega adapters específicos de adapters/condominios/{condo_id}.py.
    Cada arquivo deve exportar uma classe chamada 'Adapter'.
    Cache populado uma vez na primeira chamada.
    """
    global _CONDO_CACHE
    if _CONDO_CACHE is not None:
        return _CONDO_CACHE
    _CONDO_CACHE = {}
    condominios_dir = Path(__file__).parent / "condominios"
    if not condominios_dir.exists():
        return _CONDO_CACHE
    for py in sorted(condominios_dir.glob("[!_]*.py")):
        mod_name = f"adapters.condominios.{py.stem}"
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "Adapter"):
                _CONDO_CACHE[py.stem] = mod.Adapter
        except Exception as exc:
            print(f"[AVISO] adapter específico {py.name}: {exc}")
    return _CONDO_CACHE


def get_adapter(empresa_id: str, config: dict):
    """
    Retorna a instância de adapter correta para o condomínio.

    Prioridade:
      1. Adapter específico em adapters/condominios/{condo_id}.py
      2. Adapter genérico por empresa_gestora (dict ADAPTERS)
    """
    condo_id = config.get("id", "")

    # 1. Adapter específico do condomínio
    if condo_id:
        condo_cls = _condo_adapters().get(condo_id)
        if condo_cls:
            return condo_cls(config)

    # 2. Adapter genérico por empresa
    cls = ADAPTERS.get(empresa_id)
    if not cls:
        raise ValueError(
            f"Adapter não encontrado para '{empresa_id}'. "
            f"Disponíveis: {list(ADAPTERS.keys())}"
        )
    return cls(config)
