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
import re
import unicodedata
from datetime import datetime, timedelta

from conciliacao import lirba_pdf as _lp
from conciliacao import verificacoes_historico
from conciliacao.base import Achado, RegistroComprovante, chave_registro

TIPOS_COMPROVANTE_PAGAMENTO = {"pix", "darf", "boleto", "debito_automatico"}

TOLERANCIA_CENTAVOS = 0.01

# Além disso já conta como atraso relevante (severidade "alto" em vez de "atencao") —
# ver achado_atraso_pagamento().
_DIAS_ATRASO_GRAVE = 30


def _proximo_id(contador: list) -> str:
    contador[0] += 1
    return f"ACH-{contador[0]:04d}"


def _normalizar_texto(s: str) -> str:
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")
    return s.upper()


def _motivo_isencao_comprovante(descricao: str | None, categoria: str | None) -> str | None:
    """
    Alguns lançamentos genuinamente não têm (e não deveriam ter) comprovante
    de pagamento a terceiro pra cobrar — não são despesas de verdade, são
    movimentos internos ou tarifas debitadas direto pelo banco sem gerar
    recibo. Sem esta lista, cada um deles virava um falso "sem comprovante"/
    "conteúdo não verificável" TODO mês, indefinidamente. Confirmado com o
    usuário (feedback explícito, dados reais de Baturité):
      - Transferência entre contas do PRÓPRIO condomínio (ex.: "TRANSF.P/CTA
        APLIC", movendo saldo da Ordinária pra uma conta de Aplicação) — é
        um movimento bancário interno, não uma prestação de serviço/compra.
      - Tarifas bancárias ("Despesas Bancárias") — debitadas direto em
        extrato pelo próprio banco, sem comprovante individual por natureza.
    Retorna o nome da regra (pra registrar em Achado.regra_aplicada) ou None
    quando nenhuma isenção se aplica.
    """
    texto = _normalizar_texto(f"{descricao or ''} {categoria or ''}")
    # as regras abaixo olham só a DESCRIÇÃO do lançamento: a categoria "TARIFAS CONCESSIONÁRIAS" (água, luz, gás,
    # telefone) não é tarifa bancária, e essas contas têm fatura a anexar
    texto_desc = _normalizar_texto(descricao or "")
    if "TRANSF" in texto and "CTA" in texto:
        return "transferencia_interna_entre_contas_proprias"
    if "BANCARI" in texto or (_RE_TARIFA_BANCARIA.search(texto_desc) and not _RE_CONCESSIONARIA.search(texto_desc)):
        return "tarifa_bancaria_sem_comprovante_individual"
    if _RE_ENCARGO_DEBITADO_PELO_BANCO.search(texto_desc):
        return "encargo_debitado_pelo_banco_sem_comprovante_individual"
    if _RE_ISENCAO_DE_COTA.search(texto_desc):
        return "isencao_de_cota_lancamento_contabil_sem_comprovante"
    return None


# Tarifas debitadas direto em extrato pelo próprio banco, com o histórico abreviado ("TAR/CUSTAS COBRANCA",
# "TAR PIX QR LIQ BOLECODE", "TARIFA BOLETO", "TAR COBRANCA MENSAL", "TARIFA PLANO ADAPT") — mesma regra das
# "Despesas Bancárias" acima: não há prestador nem recibo a anexar.
_RE_TARIFA_BANCARIA = re.compile(r"\bTAR(?:IFAS?)?\b")
# descrições de concessionária (água/luz/gás/telefone/internet) NUNCA são tarifa bancária, mesmo citando "tarifa"
_RE_CONCESSIONARIA = re.compile(
    r"ENERGIA|ELETRIC|\bAGUA\b|ESGOTO|\bGAS\b|TELEFON|SABESP|COMGAS|\bENEL\b|\bVIVO\b|\bCLARO\b|\bTIM\b|INTERNET")
# "ISENÇÃO - RECIBO: 40354847 - UNIDADE: R - 000027": abatimento/isenção de cota de uma unidade — lançamento
# contábil interno do condomínio, não há pagamento a terceiro nem documento a anexar.
_RE_ISENCAO_DE_COTA = re.compile(r"\bISENCAO\s*-?\s*RECIBO")
# NÃO isentos (decisão do dono nos relatórios aprovados): "Acerto Contábil - FORNECEDOR - NF 99" (re-lançamento de despesa
# real) segue como "sem comprovante" (severidade alto mantida na revisão humana de Port Saint Tropez 03/2026); o mesmo vale,
# por analogia, para "APROP DESP" e "REGULARIZAÇÕES CONTÁBEIS".
# Imposto/encargo que o banco debita sozinho (IR/IOF sobre resgate de aplicação, juros de saldo devedor).
_RE_ENCARGO_DEBITADO_PELO_BANCO = re.compile(
    r"\bI\.?\s?R\.?\s?S?\s?/\s?RESGATE|\bIR\s+S/\s*RESGATE|\bIOF\b|JUROS\s+S/\s*SALDO\s+DEVEDOR"
)


def _valores_batem(a: float, b: float, tolerancia: float = TOLERANCIA_CENTAVOS) -> bool:
    return abs(a - b) <= tolerancia


def _proximo_dia_util(data: datetime) -> datetime:
    """
    Primeiro dia ÚTIL BANCÁRIO a partir de `data` (ela mesma, se já for): pula sábado, domingo e os feriados em que
    os bancos fecham (ver _feriados_bancarios). Vencimento em dia sem expediente bancário pago no dia útil seguinte é
    o comportamento normal do sistema bancário, não atraso — confirmado com o usuário para fins de semana (vencimentos
    em 25/07/2026 (sábado) e 12/07/2026 (domingo) pagos na segunda) e, aqui, estendido aos feriados (ex.: boleto de
    15/02/2026 pago em 18/02/2026, depois do Carnaval).
    """
    # _feriados_bancarios (definida mais abaixo neste módulo) devolve `date`s
    while data.weekday() >= 5 or data.date() in _feriados_bancarios(data.year):
        data = data + timedelta(days=1)
    return data


def achado_atraso_pagamento(registro: RegistroComprovante, contador: list) -> Achado | None:
    """
    Compara `vencimento` x `pagamento` (data efetiva) do mesmo registro —
    exige os dois campos em "DD/MM/YYYY". Retorna None (não é achado) tanto
    quando o pagamento foi em dia (considerando o rollover de fim de semana,
    ver _proximo_dia_util — confirmado com o usuário como falso positivo real:
    vencimentos em 25/07/2026 (sábado) e 12/07/2026 (domingo) pagos na
    segunda-feira seguinte estavam sendo marcados como atraso indevidamente)
    quanto quando falta um dos dois campos (formato de origem só registra uma
    data) — nesse segundo caso a checagem é "não aplicável" para esse
    registro, não "sem atraso confirmado", e cabe a quem chama decidir como
    isso aparece no relatório (ver seção "Verificações realizadas" em
    scripts/gerar_relatorio_conciliacao.py).
    """
    if not (registro.vencimento and registro.pagamento):
        return None
    try:
        venc = datetime.strptime(registro.vencimento, "%d/%m/%Y")
        pago = datetime.strptime(registro.pagamento, "%d/%m/%Y")
    except ValueError:
        return None
    prazo_limite = _proximo_dia_util(venc)
    if pago <= prazo_limite:
        return None
    dias_atraso = (pago - prazo_limite).days
    return Achado(
        id=_proximo_id(contador),
        tipo="atraso_pagamento",
        severidade_sugerida="alto" if dias_atraso > _DIAS_ATRASO_GRAVE else "atencao",
        regra_aplicada="data_pagamento_posterior_ao_vencimento",
        registros_relacionados=[chave_registro(registro)],
        linha_demonstrativo=registro.categoria_demonstrativo,
        valor_esperado=None,
        valor_encontrado=registro.valor,
        confianca_deterministica=1.0,
    )


