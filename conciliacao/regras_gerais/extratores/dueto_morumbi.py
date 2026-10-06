"""
Extrator das regras gerais — Dueto Morumbi (Manager ADM, `manager_adm_pdf`).

Mesmo formato do Fatto Morumbi (ver `fatto_morumbi.py::ExtratorManagerAdm`): ContasData com "Nº lancto.", Resumo
Financeiro depois das Posições, receitas por recibo com sinal. Particularidades do Dueto (abr a ago/2026):

  * contas: ORDINARIA, FUNDO DE RESERVA, ALUGUEL S.FESTA /CHURRASQUEIRA e, só em ago/2026, ALUGUEL SALAO DE FESTAS (conta
    de passagem: recebe R$ 8.243,03 de aluguéis e os repassa — "TRANSFERENCIA ENTRE CONTAS" — para a anterior);
  * o débito da ORDINARIA do Resumo = Demonstrativo de Despesas + "RECIBOS DIVERGENTES" + "TRANSFERENCIA ENTRE CONTAS"
    (ago/2026: 167.258,00 + 3.057,25 + 8.243,03 = 178.558,28; jul/2026: 144.939,80 + 1.941,36); ambos só constam da
    Posição Financeira da conta e entram como lançamentos para a conferência fechar ao centavo (a transferência é
    despesa da conta que repassa, mas não é despesa do condomínio — as regras 5/7/8 a ignoram pela categoria);
  * nenhuma conta tem aplicação financeira: não há rendimento (cobertura da regra 3 = False com o motivo);
  * garantidora: dezenas de recibos "*BOLETO cedido GARANTIDORA ... -0,02/-0,04" e "DESCONTO ... (unidade ...)" com sinal
    negativo impresso (receita negativa de verdade, ver relatório).
"""
from conciliacao.regras_gerais.extratores.fatto_morumbi import ExtratorManagerAdm


class Extrator(ExtratorManagerAdm):
    pass
