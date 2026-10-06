"""
As REGRAS GERAIS da Validação de Balancetes, sobre o modelo de modelo.py.

Todas devolvem list[Achado] (tipos novos em conciliacao/base.py) e carregam em
`Achado.detalhes` os fatos que o relatório precisa (conta, descrição, página...).
Não há texto narrativo aqui — só fatos e a regra aplicada (como no resto do motor).

Regras:
  receita_negativa            qualquer linha de receita com valor < 0
  rendimento_desproporcional  rendimento de uma conta fora da proporção do saldo
  pagamento_sem_identificacao lançamento sem fornecedor/histórico identificável
  parcelas_mesmo_mes          duas+ parcelas da mesma série pagas no mesmo mês
  lancamento_em_outra_subconta / subconta_atipica
                              subconta diferente da do mês anterior / subconta nova

Parâmetros por condomínio (config/validacao_balancetes.json › "regras"):
  rendimento: {"tolerancia": 0.30, "ignorar_contas": [...], "contas_aplicadas": [...]}
"""
import re
import statistics
import unicodedata
from typing import Optional

from conciliacao.base import Achado
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa

TOLERANCIA_REND_PADRAO = 0.25
_CENTAVO = 0.011


# ── utilidades ───────────────────────────────────────────────────────────────

def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", _sem_acento(s).upper())).strip()


_RE_PARCELA = re.compile(r"\bPARC(?:ELA)?S?\.?\s*(\d{1,2})\s*(?:/|DE|-)\s*(\d{1,2})\b", re.IGNORECASE)
# "PARC 02/06", "PARCELA 2/12", "PARC. 10 DE 12". Só com a palavra PARC: "02/06" solto
# pode ser data ou competência.


_RE_NF = re.compile(r"\bNFS?E?\b\.?\s*(?:N[º°O]\.?)?\s*[:.]?\s*(\d{2,})", re.IGNORECASE)


def nf_da_descricao(descricao: str) -> Optional[str]:
    """Nº da Nota Fiscal citada na descrição ("NF. 4740", "NF: 128117"), se houver."""
    m = _RE_NF.search(descricao or "")
    return m.group(1) if m else None


def parcela_da_descricao(descricao: str) -> Optional[tuple[int, int]]:
    """(n, total) se a descrição traz "PARC n/total"; None caso contrário."""
    m = _RE_PARCELA.search(descricao or "")
    if not m:
        return None
    n, total = int(m.group(1)), int(m.group(2))
    return (n, total) if 1 <= n <= total <= 99 else None


_RE_LIXO_BASE = re.compile(
    r"\b(PARC(?:ELA)?S?\.?\s*\d+\s*(?:/|DE|-)\s*\d+|NFS?E?\.?\s*:?\s*\d+|NF\s*N?[ºO°]?\s*\d+|"
    r"NOTA FISCAL\s*\d*|\d{1,2}/\d{2,4}|\d{2}\.\d{4}|\d+|"
    r"JAN(?:EIRO)?|FEV(?:EREIRO)?|MAR(?:CO)?|ABR(?:IL)?|MAI(?:O)?|JUN(?:HO)?|JUL(?:HO)?|AGO(?:STO)?|SET(?:EMBRO)?|OUT(?:UBRO)?|NOV(?:EMBRO)?|DEZ(?:EMBRO)?)\b",
    re.IGNORECASE,
)


def base_da_descricao(descricao: str) -> str:
    """Descrição sem parcela, nº de NF, datas, números e nomes de mês — identifica
    'a mesma despesa recorrente' entre meses e entre parcelas."""
    return _norm(_RE_LIXO_BASE.sub(" ", _sem_acento(descricao or "")))


def chave_despesa(l: LancamentoDespesa) -> str:
    """Identidade 'fornecedor/despesa' de um lançamento: o fornecedor, se o arquivo
    traz o campo; senão a descrição sem parcela/NF/mês."""
    if l.fornecedor and _norm(l.fornecedor):
        return _norm(l.fornecedor)
    return base_da_descricao(l.descricao)