# Regexes de NF compartilhados com a leitura do anexo (conciliacao/lirba_pdf.py) — uma definição só.
_RE_NF_NA_DESCRICAO = _lp.RE_NF_NA_DESCRICAO
_RE_NF_NO_COMPROVANTE = _lp.RE_MARCADOR_NF
# Confirmado em dados reais (Ciudad Real, formato de página embutida — ver
# conciliacao/condominios/central_das_artes.py::_ler_comprovante_embutido)
# que o "texto_bruto" às vezes é só a CAPA-RESUMO do comprovante embutido
# ("Comprovante de Despesa\n<código>\n<descrição>\n<valor>\n<data>\nData\n
# Histórico\nValor\n<página>/<total>", sempre entre 230-280 caracteres) — a
# ANEXAÇÃO de verdade (as páginas seguintes, muitas vezes até 22 páginas de
# imagem escaneada) nunca é lida por esse leitor. Sem esse piso, TODA
# despesa com "NF." na descrição virava "nota_fiscal_ausente" mesmo quando
# a NF genuinamente está anexada, só não foi lida ainda — confirmado que
# isso gerava 54 falsos positivos de 72 despesas num único mês. Comprovantes
# de verdade (bancários ou PDF nativo) sempre passam de 300 caracteres.
_TAMANHO_MINIMO_TEXTO_CONFIAVEL = 300


def achado_nota_fiscal_ausente(
    descricao: str | None, texto_comprovante: str | None, valor_esperado: float | None,
    valor_encontrado: float | None, categoria: str | None,
    registros_relacionados: list[str], contador: list,
    nf_em_outros_anexos=None,
) -> "Achado | None":
    """
    Quando a PRÓPRIA listagem já cita um número de Nota Fiscal na descrição
    do lançamento (ex.: "MANUT. ELEVADOR 08/2026 - OTIS - NF. 415106") — ou
    seja, existe uma NF de verdade por trás dessa despesa —, mas o
    comprovante anexado (já com VALOR confirmado, ver chamadores) não traz
    nem o mesmo número nem nenhum marcador de Nota Fiscal (confirmado em
    dados reais, Upper Itaim: a maioria dos comprovantes anexados é só um
    "Comprovante de Pagamento Eletrônico" bancário — prova que o dinheiro
    saiu, não prova o que foi comprado/contratado). Mesma lógica de "valor
    confere mas documentação não está completa" já usada em
    conciliacao/interpretacao.py pro Central das Artes, generalizada aqui
    como função de PROPÓSITO GERAL — recebe texto/descrição já prontos (não
    dois RegistroComprovante) porque cada formato organiza essa informação
    de um jeito diferente: gerar_achados_lirba tem despesa+comprovante como
    registros separados; gerar_achados (Addomus) pode ter VÁRIAS páginas de
    comprovante pro mesmo código (concatenar antes de chamar); gerar_achados_
    gcont tem despesa e comprovante no MESMO registro (passar o mesmo texto
    duas vezes). Quem chama decide como montar `texto_comprovante` E
    `registros_relacionados` pro seu próprio formato — a regra em si (o QUE
    verificar) é a mesma pra todos, só a leitura/montagem dos dados diverge
    (ver [[feedback_despesas_tabela_completa]]).

    Escopo deliberadamente estreito: só dispara quando a LISTAGEM já cita um
    nº de NF — nunca em despesas de folha de pagamento, tributos (INSS/FGTS)
    ou tarifas bancárias, que legitimamente não têm Nota Fiscal nenhuma e
    cuja descrição não cita "NF." (evita alarme falso em massa).
    """
    m_nf = _RE_NF_NA_DESCRICAO.search(descricao or "")
    if not m_nf:
        return None
    texto_comp = texto_comprovante or ""
    if len(texto_comp) < _TAMANHO_MINIMO_TEXTO_CONFIAVEL:
        # Não temos confiança de que já lemos o CONTEÚDO do comprovante (só
        # uma capa-resumo, ou nada) — "não achamos NF" não é a mesma coisa
        # que "confirmamos que a NF não está lá" (ver comentário acima).
        return None
    # Não basta o NÚMERO da NF aparecer no texto do comprovante — o campo
    # "Histórico" de um comprovante bancário sempre REPETE a mesma descrição
    # da listagem (confirmado em dados reais, Upper Itaim: "Histórico: MANUT.
    # ELEVADOR 08/2026 - OTIS - NF. 415106" aparece dentro do PRÓPRIO
    # comprovante de pagamento, só porque o sistema copia a descrição — não
    # prova que a Nota Fiscal em si foi anexada). Só um marcador de Nota
    # Fiscal de verdade ("NOTA FISCAL", "NFS-e", "DANFE") conta.
    if _RE_NF_NO_COMPROVANTE.search(texto_comp):
        return None
    # Página do anexo que o OCR não conseguiu LER (foto de baixa resolução, escaneada de lado...: muito texto, quase
    # nenhuma palavra de documento): não dá para afirmar que a Nota Fiscal NÃO está ali.
    if "[Página " in texto_comp:
        from conciliacao import ocr as _ocr
        for _p, _t in _lp.paginas_do_texto_bruto(texto_comp):
            if len(_t) >= 200 and not _lp.eh_pagina_pagamento(_t) and _ocr._pontuacao_texto(_t) < 8:
                return None
    # "NF. 13462. REC.:" — a própria listagem diz que o documento é um RECIBO (prestador sem nota fiscal): o recibo
    # anexado é o documento fiscal esperado.
    if re.search(r"\bREC\b\.?", descricao or "", re.IGNORECASE) and re.search(r"RECIBO", texto_comp, re.IGNORECASE):
        return None
    # Anexo de várias páginas (ContasData): o documento que traz o MESMO nº de NF (ex.: recibo/fatura com
    # "nº 1.378") conta, desde que não seja o comprovante bancário nem o boleto — esses só repetem o histórico.
    if "[Página " in texto_comp and _lp.numero_nf_em_documento(texto_comp, m_nf.group(1)):
        return None
    # A NF citada pode estar anexada à despesa de OUTRO código do mesmo arquivo (caso típico: a retenção
    # "INSS - NF. 24282 - FORNECEDOR" paga em guia; a NF 24282 acompanha a despesa do serviço). Nesse caso a
    # NF está na pasta — "Nota Fiscal não anexada" só vale quando nenhum anexo do arquivo traz essa NF.
    if nf_em_outros_anexos is not None and nf_em_outros_anexos(m_nf.group(1), descricao or ""):
        return None
    return Achado(
        id=_proximo_id(contador),
        tipo="nota_fiscal_ausente",
        severidade_sugerida="atencao",
        regra_aplicada="descricao_cita_nf_mas_comprovante_nao_traz_nf",
        registros_relacionados=registros_relacionados,
        linha_demonstrativo=categoria,
        valor_esperado=valor_esperado,
        valor_encontrado=valor_encontrado,
        confianca_deterministica=0.8,
    )


