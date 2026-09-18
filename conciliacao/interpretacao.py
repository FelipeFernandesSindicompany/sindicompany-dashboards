"""
Contrato da camada de interpretação — SEM lógica de IA embutida aqui.

Esta camada só faz duas coisas:
  1. Gera um AchadoRevisado por achado bruto — texto/severidade preenchidos
     automaticamente a partir dos próprios fatos do achado (tipo, valores,
     regra aplicada, e — quando disponíveis — os RegistroComprovante
     relacionados), para que a geração do relatório nunca dependa de alguém
     digitar título/parágrafo manualmente antes de gerar o PDF. Objetivo
     explícito do usuário: automação de ponta a ponta — se um relatório
     sair incorreto, a correção é pedida depois (e vira ajuste no gerador
     de texto aqui, não uma revisão manual pontual).
  2. Valida o resultado antes de liberar para a etapa de render, garantindo
     que nenhum AchadoRevisado invente um achado_id que não existe, ou mude
     a severidade sem justificar.

Por quê separado do matching.py: a camada determinística nunca decide texto
nem severidade final; esta camada nunca decide números (só relata os que já
vieram prontos no Achado/RegistroComprovante). Isso mantém a auditoria dos
dois lados rastreável e revisável independentemente — inclusive quando o
texto é gerado automaticamente, o `revisado_por` deixa isso explícito
("sistema:narrativa_automatica", nunca "pendente" nem se passando por
revisão humana).
"""
from datetime import datetime, timezone

from conciliacao.base import SEVERIDADES, Achado, AchadoRevisado, RegistroComprovante, chave_registro


def _fmt_moeda(v: float | None) -> str:
    if v is None:
        return "valor não informado"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _registro_principal(achado: Achado, registros_por_chave: dict) -> RegistroComprovante | None:
    for chave in achado.registros_relacionados:
        r = registros_por_chave.get(chave)
        if r:
            return r
    return None


def _categoria(achado: Achado, registro: RegistroComprovante | None) -> str:
    return achado.linha_demonstrativo or (registro.categoria_demonstrativo if registro else None) or "lançamento"


def _texto_sem_comprovante(achado: Achado, registro: RegistroComprovante | None) -> tuple[str, str, str]:
    categoria = _categoria(achado, registro)
    valor = _fmt_moeda(achado.valor_esperado)
    fornecedor = f" ({registro.fornecedor})" if registro and registro.fornecedor else ""
    titulo = f"Comprovante sem anexo — {categoria} ({valor})"
    paragrafo = (
        f"O lançamento de {categoria}{fornecedor}, no valor de {valor}, não tem comprovante de "
        f"pagamento pareado/anexado na pasta de prestação de contas."
    )
    o_que_verificar = "Solicitar o comprovante à administradora antes de aprovar a prestação de contas."
    return titulo, paragrafo, o_que_verificar


def _texto_divergencia_valor(achado: Achado, registro: RegistroComprovante | None) -> tuple[str, str, str]:
    categoria = _categoria(achado, registro)
    esperado = _fmt_moeda(achado.valor_esperado)
    encontrado = _fmt_moeda(achado.valor_encontrado)
    regra = achado.regra_aplicada
    if "ocr" in regra:
        titulo = f"Valor do comprovante não confirma com a listagem — possível erro de leitura do OCR ({categoria})"
        paragrafo = (
            f"O valor esperado na listagem ({esperado}) não confere com o valor lido automaticamente no comprovante "
            f"digitalizado ({encontrado}). Isso pode ser um erro de leitura do OCR (comum quando um dígito sai trocado, "
            f"ou quando o comprovante é de um pagamento consolidado que não permite isolar o valor individual) — não é "
            f"necessariamente uma divergência financeira real."
        )
        o_que_verificar = (
            f"Conferir visualmente o valor no recorte do comprovante anexado — se realmente mostrar {encontrado} "
            f"impresso, investigar o pagamento; se mostrar {esperado}, é só falha de leitura automática."
        )
    elif "soma" in regra or "saldo" in regra:
        titulo = f"Soma não confere com o total declarado — {categoria}"
        paragrafo = (
            f"A soma dos lançamentos extraídos ({encontrado}) não bate com o total declarado no próprio documento "
            f"({esperado})."
        )
        o_que_verificar = "Conferir o demonstrativo original — pode haver um lançamento que não foi capturado, ou o total declarado pode estar incorreto."
    else:
        titulo = f"Divergência de valor — {categoria}"
        paragrafo = f"O valor esperado ({esperado}) não confere com o valor encontrado no comprovante ({encontrado})."
        o_que_verificar = "Conferir o comprovante anexado para confirmar qual valor está correto."
    return titulo, paragrafo, o_que_verificar


