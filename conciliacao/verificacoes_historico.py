"""
Histórico de categorias já vistas em conciliações anteriores do mesmo
condomínio — usado só como heurística de "subconta atípica"
(conciliacao/matching.py::achados_subconta_atipica), nunca como fonte de
verdade financeira.

Lê os próprios registros_comprovantes.json já gerados pelo motor de
conciliação (data/<pasta_dados>/conciliacao/<mes>/), não o dashboard
publicado — mantém a mesma regra já estabelecida em
conciliacao/demonstrativo_reader.py de não ancorar validação em dados já
publicados, só nos arquivos-fonte/artefatos da própria conciliação.
"""
from conciliacao import storage
from conciliacao.base import RegistroComprovante


def _meses_anteriores(mes_atual: str, quantidade: int) -> list[str]:
    ano, mes = (int(x) for x in mes_atual.split("-"))
    resultado = []
    for _ in range(quantidade):
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
        resultado.append(f"{ano:04d}-{mes:02d}")
    return resultado


def categorias_conhecidas(pasta_dados: str, mes_atual: str, meses_lookback: int = 6) -> set[str]:
    """
    Categorias (`categoria_demonstrativo`) vistas em qualquer versão já
    processada dos últimos `meses_lookback` meses anteriores a `mes_atual`
    desse condomínio.

    Conjunto vazio quando não há histórico ainda (primeiro mês processado) —
    quem chama deve tratar isso como "checagem pulada por falta de
    histórico", nunca como "nenhuma categoria é válida" (evita gerar
    falso-positivo em massa no primeiro mês de um condomínio novo).
    """
    categorias: set[str] = set()
    for mes in _meses_anteriores(mes_atual, meses_lookback):
        base_dir = storage.condo_mes_dir(pasta_dados, mes)
        version_dir = storage.latest_version_dir(base_dir)
        if not version_dir:
            continue
        registros = storage.read_dataclass_list(
            version_dir / "registros_comprovantes.json", RegistroComprovante
        )
        categorias.update(r.categoria_demonstrativo for r in registros if r.categoria_demonstrativo)
    return categorias
