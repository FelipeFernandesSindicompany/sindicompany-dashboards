"""
Motor de matching determinístico — cruza RegistroComprovante[] (extraídos do
PDF da pasta de prestação de contas) contra DadosFinanceiros (já produzido
pelo adapter de demonstrativo existente, ver adapters/base.py).

Nenhuma regra aqui decide "é grave" ou escreve texto — só classifica o tipo
de achado, calcula valores esperado/encontrado e registra a regra aplicada,
para que a camada de interpretação (conciliacao/interpretacao.py) trabalhe
sempre em cima de fatos rastreáveis, nunca de julgamento embutido no código.

Tipos de comprovante de pagamento (têm código de lançamento e podem ser
pareados 1:1 com uma "despesa_interna" do mesmo código):
"""
from conciliacao.base import Achado, RegistroComprovante, chave_registro

TIPOS_COMPROVANTE_PAGAMENTO = {"pix", "darf", "boleto", "debito_automatico"}

TOLERANCIA_CENTAVOS = 0.01


def _proximo_id(contador: list) -> str:
    contador[0] += 1
    return f"ACH-{contador[0]:04d}"


def _valores_batem(a: float, b: float, tolerancia: float = TOLERANCIA_CENTAVOS) -> bool:
    return abs(a - b) <= tolerancia