def achados_subconta_atipica(
    despesas: list[RegistroComprovante], pasta_dados: str | None, mes_atual: str | None, contador: list
) -> list[Achado]:
    """
    Sinaliza categorias (`categoria_demonstrativo`) nunca vistas nos últimos
    meses processados desse condomínio (ver
    conciliacao/verificacoes_historico.py) — é uma HEURÍSTICA, não prova de
    erro (pode ser a primeira vez que uma categoria legítima aparece, ex.:
    uma despesa extraordinária nova). Por isso severidade "informativo" de
    propósito: fica registrado em achados_brutos.json/achados_revisados.json
    para quem revisar decidir se sobe a gravidade, mas não polui o PDF final
    por padrão (achados "informativo" não entram no relatório — ver
    scripts/gerar_relatorio_conciliacao.py::etapa_render).

    Sem `pasta_dados`/`mes_atual` (chamada sem contexto de condomínio/mês) ou
    sem histórico ainda (primeiro mês processado) — lista vazia, para não
    gerar falso-positivo em massa.
    """
    if not (pasta_dados and mes_atual):
        return []
    conhecidas = verificacoes_historico.categorias_conhecidas(pasta_dados, mes_atual)
    if not conhecidas:
        return []
    achados: list[Achado] = []
    categorias_ja_reportadas: set[str] = set()
    for d in despesas:
        cat = d.categoria_demonstrativo
        if not cat or cat in conhecidas or cat in categorias_ja_reportadas:
            continue
        categorias_ja_reportadas.add(cat)
        mesma_categoria = [x for x in despesas if x.categoria_demonstrativo == cat]
        achados.append(Achado(
            id=_proximo_id(contador),
            tipo="subconta_atipica",
            severidade_sugerida="informativo",
            regra_aplicada="categoria_nao_vista_no_historico_recente",
            registros_relacionados=[chave_registro(x) for x in mesma_categoria],
            linha_demonstrativo=cat,
            valor_esperado=None,
            valor_encontrado=sum(x.valor for x in mesma_categoria),
            confianca_deterministica=0.5,
        ))
    return achados


_RE_IDENT_EXTRATO = re.compile(r"identifica[çc][ãa]o\s+no\s+extrato\s*:?\s*(?:D[AE]\s+)?([A-Za-zÀ-ÿ]{4,})", re.IGNORECASE)


def _debito_identifica_fornecedor(r: RegistroComprovante, contexto: str = "") -> bool:
    """O comprovante de débito automático do Itaú nunca traz o CNPJ do beneficiário, mas traz
    "Identificação no extrato: DA <FORNECEDOR> <instalação>". Quando esse nome bate com o fornecedor/descrição
    (ou, em `contexto`, a razão social/nome fantasia da tela interna da despesa), o beneficiário está
    identificado e a ausência de CNPJ não é achado."""
    m = _RE_IDENT_EXTRATO.search(r.texto_bruto or "")
    if not m:
        return False
    token = _normalizar_texto(m.group(1))[:4]
    alvo = _normalizar_texto(f"{r.fornecedor or ''} {r.descricao or ''} {contexto}")
    return len(token) >= 4 and token in alvo


_RE_LISTA_CODIGOS_PAGAMENTO = re.compile(
    r"identifica[çc][ãa]o\s+(?:no\s+extrato|do\s+comprovante)\s*:?\s*((?:D\d{3,6}\b[^\S\n]*[^\S\n\dD]{0,30}){1,15})",
    re.IGNORECASE)
