"""
Extrator das regras gerais — Alvorada.

Cadastrado como habitacional_xlsx (planilha "prestacao_contas_M_AAAA.xlsx", até jul/2026), mas a administradora também entrega a
"Pasta Digital" em PDF (ContasData, "Voltar ao índice", ~30 MB com o Demonstrativo e os comprovantes; jun-set/2026) — mesma
migração do Onze 22, Baturité e Port Saint Tropez. Despacha pela EXTENSÃO: .xlsx → extratores/habitacional_xlsx.py;
.pdf → extratores/contasdata.py.
"""
from conciliacao.regras_gerais.extratores.port_saint_tropez import ExtratorPlanilhaOuContasData


class Extrator(ExtratorPlanilhaOuContasData):
    pass