def _texto_atraso_pagamento(achado: Achado, registro: RegistroComprovante | None) -> tuple[str, str, str]:
    categoria = _categoria(achado, registro)
    valor = _fmt_moeda(achado.valor_encontrado)
    fornecedor = registro.fornecedor if registro and registro.fornecedor else categoria
    venc = registro.vencimento if registro else None
    pago = registro.pagamento if registro else None
    titulo = f"Atraso de pagamento — {fornecedor}"
    if venc and pago:
        paragrafo = (
            f"O comprovante de pagamento a {fornecedor} ({valor}) mostra vencimento em {venc} e pagamento "
            f"efetivado em {pago} — atraso além do dia útil seguinte ao vencimento (já descontado o rollover de "
            f"fim de semana)."
        )
    else:
        paragrafo = f"O comprovante de pagamento a {fornecedor} ({valor}) foi pago após o vencimento."
    o_que_verificar = "Confirmar se houve cobrança de juros/multa por atraso e, se sim, se o valor pago já inclui esse acréscimo ou se falta um lançamento complementar."
    return titulo, paragrafo, o_que_verificar


def _texto_conteudo_nao_verificavel(achado: Achado, registro: RegistroComprovante | None) -> tuple[str, str, str]:
    categoria = _categoria(achado, registro)
    valor = _fmt_moeda(achado.valor_esperado)
    # texto_bruto curto (só cabeçalho/rodapé) é sinal de página genuinamente
    # em branco — ver _OCR_TEXTO_MINIMO em conciliacao/lirba_pdf.py — texto
    # mais longo indica que existe conteúdo, só não reconhecido ainda.
    provavelmente_em_branco = bool(registro) and len((registro.texto_bruto or "").strip()) < 100
    titulo = f"Comprovante anexado, conteúdo não confirmado automaticamente — {categoria} ({valor})"
    if provavelmente_em_branco:
        paragrafo = (
            f"A página de comprovante para este lançamento ({valor}) existe na pasta, mas está em branco — "
            f"não há documento anexado de fato."
        )
        o_que_verificar = "Confirmar com a administradora se o comprovante foi apenas esquecido na montagem da pasta, ou se não existe para este tipo de lançamento."
    else:
        paragrafo = (
            f"A página de comprovante para este lançamento ({valor}) existe e tem conteúdo, mas o sistema não "
            f"conseguiu confirmar o valor automaticamente — formato de documento ainda não reconhecido pela leitura automática."
        )
        o_que_verificar = f"Conferir visualmente no recorte anexado se o valor do documento corresponde a {valor}."
    return titulo, paragrafo, o_que_verificar


def _texto_cnpj_ausente(achado: Achado, registro: RegistroComprovante | None) -> tuple[str, str, str]:
    categoria = _categoria(achado, registro)
    valor = _fmt_moeda(achado.valor_encontrado)
    titulo = f"CNPJ não identificado — {categoria} ({valor})"
    paragrafo = f"O comprovante de débito automático ({valor}) não trouxe um CNPJ extraível em texto simples."
    o_que_verificar = "Confirmar o CNPJ da concessionária/fornecedor manualmente, se necessário para auditoria fiscal."
    return titulo, paragrafo, o_que_verificar


def _texto_duplicidade(achado: Achado) -> tuple[str, str, str]:
    categoria = achado.linha_demonstrativo or "lançamento"
    valor = _fmt_moeda(achado.valor_encontrado or achado.valor_esperado)
    n = len(achado.registros_relacionados)
    titulo = f"Possível duplicidade — {categoria} ({valor})"
    paragrafo = f"Encontrados {n} lançamentos com o mesmo código/fornecedor e valor ({valor}) repetidos."
    o_que_verificar = "Confirmar se são pagamentos distintos legítimos (ex.: parcelas do mesmo valor) ou um lançamento duplicado por engano."
    return titulo, paragrafo, o_que_verificar


def _texto_consolidacao(achado: Achado) -> tuple[str, str, str]:
    categoria = achado.linha_demonstrativo or "lançamento"
    valor = _fmt_moeda(achado.valor_encontrado)
    n = len(achado.registros_relacionados) - 1
    titulo = f"Pagamento consolidado — {categoria} ({valor})"
    paragrafo = f"Este pagamento ({valor}) parece consolidar {max(n, 1)} despesa(s) menor(es) cuja soma bate com o valor pago."
    o_que_verificar = "Confirmar que a consolidação é legítima (ex.: DARF consolidando retenções de vários fornecedores/competências)."
    return titulo, paragrafo, o_que_verificar


