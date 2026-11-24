"""
Extrator das regras gerais — Go Liberdade (Habitacional/Graiche).

Entrega normal: planilha .xlsx (extrator Habitacional). Em out/2026 a administradora passou a enviar o PDF resumido de 6 páginas (Resumo Financeiro
Contábil + Demonstrativo de Despesas com link do portal por lançamento + Posição de Devedores), o MESMO formato do Elo & Elo Duo: a leitura é a do
extrator do Elo (xlsx -> Habitacional; PDF -> ContasData).
"""
from conciliacao.regras_gerais.extratores.elo_elo_duo import Extrator as _Elo


class Extrator(_Elo):
    pass