_RE_TOTAL_PAGO_TEXTO = [
    re.compile(r"valor\s+total:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
    re.compile(r"valor\s+do\s+pagamento:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
    re.compile(r"\bvalor:?\s*R\$\s*([\d.]+,\d{2})", re.IGNORECASE),
]


def _despesas_por_composicao_fundo_ordinario(despesas: list[RegistroComprovante]) -> list[RegistroComprovante]:
    """Pseudo-registros (mesmo código/página) com valor e categoria vindos da "Composição da Despesa" da
    tela interna, SÓ do Fundo Ordinário — mesma regra do adapter do demonstrativo (adapters/addomus_pdf.py).
    Sem isso, a despesa rateada entre fundos (ex.: Garantidora 2/2 = R$ 1.719,50 no Ordinário + R$ 527,04 no
    Fundo de Obras) entrava inteira na categoria do 1º item e a soma por categoria divergia do demonstrativo
    exatamente pelo valor que está em outro fundo (falso "soma não confere")."""
    import dataclasses

    from adapters.addomus_pdf import _CATEGORIAS_NIVEL2, _RE_COMPOSICAO

    saida: list[RegistroComprovante] = []
    for d in despesas:
        por_categoria: dict[str, float] = {}
        for m in _RE_COMPOSICAO.finditer(d.texto_bruto or ""):
            cod_cat, cod_fundo, nome_fundo, _rat, valor = m.groups()
            if "Fundo Ordin" not in nome_fundo and cod_fundo != "3.1":
                continue
            partes = cod_cat.split(".")
            nome = _CATEGORIAS_NIVEL2.get(f"{partes[0]}.{partes[1]}")
            if nome:
                por_categoria[nome] = por_categoria.get(nome, 0.0) + float(valor.replace(".", "").replace(",", "."))
        if not por_categoria:
            saida.append(d)
            continue
        for nome, soma in por_categoria.items():
            saida.append(dataclasses.replace(d, categoria_demonstrativo=nome, valor=round(soma, 2)))
    return saida


def _imposto_da_descricao(descricao: str | None) -> str | None:
    m = re.match(r"\s*(INSS|PCC|ISS|IRRF|PIS|COFINS|CSLL|CSRF)\b", descricao or "", re.IGNORECASE)
    return m.group(1).upper() if m else None


def _codigos_listados_no_pagamento(texto: str | None) -> list[str]:
    """Códigos de despesa (D1213 D1217 ...) listados na "identificação no extrato/do comprovante" de um
    comprovante de pagamento consolidado."""
    m = _RE_LISTA_CODIGOS_PAGAMENTO.search(texto or "")
    return re.findall(r"D(\d{3,6})\b", m.group(1)) if m else []


def _total_pago_no_texto(texto: str | None) -> float | None:
    for rx in _RE_TOTAL_PAGO_TEXTO:
        m = rx.search(texto or "")
        if m:
            return float(m.group(1).replace(".", "").replace(",", "."))
    return None


def gerar_achados(
    registros: list[RegistroComprovante], dados_financeiros=None,
    pasta_dados: str | None = None, mes_atual: str | None = None,
) -> list[Achado]:
    """
    Executa as regras determinísticas, na ordem:
      1. Pareamento código-a-código (despesa_interna x comprovante de pagamento)
      2. Consolidação many-to-one (N despesas sem par direto somam 1 pagamento órfão)
      3. Duplicidade (mesmo código de despesa_interna repetido com mesmo valor)
      4. CNPJ ausente (débito automático de concessionária sem CNPJ extraído)
      5. Divergência de total por categoria (se dados_financeiros for passado)
      6. Atraso de pagamento (vencimento x pagamento de cada despesa_interna)
      7. Subconta/categoria atípica (heurística de histórico — se pasta_dados/mes_atual forem passados)

    `dados_financeiros` é opcional (DadosFinanceiros do adapter existente,
    ver adapters/base.py) — quando ausente, a regra 5 é pulada.
    """
    contador = [0]
    achados: list[Achado] = []

    despesas_internas = [r for r in registros if r.tipo_documento == "despesa_interna"]
    # "comprovante_imagem" = anexo digitalizado confirmado por OCR (valor + prova de pagamento) — ver
    # conciliacao/addomus_pdf.py::_confirmar_anexos_imagem.
    pagamentos = [r for r in registros if r.tipo_documento in TIPOS_COMPROVANTE_PAGAMENTO | {"comprovante_imagem"}]

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
            # Um código pode ter VÁRIAS páginas de comprovante pareadas (capa
            # + continuação do mesmo boleto/fatura) — concatena o texto de
            # todas antes de checar, senão um marcador de NF numa página
            # posterior nunca seria visto (ver achado_nota_fiscal_ausente).
            texto_pares = "\n\n---\n\n".join(p.texto_bruto or "" for p in pares)
            achado_nf = achado_nota_fiscal_ausente(
                despesa.descricao, texto_pares, despesa.valor, valor_pagamento,
                despesa.categoria_demonstrativo,
                [chave_registro(despesa)] + chaves_pagamento, contador,
            )
            if achado_nf:
                achados.append(achado_nf)
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

    # ── 1b. Pagamento CONSOLIDADO que lista os códigos das despesas ──────────
    # Um DARF/boleto pode quitar várias despesas de uma vez e dizer quais no próprio comprovante
    # ("identificação no extrato: D1213 D1217 D1221 D1225"). Só vale quando a soma dos valores das
    # despesas listadas fecha com o total pago no comprovante (±0,01); despesa sem par própria entre elas
    # deixa de ser "sem comprovante" e fica verificada.
    despesas_ainda_sem_par_apos_lista: list[RegistroComprovante] = []
    cobertas_por_lista: dict[str, tuple] = {}
    for pagamento in pagamentos:
        codigos = _codigos_listados_no_pagamento(pagamento.texto_bruto)
        total = _total_pago_no_texto(pagamento.texto_bruto)
        if not codigos or not total:
            continue
        despesas_listadas = [despesas_por_codigo[c][0] for c in codigos if c in despesas_por_codigo]
        if len(despesas_listadas) != len(codigos):
            continue  # algum código listado não existe como despesa neste arquivo — não arrisca
        # (a) a lista de códigos do comprovante fecha sozinha com o total pago
        if len(codigos) >= 2 and _valores_batem(sum(d.valor for d in despesas_listadas), total):
            for d in despesas_listadas:
                cobertas_por_lista.setdefault(d.codigo, (pagamento, total, despesas_listadas))
            continue
        # (b) o banco TRUNCA a lista de códigos no extrato (ex.: "D892 D1136" num DARF de PCC de R$ 3.646,29
        # que paga 8 retenções): todas as retenções do MESMO imposto, mesmo fornecedor e mesmo vencimento
        # do pagamento somadas fecham com o total pago, ao centavo — então são todas desse pagamento.
        imposto = _imposto_da_descricao(despesas_listadas[0].descricao)
        if not imposto:
            continue
        forn = _normalizar_texto(despesas_listadas[0].fornecedor or "")
        piscina = [d for d in despesas_internas
                   if _imposto_da_descricao(d.descricao) == imposto
                   and _normalizar_texto(d.fornecedor or "") == forn
                   and d.vencimento == despesas_listadas[0].vencimento]
        if len(piscina) > len(despesas_listadas) and _valores_batem(sum(d.valor for d in piscina), total):
            for d in piscina:
                cobertas_por_lista.setdefault(d.codigo, (pagamento, total, piscina))
    for despesa in despesas_sem_par:
        cobertura = cobertas_por_lista.get(despesa.codigo)
        if not cobertura:
            despesas_ainda_sem_par_apos_lista.append(despesa)
            continue
        pagamento, total, listadas = cobertura
        achados.append(Achado(
            id=_proximo_id(contador),
            tipo="ok_verificado",
            severidade_sugerida="informativo",
            regra_aplicada="pagamento_consolidado_lista_codigos_e_soma_confere",
            registros_relacionados=[chave_registro(despesa), chave_registro(pagamento)],
            linha_demonstrativo=despesa.categoria_demonstrativo,
            valor_esperado=despesa.valor,
            valor_encontrado=total,
            confianca_deterministica=1.0,
        ))
        if pagamento.codigo:
            codigos_pagamento_usados.add(pagamento.codigo)
    despesas_sem_par = despesas_ainda_sem_par_apos_lista

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
    # (exceto códigos já marcados como duplicidade — regra 4 cobre esses — e
    # lançamentos isentos de comprovante por natureza, ver
    # _motivo_isencao_comprovante: transferência interna, tarifa bancária)
    codigos_com_anexo = {r.codigo for r in registros if r.tipo_documento == "capa_comprovante" and r.codigo}
    for despesa in despesas_sem_par_restantes:
        if despesa.codigo in codigos_duplicados:
            continue
        motivo_isencao = _motivo_isencao_comprovante(despesa.descricao, despesa.categoria_demonstrativo)
        if motivo_isencao:
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="ok_verificado",
                severidade_sugerida="informativo",
                regra_aplicada=motivo_isencao,
                registros_relacionados=[chave_registro(despesa)],
                linha_demonstrativo=despesa.categoria_demonstrativo,
                valor_esperado=despesa.valor,
                valor_encontrado=despesa.valor,
                confianca_deterministica=1.0,
            ))
            continue
        if despesa.codigo in codigos_com_anexo:
            # Há páginas de anexo (capa "Comprovantes de Despesas" + imagem) desta despesa no PDF, mas o
            # OCR não confirmou valor + prova de pagamento: o comprovante EXISTE e não pôde ser lido —
            # "conteúdo não verificável", não "sem comprovante".
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="conteudo_nao_verificavel",
                severidade_sugerida="atencao",
                regra_aplicada="anexo_em_imagem_presente_valor_nao_confirmado_por_ocr",
                registros_relacionados=[chave_registro(despesa)]
                + [chave_registro(r) for r in registros
                   if r.tipo_documento == "capa_comprovante" and r.codigo == despesa.codigo][:3],
                linha_demonstrativo=despesa.categoria_demonstrativo,
                valor_esperado=despesa.valor,
                valor_encontrado=None,
                confianca_deterministica=0.8,
            ))
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
    # Código já identificado por QUALQUER página (CNPJ ou "Identificação no extrato" do beneficiário) não é achado.
    contexto_por_codigo = {
        d.codigo: (d.texto_bruto or "")[:600] for d in despesas_internas if d.codigo  # razão social / nome fantasia
    }
    codigos_debito_identificados = {
        r.codigo for r in registros
        if r.tipo_documento == "debito_automatico" and r.codigo
        and (r.cnpj_cpf or _debito_identifica_fornecedor(r, contexto_por_codigo.get(r.codigo, "")))
    }
    for r in registros:
        if r.tipo_documento == "debito_automatico" and not r.cnpj_cpf \
                and not _debito_identifica_fornecedor(r, contexto_por_codigo.get(r.codigo or "", "")) \
                and r.codigo not in codigos_debito_identificados:
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
        achados.extend(_achados_divergencia_categoria(
            _despesas_por_composicao_fundo_ordinario(despesas_internas), dados_financeiros, contador))

    # ── 7. Atraso de pagamento (vencimento x pagamento) ─────────────────────
    for despesa in despesas_internas:
        achado_atraso = achado_atraso_pagamento(despesa, contador)
        if achado_atraso and not _pago_ate_proximo_dia_util_bancario(despesa):
            achados.append(achado_atraso)

    # ── 8. Subconta/categoria atípica (heurística de histórico) ─────────────
    achados.extend(achados_subconta_atipica(despesas_internas, pasta_dados, mes_atual, contador))

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