def gerar_achados(registros: list[RegistroComprovante], dados_financeiros=None) -> list[Achado]:
    """
    Executa as regras determinísticas, na ordem:
      1. Pareamento código-a-código (despesa_interna x comprovante de pagamento)
      2. Consolidação many-to-one (N despesas sem par direto somam 1 pagamento órfão)
      3. Duplicidade (mesmo código de despesa_interna repetido com mesmo valor)
      4. CNPJ ausente (débito automático de concessionária sem CNPJ extraído)
      5. Divergência de total por categoria (se dados_financeiros for passado)

    `dados_financeiros` é opcional (DadosFinanceiros do adapter existente,
    ver adapters/base.py) — quando ausente, a regra 5 é pulada.
    """
    contador = [0]
    achados: list[Achado] = []

    despesas_internas = [r for r in registros if r.tipo_documento == "despesa_interna"]
    pagamentos = [r for r in registros if r.tipo_documento in TIPOS_COMPROVANTE_PAGAMENTO]

    despesas_por_codigo: dict[str, list[RegistroComprovante]] = {}
    for r in despesas_internas:
        if r.codigo:
            despesas_por_codigo.setdefault(r.codigo, []).append(r)

    # Códigos com mais de uma despesa_interna de mesmo valor — tratados só
    # como "duplicidade" (regra 4), nunca também como "sem_comprovante"
    # (regra 3), para não reportar a mesma evidência duas vezes.
    codigos_duplicados = {
        codigo for codigo, grupo in despesas_por_codigo.items()
        if len(grupo) >= 2 and len({round(d.valor, 2) for d in grupo}) == 1
    }

    pagamentos_por_codigo: dict[str, list[RegistroComprovante]] = {}
    pagamentos_sem_codigo: list[RegistroComprovante] = []
    for r in pagamentos:
        if r.codigo:
            pagamentos_por_codigo.setdefault(r.codigo, []).append(r)
        else:
            pagamentos_sem_codigo.append(r)

    codigos_pagamento_usados: set[str] = set()

    # ── 1. Pareamento código-a-código ──────────────────────────────────────
    # Um mesmo código de pagamento pode ter várias páginas no PDF (capa +
    # continuação do mesmo boleto/fatura) — usa o MAIOR valor do grupo como
    # representativo (páginas de capa às vezes não repetem o valor) e lista
    # todas as páginas do grupo como evidência, em vez de 1 achado por página.
    despesas_sem_par: list[RegistroComprovante] = []
    for codigo, grupo_despesa in despesas_por_codigo.items():
        pares = pagamentos_por_codigo.get(codigo)
        if not pares:
            despesas_sem_par.extend(grupo_despesa)
            continue
        codigos_pagamento_usados.add(codigo)
        despesa = grupo_despesa[0]
        valor_pagamento = max(p.valor for p in pares)
        chaves_pagamento = [chave_registro(p) for p in pares]
        if _valores_batem(despesa.valor, valor_pagamento):
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="ok_verificado",
                severidade_sugerida="informativo",
                regra_aplicada="pareamento_codigo_comprovante_valor_confere",
                registros_relacionados=[chave_registro(despesa)] + chaves_pagamento,
                linha_demonstrativo=despesa.categoria_demonstrativo,
                valor_esperado=despesa.valor,
                valor_encontrado=valor_pagamento,
                confianca_deterministica=1.0,
            ))
        else:
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="divergencia_valor",
                severidade_sugerida="alto",
                regra_aplicada="pareamento_codigo_comprovante_valor_diverge",
                registros_relacionados=[chave_registro(despesa)] + chaves_pagamento,
                linha_demonstrativo=despesa.categoria_demonstrativo,
                valor_esperado=despesa.valor,
                valor_encontrado=valor_pagamento,
                confianca_deterministica=1.0,
            ))

    # Grupos de comprovante de pagamento (por código) que não bateram com
    # nenhuma despesa_interna — mantidos agrupados (não uma página por vez).
    grupos_pagamento_orfaos: dict[str, list[RegistroComprovante]] = {
        codigo: grupo for codigo, grupo in pagamentos_por_codigo.items()
        if codigo not in codigos_pagamento_usados
    }

    # ── 2. Consolidação many-to-one (ex.: 1 DARF paga retenções de N fornecedores) ──
    despesas_sem_par_restantes = list(despesas_sem_par)
    codigos_pagamento_consolidados: set[str] = set()
    for codigo_pagamento, grupo_pagamento in grupos_pagamento_orfaos.items():
        valor_pagamento = max(p.valor for p in grupo_pagamento)
        pagamento_ref = grupo_pagamento[0]
        grupo_candidato = [
            d for d in despesas_sem_par_restantes
            if d.pagamento == pagamento_ref.pagamento and d.conta == pagamento_ref.conta
        ]
        if len(grupo_candidato) < 2:
            continue
        soma = sum(d.valor for d in grupo_candidato)
        if _valores_batem(soma, valor_pagamento):
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="consolidacao_multipla_pendente_julgamento",
                severidade_sugerida="informativo",
                regra_aplicada="soma_grupo_data_conta_bate_pagamento_consolidado",
                registros_relacionados=(
                    [chave_registro(d) for d in grupo_candidato]
                    + [chave_registro(p) for p in grupo_pagamento]
                ),
                valor_esperado=soma,
                valor_encontrado=valor_pagamento,
                # Julgamento de negócio ainda necessário (é uma consolidação plausível,
                # não uma certeza) — confiança deliberadamente < 1.0 para forçar revisão.
                confianca_deterministica=0.6,
            ))
            for d in grupo_candidato:
                despesas_sem_par_restantes.remove(d)
            codigos_pagamento_consolidados.add(codigo_pagamento)

    # ── 2b. Confirmação por valor via relatório fiscal (ex.: EFD-Reinf) ─────
    # Retenções tributárias sem comprovante direto às vezes aparecem listadas,
    # por VALOR, no quadro "Detalhamento por Periodicidade, Natureza de
    # Rendimento e Código de Receita" de um relatório fiscal anexado (a pasta
    # não referencia o código de despesa nessa tabela, só o valor retido) —
    # ver conciliacao/addomus_pdf.py::_extrair_valores_detalhamento_fiscal.
    # Confiança um pouco menor que o pareamento por código (é correspondência
    # só por valor, não por identificador), mas ainda uma evidência concreta.
    relatorios_fiscais = [r for r in registros if r.tipo_documento == "relatorio_fiscal"]
    despesas_ainda_sem_par: list[RegistroComprovante] = []
    for despesa in despesas_sem_par_restantes:
        relatorio_correspondente = next(
            (rf for rf in relatorios_fiscais
             if any(_valores_batem(despesa.valor, v) for v in rf.valores_detalhamento_fiscal)),
            None,
        )
        if relatorio_correspondente is None:
            despesas_ainda_sem_par.append(despesa)
            continue
        achados.append(Achado(
            id=_proximo_id(contador),
            tipo="consolidacao_multipla_pendente_julgamento",
            severidade_sugerida="informativo",
            regra_aplicada="valor_bate_com_detalhamento_relatorio_fiscal",
            registros_relacionados=[chave_registro(despesa), chave_registro(relatorio_correspondente)],
            linha_demonstrativo=despesa.categoria_demonstrativo,
            valor_esperado=despesa.valor,
            valor_encontrado=despesa.valor,
            confianca_deterministica=0.8,
        ))
    despesas_sem_par_restantes = despesas_ainda_sem_par

    # ── 3. O que sobrou de despesa sem par vira achado "sem_comprovante" ────
    # (exceto códigos já marcados como duplicidade — regra 4 cobre esses)
    for despesa in despesas_sem_par_restantes:
        if despesa.codigo in codigos_duplicados:
            continue
        achados.append(Achado(
            id=_proximo_id(contador),
            tipo="sem_comprovante",
            severidade_sugerida="alto",
            regra_aplicada="despesa_interna_sem_comprovante_pagamento_pareado",
            registros_relacionados=[chave_registro(despesa)],
            linha_demonstrativo=despesa.categoria_demonstrativo,
            valor_esperado=despesa.valor,
            valor_encontrado=None,
            confianca_deterministica=1.0,
        ))

    # Grupos de pagamento órfãos que não entraram em nenhuma consolidação —
    # 1 achado por código (todas as páginas do mesmo comprovante juntas),
    # não 1 achado por página física.
    for codigo_pagamento, grupo_pagamento in grupos_pagamento_orfaos.items():
        if codigo_pagamento in codigos_pagamento_consolidados:
            continue
        valor_pagamento = max(p.valor for p in grupo_pagamento)
        achados.append(Achado(
            id=_proximo_id(contador),
            tipo="sem_lancamento_correspondente",
            severidade_sugerida="atencao",
            regra_aplicada="comprovante_pagamento_sem_despesa_interna_pareada",
            registros_relacionados=[chave_registro(p) for p in grupo_pagamento],
            valor_esperado=None,
            valor_encontrado=valor_pagamento,
            confianca_deterministica=1.0,
        ))
    # Pagamentos sem código extraído — não dá para agrupar com segurança,
    # cada página vira um achado individual (evita perder evidência).
    for pagamento in pagamentos_sem_codigo:
        achados.append(Achado(
            id=_proximo_id(contador),
            tipo="sem_lancamento_correspondente",
            severidade_sugerida="atencao",
            regra_aplicada="comprovante_pagamento_sem_codigo_extraido",
            registros_relacionados=[chave_registro(pagamento)],
            valor_esperado=None,
            valor_encontrado=pagamento.valor,
            confianca_deterministica=0.8,
        ))

    # ── 4. Duplicidade (mesmo código de despesa_interna repetido, mesmo valor) ──
    for codigo, grupo in despesas_por_codigo.items():
        if len(grupo) < 2:
            continue
        valores = {round(d.valor, 2) for d in grupo}
        if len(valores) == 1:
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="duplicidade",
                severidade_sugerida="critico",
                regra_aplicada="mesmo_codigo_despesa_repetido_mesmo_valor",
                registros_relacionados=[chave_registro(d) for d in grupo],
                valor_esperado=grupo[0].valor,
                valor_encontrado=grupo[0].valor,
                confianca_deterministica=1.0,
            ))

    # ── 5. CNPJ ausente (débito automático de concessionária) ─────────────
    # Agrupado por código (não por página) — a mesma fatura pode ter várias
    # páginas de anexo, todas sem CNPJ em texto simples.
    debitos_sem_cnpj_por_codigo: dict[str, list[RegistroComprovante]] = {}
    debitos_sem_cnpj_sem_codigo: list[RegistroComprovante] = []
    for r in registros:
        if r.tipo_documento == "debito_automatico" and not r.cnpj_cpf:
            if r.codigo:
                debitos_sem_cnpj_por_codigo.setdefault(r.codigo, []).append(r)
            else:
                debitos_sem_cnpj_sem_codigo.append(r)
    for codigo, grupo in debitos_sem_cnpj_por_codigo.items():
        achados.append(Achado(
            id=_proximo_id(contador),
            tipo="cnpj_ausente",
            severidade_sugerida="informativo",
            regra_aplicada="debito_automatico_sem_cnpj_extraido",
            registros_relacionados=[chave_registro(r) for r in grupo],
            valor_esperado=None,
            valor_encontrado=max(r.valor for r in grupo),
            confianca_deterministica=1.0,
        ))
    for r in debitos_sem_cnpj_sem_codigo:
        achados.append(Achado(
            id=_proximo_id(contador),
            tipo="cnpj_ausente",
            severidade_sugerida="informativo",
            regra_aplicada="debito_automatico_sem_cnpj_extraido",
            registros_relacionados=[chave_registro(r)],
            valor_esperado=None,
            valor_encontrado=r.valor,
            confianca_deterministica=1.0,
        ))

    # ── 6. Divergência de total por categoria (opcional, exige DadosFinanceiros) ──
    if dados_financeiros is not None:
        achados.extend(_achados_divergencia_categoria(despesas_internas, dados_financeiros, contador))

    return achados


