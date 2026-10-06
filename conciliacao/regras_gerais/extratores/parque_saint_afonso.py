"""
Extrator das regras gerais — Parque Saint Afonso (GCONT).

O cadastro diz `lirba_pdf`, mas o PDF NÃO é ContasData: é o relatório "W0xx" da GCONT (Resumo Financeiro por conta,
'Demonstrativo de Receitas e Despesas Analítico' e 'Movimentação Analítica "<conta>"'). A leitura está em
`extratores/gcont.py`. Alguns meses (jun-dez/2025) são PDF digitalizado com camada de OCR ruim: o extrator confere a
leitura com o Resumo Financeiro e, não fechando, devolve cobertura False com o motivo.
"""
from conciliacao.regras_gerais.extratores.gcont import Extrator as _Gcont


class Extrator(_Gcont):
    pass
