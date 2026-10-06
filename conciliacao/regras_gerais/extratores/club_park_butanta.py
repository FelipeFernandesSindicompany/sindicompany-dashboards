"""
Extrator das regras gerais — Club Park Butantã (GCONT).

O cadastro diz `lirba_pdf`, mas o PDF NÃO é ContasData: é o relatório "W0xx" da GCONT (Resumo Financeiro por grupo de
saldo + 'Demonstrativo Analítico "<grupo>"'), o mesmo software do I-Gloo Alphaville. A leitura está em
`extratores/gcont.py`; este módulo só faz o despacho por id.
"""
from conciliacao.regras_gerais.extratores.gcont import Extrator as _Gcont


class Extrator(_Gcont):
    pass