def _texto_subconta_atipica(achado: Achado) -> tuple[str, str, str]:
    categoria = achado.linha_demonstrativo or "categoria"
    valor = _fmt_moeda(achado.valor_encontrado)
    titulo = f"Categoria atípica — {categoria} ({valor})"
    paragrafo = (
        f"A categoria \"{categoria}\" não apareceu no histórico recente processado deste condomínio — pode ser uma "
        f"despesa nova legítima ou uma classificação equivocada."
    )
    o_que_verificar = "Verificar se a categorização está correta; nenhuma ação necessária se for uma despesa nova legítima."
    return titulo, paragrafo, o_que_verificar


def gerar_esqueleto(achados: list[Achado], registros: list[RegistroComprovante] | None = None) -> list[dict]:
    """
    Gera um AchadoRevisado por achado bruto, com texto e severidade já
    preenchidos automaticamente — nunca deixa nada "pendente" esperando
    input humano, pra não travar a geração do relatório. `registros`
    (RegistroComprovante[] da mesma versão, ver storage.py) é opcional mas
    enriquece o texto de atraso_pagamento/sem_comprovante/conteudo_nao_verificavel
    com fornecedor/datas quando disponível.
    """
    agora = datetime.now(timezone.utc).isoformat()
    registros_por_chave = {chave_registro(r): r for r in (registros or [])}
    esqueleto = []
    for achado in achados:
        registro = _registro_principal(achado, registros_por_chave)
        base = {
            "achado_id": achado.id,
            "titulo": "",
            "paragrafo": "",
            "severidade_final": achado.severidade_sugerida,
            "o_que_verificar": "",
            "confianca_ia": 0.7,
            "revisado_por": "sistema:narrativa_automatica",
            "revisado_em": agora,
            "motivo_divergencia_da_sugestao": None,
        }
        if achado.tipo == "ok_verificado":
            titulo = "Verificado sem irregularidade"
            paragrafo = (
                f"Comprovante confere com o lançamento correspondente (valor R$ {achado.valor_encontrado:.2f})."
                if achado.valor_encontrado else "Comprovante confere com o lançamento correspondente."
            )
            o_que_verificar = "Nenhuma ação necessária."
            base["confianca_ia"] = 1.0
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "sem_comprovante":
            titulo, paragrafo, o_que_verificar = _texto_sem_comprovante(achado, registro)
        elif achado.tipo == "divergencia_valor":
            titulo, paragrafo, o_que_verificar = _texto_divergencia_valor(achado, registro)
        elif achado.tipo == "atraso_pagamento":
            titulo, paragrafo, o_que_verificar = _texto_atraso_pagamento(achado, registro)
        elif achado.tipo == "conteudo_nao_verificavel":
            titulo, paragrafo, o_que_verificar = _texto_conteudo_nao_verificavel(achado, registro)
        elif achado.tipo == "cnpj_ausente":
            titulo, paragrafo, o_que_verificar = _texto_cnpj_ausente(achado, registro)
        elif achado.tipo == "duplicidade":
            titulo, paragrafo, o_que_verificar = _texto_duplicidade(achado)
        elif achado.tipo == "consolidacao_multipla_pendente_julgamento":
            titulo, paragrafo, o_que_verificar = _texto_consolidacao(achado)
        elif achado.tipo == "subconta_atipica":
            titulo, paragrafo, o_que_verificar = _texto_subconta_atipica(achado)
        elif achado.tipo == "sem_lancamento_correspondente":
            categoria = achado.linha_demonstrativo or "lançamento"
            valor = _fmt_moeda(achado.valor_encontrado)
            titulo = f"Comprovante de pagamento sem despesa correspondente — {categoria} ({valor})"
            paragrafo = f"Existe um comprovante de pagamento ({valor}) que não foi pareado com nenhuma despesa listada no demonstrativo."
            o_que_verificar = "Confirmar se esse pagamento está refletido em algum lançamento do demonstrativo sob outro código, ou se falta lançar a despesa."
        else:
            # Tipo de achado desconhecido (nunca deveria acontecer — TIPOS_ACHADO
            # em base.py é fechado) — melhor um texto genérico honesto do que
            # travar a geração do relatório.
            titulo = f"Achado tipo '{achado.tipo}' — revisar"
            paragrafo = f"Regra aplicada: {achado.regra_aplicada}."
            o_que_verificar = "Revisar manualmente — tipo de achado sem narrativa automática definida."
        base["titulo"] = titulo
        base["paragrafo"] = paragrafo
        base["o_que_verificar"] = o_que_verificar
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
