"""
Configuração PRÓPRIA do módulo Validação de Balancetes (config/validacao_balancetes.json).

config/condominios.json é o cadastro compartilhado com a injeção dos dashboards e
só é LIDO aqui. Tudo o que a Validação precisa acrescentar por condomínio — pasta
de prestações no OneDrive, ajustes de leitura (cat_map, excluir_contas,
desp_fonte...), motivo pra silenciar o aviso de fechamento — mora no arquivo
próprio, para que mexer na Validação nunca mude o que a injeção dos dashboards lê.

`aplicar(condo)` devolve uma CÓPIA do cadastro com essas entradas mescladas
(dicts como parser_config.cat_map são mesclados, não substituídos).
"""
import copy
import json
from pathlib import Path

CAMINHO = Path(__file__).parent.parent / "config" / "validacao_balancetes.json"
_cache: dict | None = None


def _carregar() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CAMINHO.read_text(encoding="utf-8")).get("condominios", {})
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _mesclar(base: dict, extra: dict) -> dict:
    saida = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(saida.get(k), dict):
            saida[k] = _mesclar(saida[k], v)
        else:
            saida[k] = copy.deepcopy(v)
    return saida


def aplicar(condo: dict) -> dict:
    extra = _carregar().get(condo.get("id", ""))
    return _mesclar(condo, extra) if extra else copy.deepcopy(condo)
