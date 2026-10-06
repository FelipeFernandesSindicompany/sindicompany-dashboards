"""
Leitores do balancete usados SÓ pela Validação de Balancetes.

Por que existe: a injeção dos dashboards usa adapters/*.py (compartilhados).
A auditoria de 05/10/2026 achou erros de leitura nesses adaptadores (categorias
perdidas ou contadas em dobro, página descartada, arquivo errado...). Corrigi-los
lá mudaria o que a injeção mensal lê — e a Validação tem de ser independente dos
dashboards. Então as versões corrigidas ficam aqui, ao lado da Validação, e
adapters/ permanece exatamente como estava.

Como funciona: `get_leitor(condo)` faz o mesmo despacho de adapters.get_adapter
(adapter específico do condomínio > adapter da administradora), mas:
  - para um módulo corrigido neste pacote (lirba_pdf, manager_adm_pdf,
    lello_mhtml, datadigitus_pdf, alliz_pdf, baturite, saint_simon), usa a cópia
    corrigida;
  - adapters específicos de condomínio que HERDAM de um desses (Dueto, Hub,
    Villa Park, Splendor, Padre Carvalho, Blue Sky...) são recarregados em
    isolamento com a base corrigida — o arquivo em adapters/condominios/ não é
    alterado nem importado de volta pelos dashboards;
  - o que não foi corrigido continua vindo de adapters/ (somente leitura).

Os leitores só abrem os ARQUIVOS de prestação de contas (PDF/XLSX); nada aqui
consulta dashboards.
"""
import importlib.util
import sys
from pathlib import Path

_AQUI = Path(__file__).parent
_PREFIXO = "conciliacao.leitores_validacao."

# módulo compartilhado (adapters.X) -> cópia corrigida (arquivo neste pacote)
_FAMILIAS = {
    "adapters.lirba_pdf": "lirba_pdf",
    "adapters.manager_adm_pdf": "manager_adm_pdf",
    "adapters.lello_mhtml": "lello_mhtml",
    "adapters.datadigitus_pdf": "datadigitus_pdf",
    "adapters.alliz_pdf": "alliz_pdf",
}
# adapters específicos de condomínio que foram corrigidos (arquivo neste pacote)
_POR_CONDO = {"baturite": "baturite", "saint_simon": "saint_simon"}
# empresa_gestora -> (módulo corrigido, classe)
_POR_EMPRESA = {
    "lirba_pdf": ("lirba_pdf", "AdapterLirbaPDF"),
    "manager_adm_pdf": ("manager_adm_pdf", "AdapterManagerAdmPDF"),
    "lello_xls": ("lello_mhtml", "AdapterLelloMHTML"),
    "datadigitus_pdf": ("datadigitus_pdf", "AdapterDatadigitusPDF"),
    "alliz_pdf": ("alliz_pdf", "AdapterAllizPDF"),
}

_corrigidos: dict = {}


def _carregar_arquivo(nome: str, caminho: Path, substituir: dict | None = None):
    """Executa `caminho` como um módulo novo chamado `nome`. `substituir`
    ({"adapters.x": módulo}) vale só durante a execução: é o que faz o
    `from adapters.x import Classe` do arquivo carregado receber a versão corrigida."""
    spec = importlib.util.spec_from_file_location(nome, caminho)
    modulo = importlib.util.module_from_spec(spec)
    guardados = {k: sys.modules.get(k) for k in (substituir or {})}
    try:
        sys.modules.update(substituir or {})
        sys.modules[nome] = modulo
        spec.loader.exec_module(modulo)
    except Exception:
        sys.modules.pop(nome, None)
        raise
    finally:
        for k, v in guardados.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return modulo


def _modulos_corrigidos() -> dict:
    """{'adapters.lirba_pdf': <módulo corrigido>, ...}, carregado uma vez."""
    if not _corrigidos:
        for compartilhado, stem in _FAMILIAS.items():
            _corrigidos[compartilhado] = _carregar_arquivo(_PREFIXO + stem, _AQUI / f"{stem}.py")
    return _corrigidos


def get_leitor(condo: dict):
    """Instância do adaptador de leitura para a Validação deste condomínio."""
    import adapters  # compartilhado, só leitura

    corrigidos = _modulos_corrigidos()
    condo_id = condo.get("id", "")

    if condo_id in _POR_CONDO:
        mod = _carregar_arquivo(_PREFIXO + "condo_" + condo_id, _AQUI / f"{_POR_CONDO[condo_id]}.py", corrigidos)
        return mod.Adapter(condo)

    especifico = Path(adapters.__file__).parent / "condominios" / f"{condo_id}.py"
    if condo_id and especifico.exists():
        try:
            mod = _carregar_arquivo(_PREFIXO + "condo_" + condo_id, especifico, corrigidos)
            if hasattr(mod, "Adapter"):
                return mod.Adapter(condo)
        except Exception as exc:
            print(f"[AVISO] leitor específico de {condo_id} não carregou na Validação ({exc}); "
                  f"usando o adapter compartilhado.")
            return adapters.get_adapter(condo["empresa_gestora"], condo)

    empresa = condo["empresa_gestora"]
    if empresa in _POR_EMPRESA:
        stem, classe = _POR_EMPRESA[empresa]
        modulo = next(m for k, m in corrigidos.items() if k.endswith("." + stem))
        return getattr(modulo, classe)(condo)
    return adapters.get_adapter(empresa, condo)
