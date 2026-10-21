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
import re
from datetime import datetime, timezone

from conciliacao.base import SEVERIDADES, Achado, AchadoRevisado, RegistroComprovante, chave_registro
from conciliacao.regras_gerais.textos import TEXTOS as _TEXTOS_REGRAS_GERAIS, texto_subconta_nova as _texto_subconta_nova


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
    # Linha de valor NEGATIVO na listagem (ex.: "REF A DEV PAGTO A MAIOR ... -48.758,96"): é estorno/devolução, não um pagamento.
    negativo = False
    if registro and registro.descricao and registro.valor:
        for m in re.finditer(r"(?<=\s)-(\d{1,3}(?:\.\d{3})*,\d{2})", registro.descricao):      # sinal COLADO no número ("-48.758,96"); "NF - 12.198,46" é separador
            if abs(float(m.group(1).replace(".", "").replace(",", ".")) - abs(registro.valor)) < 0.005:
                negativo = True
    if negativo:
        titulo = f"Estorno/devolução sem documento anexo — {categoria} ({valor})"
        paragrafo = (
            f"O lançamento de {categoria}, no valor de {valor}, aparece com valor NEGATIVO na listagem de despesas "
            f"(estorno/devolução: \"{(registro.descricao or '')[:120]}\") e não tem documento anexado na pasta de prestação de contas "
            f"que o sustente."
        )
        o_que_verificar = (
            "Qual é a explicação para este lançamento negativo? Qual foi o pagamento a maior que o originou, onde está o comprovante da devolução "
            "e em que conta e em que data o valor foi creditado?"
        )
        return titulo, paragrafo, o_que_verificar
    if (achado.detalhes or {}).get("pagina_em_branco"):
        paragrafo = (
            f"O lançamento de {categoria}{fornecedor}, no valor de {valor}, tem a página de comprovante no arquivo "
            f"(página {achado.detalhes.get('pagina')}), mas ela está em branco: nenhum documento foi anexado."
        )
    else:
        paragrafo = (
            f"O lançamento de {categoria}{fornecedor}, no valor de {valor}, não tem comprovante de "
            f"pagamento pareado/anexado na pasta de prestação de contas."
        )
    o_que_verificar = "Por que este lançamento está sem comprovante anexado na prestação de contas? Podem enviar o comprovante de pagamento ou explicar por que ele não existe?"
    return titulo, paragrafo, o_que_verificar