def _achados_divergencia_categoria(despesas: list[RegistroComprovante], dados_financeiros, contador: list) -> list[Achado]:
    """Compara a soma dos comprovantes extraídos por categoria contra o total do
    demonstrativo (DadosFinanceiros já lido pelo adapter existente) — reaproveitado
    por gerar_achados() (Addomus) e gerar_achados_lirba()."""
    soma_por_categoria: dict[str, float] = {}
    for d in despesas:
        if d.categoria_demonstrativo:
            soma_por_categoria[d.categoria_demonstrativo] = (
                soma_por_categoria.get(d.categoria_demonstrativo, 0.0) + d.valor
            )
    achados = []
    for categoria, total_demonstrativo in dados_financeiros.categorias_despesa.items():
        total_extraido = soma_por_categoria.get(categoria, 0.0)
        if not _valores_batem(total_extraido, total_demonstrativo, tolerancia=0.02):
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="divergencia_valor",
                severidade_sugerida="critico",
                regra_aplicada="soma_comprovantes_categoria_diverge_do_demonstrativo",
                registros_relacionados=[
                    chave_registro(d) for d in despesas if d.categoria_demonstrativo == categoria
                ],
                linha_demonstrativo=categoria,
                valor_esperado=total_demonstrativo,
                valor_encontrado=total_extraido,
                confianca_deterministica=1.0,
            ))
    return achados


