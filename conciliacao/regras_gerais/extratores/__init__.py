"""
Extratores das regras gerais: um por FORMATO de arquivo (e, quando um condomínio
foge do padrão da administradora, um específico dele).

Contrato — cada módulo exporta `class Extrator`:

    class Extrator:
        def __init__(self, condo: dict): ...        # cadastro + config da Validação já mesclados
        def extrair(self, caminho: Path, mes: str) -> DadosRegras: ...

`extrair` lê SOMENTE o arquivo de prestação de contas (PDF/XLSX/XLS) e devolve
conciliacao.regras_gerais.modelo.DadosRegras com:
  receitas     — todas as linhas de receita/crédito de cada conta, COM SINAL
  contas       — saldo anterior/atual, créditos, débitos e rendimento de cada conta
  lancamentos  — cada despesa do Demonstrativo de Despesas, com a subconta/categoria do arquivo
  cobertura    — quais dessas três coisas este formato permite ler; o que não permite
                 fica False com o motivo em `motivos_nao_cobertos` (nunca finja ler).

Nunca lança por causa do conteúdo do arquivo: se algo não puder ser lido, devolve
cobertura False + motivo, ou levanta ValueError com mensagem clara (quem chama avisa
e segue sem aquelas regras).

Despacho (como adapters/conciliacao): extrator do condomínio > extrator do formato.
"""
import importlib
import importlib.util
from pathlib import Path
from typing import Optional

# empresa_gestora -> módulo deste pacote. O módulo pode ainda não existir (formato em
# implementação): get_extrator devolve None e a Validação marca as regras como "não
# aplicáveis a este formato" com o motivo.
EXTRATORES_POR_EMPRESA: dict[str, str] = {
    "habitacional_xlsx": "habitacional_xlsx",
    "lfc_xlsx": "habitacional_xlsx",
    "lirba_pdf": "contasdata",
    "gk_pdf": "gk",
    "manager_adm_pdf": "manager_adm",
    "convivium_pdf": "convivium",
    "lello_xls": "lello_mhtml",
    "auxiliadora_xls": "auxiliadora_xls",
    "iello_pdf": "balancete_mensal",
    "lello_pdf": "balancete_mensal",
    "datadigitus_pdf": "datadigitus",
    "alliz_pdf": "alliz",
    "consvicta_pdf": "consvicta",
    "ucondo_pdf": "ucondo",
    "addomus_pdf": "addomus",
    "sk_condominios_pdf": "sk_condominios",
}
# Condomínio que foge do padrão da administradora: basta criar o arquivo
# `extratores/<id_do_condominio>.py` — é descoberto sozinho, sem registrar aqui.

_DIR = Path(__file__).parent


def get_extrator(condo: dict) -> Optional[object]:
    """Instância do extrator deste condomínio, ou None se o formato ainda não tem."""
    condo_id = condo.get("id", "")
    nome = condo_id if condo_id and (_DIR / f"{condo_id}.py").exists() else EXTRATORES_POR_EMPRESA.get(condo.get("empresa_gestora", ""))
    if not nome or not (_DIR / f"{nome}.py").exists():
        return None
    modulo = importlib.import_module(f"conciliacao.regras_gerais.extratores.{nome}")
    return modulo.Extrator(condo)