# Palavras da descrição que NÃO identificam o fornecedor (tributos, meses, termos genéricos) — usadas para
# amarrar uma retenção ("INSS - NF. 24282 - FORT SERV") à NF do serviço anexada em outro código.
_PALAVRAS_GENERICAS_FORNECEDOR = {
    "INSS", "CSLL", "COFINS", "PIS", "IRRF", "FGTS", "ISSQN", "NOTA", "FISCAL", "LTDA", "EIRELI", "REF", "PARC",
    "JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO",
    "DEZEMBRO", "SERVICO", "SERVICOS", "COMERCIO", "INDUSTRIA", "CONDOMINIO", "LOCACAO", "MANUTENCAO", "RETENCAO",
}


def _tokens_fornecedor(descricao: str) -> set[str]:
    palavras = re.findall(r"[A-Z]{3,}", _normalizar_texto(descricao))
    return {w for w in palavras if w not in _PALAVRAS_GENERICAS_FORNECEDOR}


def _construir_nf_em_outros_anexos(comprovantes: list[RegistroComprovante]):
    """Devolve f(numero_nf, descricao_listagem) -> bool: existe, no anexo de OUTRO código do mesmo arquivo, uma
    página de Nota Fiscal (marcador de NF, não comprovante bancário) que traz esse nº de NF e algum token do
    fornecedor citado na descrição?"""
    paginas_nf: list[tuple[str, str, str]] = []  # (codigo, texto, texto normalizado)
    for c in comprovantes:
        for _p, t in _lp.paginas_do_texto_bruto(c.texto_bruto):
            if _lp.tem_marcador_nf(t) and not _lp.eh_pagina_pagamento(t):
                paginas_nf.append((c.codigo, t, _normalizar_texto(t)))
    if not paginas_nf:
        return lambda numero, descricao, codigo=None: False

    def _f(numero: str, descricao: str, codigo: str | None = None) -> bool:
        n = numero.lstrip("0") or numero
        corpo = r"[.\s]?".join([n[:-3], n[-3:]]) if len(n) >= 4 else re.escape(n)
        padrao = re.compile(rf"(?<!\d)0*{corpo}(?!\d)")
        tokens = _tokens_fornecedor(descricao)
        for cod, t, tn in paginas_nf:
            if codigo is not None and cod == codigo:
                continue
            if padrao.search(t) and (not tokens or any(tok in tn for tok in tokens)):
                return True
        return False
    return _f


# Descrição de lançamento que é a retenção/recolhimento de um tributo ("INSS S/FOLHA PAGTO MAIO/2026",
# "CSLL/COFINS/PIS 1537579 VILA VELHA", "ISS - 03/2026 - NF. ...", "FGTS ...").
_RE_DESCRICAO_TRIBUTO = re.compile(
    r"(?:^|[\s\-/])(?:INSS|ISS|ISSQN|PIS|COFINS|CSLL|IRRF|IRPJ|FGTS|GPS|DARF)(?:[\s/\-:]|$)", re.IGNORECASE)