def gerar_achados_lirba(registros: list[RegistroComprovante], dados_financeiros=None) -> list[Achado]:
    """
    Regras para o formato Lirba/ContasData (ver conciliacao/lirba_pdf.py) —
    mais simples que gerar_achados(): a página de "Comprovante de Despesa"
    não tem texto útil (é imagem digitalizada), então não há valor pra
    comparar — só existência ou não do comprovante pelo código.
    """
    contador = [0]
    achados: list[Achado] = []

    despesas = [r for r in registros if r.tipo_documento == "despesa_listada"]
    comprovantes = [r for r in registros if r.tipo_documento == "comprovante_anexado"]
    codigos_com_comprovante = {r.codigo for r in comprovantes}

    # Alguns exports (ex.: Habitacional XLSX de Baturité) nunca preenchem a
    # coluna Anexo com hyperlink real em NENHUMA linha do mês — a ausência de
    # comprovante_anexado aí é sistêmica do arquivo inteiro, não evidência de
    # item específico sem documentação. Rodar a checagem normal geraria
    # "sem_comprovante" em 100% dos itens (falso positivo em massa), então
    # ela é pulada só nesse caso — quando existe pelo menos 1 comprovante no
    # mês (ex.: Guaratambé, Alvorada), a checagem roda normalmente (código já
    # é único por linha mesmo quando o Nº Lançto. bruto é degenerado — ver
    # conciliacao/habitacional_xlsx.py::extrair_comprovantes).
    avaliar_comprovante = bool(comprovantes)

    if avaliar_comprovante:
        # ── 1. Cada despesa listada tem (ou não) uma página "Comprovante de Despesa" ──
        for d in despesas:
            if d.codigo in codigos_com_comprovante:
                achados.append(Achado(
                    id=_proximo_id(contador),
                    tipo="ok_verificado",
                    severidade_sugerida="informativo",
                    regra_aplicada="codigo_tem_pagina_comprovante_anexado",
                    registros_relacionados=[chave_registro(d)],
                    linha_demonstrativo=d.categoria_demonstrativo,
                    valor_esperado=d.valor,
                    valor_encontrado=d.valor,
                    confianca_deterministica=1.0,
                ))
            else:
                achados.append(Achado(
                    id=_proximo_id(contador),
                    tipo="sem_comprovante",
                    severidade_sugerida="alto",
                    regra_aplicada="despesa_listada_sem_pagina_comprovante_anexado",
                    registros_relacionados=[chave_registro(d)],
                    linha_demonstrativo=d.categoria_demonstrativo,
                    valor_esperado=d.valor,
                    valor_encontrado=None,
                    confianca_deterministica=1.0,
                ))

        # ── 2. Duplicidade (mesmo código listado mais de uma vez, mesmo valor) ──
        por_codigo: dict[str, list[RegistroComprovante]] = {}
        for d in despesas:
            por_codigo.setdefault(d.codigo, []).append(d)
        for codigo, grupo in por_codigo.items():
            if len(grupo) >= 2 and len({round(d.valor, 2) for d in grupo}) == 1:
                achados.append(Achado(
                    id=_proximo_id(contador),
                    tipo="duplicidade",
                    severidade_sugerida="critico",
                    regra_aplicada="mesmo_codigo_despesa_listada_repetido_mesmo_valor",
                    registros_relacionados=[chave_registro(d) for d in grupo],
                    valor_esperado=grupo[0].valor,
                    valor_encontrado=grupo[0].valor,
                    confianca_deterministica=1.0,
                ))

    # ── 3. Divergência de total por categoria (opcional, exige DadosFinanceiros) ──
    if dados_financeiros is not None:
        achados.extend(_achados_divergencia_categoria(despesas, dados_financeiros, contador))

    return achados