def _texto_divergencia_valor(achado: Achado, registro: RegistroComprovante | None) -> tuple[str, str, str]:
    categoria = _categoria(achado, registro)
    esperado = _fmt_moeda(achado.valor_esperado)
    encontrado = _fmt_moeda(achado.valor_encontrado)
    regra = achado.regra_aplicada
    repetido = bool((achado.detalhes or {}).get("valor_repetido_no_comprovante"))   # marca posta só nos condomínios que pedem
    if regra == "guia_consolidada_nao_fecha_com_a_soma_dos_lancamentos":
        det = achado.detalhes or {}
        soma, total, n = _fmt_moeda(det.get("soma")), _fmt_moeda(det.get("total")), det.get("n")
        dif = _fmt_moeda(round((det.get("total") or 0) - (det.get("soma") or 0), 2))
        itens = "; ".join(f"{i['descricao']} ({_fmt_moeda(i['valor'])})" for i in (det.get("itens") or [])[:12])
        titulo = f"Guia consolidada de {total} não fecha com os lançamentos listados ({n} lançamentos somam {soma})"
        paragrafo = (f"O comprovante anexado a {n} lançamentos é uma mesma guia de recolhimento no valor de {total}, mas os lançamentos listados que apontam "
                     f"para ela somam {soma}; a diferença de {dif} não aparece nesses lançamentos. Lançamentos: {itens}.")
        o_que_verificar = (f"A que lançamentos correspondem os {dif} restantes da guia de {total}? Podem enviar a composição completa da guia e indicar "
                           f"em quais lançamentos da listagem ela foi dividida?")
    elif regra == "demonstrativo_de_despesas_repetido_no_arquivo":
        det = achado.detalhes or {}
        n = det.get("copias")
        um_bloco = _fmt_moeda(det.get("total_um_bloco"))
        declarado = _fmt_moeda(det.get("total_declarado"))
        titulo = f"Demonstrativo de Despesas repetido {n} vezes no arquivo (total declarado {declarado})"
        paragrafo = (
            f"Na aba \"Demonstrativo de Despesas\" o mesmo bloco de lançamentos aparece {n} vezes, idêntico. O \"TOTAL DE DESPESAS\" "
            f"declarado no arquivo é {declarado}, que é {n} × {um_bloco}; {um_bloco} é o total de um bloco e confere com os débitos da conta "
            f"Ordinária no Demonstrativo de Contas. Para esta validação foi lido um único bloco."
        )
        o_que_verificar = (f"Por que o arquivo enviado traz o Demonstrativo de Despesas repetido {n} vezes, com total declarado de {declarado}? "
                           f"O correto é {um_bloco}? Podem reenviar o arquivo corrigido?")
    elif regra == "extrato_bancario_nao_contem_o_valor_listado":
        ex = (achado.detalhes or {}).get("extrato") or {}
        dia = ex.get("dia") or "data do lançamento"
        saidas = ex.get("saidas_do_dia") or []
        lista = "; ".join(_fmt_moeda(v) for v in saidas)
        titulo = f"Comprovante é um extrato bancário que não mostra o pagamento — {categoria} ({esperado})"
        paragrafo = (
            f"O comprovante anexado a este lançamento ({esperado}, {dia}) é um extrato bancário com várias transações, e nele não há "
            f"um pagamento de {esperado} nem uma soma de pagamentos do dia {dia} que feche esse valor"
            + (f" (saídas do dia no extrato: {lista}; total {_fmt_moeda(round(sum(saidas), 2))})" if saidas else
               f" (o extrato anexado não traz movimentação em {dia}; dias que ele mostra: {', '.join(ex.get('dias_no_extrato') or []) or 'não identificados'})")
            + ". Conferido pelas linhas do próprio extrato, não por um valor isolado lido por OCR."
        )
        o_que_verificar = (f"Onde está o comprovante do pagamento de {esperado} do dia {dia}? O extrato anexado cobre esse dia? "
                           f"Podem enviar o extrato ou o comprovante correto?")
    elif "ocr" in regra and repetido:
        # O mesmo valor aparece em mais de um campo do comprovante (ex.: "Valor do lançamento" e "Valor pago"): a
        # leitura não é um dígito trocado, a divergência é real.
        titulo = f"Valor do comprovante diverge da listagem — {categoria} (listagem {esperado}, comprovante {encontrado})"
        paragrafo = (
            f"O comprovante anexado mostra {encontrado} (valor repetido em mais de um campo do próprio comprovante, "
            f"portanto a leitura é confiável), mas a listagem registra {esperado}. Pode ser um pagamento consolidado "
            f"(um único comprovante cobrindo vários lançamentos) ou um lançamento com valor incorreto."
        )
        o_que_verificar = (
            "Por que o comprovante mostra " + encontrado + " se a listagem registra " + esperado + "? Qual é a composição desse pagamento e em quais "
            "lançamentos da listagem ele foi dividido (a soma deles fecha com o valor do comprovante)?"
        )
    elif "ocr" in regra:
        titulo = f"Valor do comprovante não confirma com a listagem — possível erro de leitura do OCR ({categoria})"
        paragrafo = (
            f"O valor esperado na listagem ({esperado}) não confere com o valor lido automaticamente no comprovante "
            f"digitalizado ({encontrado}). Isso pode ser um erro de leitura do OCR (comum quando um dígito sai trocado, "
            f"ou quando o comprovante é de um pagamento consolidado que não permite isolar o valor individual) — não é "
            f"necessariamente uma divergência financeira real."
        )
        o_que_verificar = (
            f"O valor pago foi {esperado} (como na listagem) ou {encontrado}? Se foi {encontrado}, qual é a explicação para a diferença "
            f"em relação ao valor listado?"
        )
    elif "soma" in regra or "saldo" in regra:
        titulo = f"Soma não confere com o total declarado — {categoria}"
        paragrafo = (
            f"A soma dos lançamentos extraídos ({encontrado}) não bate com o total declarado no próprio documento "
            f"({esperado})."
        )
        o_que_verificar = f"Por que a soma dos lançamentos ({encontrado}) não fecha com o total declarado ({esperado})? Falta algum lançamento no demonstrativo ou o total declarado está incorreto?"
    else:
        titulo = f"Divergência de valor — {categoria}"
        paragrafo = f"O valor esperado ({esperado}) não confere com o valor encontrado no comprovante ({encontrado})."
        o_que_verificar = f"Qual é o valor correto deste lançamento: {esperado} (listagem) ou {encontrado} (comprovante)? Qual é a explicação para a diferença?"
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
            f"efetivado em {pago} — pagamento posterior ao vencimento (vencimento em fim de semana ou feriado já foi "
            f"considerado no próximo dia útil)."
        )
    else:
        paragrafo = f"O comprovante de pagamento a {fornecedor} ({valor}) foi pago após o vencimento."
    o_que_verificar = "Por que este pagamento foi feito após o vencimento? Houve cobrança de juros ou multa e, se sim, o valor pago já inclui esse acréscimo ou falta um lançamento complementar?"
    return titulo, paragrafo, o_que_verificar


