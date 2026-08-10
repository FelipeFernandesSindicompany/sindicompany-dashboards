from adapters.habitacional_xlsx import AdapterHabitacionalXLSX
from adapters.lello_mhtml import AdapterLelloMHTML
from adapters.lirba_pdf import AdapterLirbaPDF
from adapters.datadigitus_pdf import AdapterDatadigitusPDF
from adapters.iello_pdf import AdapterIelloPDF
from adapters.lfc_xlsx import AdapterLFCXLSX
from adapters.manager_adm_pdf import AdapterManagerAdmPDF
from adapters.auxiliadora_xls import AdapterAuxiliadoraXLS

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
    # Legado / exemplos
    "empresa_a": AdapterEmpresaA,
    "empresa_b": AdapterEmpresaB,
}


def get_adapter(empresa_id: str, config: dict):
    cls = ADAPTERS.get(empresa_id)
    if not cls:
        raise ValueError(
            f"Adapter não encontrado para '{empresa_id}'. "
            f"Disponíveis: {list(ADAPTERS.keys())}"
        )
    return cls(config)