def gerar_achados_datadigitus(registros: list[RegistroComprovante], dados_financeiros=None) -> list[Achado]:
    """
    Regras para o formato DataDigitus (ver conciliacao/datadigitus_pdf.py) —
    o "Prestação de Contas" desse software é só a listagem de despesas do
    próprio demonstrativo, sem comprovante escaneado nem link anexado em
    lugar nenhum do arquivo. Não há checagem de "comprovante ausente" aqui
    (não existe evidência externa pra cruzar) — só duas checagens de
    consistência aritmética do próprio documento:
      1. Duplicidade: mesma data + valor + categoria repetidos.
      2. Divergência entre a soma dos lançamentos de uma conta e o total
         "TOTAL DA CONTA X" declarado no mesmo documento.
    `dados_financeiros` não é usado (mantido só pra manter a mesma
    assinatura das demais funções de matching, ver gerar_achados_por_empresa
    em scripts/gerar_relatorio_conciliacao.py).
    """
    contador = [0]
    achados: list[Achado] = []

    despesas = [r for r in registros if r.tipo_documento == "despesa_listada"]
    totais_declarados = [r for r in registros if r.tipo_documento == "total_conta_declarado"]

    # ── 1. Duplicidade (mesma data + valor + categoria + histórico) ──────────
    # Inclui o histórico na chave (não só data+valor+categoria) porque duas
    # despesas diferentes e legítimas podem coincidir em data/valor/categoria
    # (ex.: "COMGÁS CONSUMO - SALÃO DE FESTAS" e "COMGÁS - ZELADOR" no mesmo
    # dia, ambas R$ 12,40, mesma categoria) — só vira achado quando o texto
    # do histórico também é idêntico, sinal bem mais forte de lançamento
    # repetido (ex.: mesma "TAXA ANUAL ELEVADOR/PMSP" lançada duas vezes).
    grupos_por_data_valor_cat: dict[tuple, list[RegistroComprovante]] = {}
    for d in despesas:
        if not d.descricao:
            continue  # sem histórico extraído (linha com quebra) — não dá pra comparar com segurança
        # autenticacao (nº de documento/NF/Fatura, quando extraído — ver
        # conciliacao/consvicta_pdf.py) entra na chave pra não confundir duas
        # faturas distintas do mesmo fornecedor que coincidem em data+valor
        # (ex.: duas contas de luz de medidores diferentes, mesmo R$).
        chave = (d.vencimento, round(d.valor, 2), d.categoria_demonstrativo, d.descricao.strip().upper(), d.autenticacao)
        grupos_por_data_valor_cat.setdefault(chave, []).append(d)
    for grupo in grupos_por_data_valor_cat.values():
        if len(grupo) >= 2:
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="duplicidade",
                severidade_sugerida="atencao",
                regra_aplicada="mesma_data_valor_categoria_historico_repetidos",
                registros_relacionados=[chave_registro(d) for d in grupo],
                linha_demonstrativo=grupo[0].categoria_demonstrativo,
                valor_esperado=grupo[0].valor,
                valor_encontrado=grupo[0].valor,
                # Sinal mais fraco que duplicidade por código (regra 4 de
                # gerar_achados()) — aqui é por coincidência de 4 campos, sem
                # identificador único, então confiança < 1.0 força revisão.
                confianca_deterministica=0.85,
            ))

    # ── 2. Soma dos lançamentos de cada conta x total declarado ─────────────
    soma_por_conta: dict[str, float] = {}
    registros_por_conta: dict[str, list[RegistroComprovante]] = {}
    for d in despesas:
        soma_por_conta[d.conta] = soma_por_conta.get(d.conta, 0.0) + d.valor
        registros_por_conta.setdefault(d.conta, []).append(d)
    for total in totais_declarados:
        soma_extraida = soma_por_conta.get(total.descricao, 0.0)
        if not _valores_batem(soma_extraida, total.valor, tolerancia=0.02):
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="divergencia_valor",
                severidade_sugerida="critico",
                regra_aplicada="soma_lancamentos_diverge_total_da_conta_declarado",
                registros_relacionados=(
                    [chave_registro(d) for d in registros_por_conta.get(total.descricao, [])]
                    + [chave_registro(total)]
                ),
                linha_demonstrativo=total.descricao,
                valor_esperado=total.valor,
                valor_encontrado=soma_extraida,
                confianca_deterministica=1.0,
            ))

    return achados