def _texto_conteudo_nao_verificavel(achado: Achado, registro: RegistroComprovante | None) -> tuple[str, str, str]:
    if achado.regra_aplicada == "anexo_despesa_com_valor_nao_confirmado_por_ocr":
        # Palm Beach — anexo de despesa identificado (fornecedor/nº doc de
        # texto real), mas o OCR não confirmou o valor na capa do anexo.
        fornecedor = registro.fornecedor if registro and registro.fornecedor else "fornecedor não identificado"
        doc = f" (Doc. {registro.codigo})" if registro and registro.codigo else ""
        titulo = f"Comprovante anexado, valor não confirmado — {fornecedor}{doc}"
        paragrafo = f"Existe um anexo de despesa para {fornecedor}{doc}, categoria \"{achado.linha_demonstrativo or 'não identificada'}\", mas o sistema não conseguiu ler o valor na capa do anexo."
        o_que_verificar = "Qual é o valor do documento anexado e a que despesa ele se refere? Podem confirmar o valor?"
        return titulo, paragrafo, o_que_verificar
    if achado.regra_aplicada == "valor_lido_implausivel_possivel_erro_ocr":
        # Palm Beach — valor OCR'd acima do teto de plausibilidade (ver
        # _VALOR_MAXIMO_PLAUSIVEL em conciliacao/condominios/palm_beach.py).
        valor_lido = _fmt_moeda(achado.valor_encontrado)
        titulo = f"Valor lido implausível — possível erro de leitura do OCR ({valor_lido})"
        paragrafo = (
            f"O valor lido neste documento ({valor_lido}) é alto demais pra ser plausível como uma despesa "
            f"individual do condomínio — provavelmente um erro de leitura do OCR (dígito extra ou separador "
            f"decimal trocado), não um valor real."
        )
        o_que_verificar = f"O valor deste documento é mesmo {valor_lido}? Podem confirmar o valor real e a que lançamento ele corresponde?"
        return titulo, paragrafo, o_que_verificar
    if achado.regra_aplicada == "documento_outros_documentos_tipo_nao_reconhecido":
        # Palm Beach — documento presente, mas nenhum classificador (extrato/
        # FOPAG/certidão/recibo/valor de transação) reconheceu o tipo.
        titulo = "Documento anexado, tipo não reconhecido automaticamente"
        paragrafo = "O documento está presente na pasta de \"Outros documentos\", mas o sistema não reconheceu o tipo nem conseguiu extrair um valor de transação."
        o_que_verificar = "Que documento é este e a que lançamento ele se refere? Podem explicar por que ele está na pasta de outros documentos?"
        return titulo, paragrafo, o_que_verificar

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
        o_que_verificar = "O comprovante deste lançamento foi esquecido na montagem da pasta ou não existe para este tipo de lançamento? Se existir, podem enviá-lo?"
    else:
        paragrafo = (
            f"A página de comprovante para este lançamento ({valor}) existe e tem conteúdo, mas o sistema não "
            f"conseguiu confirmar o valor automaticamente — formato de documento ainda não reconhecido pela leitura automática."
        )
        o_que_verificar = f"O documento anexado comprova o valor de {valor}? Podem confirmar o valor do documento e explicar a diferença, se houver?"
    return titulo, paragrafo, o_que_verificar


def _texto_cnpj_ausente(achado: Achado, registro: RegistroComprovante | None) -> tuple[str, str, str]:
    categoria = _categoria(achado, registro)
    valor = _fmt_moeda(achado.valor_encontrado)
    titulo = f"CNPJ não identificado — {categoria} ({valor})"
    paragrafo = f"O comprovante de débito automático ({valor}) não trouxe um CNPJ extraível em texto simples."
    o_que_verificar = "Qual é o CNPJ do fornecedor/concessionária deste débito automático? Podem informá-lo para a conferência fiscal?"
    return titulo, paragrafo, o_que_verificar


