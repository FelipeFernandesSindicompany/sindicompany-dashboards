"""
Contrato da camada de interpretação — SEM lógica de IA embutida aqui.

Esta camada só faz duas coisas:
  1. Gera um esqueleto (achados_revisados.json) a partir dos achados brutos,
     para ser preenchido por quem/o que fizer a revisão (uma sessão de
     agente lendo os crops de evidência + o contexto do demonstrativo, ou um
     humano) — exatamente o mesmo tipo de leitura que produziu o PDF-modelo.
  2. Valida o resultado preenchido antes de liberar para a etapa de render,
     garantindo que nenhum AchadoRevisado invente um achado_id que não
     existe, ou mude a severidade sem justificar.

Por quê separado do matching.py: a camada determinística nunca decide texto
nem severidade final; a camada de interpretação nunca decide números. Isso
mantém a auditoria dos dois lados rastreável e revisável independentemente.
"""
from datetime import datetime, timezone

from conciliacao.base import SEVERIDADES, Achado, AchadoRevisado


def gerar_esqueleto(achados: list[Achado]) -> list[dict]:
    """
    Gera um AchadoRevisado "rascunho" por achado bruto — severidade e
    confiança herdadas, texto vazio para preenchimento posterior.

    Achados tipo "ok_verificado" já vêm com texto padrão preenchido (não
    exigem revisão narrativa), os demais ficam com paragrafo/titulo vazios
    para o passo de interpretação completar.
    """
    agora = datetime.now(timezone.utc).isoformat()
    esqueleto = []
    for achado in achados:
        base = {
            "achado_id": achado.id,
            "titulo": "",
            "paragrafo": "",
            "severidade_final": achado.severidade_sugerida,
            "o_que_verificar": "",
            "confianca_ia": 0.0,
            "revisado_por": "pendente",
            "revisado_em": agora,
            "motivo_divergencia_da_sugestao": None,
        }
        if achado.tipo == "ok_verificado":
            base.update({
                "titulo": "Verificado sem irregularidade",
                "paragrafo": (
                    f"Comprovante confere com o lançamento correspondente "
                    f"(valor R$ {achado.valor_encontrado:.2f})." if achado.valor_encontrado else
                    "Comprovante confere com o lançamento correspondente."
                ),
                "o_que_verificar": "Nenhuma ação necessária.",
                "confianca_ia": 1.0,
                "revisado_por": "sistema:regra_deterministica",
            })
        esqueleto.append(base)
    return esqueleto


def validar(achados: list[Achado], revisados: list[AchadoRevisado]) -> list[str]:
    """Retorna lista de erros (vazia = ok). Não lança exceção — quem chama decide o que fazer."""
    erros: list[str] = []
    ids_validos = {a.id: a for a in achados}
    ids_vistos: set[str] = set()

    for r in revisados:
        if r.achado_id not in ids_validos:
            erros.append(f"achado_id '{r.achado_id}' não existe nos achados brutos")
            continue
        ids_vistos.add(r.achado_id)

        if r.severidade_final not in SEVERIDADES:
            erros.append(f"{r.achado_id}: severidade_final inválida '{r.severidade_final}'")

        achado = ids_validos[r.achado_id]
        if r.severidade_final != achado.severidade_sugerida and not r.motivo_divergencia_da_sugestao:
            erros.append(
                f"{r.achado_id}: severidade mudou de '{achado.severidade_sugerida}' para "
                f"'{r.severidade_final}' sem motivo_divergencia_da_sugestao"
            )

        if not (0.0 <= r.confianca_ia <= 1.0):
            erros.append(f"{r.achado_id}: confianca_ia fora de [0,1]: {r.confianca_ia}")

        if not r.titulo.strip() or not r.paragrafo.strip():
            erros.append(f"{r.achado_id}: titulo/paragrafo vazio — revisão incompleta")

    faltando = set(ids_validos) - ids_vistos
    if faltando:
        erros.append(f"achados sem revisão correspondente: {sorted(faltando)}")

    return erros
