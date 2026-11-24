"""
Conciliador específico — Go Liberdade.

Planilha .xlsx (Habitacional) -> conciliador Habitacional, como sempre. PDF resumido com links do portal GoControleDocumentos da Graiche (out/2026,
6 páginas) -> o mesmo conciliador do Elo & Elo Duo (cada linha do Demonstrativo de Despesas com link vira `despesa_listada` + `comprovante_anexado`).
"""
from conciliacao.condominios.elo_elo_duo import Conciliador as _ConciliadorElo


class Conciliador(_ConciliadorElo):
    pass