def _texto_duplicidade(achado: Achado) -> tuple[str, str, str]:
    categoria = achado.linha_demonstrativo or "lançamento"
    valor = _fmt_moeda(achado.valor_encontrado or achado.valor_esperado)
    n = len(achado.registros_relacionados)
    titulo = f"Possível duplicidade — {categoria} ({valor})"
    if achado.regra_aplicada == "mesma_data_valor_categoria_historico_repetidos":
        paragrafo = (f"Encontrados {n} lançamentos com a mesma data, o mesmo histórico, a mesma categoria e o mesmo valor ({valor}), "
                     f"sem número de documento que os diferencie.")
    else:
        paragrafo = f"Encontrados {n} lançamentos com o mesmo código/fornecedor e valor ({valor}) repetidos."
    o_que_verificar = "Estes lançamentos repetidos são pagamentos distintos legítimos (por exemplo, parcelas do mesmo valor) ou houve duplicidade por engano? Em caso de duplicidade, haverá estorno?"
    return titulo, paragrafo, o_que_verificar


def _texto_consolidacao(achado: Achado) -> tuple[str, str, str]:
    categoria = achado.linha_demonstrativo or "lançamento"
    valor = _fmt_moeda(achado.valor_encontrado)
    n = len(achado.registros_relacionados) - 1
    titulo = f"Pagamento consolidado — {categoria} ({valor})"
    paragrafo = f"Este pagamento ({valor}) parece consolidar {max(n, 1)} despesa(s) menor(es) cuja soma bate com o valor pago."
    o_que_verificar = "Este pagamento consolida de fato as despesas indicadas (por exemplo, uma guia reunindo retenções de vários fornecedores e competências)? Podem informar a composição do pagamento?"
    return titulo, paragrafo, o_que_verificar


