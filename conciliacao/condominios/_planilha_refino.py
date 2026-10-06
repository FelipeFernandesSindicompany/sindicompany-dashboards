"""
Refino do matching das planilhas com link de anexo (Habitacional / LFC — Cinque Terre, Go Liberdade,
Onze 22, Guaratambé, ...): roda `matching.gerar_achados_planilha_com_links` (inalterado) e reclassifica o
que a varredura de out/2026 mostrou ser falso "sem comprovante".

  - "IR S/ APLICAÇÃO ..." (imposto de renda retido na fonte sobre aplicação financeira, debitado pelo banco):
    não há prestador nem recibo a anexar — mesma natureza das tarifas bancárias/IOF já isentas em
    matching._motivo_isencao_comprovante, mas essa grafia ("S/ APLICAÇÃO" em vez de "S/ RESGATE") não era
    coberta (Cinque Terre 07/2026, R$ 1.922,59, categoria "IR S/APLICAÇÃO"; aparecia todo mês).

Tudo o mais (lançamento sem link de verdade, ex.: "falta documento", "Aguardando Documento", débito
automático de concessionária sem fatura anexada, repasses sem comprovante) continua "sem comprovante".

Arquivo com prefixo "_": não é carregado como conciliador de condomínio.
"""
import dataclasses
import re

from conciliacao import matching
from conciliacao.base import chave_registro

_RE_IR_SOBRE_APLICACAO = re.compile(
    r"\b(?:IR|IRRF|I\.R\.)\s*(?:S/|SOBRE)\s*(?:APLIC|RENDIM)|IMPOSTO\s+(?:DE\s+RENDA\s+)?(?:S/|SOBRE)\s*(?:APLIC|RENDIM)",
    re.IGNORECASE,
)


def gerar_achados_planilha_refinado(registros, dados_financeiros=None, pasta_dados=None, mes_atual=None):
    achados = matching.gerar_achados_planilha_com_links(
        registros, dados_financeiros, pasta_dados=pasta_dados, mes_atual=mes_atual)
    por_chave = {chave_registro(r): r for r in registros}
    saida = []
    for a in achados:
        if a.tipo == "sem_comprovante" and a.registros_relacionados:
            r = por_chave.get(a.registros_relacionados[0])
            texto = f"{(r.descricao or '') if r else ''} {(r.categoria_demonstrativo or '') if r else ''}"
            if r is not None and _RE_IR_SOBRE_APLICACAO.search(texto):
                a = dataclasses.replace(
                    a, tipo="ok_verificado", severidade_sugerida="informativo",
                    regra_aplicada="imposto_sobre_aplicacao_debitado_pelo_banco_sem_comprovante_individual",
                    valor_encontrado=a.valor_esperado, confianca_deterministica=1.0)
        saida.append(a)
    return saida