def gerar_achados_lirba(
    registros: list[RegistroComprovante], dados_financeiros=None,
    pasta_dados: str | None = None, mes_atual: str | None = None,
) -> list[Achado]:
    """
    Regras para o formato Lirba/ContasData (ver conciliacao/lirba_pdf.py).

    A página de "Comprovante de Despesa" é uma imagem digitalizada — quando
    o OCR (conciliacao/ocr.py, chamado no próprio extrator) consegue
    confirmar um "Valor do pagamento" nela, o comprovante vem com
    `valor > 0` e o conteúdo pode ser cruzado contra o valor da listagem
    (igual a um pareamento por código, ver gerar_achados()); quando não (OCR
    indisponível na máquina, imagem ilegível, ou a página é genuinamente uma
    capa sem anexo — confirmado em dados reais que isso acontece, ex.:
    comprovante 0001 do Baturité), o comprovante fica com `valor == 0.0` e o
    achado é "conteudo_nao_verificavel" em vez de um "ok_verificado" às
    cegas — nunca se finge ter confirmado o que não foi confirmado.
    """
    contador = [0]
    achados: list[Achado] = []

    despesas = [r for r in registros if r.tipo_documento == "despesa_listada"]
    comprovantes = [r for r in registros if r.tipo_documento == "comprovante_anexado"]
    comprovantes_por_codigo = {r.codigo: r for r in comprovantes}

    # ── 0. Consolidação: comprovantes que compartilham o mesmo identificador
    #      "autenticacao" (ex.: N° Recibo Declaração de uma guia consolidada
    #      da Receita Federal, ver conciliacao/lirba_pdf.py junto de
    #      _RE_TOTAL_DO_DOCUMENTO) e o mesmo valor agregado NÃO são N
    #      comprovantes individuais — são o MESMO documento referenciado por
    #      N códigos de despesa diferentes (confirmado em dados reais: Port
    #      Saint Tropez, 11 códigos distintos, mesmo recibo, mesmo total).
    #      Comparar cada um sozinho contra o valor agregado geraria N
    #      "divergência de valor" falsas — em vez disso agrupa e emite UM
    #      achado de consolidação por grupo (mesmo padrão já usado pro
    #      Addomus em gerar_achados(), "soma do grupo bate com o pagamento
    #      consolidado"), comparando a SOMA das despesas do grupo contra o
    #      valor agregado do documento compartilhado.
    grupos_consolidados: dict[tuple[str, float], list[RegistroComprovante]] = {}
    for r in comprovantes:
        if r.autenticacao and r.valor > 0:
            grupos_consolidados.setdefault((r.autenticacao, round(r.valor, 2)), []).append(r)

    codigos_consolidados: set[str] = set()
    for (_autenticacao, valor_total), grupo_comp in grupos_consolidados.items():
        codigos_do_grupo = {c.codigo for c in grupo_comp}
        if len(codigos_do_grupo) < 2:
            continue  # documento referenciado por um único código — segue o fluxo normal abaixo
        despesas_do_grupo = [d for d in despesas if d.codigo in codigos_do_grupo]
        if not despesas_do_grupo:
            continue
        soma = sum(d.valor for d in despesas_do_grupo)
        achados.append(Achado(
            id=_proximo_id(contador),
            tipo="consolidacao_multipla_pendente_julgamento",
            severidade_sugerida="informativo",
            regra_aplicada="comprovantes_compartilham_mesma_guia_consolidada",
            registros_relacionados=(
                [chave_registro(d) for d in despesas_do_grupo]
                + [chave_registro(c) for c in grupo_comp]
            ),
            valor_esperado=soma,
            valor_encontrado=valor_total,
            # Julgamento de negócio ainda necessário (confirma que a guia é
            # legítima e cobre exatamente esses códigos, não uma prova cega) —
            # confiança deliberadamente < 1.0, igual à consolidação do Addomus.
            confianca_deterministica=0.6 if _valores_batem(soma, valor_total) else 0.4,
        ))
        codigos_consolidados.update(codigos_do_grupo)

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
    nf_fora = _construir_nf_em_outros_anexos(comprovantes)

    if avaliar_comprovante:
        # ── 1. Cada despesa listada tem (ou não) uma página "Comprovante de Despesa",
        #        e — quando o OCR confirmou conteúdo — o valor bate com a listagem ──
        for d in despesas:
            if d.codigo in codigos_consolidados:
                continue  # já virou achado de consolidação no bloco 0 acima
            comp = comprovantes_por_codigo.get(d.codigo)
            # Conciliadores de comprovante-documento único (Central das Artes, Ciudad Real, Upper Itaim: o anexo é um PDF
            # baixado/lido inteiro) às vezes têm o texto completo mas nenhuma regra da cadeia reconhece o formato do
            # valor (conta de gás, taxa de elevadores, extrato bancário...). Se o valor da listagem aparece, formatado
            # como moeda, no texto de um anexo LIDO DE VERDADE (>= 300 caracteres; a capa-resumo de ~250 caracteres repete
            # o valor da própria listagem e nunca conta), ele está confirmado. (Anexos de várias páginas do ContasData
            # genérico já passaram por essa busca em lirba_pdf.resolver_comprovante.)
            if (comp is not None and comp.valor <= 0 and "[Página " not in (comp.texto_bruto or "")
                    and len(comp.texto_bruto or "") >= _TAMANHO_MINIMO_TEXTO_CONFIAVEL
                    and _lp.valor_aparece_no_texto(comp.texto_bruto, d.valor)):
                comp.valor = d.valor
            motivo_isencao = _motivo_isencao_comprovante(d.descricao, d.categoria_demonstrativo)
            if motivo_isencao:
                achados.append(Achado(
                    id=_proximo_id(contador),
                    tipo="ok_verificado",
                    severidade_sugerida="informativo",
                    regra_aplicada=motivo_isencao,
                    registros_relacionados=[chave_registro(d)] + ([chave_registro(comp)] if comp else []),
                    linha_demonstrativo=d.categoria_demonstrativo,
                    valor_esperado=d.valor,
                    valor_encontrado=d.valor,
                    confianca_deterministica=1.0,
                ))
            elif comp is None:
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
            elif comp.valor > 0:
                # Comprovante primeiro em registros_relacionados (não a despesa) —
                # scripts/gerar_relatorio_conciliacao.py::etapa_render usa sempre
                # o PRIMEIRO registro da lista pra escolher a página de evidência
                # do relatório, e aqui o que interessa mostrar é o comprovante em
                # si (um recibo), não a linha dele na listagem agregada de
                # despesas (uma tabela inteira, evidência bem menos legível).
                if _valores_batem(d.valor, comp.valor):
                    achados.append(Achado(
                        id=_proximo_id(contador),
                        tipo="ok_verificado",
                        severidade_sugerida="informativo",
                        regra_aplicada="codigo_tem_comprovante_com_valor_confirmado_por_ocr",
                        registros_relacionados=[chave_registro(comp), chave_registro(d)],
                        linha_demonstrativo=d.categoria_demonstrativo,
                        valor_esperado=d.valor,
                        valor_encontrado=comp.valor,
                        confianca_deterministica=1.0,
                    ))
                    # Retenção/recolhimento de tributo ("INSS - NF. 24282 - FORNECEDOR", "CSLL/COFINS/PIS - NF 3832"):
                    # o que se paga é o tributo, comprovado pela guia/DARF e pelo comprovante bancário. A Nota Fiscal
                    # é o documento da despesa do SERVIÇO — que, quando está neste mês, tem a própria linha (e é
                    # cobrada ali) ou, na maioria dos casos (a retenção paga no mês seguinte à competência), é de um
                    # mês anterior e já foi conferida lá. Cobrar a NF em cada retenção gerava dezenas de "Nota Fiscal
                    # não anexada" por mês sem nenhum documento realmente faltando.
                    achado_nf = None if _RE_DESCRICAO_TRIBUTO.search(d.descricao or "") else achado_nota_fiscal_ausente(
                        d.descricao, comp.texto_bruto, d.valor, comp.valor, d.categoria_demonstrativo,
                        [chave_registro(comp), chave_registro(d)], contador,
                        nf_em_outros_anexos=lambda n, desc, _c=d.codigo: nf_fora(n, desc, _c),
                    )
                    if achado_nf:
                        achados.append(achado_nf)
                elif comp.autenticacao and comp.valor > d.valor and _RE_DESCRICAO_TRIBUTO.search(d.descricao or ""):
                    # Retenção (INSS, CSLL/COFINS/PIS, ISS...) cujo anexo é a GUIA do tributo (DARF/GPS/DAMSP): a guia é
                    # única e consolidada, o total dela é a soma de várias retenções — comparar a retenção com o total
                    # da guia seria divergência falsa. Fica registrado (informativo) para julgamento, como as demais
                    # consolidações.
                    achados.append(Achado(
                        id=_proximo_id(contador),
                        tipo="consolidacao_multipla_pendente_julgamento",
                        severidade_sugerida="informativo",
                        regra_aplicada="guia_de_tributo_consolidada_com_total_maior_que_a_retencao_listada",
                        registros_relacionados=[chave_registro(comp), chave_registro(d)],
                        linha_demonstrativo=d.categoria_demonstrativo,
                        valor_esperado=d.valor,
                        valor_encontrado=comp.valor,
                        confianca_deterministica=0.5,
                    ))
                else:
                    achados.append(Achado(
                        id=_proximo_id(contador),
                        tipo="divergencia_valor",
                        severidade_sugerida="alto",
                        regra_aplicada="valor_ocr_comprovante_diverge_valor_listagem",
                        registros_relacionados=[chave_registro(comp), chave_registro(d)],
                        linha_demonstrativo=d.categoria_demonstrativo,
                        valor_esperado=d.valor,
                        valor_encontrado=comp.valor,
                        confianca_deterministica=0.9,  # OCR, não texto nativo — leve margem de erro de leitura
                    ))
                achado_atraso = achado_atraso_pagamento(comp, contador)
                if achado_atraso:
                    achado_atraso.linha_demonstrativo = d.categoria_demonstrativo
                    achado_atraso.registros_relacionados.append(chave_registro(d))
                    achados.append(achado_atraso)
            else:
                achados.append(Achado(
                    id=_proximo_id(contador),
                    tipo="conteudo_nao_verificavel",
                    severidade_sugerida="atencao",
                    regra_aplicada="pagina_comprovante_existe_mas_ocr_nao_confirmou_valor",
                    registros_relacionados=[chave_registro(comp), chave_registro(d)],
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

    # ── 4. Subconta/categoria atípica (heurística de histórico) ─────────────
    achados.extend(achados_subconta_atipica(despesas, pasta_dados, mes_atual, contador))

    return achados


def gerar_achados_planilha_com_links(
    registros: list[RegistroComprovante], dados_financeiros=None,
    pasta_dados: str | None = None, mes_atual: str | None = None,
) -> list[Achado]:
    """Planilhas em que o comprovante é um HYPERLINK da coluna "Anexo" para um sistema externo (Habitacional,
    Guaratambé, e Baturité/Port Saint Tropez nos meses em planilha).

    Mesmas regras do gerar_achados_lirba (lançamento sem link = sem comprovante, duplicidade, subconta...), mas
    SEM o achado "conteúdo não verificável" por lançamento: o comprovante está num sistema externo e o conteúdo
    não é legível pela Validação — link presente confirma a existência, e declarar 56 lançamentos "não
    verificáveis" em toda planilha seria ruído idêntico em todo mês. Só se aplica quando TODOS os comprovantes
    anexados são links http; em PDF (comprovante é página) o comportamento é o de sempre."""
    achados = gerar_achados_lirba(registros, dados_financeiros, pasta_dados=pasta_dados, mes_atual=mes_atual)
    anexos = [r for r in registros if r.tipo_documento == "comprovante_anexado"]
    so_links = bool(anexos) and all((r.texto_bruto or "").lower().startswith("http") for r in anexos)
    if not so_links:
        return achados
    return [a for a in achados
            if not (a.tipo == "conteudo_nao_verificavel"
                    and a.regra_aplicada == "pagina_comprovante_existe_mas_ocr_nao_confirmou_valor")]


def gerar_achados_datadigitus(
    registros: list[RegistroComprovante], dados_financeiros=None,
    pasta_dados: str | None = None, mes_atual: str | None = None,
) -> list[Achado]:
    """
    Regras para o formato DataDigitus (ver conciliacao/datadigitus_pdf.py) —
    o "Prestação de Contas" desse software é só a listagem de despesas do
    próprio demonstrativo, sem comprovante escaneado nem link anexado em
    lugar nenhum do arquivo. Não há checagem de "comprovante ausente" aqui
    (não existe evidência externa pra cruzar), nem de atraso de pagamento
    (o formato só registra uma data por lançamento, sem vencimento e
    pagamento separados) — só:
      1. Duplicidade: mesma data + valor + categoria repetidos.
      2. Divergência entre a soma dos lançamentos de uma conta e o total
         "TOTAL DA CONTA X" declarado no mesmo documento.
      3. Subconta/categoria atípica (heurística de histórico, se
         pasta_dados/mes_atual forem passados).
    Esta função também é reaproveitada, sem alteração, por Consvicta, Lello
    XLS, Alliz, Auxiliadora e uCondo — mesma limitação de uma única data em
    todos eles (ver scripts/gerar_relatorio_conciliacao.py::gerar_achados_por_empresa).
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

    # ── 3. Subconta/categoria atípica (heurística de histórico) ─────────────
    achados.extend(achados_subconta_atipica(despesas, pasta_dados, mes_atual, contador))

    return achados


def _pascoa(ano: int):
    """Domingo de Páscoa (algoritmo gregoriano anônimo)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    mes, dia = divmod(h + L - 7 * m + 114, 31)
    return datetime(ano, mes, dia + 1)


def _feriados_bancarios(ano: int) -> set:
    """Dias sem compensação bancária: feriados nacionais fixos + Carnaval (seg/ter), Sexta-feira Santa e Corpus
    Christi — mais 25/01 e 09/07 (São Paulo, onde estão os condomínios). Feriado municipal de outras cidades não entra."""
    pascoa = _pascoa(ano)
    moveis = [pascoa - timedelta(days=48), pascoa - timedelta(days=47), pascoa - timedelta(days=2),
              pascoa + timedelta(days=60)]
    fixos = [(1, 1), (25, 1), (21, 4), (1, 5), (9, 7), (7, 9), (12, 10), (2, 11), (15, 11), (20, 11), (25, 12)]
    return {d.date() for d in moveis} | {datetime(ano, m, d).date() for d, m in fixos}


def _pago_ate_proximo_dia_util_bancario(registro: RegistroComprovante) -> bool:
    """True quando a data de pagamento é no máximo o 1º dia ÚTIL BANCÁRIO (sem fim de semana nem feriado) a partir do
    vencimento — pagar na quarta-feira de cinzas um boleto que venceu no domingo de Carnaval não é atraso. Só é usada
    para DESCARTAR atrasos de formatos com data de liquidação lida do próprio comprovante (GCONT, Addomus)."""
    try:
        venc = datetime.strptime(registro.vencimento or "", "%d/%m/%Y")
        pago = datetime.strptime(registro.pagamento or "", "%d/%m/%Y")
    except ValueError:
        return False
    limite = venc
    feriados = _feriados_bancarios(limite.year) | _feriados_bancarios(limite.year + 1)
    while limite.weekday() >= 5 or limite.date() in feriados:
        limite += timedelta(days=1)
    return pago <= limite


_RE_COMPLEMENTO_CAPA = re.compile(r"Destina-se a:[^\n]*\n(.*?)\n\s*Valor Emitido", re.DOTALL)


def _complemento_capa(texto_bruto: str | None) -> str:
    """Bloco "<cód. categoria> <categoria> <complemento>" da capa GCONT (pode quebrar em 2 linhas, ex.: o nº da chapa
    do elevador na linha de baixo), sem os valores, normalizado; "" se ausente."""
    m = _RE_COMPLEMENTO_CAPA.search(texto_bruto or "")
    if not m:
        return ""
    bloco = re.sub(r"(?<![\d.,])[\d.]+,\d{2}(?!\d)", " ", m.group(1))
    return re.sub(r"\s+", " ", _normalizar_texto(bloco)).strip()


_RE_RECIBO_OCR = re.compile(r"\[RECIBO OCR pag\. \d+\]\n(.*)", re.DOTALL)
_RE_RECIBO_IDENT = re.compile(r"Identifica\S*\s+no\s+extrato\s+(.+)", re.IGNORECASE)
_RE_RECIBO_AUTENT = re.compile(r"autentica\S*\s*:?\s*([A-Za-z0-9]{12,})", re.IGNORECASE)


def _assinatura_recibo(texto_bruto: str | None):
    """Identificador do recibo anexado (instalação do débito automático + autenticação), ou None
    quando o texto não traz o recibo OCR / nada identificável."""
    m = _RE_RECIBO_OCR.search(texto_bruto or "")
    if not m:
        return None
    corpo = m.group(1)
    ident = _RE_RECIBO_IDENT.search(corpo)
    aut = _RE_RECIBO_AUTENT.search(corpo)
    partes = (re.sub(r"\s+", " ", ident.group(1)).strip().upper() if ident else None,
              aut.group(1).upper() if aut else None)
    return partes if any(partes) else None


def gerar_achados_gcont(
    registros: list[RegistroComprovante], dados_financeiros=None,
    pasta_dados: str | None = None, mes_atual: str | None = None,
) -> list[Achado]:
    """
    Regras para o formato GCONT (ver conciliacao/condominios/club_park_butanta.py)
    — cada pagamento já vem com sua própria página de "Comprovantes de
    despesas" auto-suficiente (o sistema só gera a página quando o pagamento
    é efetivado), então não existe "sem comprovante" nesse formato. Checagens:
      1. Duplicidade: mesmo fornecedor + documento + valor repetidos (ou
         fornecedor + vencimento + valor, quando não há nº de documento).
      2. Soma dos comprovantes extraídos x total declarado no Livro Caixa
         ("N itens VALOR_TOTAL").
      3. Atraso de pagamento (vencimento x liquidação, ambos extraídos da
         própria página do comprovante).
      4. Subconta/categoria atípica (heurística de histórico).
    """
    contador = [0]
    achados: list[Achado] = []

    despesas = [r for r in registros if r.tipo_documento == "despesa_com_comprovante"]
    # "total_declarado" = Livro Caixa (Club Park, Saint Afonso); "total_demonstrativos_declarado" =
    # soma dos "Total de DESPESAS" dos Demonstrativos Analíticos (HSA, ex.: I-Gloo Alphaville).
    totais_declarados = [r for r in registros
                         if r.tipo_documento in ("total_declarado", "total_demonstrativos_declarado")]

    # ── 1. Duplicidade ────────────────────────────────────────────────────
    grupos: dict[tuple, list[RegistroComprovante]] = {}
    for d in despesas:
        fornecedor_norm = (d.fornecedor or "").strip().upper()
        # autenticacao aqui guarda o nº de Documento/NF (ver extrator) — quando
        # ausente (ex.: contas de concessionária sem NF), cai no fallback por
        # vencimento pra ainda ter uma chave razoável de deduplicação.
        # O "Complemento" da capa ("2.6.8 Taxa de Elevadores Nº CHAPA 137900") entra na chave: a taxa municipal de
        # elevadores tem o MESMO valor (R$ 236,35) para cada elevador, paga no mesmo dia — só a chapa diferencia,
        # e dois pagamentos com chapas diferentes não são duplicidade (Plano & Estação, Top Nine, 06/2026).
        chave = (fornecedor_norm, d.autenticacao or d.vencimento, round(d.valor, 2), _complemento_capa(d.texto_bruto))
        grupos.setdefault(chave, []).append(d)
    # Conciliadores que anexam o recibo em imagem (OCR) ao texto_bruto sob "[RECIBO OCR pag. N]"
    # (ver conciliacao/condominios/_gcont_comum.py) permitem separar pagamentos DISTINTOS de mesmo
    # fornecedor/valor/dia (ex.: débito automático Comgás de instalações diferentes) das repetições
    # reais (recibo idêntico). Sem assinatura legível o registro fica no mesmo balde (conservador).
    subgrupos: list[list[RegistroComprovante]] = []
    for grupo in grupos.values():
        if len(grupo) < 2:
            continue
        por_assinatura: dict = {}
        for d in grupo:
            por_assinatura.setdefault(_assinatura_recibo(d.texto_bruto), []).append(d)
        subgrupos.extend(por_assinatura.values())
    for grupo in subgrupos:
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

    # ── 3. Atraso de pagamento (vencimento x liquidação) ─────────────────────
    for despesa in despesas:
        achado_atraso = achado_atraso_pagamento(despesa, contador)
        if achado_atraso and not _pago_ate_proximo_dia_util_bancario(despesa):
            achados.append(achado_atraso)

    # ── 3b. Nota Fiscal ausente — GCONT tem despesa e comprovante no MESMO
    # registro ("despesa_com_comprovante", auto-suficiente por natureza, ver
    # docstring acima), então descrição e texto do comprovante vêm do mesmo
    # objeto (ver achado_nota_fiscal_ausente).
    for despesa in despesas:
        achado_nf = achado_nota_fiscal_ausente(
            despesa.descricao, despesa.texto_bruto, despesa.valor, despesa.valor,
            despesa.categoria_demonstrativo, [chave_registro(despesa)], contador,
        )
        if achado_nf:
            achados.append(achado_nf)

    # ── 4. Subconta/categoria atípica (heurística de histórico) ─────────────
    achados.extend(achados_subconta_atipica(despesas, pasta_dados, mes_atual, contador))

    return achados


def gerar_achados_balancete_mensal(
    registros: list[RegistroComprovante], dados_financeiros=None,
    pasta_dados: str | None = None, mes_atual: str | None = None,
) -> list[Achado]:
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
    `pasta_dados`/`mes_atual` são aceitos só para manter a mesma assinatura
    das demais funções de matching — subconta/categoria atípica não se
    aplica aqui (não há `categoria_demonstrativo` por lançamento, só totais
    agregados).
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


def gerar_achados_palm_beach(
    registros: list[RegistroComprovante], dados_financeiros=None,
    pasta_dados: str | None = None, mes_atual: str | None = None,
) -> list[Achado]:
    """
    Regras para Palm Beach (ver conciliacao/condominios/palm_beach.py) —
    duas seções tratadas de formas diferentes, nenhuma com pareamento
    despesa-a-despesa no sentido usual (não existe "sem_comprovante" nem
    "divergencia_valor" aqui — ver docstring do módulo pra por quê):
      - "anexo_despesa_com_valor"/"anexo_despesa_sem_valor_identificado":
        página-capa de "Despesas > Anexos", já vem com fornecedor/nº doc/
        categoria de texto real — confirma o valor quando o OCR conseguiu
        ler (ok_verificado), ou sinaliza quando não (conteudo_nao_verificavel,
        mais acionável que os de "Outros documentos" porque já se sabe a
        qual despesa esse anexo pertence).
      - "comprovante_com_valor"/"comprovante_valor_suspeito"/
        "comprovante_sem_valor_identificado"/"documento_apoio_sem_valor":
        documentos da seção "Outros documentos" (sem vínculo com uma
        despesa específica) — ver docstring do módulo.
    """
    contador = [0]
    achados: list[Achado] = []

    for r in registros:
        if r.tipo_documento == "anexo_despesa_com_valor":
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="ok_verificado",
                severidade_sugerida="informativo",
                regra_aplicada="anexo_despesa_com_valor_confirmado_por_ocr",
                registros_relacionados=[chave_registro(r)],
                linha_demonstrativo=r.categoria_demonstrativo,
                valor_esperado=None,
                valor_encontrado=r.valor,
                confianca_deterministica=0.85,
            ))
        elif r.tipo_documento == "anexo_despesa_sem_valor_identificado":
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="conteudo_nao_verificavel",
                severidade_sugerida="atencao",
                regra_aplicada="anexo_despesa_com_valor_nao_confirmado_por_ocr",
                registros_relacionados=[chave_registro(r)],
                linha_demonstrativo=r.categoria_demonstrativo,
                valor_esperado=None,
                valor_encontrado=None,
                confianca_deterministica=1.0,
            ))
        elif r.tipo_documento == "comprovante_com_valor":
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="ok_verificado",
                severidade_sugerida="informativo",
                regra_aplicada="documento_outros_documentos_com_valor_confirmado_por_ocr",
                registros_relacionados=[chave_registro(r)],
                valor_esperado=None,
                valor_encontrado=r.valor,
                confianca_deterministica=0.8,
            ))
        elif r.tipo_documento == "comprovante_valor_suspeito":
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="conteudo_nao_verificavel",
                severidade_sugerida="atencao",
                regra_aplicada="valor_lido_implausivel_possivel_erro_ocr",
                registros_relacionados=[chave_registro(r)],
                valor_esperado=None,
                valor_encontrado=r.valor,
                confianca_deterministica=0.4,
            ))
        elif r.tipo_documento == "comprovante_sem_valor_identificado":
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="conteudo_nao_verificavel",
                severidade_sugerida="atencao",
                regra_aplicada="documento_outros_documentos_tipo_nao_reconhecido",
                registros_relacionados=[chave_registro(r)],
                valor_esperado=None,
                valor_encontrado=None,
                confianca_deterministica=1.0,
            ))
        elif r.tipo_documento == "documento_apoio_sem_valor":
            achados.append(Achado(
                id=_proximo_id(contador),
                tipo="ok_verificado",
                severidade_sugerida="informativo",
                regra_aplicada="documento_de_apoio_sem_valor_individual_comparavel",
                registros_relacionados=[chave_registro(r)],
                valor_esperado=None,
                valor_encontrado=None,
                confianca_deterministica=1.0,
            ))

    return achados