def _texto_subconta_atipica(achado: Achado) -> tuple[str, str, str]:
    categoria = achado.linha_demonstrativo or "categoria"
    valor = _fmt_moeda(achado.valor_encontrado)
    titulo = f"Categoria atípica — {categoria} ({valor})"
    paragrafo = (
        f"A categoria \"{categoria}\" não apareceu no histórico recente processado deste condomínio — pode ser uma "
        f"despesa nova legítima ou uma classificação equivocada."
    )
    o_que_verificar = "Por que esta categoria apareceu neste mês e qual a justificativa da classificação? É uma despesa nova legítima ou houve classificação equivocada?"
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
        if achado.tipo == "ok_verificado" and achado.regra_aplicada == "anexo_despesa_com_valor_confirmado_por_ocr":
            # Palm Beach — página-capa de "Despesas > Anexos": fornecedor/nº
            # doc vêm de texto real (ver conciliacao/condominios/palm_beach.py).
            fornecedor = registro.fornecedor if registro and registro.fornecedor else "fornecedor não identificado"
            doc = f" (Doc. {registro.codigo})" if registro and registro.codigo else ""
            valor = _fmt_moeda(achado.valor_encontrado)
            titulo = f"Comprovante confirmado — {fornecedor}{doc} ({valor})"
            paragrafo = f"Anexo da despesa a {fornecedor}{doc}, categoria \"{achado.linha_demonstrativo or 'não identificada'}\" — valor {valor} confirmado na própria capa do anexo."
            o_que_verificar = "Nenhuma ação necessária."
            base["confianca_ia"] = 0.85
        elif achado.tipo == "ok_verificado" and achado.regra_aplicada == "documento_de_apoio_sem_valor_individual_comparavel":
            # Palm Beach (ver conciliacao/condominios/palm_beach.py) — extrato
            # bancário, certidão, folha de pagamento ou recibo de entrega: não
            # é um comprovante de pagamento com valor a conferir, só confirma
            # que o documento de apoio existe na pasta.
            descricao_doc = (registro.descricao if registro and registro.descricao else "documento de apoio")
            titulo = f"Documento de apoio confirmado — {descricao_doc}"
            paragrafo = f"Documento anexado ({descricao_doc}) confirmado como presente na pasta — não é um comprovante de pagamento com valor individual a conferir."
            o_que_verificar = "Nenhuma ação necessária."
            base["confianca_ia"] = 1.0
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "ok_verificado" and achado.regra_aplicada == "documento_outros_documentos_com_valor_confirmado_por_ocr":
            valor = _fmt_moeda(achado.valor_encontrado)
            titulo = f"Comprovante confirmado — valor lido por OCR ({valor})"
            paragrafo = (
                f"Documento de pagamento confirmado, {valor} lido do próprio comprovante. Este formato não tem uma "
                f"listagem de despesas individual com código pra cruzar (ver seção de metodologia) — a confirmação "
                f"é da leitura do documento em si, não de um pareamento com a despesa correspondente."
            )
            o_que_verificar = "Nenhuma ação necessária."
        elif achado.tipo == "ok_verificado" and registro and "não foi enviado para a administradora" in (registro.texto_bruto or "").lower():
            # "DEMONSTRATIVO DE PAGAMENTO" (sistema Robotton, ver
            # conciliacao/condominios/central_das_artes.py) é um aviso
            # GERADO PELO PRÓPRIO SISTEMA quando o documento original (conta/
            # nota/fatura) não chegou até o fechamento da pasta de prestação
            # de contas — o texto do próprio documento confirma isso
            # ("...que até o fechamento da pasta de prestação de contas não
            # foi enviado para a Administradora..."). O valor bater com a
            # listagem NÃO resolve essa pendência — o valor está só nesse
            # demonstrativo interno, não no documento original em si.
            # Confirmado com o síndico: bater o valor não é o mesmo que ter
            # o documento — precisa continuar aparecendo como pendência.
            valor = _fmt_moeda(achado.valor_encontrado)
            titulo = f"Documento original não enviado — {achado.linha_demonstrativo or 'despesa'} ({valor})"
            paragrafo = (
                f"O valor deste lançamento ({valor}) confere, mas o comprovante disponível é só um "
                f"\"Demonstrativo de Pagamento\" interno — o documento original (conta/fatura) ainda não "
                f"foi enviado para a administradora, segundo o próprio sistema."
            )
            o_que_verificar = "Por que o documento original (conta/fatura) deste lançamento não foi enviado? Podem encaminhá-lo?"
            base["confianca_ia"] = 1.0
            base["revisado_por"] = "sistema:regra_deterministica"
            base["severidade_final"] = "atencao"
            base["motivo_divergencia_da_sugestao"] = (
                "Valor confere, mas o documento original não foi enviado para a administradora "
                "(aviso do próprio sistema) — pendência de documentação, não de valor."
            )
        elif achado.tipo == "ok_verificado" and registro and re.search(
            r"CART[AÃ]O\s+DE\s+CR[EÉ]DITO|\b(?:VISA|MASTERCARD)\b", registro.texto_bruto or "", re.IGNORECASE
        ) and not re.search(r"NOTA\s+FISCAL|NFS-?E|DANFE", registro.texto_bruto or "", re.IGNORECASE):
            # Marcador ESTREITO de propósito — "cart" sozinho (ex.:
            # "Carteira", campo padrão de boleto bancário) já gerou falso
            # positivo confirmado em dados reais (Upper Itaim, código 0016:
            # um pagamento comum com Nota Fiscal genuinamente anexada, só
            # que o boleto também incluído no mesmo texto tem o campo
            # "Carteira") — exige a frase completa "cartão de crédito" ou a
            # bandeira do cartão, e NUNCA dispara se o texto já tem um
            # marcador de Nota Fiscal de verdade (documentação já está
            # completa nesse caso, não faz sentido pedir de novo).
            # Fatura de cartão de crédito — o valor TOTAL bater não comprova
            # o que foi efetivamente comprado; precisa das notas fiscais
            # individuais de cada compra pra isso. Mesma lógica do
            # "documento original não enviado" acima: bater o valor não
            # encerra a pendência de documentação.
            valor = _fmt_moeda(achado.valor_encontrado)
            titulo = f"Notas fiscais do cartão de crédito pendentes — {achado.linha_demonstrativo or 'despesa'} ({valor})"
            paragrafo = (
                f"O valor total da fatura do cartão de crédito ({valor}) confere, mas isso não comprova o "
                f"que foi efetivamente comprado — faltam as notas fiscais individuais de cada compra."
            )
            o_que_verificar = (
                "Onde estão as notas fiscais individuais do que foi comprado no cartão de crédito? "
                "Podem anexá-las para comprovar o que foi adquirido?"
            )
            base["confianca_ia"] = 1.0
            base["revisado_por"] = "sistema:regra_deterministica"
            base["severidade_final"] = "atencao"
            base["motivo_divergencia_da_sugestao"] = (
                "Valor total da fatura confere, mas faltam as notas fiscais individuais das compras — "
                "pendência de documentação, não de valor."
            )
        elif achado.tipo == "ok_verificado":
            titulo = "Verificado sem irregularidade"
            paragrafo = (
                f"Comprovante confere com o lançamento correspondente (valor R$ {achado.valor_encontrado:.2f})."
                if achado.valor_encontrado else "Comprovante confere com o lançamento correspondente."
            )
            o_que_verificar = "Nenhuma ação necessária."
            base["confianca_ia"] = 1.0
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "documento_original_nao_enviado":
            itens = (achado.detalhes or {}).get("itens") or []
            lista = "; ".join(f"cód. {i['codigo']} — {i['descricao'][:60].strip()}" + (f", {i['data']}" if i.get("data") else "") + f" ({_fmt_moeda(i['valor'])})" for i in itens)
            titulo = f"Documento original não enviado — {len(itens)} lançamentos ({_fmt_moeda(achado.valor_encontrado)})"
            paragrafo = (
                f"Em {len(itens)} lançamentos (total {_fmt_moeda(achado.valor_encontrado)}) o comprovante disponível é só um "
                f"\"Demonstrativo de Pagamento\" interno — o documento original (conta/fatura) ainda não foi enviado para a "
                f"administradora, segundo o próprio sistema. Os valores conferem com a listagem. Lançamentos: {lista}."
            )
            o_que_verificar = (f"Por que os documentos originais (contas/faturas) desses {len(itens)} lançamentos não foram enviados? "
                               f"Podem encaminhá-los?")
            base["confianca_ia"] = 1.0
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "despesa_negativa":
            itens = (achado.detalhes or {}).get("itens") or []
            lista = "; ".join(f"cód. {i['codigo']} — {i['descricao'].strip()} ({_fmt_moeda(i['valor'])})" for i in itens)
            titulo = f"Despesa lançada com valor negativo — {len(itens)} lançamento(s) ({_fmt_moeda(achado.valor_encontrado)})"
            paragrafo = (
                f"Na listagem de despesas constam {len(itens)} lançamento(s) com valor negativo, somando {_fmt_moeda(achado.valor_encontrado)}: {lista}. "
                f"Não existe despesa negativa: um valor negativo é um crédito (recebimento, reembolso ou estorno) e não pode constar como despesa — "
                f"deve ser lançado como receita, sem reduzir o total das despesas do mês."
            )
            o_que_verificar = ("O que é esse(s) lançamento(s) e por que foi(ram) lançado(s) como despesa com sinal negativo? Se for crédito "
                               "(recebimento, reembolso ou estorno), podem corrigir, passando-o para as receitas e retirando-o das despesas?")
            base["confianca_ia"] = 1.0
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "conta_concessionaria_nao_anexada":
            itens = (achado.detalhes or {}).get("itens") or []
            lista = "; ".join(f"cód. {i['codigo']} — {i['descricao'].strip()} ({_fmt_moeda(i['valor'])})" for i in itens)
            titulo = f"Conta (fatura) de concessionária não anexada — {len(itens)} lançamento(s) ({_fmt_moeda(achado.valor_encontrado)})"
            paragrafo = (
                f"Em {len(itens)} lançamento(s) de concessionárias (energia, água, gás, telefone/internet; total {_fmt_moeda(achado.valor_encontrado)}) "
                f"o anexo é apenas a confirmação do pagamento — a conta (fatura) com o consumo e o vencimento não está anexada. Lançamentos: {lista}."
            )
            o_que_verificar = (f"Podem enviar a conta (fatura) de cada um desses {len(itens)} lançamento(s) de concessionária, "
                               f"para conferirmos o consumo, o vencimento e o valor cobrado?")
            base["confianca_ia"] = 1.0
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "sem_comprovante":
            titulo, paragrafo, o_que_verificar = _texto_sem_comprovante(achado, registro)
        elif achado.tipo == "divergencia_valor":
            titulo, paragrafo, o_que_verificar = _texto_divergencia_valor(achado, registro)
            if achado.regra_aplicada in ("extrato_bancario_nao_contem_o_valor_listado", "demonstrativo_de_despesas_repetido_no_arquivo", "guia_consolidada_nao_fecha_com_a_soma_dos_lancamentos"):
                base["severidade_final"] = "atencao"
                base["motivo_divergencia_da_sugestao"] = (
                    "Pergunta sobre o arquivo/anexo enviado pela administradora (conferido pelas linhas do próprio documento), "
                    "não uma divergência financeira confirmada.")
        elif achado.tipo == "atraso_pagamento":
            titulo, paragrafo, o_que_verificar = _texto_atraso_pagamento(achado, registro)
        elif achado.tipo == "conteudo_nao_verificavel":
            titulo, paragrafo, o_que_verificar = _texto_conteudo_nao_verificavel(achado, registro)
        elif achado.tipo == "cnpj_ausente":
            titulo, paragrafo, o_que_verificar = _texto_cnpj_ausente(achado, registro)
        elif achado.tipo == "duplicidade":
            titulo, paragrafo, o_que_verificar = _texto_duplicidade(achado)
        elif achado.tipo == "nota_fiscal_ausente":
            categoria = _categoria(achado, registro)
            valor = _fmt_moeda(achado.valor_encontrado)
            descricao_curta = (registro.descricao or categoria) if registro else categoria
            titulo = f"Nota Fiscal não anexada — {descricao_curta} ({valor})"
            paragrafo = (
                f"O valor deste lançamento ({valor}) confere, mas a própria listagem cita um número de "
                f"Nota Fiscal e o comprovante anexado é só a confirmação bancária do pagamento — não traz "
                f"a Nota Fiscal em si."
            )
            o_que_verificar = "Onde está a Nota Fiscal deste lançamento? Por que ela não foi anexada junto ao comprovante de pagamento? Podem enviá-la?"
            base["confianca_ia"] = 0.8
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "lancamento_removido_mes_anterior":
            categoria = _categoria(achado, registro)
            valor = _fmt_moeda(achado.valor_encontrado)
            descricao = (registro.descricao if registro else None) or categoria
            titulo = f"Lançamento recorrente ausente este mês — {descricao} ({valor} no mês anterior)"
            paragrafo = (
                f"Um lançamento muito parecido com este ({descricao}, {valor}) apareceu no mês anterior e "
                f"não tem equivalente neste mês — pode ser um cancelamento legítimo ou uma despesa que "
                f"deixou de ser cobrada/lançada por engano."
            )
            o_que_verificar = "Por que este lançamento recorrente não aparece neste mês? Foi descontinuado legitimamente ou deixou de ser lançado/cobrado por engano?"
            base["confianca_ia"] = 0.6
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "consolidacao_multipla_pendente_julgamento":
            titulo, paragrafo, o_que_verificar = _texto_consolidacao(achado)
        elif achado.tipo in _TEXTOS_REGRAS_GERAIS:
            titulo, paragrafo, o_que_verificar = _TEXTOS_REGRAS_GERAIS[achado.tipo](achado)
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "subconta_atipica" and (achado.detalhes.get("lancamentos") or achado.detalhes.get("so_total")):
            titulo, paragrafo, o_que_verificar = _texto_subconta_nova(achado)
            base["revisado_por"] = "sistema:regra_deterministica"
        elif achado.tipo == "subconta_atipica":
            titulo, paragrafo, o_que_verificar = _texto_subconta_atipica(achado)
        elif achado.tipo == "sem_lancamento_correspondente":
            categoria = achado.linha_demonstrativo or "lançamento"
            valor = _fmt_moeda(achado.valor_encontrado)
            titulo = f"Comprovante de pagamento sem despesa correspondente — {categoria} ({valor})"
            paragrafo = f"Existe um comprovante de pagamento ({valor}) que não foi pareado com nenhuma despesa listada no demonstrativo."
            o_que_verificar = "A que lançamento do demonstrativo este pagamento corresponde? Ele aparece sob outro código ou falta lançar a despesa?"
        else:
            # Tipo de achado desconhecido (nunca deveria acontecer — TIPOS_ACHADO
            # em base.py é fechado) — melhor um texto genérico honesto do que
            # travar a geração do relatório.
            titulo = f"Achado tipo '{achado.tipo}' — revisar"
            paragrafo = f"Regra aplicada: {achado.regra_aplicada}."
            o_que_verificar = "Podem explicar este lançamento/apontamento? (tipo sem narrativa automática definida)"
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
