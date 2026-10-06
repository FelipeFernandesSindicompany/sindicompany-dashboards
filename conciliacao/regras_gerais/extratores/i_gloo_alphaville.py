"""
Extrator das regras gerais — I-Gloo Alphaville (HSA Condomínios).

O cadastro diz `lirba_pdf`, mas o PDF NÃO é ContasData: é o relatório "W0xx" da HSA/GCONT (Resumo Financeiro por grupo de
saldo + 'Demonstrativo Analítico "<grupo>"'). A leitura está em `extratores/gcont.py`; este módulo só faz o despacho por id
(o despacho por empresa mandaria o arquivo para o extrator ContasData, que o recusa).
"""
from conciliacao.regras_gerais.extratores.gcont import Extrator as _Gcont


class Extrator(_Gcont):
    pass