def gerar_achados_gcont(registros: list[RegistroComprovante], dados_financeiros=None) -> list[Achado]:
    """
    Regras para o formato GCONT (ver conciliacao/condominios/club_park_butanta.py)
    — cada pagamento já vem com sua própria página de "Comprovantes de
    despesas" auto-suficiente (o sistema só gera a página quando o pagamento
    é efetivado), então não existe "sem comprovante" nesse formato. Só duas
    checagens de consistência:
      1. Duplicidade: mesmo fornecedor + documento + valor repetidos (ou
         fornecedor + vencimento + valor, quando não há nº de documento).
      2. Soma dos comprovantes extraídos x total declarado no Livro Caixa
         ("N itens VALOR_TOTAL").
    """
    contador = [0]
    achados: list[Achado] = []

    despesas = [r for r in registros if r.tipo_documento == "despesa_com_comprovante"]
    totais_declarados = [r for r in registros if r.tipo_documento == "total_declarado"]

    # ── 1. Duplicidade ────────────────────────────────────────────────────
    grupos: dict[tuple, list[RegistroComprovante]] = {}
    for d in despesas:
        fornecedor_norm = (d.fornecedor or "").strip().upper()
        # autenticacao aqui guarda o nº de Documento/NF (ver extrator) — quando
        # ausente (ex.: contas de concessionária sem NF), cai no fallback por
        # vencimento pra ainda ter uma chave razoável de deduplicação.
        chave = (fornecedor_norm, d.autenticacao or d.vencimento, round(d.valor, 2))
        grupos.setdefault(chave, []).append(d)
    for grupo in grupos.values():
        if len(grupo) >= 2:
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="duplicidade",
                severidade_sugerida="atencao",
                regra_aplicada="mesmo_fornecedor_documento_valor_repetidos",
                registros_relacionados=[chave_registro(d) for d in grupo],
                linha_demonstrativo=grupo[0].categoria_demonstrativo,
                valor_esperado=grupo[0].valor,
                valor_encontrado=grupo[0].valor,
                confianca_deterministica=0.8,
            ))

    # ── 2. Soma dos comprovantes x total declarado no Livro Caixa ──────────
    soma_extraida = sum(d.valor for d in despesas)
    for total in totais_declarados:
        if not _valores_batem(soma_extraida, total.valor, tolerancia=0.02):
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="divergencia_valor",
                severidade_sugerida="critico",
                regra_aplicada="soma_comprovantes_diverge_total_livro_caixa",
                registros_relacionados=[chave_registro(d) for d in despesas] + [chave_registro(total)],
                valor_esperado=total.valor,
                valor_encontrado=soma_extraida,
                confianca_deterministica=1.0,
            ))

    return achados