def _fmt(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class _Contador:
    def __init__(self):
        self.n = 0

    def proximo(self) -> str:
        self.n += 1
        return f"RG-{self.n:04d}"


# ── Regra 4: receita negativa ────────────────────────────────────────────────

# Linhas negativas que são MOVIMENTO da aplicação financeira (não receita de verdade): não são divergência.
_RE_RECEITA_NEG_ESTRUTURAL = re.compile(
    r"APLICA[CÇ][AÃ]O|RESGATE|\bIR\b.*\bRESGATE|\bIOF\b|IR\s*/\s*IOF|\bIR\s+INVESTIMENTO", re.IGNORECASE)


# "Correção/ajuste/estorno de rendimento da aplicação" NÃO é movimento estrutural: é receita negativa de verdade.
_RE_AJUSTE_RENDIMENTO = re.compile(r"CORRE[CÇ][AÃ]O|AJUSTE|ESTORNO|DEVOLU[CÇ][AÃ]O", re.IGNORECASE)


def regra_receita_negativa(dados: DadosRegras, cont: _Contador, cfg: Optional[dict] = None) -> list[Achado]:
    """Qualquer linha de receita com valor < 0 é divergência (decisão do dono do produto).

    Exceções, só por configuração do condomínio (`regras.receita_negativa`):
      ignorar_tipos      lista de `tipo` de linha (ex.: ["baixa_inadimplencia"]) — linhas que o
                         formato lança negativas por construção;
      ignorar_descricao  lista de regex sobre a descrição (ex.: ["TARIFA BANC"]).
    Por padrão não entram só os movimentos de aplicação/resgate/IOF (não são receita).
    Linhas repetidas (mesma conta e mesma descrição) viram UM achado com a lista e a soma.
    """
    cfg = cfg or {}
    tipos_ign = set(cfg.get("ignorar_tipos", []))
    # `estruturais`: negativos que fazem parte de um par entrada/saída conferido por `compensacoes` — só esta
    # regra os ignora (os leitores NÃO os descartam, senão a compensação não os enxerga).
    regex_ign = [re.compile(r, re.IGNORECASE) for r in list(cfg.get("ignorar_descricao", [])) + list(cfg.get("estruturais", []))]
    grupos: dict[tuple, list] = {}
    for r in dados.receitas:
        if r.valor >= -_CENTAVO or r.tipo in tipos_ign:
            continue
        desc = r.descricao or ""
        movimento = _RE_RECEITA_NEG_ESTRUTURAL.search(_sem_acento(desc)) and not _RE_AJUSTE_RENDIMENTO.search(_sem_acento(desc))
        if movimento or any(x.search(desc) for x in regex_ign):
            continue
        grupos.setdefault(re.sub(r"\d+", "", _norm(desc)), []).append(r)
    achados = []
    for linhas in grupos.values():
        r = linhas[0]
        total = round(sum(x.valor for x in linhas), 2)
        contas_do_grupo = sorted({x.conta for x in linhas if x.conta})
        conta_txt = r.conta if len(contas_do_grupo) <= 1 else "contas " + ", ".join(contas_do_grupo)
        achados.append(Achado(
            id=cont.proximo(), tipo="receita_negativa", severidade_sugerida="alto",
            regra_aplicada="receita_com_valor_negativo", linha_demonstrativo=conta_txt,
            valor_encontrado=total,
            detalhes={"conta": conta_txt, "descricao": r.descricao, "data": r.data, "pagina": r.pagina,
                      "local": r.local, "bbox": r.bbox, "tipo_receita": r.tipo, "quantidade": len(linhas),
                      "itens": [{"valor": x.valor, "data": x.data, "descricao": x.descricao, "pagina": x.pagina,
                                 "local": x.local} for x in linhas[:20]]},
        ))
    return achados


# ── Compensação: o dinheiro que entra e o que sai de um mesmo grupo devem fechar ────────────

def regra_compensacao(dados: DadosRegras, cont: _Contador, compensacoes: Optional[list]) -> list[Achado]:
    """Para grupos que a administradora lança como ENTRADA e SAÍDA que se anulam (ex.: NYC — a locação do
    estacionamento entra como receita e o desconto do mesmo valor sai como receita negativa), confere se
    o líquido do mês fecha. Configuração por condomínio (`regras.compensacoes`):
        [{"nome": "Estacionamento", "regex": "ESTAC", "tolerancia": 1.00}]
    Considera todas as linhas de receita cuja descrição casa o regex (positivas = entrada, negativas = saída).
    A verificação é OBRIGATÓRIA todo mês para o condomínio configurado: gera achado quando o líquido
    passa da tolerância E também quando falta a entrada, a saída ou o grupo inteiro no mês."""
    achados = []
    for cfg in compensacoes or []:
        rx = re.compile(cfg["regex"], re.IGNORECASE)
        tol = float(cfg.get("tolerancia", 1.0))
        linhas = [r for r in dados.receitas if rx.search(r.descricao or "")]
        entrada = round(sum(r.valor for r in linhas if r.valor > 0), 2)
        saida = round(sum(r.valor for r in linhas if r.valor < 0), 2)
        liquido = round(entrada + saida, 2)
        if entrada > 0 and saida < 0:
            situacao = "liquido"
            if abs(liquido) <= tol:
                continue
        elif entrada > 0:
            situacao = "sem_saida"
        elif saida < 0:
            situacao = "sem_entrada"
        else:
            situacao = "sem_lancamentos"
        principais = sorted(linhas, key=lambda r: -abs(r.valor))[:6]
        achados.append(Achado(
            id=cont.proximo(), tipo="compensacao_nao_fecha", severidade_sugerida="atencao",
            regra_aplicada="entrada_e_saida_do_grupo_nao_se_anulam_no_mes", linha_demonstrativo=cfg.get("nome", "grupo"),
            valor_esperado=0.0, valor_encontrado=liquido,
            detalhes={"grupo": cfg.get("nome", "grupo"), "situacao": situacao, "entrada": entrada, "saida": saida,
                      "liquido": liquido, "quantidade": len(linhas),
                      "pagina": principais[0].pagina if principais else None,
                      "local": principais[0].local if principais else None,
                      "principais": [{"descricao": r.descricao, "valor": r.valor, "pagina": r.pagina} for r in principais]},
        ))
    return achados


# ── Regra 3: rendimento proporcional ao saldo ────────────────────────────────

def _base(c: ContaMes, modo: str = "media") -> float:
    """Saldo de referência do rendimento (positivo): "media" = média do anterior e do atual
    (padrão), "anterior" ou "atual". Conta devedora/zerada não rende: base 0. O modo certo varia
    por condomínio (config `regras.rendimento.base`): onde o rendimento é creditado sobre o saldo
    do fim do mês (ex.: Alvorada), "atual" alinha as contas melhor que a média."""
    if modo == "anterior":
        v = c.saldo_anterior
    elif modo == "atual":
        v = c.saldo_atual
    else:
        v = (c.saldo_anterior + c.saldo_atual) / 2
    return max(0.0, v)


def _chave_conta(nome: str) -> str:
    """Nome de conta comparável entre meses/blocos: sem acento, só letras e dígitos."""
    return re.sub(r"[^A-Z0-9]", "", _sem_acento(nome or "").upper())


def _mesma_conta(a: str, b: str) -> bool:
    ka, kb = _chave_conta(a), _chave_conta(b)
    return bool(ka) and bool(kb) and (ka == kb or (min(len(ka), len(kb)) >= 8 and (ka.startswith(kb) or kb.startswith(ka))))


def regra_rendimento(dados: DadosRegras, anterior: Optional[DadosRegras], cont: _Contador,
                     cfg: Optional[dict] = None) -> list[Achado]:
    """Rendimento creditado em cada conta deve ser proporcional ao saldo dela.

    Taxa de cada conta = rendimento / saldo médio (média do saldo anterior e do atual: o
    saldo muda ao longo do mês com pagamentos e depósitos). Compara cada conta com a taxa
    mediana do grupo (contas com rendimento no mês). Divergem: conta com taxa fora da
    tolerância e conta que tinha rendimento no mês anterior (ou está em
    `contas_aplicadas`) e ficou sem nenhum agora.
    """
    cfg = cfg or {}
    tol = float(cfg.get("tolerancia", TOLERANCIA_REND_PADRAO))
    modo = cfg.get("base", "media")
    ignorar = [n for n in cfg.get("ignorar_contas", [])]
    obrigatorias = [n for n in cfg.get("contas_aplicadas", [])]

    def _ignorada(nome):
        return any(_mesma_conta(nome, n) for n in ignorar)

    contas = [c for c in dados.contas if not _ignorada(c.nome)]
    if anterior:
        obrigatorias += [c.nome for c in anterior.contas if c.rendimento > _CENTAVO and not _ignorada(c.nome)]

    def base(c):
        return _base(c, modo)

    com_rend = [c for c in contas if c.rendimento > _CENTAVO and base(c) > _CENTAVO]
    achados = []
    taxas = {_chave_conta(c.nome): c.rendimento / base(c) for c in com_rend}
    mediana = statistics.median(taxas.values()) if taxas else None

    resumo = {"tolerancia": tol, "base": modo, "taxa_mediana": mediana,
              "contas": [{"nome": c.nome, "saldo_anterior": c.saldo_anterior, "saldo_atual": c.saldo_atual,
                          "base": base(c), "rendimento": c.rendimento, "taxa": taxas.get(_chave_conta(c.nome))}
                         for c in contas if base(c) > _CENTAVO or c.rendimento > _CENTAVO]}

    for c in com_rend:
        if mediana and len(com_rend) >= 2:
            desvio = taxas[_chave_conta(c.nome)] / mediana - 1
            if abs(desvio) > tol:
                esperado = round(base(c) * mediana, 2)
                achados.append(Achado(
                    id=cont.proximo(), tipo="rendimento_desproporcional", severidade_sugerida="atencao",
                    regra_aplicada="rendimento_conta_fora_da_proporcao_do_saldo", linha_demonstrativo=c.nome,
                    valor_esperado=esperado, valor_encontrado=round(c.rendimento, 2),
                    detalhes={**resumo, "conta": c.nome, "motivo": "taxa_fora_da_mediana",
                              "taxa_conta": taxas[_chave_conta(c.nome)], "desvio": desvio, "pagina": c.pagina},
                ))
    for c in contas:
        if any(_mesma_conta(c.nome, n) for n in obrigatorias) and c.rendimento <= _CENTAVO and base(c) > _CENTAVO:
            esperado = round(base(c) * mediana, 2) if mediana else None
            achados.append(Achado(
                id=cont.proximo(), tipo="rendimento_desproporcional", severidade_sugerida="atencao",
                regra_aplicada="conta_com_saldo_sem_rendimento_no_mes", linha_demonstrativo=c.nome,
                valor_esperado=esperado, valor_encontrado=0.0,
                detalhes={**resumo, "conta": c.nome, "motivo": "sem_rendimento", "pagina": c.pagina,
                          "exigida_por": "configuracao" if any(_mesma_conta(c.nome, n) for n in cfg.get("contas_aplicadas", [])) else "mes_anterior",
                          "contas_com_rendimento": [x.nome for x in contas if x.rendimento > _CENTAVO],
                          "rendimento_total_mes": round(sum(x.rendimento for x in contas), 2)},
            ))
    return achados


# ── Regra 5: pagamento sem identificação ─────────────────────────────────────

# Marcadores de texto: com \b no começo para não casar no meio de outra palavra (ex.: "para
# Identificar Problema" casava "A IDENTIFICAR" dentro de "para").
_RE_NAO_IDENT = re.compile(
    r"\bN[AÃ]O\s+IDENTIFICAD|\bSEM\s+IDENTIFICA|\bA\s+IDENTIFICAR\b|\bN[AÃ]O\s+IDENTIF|\bDESCONHECID|"
    r"\bD[ÉE]BITO\s+(?:/\s*)?CR[ÉE]DITO\s+N[ÃA]O|\bPAGAMENTO\s+DIVERSO|\bSEM\s+HIST[ÓO]RICO",
    re.IGNORECASE,
)


def regra_sem_identificacao(dados: DadosRegras, cont: _Contador) -> list[Achado]:
    achados = []
    for l in dados.lancamentos:
        texto = f"{l.descricao or ''} {l.fornecedor or ''} {l.categoria or ''}"
        vazio = not (l.descricao or "").strip() and not (l.fornecedor or "").strip()
        marcado = bool(_RE_NAO_IDENT.search(_sem_acento(texto)) or _RE_NAO_IDENT.search(texto))
        if not (vazio or marcado):
            continue
        achados.append(Achado(
            id=cont.proximo(), tipo="pagamento_sem_identificacao", severidade_sugerida="alto",
            regra_aplicada="lancamento_sem_fornecedor_ou_historico_identificavel" if vazio else "historico_marcado_como_nao_identificado",
            linha_demonstrativo=l.categoria, valor_encontrado=l.valor,
            detalhes={"codigo": l.codigo, "data": l.data, "descricao": l.descricao, "categoria": l.categoria,
                      "conta": l.conta, "pagina": l.pagina, "local": l.local, "bbox": l.bbox},
        ))
    return achados


# ── Regra 7: duas parcelas no mesmo mês ──────────────────────────────────────

def regra_parcelas_mesmo_mes(dados: DadosRegras, cont: _Contador, anterior: Optional[DadosRegras] = None) -> list[Achado]:
    """Duas ou mais parcelas DIFERENTES da mesma série (fornecedor/despesa + total) no mesmo mês.
    Pagamento fracionado que se repete todo mês (a mesma parcela n do mesmo fornecedor já constava
    no mês anterior) não é divergência."""
    ja_vistas: set = set()
    if anterior is not None:
        for l in anterior.lancamentos:
            pp = parcela_da_descricao(l.descricao)
            if pp:
                ja_vistas.add((chave_despesa(l), pp[1], pp[0]))
    series: dict[tuple, list[tuple[int, LancamentoDespesa]]] = {}
    for l in dados.lancamentos:
        p = parcela_da_descricao(l.descricao)
        if not p:
            continue
        n, total = p
        series.setdefault((chave_despesa(l), total), []).append((n, l))
    achados = []
    for (chave, total), itens in series.items():
        numeros = {n for n, _ in itens}
        if len(numeros) < 2:       # mesma parcela repetida é duplicidade (outra regra)
            continue
        if any((chave, total, n) in ja_vistas for n in numeros):
            continue               # pagamento fracionado recorrente: a parcela já constava no mês anterior
        itens = sorted(itens, key=lambda x: x[0])
        achados.append(Achado(
            id=cont.proximo(), tipo="parcelas_mesmo_mes", severidade_sugerida="atencao",
            regra_aplicada="duas_parcelas_da_mesma_serie_pagas_no_mesmo_mes",
            linha_demonstrativo=itens[0][1].categoria,
            valor_encontrado=round(sum(l.valor for _, l in itens), 2),
            detalhes={"fornecedor_ou_despesa": itens[0][1].fornecedor or chave, "total_parcelas": total,
                      "parcelas": [{"n": n, "valor": l.valor, "data": l.data, "codigo": l.codigo,
                                    "descricao": l.descricao, "pagina": l.pagina, "local": l.local,
                                    "bbox": l.bbox, "nf": nf_da_descricao(l.descricao)} for n, l in itens]},
        ))
    return achados


# ── Regra 8: subcontas ───────────────────────────────────────────────────────

_RE_RETENCAO = re.compile(
    r"^\s*(?:INSS|ISS|IRRF?|PIS|COFINS|CSLL|IR\b)|RETEN[CÇ][AÃ]O|CSLL\s*/\s*COFINS\s*/\s*PIS",
    re.IGNORECASE,
)
_PREFIXO_MINIMO_CATEGORIA = 8
LIMITE_TROCAS_SUBCONTA = 8      # acima disso no mesmo mês: reclassificação em massa (um achado só)
LIMITE_SUBCONTAS_NOVAS = 8   # acima disso no mesmo mês: plano de contas reorganizado (um achado só)


def _mesma_categoria(a: str, b: str) -> bool:
    """Igual, ou renome simples do grupo (um nome é prefixo do outro: "MANUTENÇÕES EVENTUAIS" x
    "MANUTENÇÕES EVENTUAIS E AQUISIÇÕES")."""
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    curto, longo = sorted((na, nb), key=len)
    return len(curto) >= _PREFIXO_MINIMO_CATEGORIA and longo.startswith(curto)


def regra_subcontas(dados: DadosRegras, historico: list, cont: _Contador, cfg: Optional[dict] = None) -> list[Achado]:
    """Regra 8 — lançamento em subconta diferente da que a mesma despesa/fornecedor usou nos meses
    anteriores, e subconta que não existia antes.

    `historico` = DadosRegras dos meses anteriores (os mais recentes primeiro, até ~6): a comparação é
    com a UNIÃO deles, não só com o mês imediatamente anterior — assim uma despesa eventual que some
    e volta, ou uma subconta usada em outros meses, não vira alarme. Linhas de retenção de imposto
    (INSS/ISS/PIS-COFINS-CSLL...) seguem a subconta da nota que as originou e não entram na regra de
    troca. Sem nenhum mês anterior legível, a regra não roda."""
    historico = [h for h in (historico or []) if h is not None and h.lancamentos]
    if not historico:
        return []
    cfg = cfg or {}
    # Renomeação do plano de contas pela administradora (config `regras.subcontas.equivalentes`:
    # {"nome antigo": "nome novo"}) — os dois nomes valem como a MESMA subconta.
    equivalentes = {_norm(k): v for k, v in cfg.get("equivalentes", {}).items()}

    def _canon(nome: str) -> str:
        return equivalentes.get(_norm(nome), nome)

    def _transferencia(nome: str) -> bool:
        return _norm(nome).startswith("TRANSFERENCIA")

    cat_anterior: dict[str, dict] = {}     # chave da despesa -> {categoria normalizada: nome}
    categorias_anteriores: dict[str, str] = {}
    for h in historico:
        for l in h.lancamentos:
            cat = _canon(l.categoria)
            cat_anterior.setdefault(chave_despesa(l), {})[_norm(cat)] = cat
            categorias_anteriores[_norm(cat)] = cat

    def _existia(cat_nome: str, conjunto: dict) -> bool:
        return any(_mesma_categoria(cat_nome, n) for n in conjunto.values())

    achados = []
    por_nova: dict[str, list[LancamentoDespesa]] = {}
    por_troca: dict[tuple, list[LancamentoDespesa]] = {}
    for l in dados.lancamentos:
        cat_l = _canon(l.categoria)
        if _transferencia(cat_l):
            continue               # transferência entre contas não é subconta de despesa
        antes = cat_anterior.get(chave_despesa(l))
        if antes and not _existia(cat_l, antes):
            if _RE_RETENCAO.search(_sem_acento(l.descricao or "")):
                continue
            # a mesma despesa/fornecedor estava em OUTRA subconta (vale mesmo se a atual também for nova)
            por_troca.setdefault((chave_despesa(l), cat_l), []).append(l)
        elif not _existia(cat_l, categorias_anteriores):
            por_nova.setdefault(cat_l, []).append(l)

    def _itens(ls):
        return [{"descricao": x.descricao, "valor": x.valor, "data": x.data, "codigo": x.codigo,
                 "pagina": x.pagina, "local": x.local, "bbox": x.bbox} for x in ls]

    if len(por_nova) > LIMITE_SUBCONTAS_NOVAS:
        # Muitas subcontas novas de uma vez = a administradora reorganizou o plano de contas: um
        # achado só, listando-as, em vez de dezenas de alertas iguais.
        todas = [x for ls in por_nova.values() for x in ls]
        achados.append(Achado(
            id=cont.proximo(), tipo="subconta_atipica", severidade_sugerida="atencao",
            regra_aplicada="varias_subcontas_novas_plano_de_contas_reorganizado",
            linha_demonstrativo=f"{len(por_nova)} subcontas novas",
            valor_encontrado=round(sum(x.valor for x in todas), 2),
            detalhes={"categoria": f"{len(por_nova)} subcontas novas", "reorganizacao": True,
                      "categorias": sorted(por_nova), "lancamentos": _itens(todas[:30]),
                      "meses_comparados": len(historico)}))
        por_nova = {}
    for categoria, ls in por_nova.items():
        achados.append(Achado(
            id=cont.proximo(), tipo="subconta_atipica", severidade_sugerida="atencao",
            regra_aplicada="subconta_nao_existia_nos_meses_anteriores", linha_demonstrativo=categoria,
            valor_encontrado=round(sum(x.valor for x in ls), 2),
            detalhes={"categoria": categoria, "lancamentos": _itens(ls), "meses_comparados": len(historico)},
        ))
    if len(por_troca) > LIMITE_TROCAS_SUBCONTA:
        # Muitas despesas trocando de subconta de uma vez = reclassificação em massa (a administradora
        # mexeu no plano de contas): um achado só, com a lista de quem foi para onde.
        trocas = []
        for (chave, categoria), ls in por_troca.items():
            trocas.append({"despesa": ls[0].fornecedor or chave, "de": sorted(cat_anterior.get(chave, {}).values()),
                           "para": categoria, "valor": round(sum(x.valor for x in ls), 2), "lancamentos": len(ls)})
        trocas.sort(key=lambda t: -abs(t["valor"]))
        todos = [x for ls in por_troca.values() for x in ls]
        achados.append(Achado(
            id=cont.proximo(), tipo="lancamento_em_outra_subconta", severidade_sugerida="atencao",
            regra_aplicada="varias_despesas_mudaram_de_subconta_reclassificacao", linha_demonstrativo=f"{len(por_troca)} despesas",
            valor_encontrado=round(sum(x.valor for x in todos), 2),
            detalhes={"reclassificacao_em_massa": True, "quantidade": len(por_troca), "trocas": trocas[:40],
                      "lancamentos": _itens(todos[:20]), "meses_comparados": len(historico)}))
        por_troca = {}
    for (chave, categoria), ls in por_troca.items():
        antes = sorted(cat_anterior.get(chave, {}).values())
        achados.append(Achado(
            id=cont.proximo(), tipo="lancamento_em_outra_subconta", severidade_sugerida="atencao",
            regra_aplicada="mesma_despesa_em_subconta_diferente_dos_meses_anteriores", linha_demonstrativo=categoria,
            valor_encontrado=round(sum(x.valor for x in ls), 2),
            detalhes={"despesa": ls[0].fornecedor or chave, "categoria_atual": categoria,
                      "categoria_nova": not _existia(categoria, categorias_anteriores),
                      "categorias_mes_anterior": antes, "lancamentos": _itens(ls),
                      "meses_comparados": len(historico)},
        ))
    return achados


PISO_CATEGORIA = 1000.0   # categorias abaixo disso não geram achado (evita ruído em formatos só com totais)


def regra_subcontas_categorias(dados: DadosRegras, anterior: DadosRegras, cont: _Contador,
                               piso: float = PISO_CATEGORIA) -> list[Achado]:
    """Regra 8 para formatos que só trazem o TOTAL de cada categoria (sem lançamentos):
    categoria nova neste mês (valor >= piso). Categoria que apenas deixou de ter gasto não
    é divergência — despesa eventual some e volta naturalmente."""
    atual = {_norm(k): (k, v) for k, v in dados.categorias.items()}
    antes = {_norm(k): (k, v) for k, v in anterior.categorias.items()}
    achados = []
    for chave, (nome, valor) in atual.items():
        if chave not in antes and abs(valor) >= piso:
            achados.append(Achado(
                id=cont.proximo(), tipo="subconta_atipica", severidade_sugerida="atencao",
                regra_aplicada="categoria_nao_existia_no_mes_anterior", linha_demonstrativo=nome,
                valor_encontrado=round(valor, 2),
                detalhes={"categoria": nome, "so_total": True, "lancamentos": []}))
    return achados


# ── orquestração ─────────────────────────────────────────────────────────────

REGRAS_NOMES = {
    "receita_negativa": "Receitas com valor negativo",
    "rendimento": "Rendimentos distribuídos entre as contas",
    "sem_identificacao": "Pagamentos sem identificação",
    "parcelas": "Duas parcelas pagas no mesmo mês",
    "subcontas": "Lançamentos nas subcontas corretas",
}


def aplicar_regras(dados: Optional[DadosRegras], anterior: Optional[DadosRegras],
                   cfg_condo: Optional[dict] = None, historico: Optional[list] = None) -> tuple[list[Achado], dict]:
    """(achados, status) — status: {regra: {"aplicada": bool, "motivo": str|None}} para a seção
    'Verificações realizadas'. Regra que o formato não permite fica 'não aplicável' COM o motivo."""
    cfg_condo = cfg_condo or {}
    cont = _Contador()
    achados: list[Achado] = []
    status = {k: {"aplicada": False, "motivo": None} for k in REGRAS_NOMES}

    def _nao(regra, chave_cobertura, padrao):
        motivo = (dados.motivos_nao_cobertos.get(chave_cobertura) if dados else None) or padrao
        status[regra] = {"aplicada": False, "motivo": motivo}

    if dados is None:
        for regra in REGRAS_NOMES:
            status[regra] = {"aplicada": False, "motivo": "não foi possível ler os dados deste arquivo"}
        return achados, status

    cob = dados.cobertura
    if cob.get("receitas"):
        achados += regra_receita_negativa(dados, cont, cfg_condo.get("receita_negativa"))
        achados += regra_compensacao(dados, cont, cfg_condo.get("compensacoes"))
        status["receita_negativa"] = {"aplicada": True, "motivo": None}
    else:
        _nao("receita_negativa", "receitas", "o formato deste arquivo não traz as linhas de receita")

    if cob.get("rendimentos"):
        achados += regra_rendimento(dados, anterior, cont, cfg_condo.get("rendimento"))
        status["rendimento"] = {"aplicada": True, "motivo": None}
    else:
        _nao("rendimento", "rendimentos", "o formato deste arquivo não traz o rendimento de cada conta")

    if cob.get("lancamentos"):
        achados += regra_sem_identificacao(dados, cont)
        achados += regra_parcelas_mesmo_mes(dados, cont, anterior)
        status["sem_identificacao"] = {"aplicada": True, "motivo": None}
        status["parcelas"] = {"aplicada": True, "motivo": None}
        meses = [h for h in (historico if historico else ([anterior] if anterior is not None else []))
                 if h is not None and h.cobertura.get("lancamentos") and h.lancamentos]
        if meses:
            achados += regra_subcontas(dados, meses, cont, cfg_condo.get("subcontas"))
            status["subcontas"] = {"aplicada": True, "motivo": None}
        else:
            status["subcontas"] = {"aplicada": False, "motivo": "arquivo do mês anterior não localizado ou sem lançamentos legíveis"}
    else:
        for regra in ("sem_identificacao", "parcelas"):
            _nao(regra, "lancamentos", "o formato deste arquivo não lista os lançamentos individuais")
        if dados.categorias and anterior is not None and anterior.categorias:
            achados += regra_subcontas_categorias(dados, anterior, cont)
            status["subcontas"] = {"aplicada": True, "motivo": "só no nível de categoria (o formato não lista lançamentos)"}
        else:
            _nao("subcontas", "lancamentos", "o formato deste arquivo não lista os lançamentos individuais")
    return achados, status


# ── conferência da própria extração ──────────────────────────────────────────

def verificar_extracao(dados: DadosRegras) -> list[str]:
    """Avisos quando a leitura não fecha com os totais que o próprio arquivo declara:
    a soma dos lançamentos de cada conta deve bater com o débito dela no Resumo
    Financeiro. Se não bate, algum lançamento ficou de fora (ou entrou a mais) e as
    regras sobre lançamentos não são confiáveis nesse arquivo."""
    avisos = []
    if not dados.cobertura.get("lancamentos"):
        return avisos
    soma_por_conta: dict[str, float] = {}
    for l in dados.lancamentos:
        soma_por_conta[_norm(l.conta)] = soma_por_conta.get(_norm(l.conta), 0.0) + l.valor
    for c in dados.contas:
        s = soma_por_conta.get(_norm(c.nome))
        if s is None:
            continue
        if abs(s - c.debitos) > _CENTAVO:
            avisos.append(f"lançamentos lidos da conta {c.nome} somam {_fmt(s)}, mas o débito da conta no "
                          f"Resumo Financeiro é {_fmt(c.debitos)} (diferença de {_fmt(s - c.debitos)})")
    return avisos
