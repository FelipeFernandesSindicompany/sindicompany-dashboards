"""
Extrator das regras gerais — Baturité.

Baturité migrou da planilha Habitacional (XLSX "prestacao_contas_M_AAAA", abr a ago/2025 na pasta do projeto) para o
PDF "Prestação de Contas" ContasData (out/2025 em diante; set/2025 não existe na pasta). O cadastro ainda diz
`habitacional_xlsx`, então o despacho de `extratores/__init__.py` cairia só no extrator de planilha e um PDF
daria erro; este módulo resolve pela EXTENSÃO do arquivo, igual ao Port Saint Tropez:

  .xlsx/.xlsm -> extratores/habitacional_xlsx.py  (planilha; conferido nos 5 meses da pasta)
  .pdf        -> extratores/contasdata.py         (importado de forma preguiçosa; se faltar, cobertura False com motivo)

Observação: as planilhas de Baturité NÃO têm "Demonstrativo de Receitas" (só Posição Financeira por conta) — as
receitas e o rendimento saem das linhas de crédito da Posição Financeira (ver habitacional_xlsx.py).
"""
from conciliacao.regras_gerais.extratores.port_saint_tropez import ExtratorPlanilhaOuContasData


class Extrator(ExtratorPlanilhaOuContasData):
    pass