def gerar_achados_balancete_mensal(registros: list[RegistroComprovante], dados_financeiros=None) -> list[Achado]:
    """
    Regras para o formato "Balancete Mensal" (ver
    conciliacao/balancete_mensal.py) — Giardino D'Itália, Vita Parque
    (iello_pdf) e Jaú 1894 (lello_pdf). Esse formato não tem nenhum
    lançamento individual nem comprovante no arquivo — só totais agregados
    por categoria/conta. Não há comprovante-a-comprovante possível, então a
    checagem é de CONSISTÊNCIA ARITMÉTICA INTERNA do próprio balancete:
      1. Soma dos itens de cada seção ("COMPOSIÇÃO..."/"RECEBIMENTO...")
         x a linha "TOTAL" que fecha a seção.
      2. Saldo anterior + créditos + débitos x saldo final de cada conta
         em "RESUMO FINANCEIRO".
    """
    contador = [0]
    achados: list[Achado] = []

    secoes_calc = {r.codigo: r for r in registros if r.tipo_documento == "secao_soma_calculada"}
    secoes_decl = {r.codigo: r for r in registros if r.tipo_documento == "secao_total_declarado"}
    for chave, calc in secoes_calc.items():
        decl = secoes_decl.get(chave + "-total")
        if decl is None:
            continue
        if not _valores_batem(calc.valor, decl.valor, tolerancia=0.02):
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="divergencia_valor",
                severidade_sugerida="critico",
                regra_aplicada="soma_secao_diverge_total_declarado_no_balancete",
                registros_relacionados=[chave_registro(calc), chave_registro(decl)],
                linha_demonstrativo=calc.descricao,
                valor_esperado=decl.valor,
                valor_encontrado=calc.valor,
                confianca_deterministica=1.0,
            ))

    contas_calc = {r.codigo: r for r in registros if r.tipo_documento == "conta_saldo_calculado"}
    contas_decl = {r.codigo: r for r in registros if r.tipo_documento == "conta_saldo_declarado"}
    for chave, calc in contas_calc.items():
        decl = contas_decl.get(chave + "-total")
        if decl is None:
            continue
        if not _valores_batem(calc.valor, decl.valor, tolerancia=0.02):
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="divergencia_valor",
                severidade_sugerida="critico",
                regra_aplicada="saldo_conta_nao_fecha_no_resumo_financeiro",
                registros_relacionados=[chave_registro(calc), chave_registro(decl)],
                linha_demonstrativo=calc.descricao,
                valor_esperado=decl.valor,
                valor_encontrado=calc.valor,
                confianca_deterministica=1.0,
            ))

    return achados
