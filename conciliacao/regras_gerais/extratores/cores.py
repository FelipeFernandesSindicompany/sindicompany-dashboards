"""
Extrator das regras gerais — Cores.

A pasta do projeto tem as planilhas Habitacional (XLSX, até jul/2026) e, a partir de ago/2026, o "Demonstrativo de Contas"
em PDF. Despacha pela EXTENSÃO: .xlsx → extratores/habitacional_xlsx.py; .pdf → extratores/contasdata.py
(mesmo padrão do Onze 22, Port Saint Tropez e Baturité).
"""
from conciliacao.regras_gerais.extratores.port_saint_tropez import ExtratorPlanilhaOuContasData


class Extrator(ExtratorPlanilhaOuContasData):
    pass
