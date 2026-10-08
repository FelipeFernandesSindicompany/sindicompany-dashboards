"""
Extrator das regras gerais — Onze 22.

A pasta do projeto tem as planilhas Habitacional (XLSX) e a "Pasta Digital" em PDF (ContasData). Despacha pela
EXTENSÃO, igual ao Port Saint Tropez e ao Baturité: .xlsx → extratores/habitacional_xlsx.py; .pdf → extratores/contasdata.py.
"""
from conciliacao.regras_gerais.extratores.port_saint_tropez import ExtratorPlanilhaOuContasData


class Extrator(ExtratorPlanilhaOuContasData):
    # conferido em jun/2026: planilha e PDF trazem os mesmos 62 lançamentos, mesmas subcontas e mesmos totais,
    # então o histórico pode misturar os dois formatos na comparação de subcontas.
    compara_entre_formatos = True
