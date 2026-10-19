"""
Checklist de GESTOR CONDOMINIAL — pontos que um gestor olharia no balancete mesmo sem existir uma regra própria.

Só roda para o condomínio que pede (`regras.gestor` em config/validacao_balancetes.json) e lê SOMENTE os arquivos
desse condomínio (mês atual + histórico dele). Cada observação é um fato conferível (lançamento/linha citados, com
página para o print) e sai como `observacao_gestor`, severidade "atencao" (informativo = "verificado" e sai do relatório): é pergunta para o revisor, nunca
afirmação de erro e nunca "tudo certo".

Verificações (todas desligáveis em `gestor.desativar`):
  compra_marketplace        despesa paga em marketplace/intermediador de pagamento (sem fornecedor identificável)
  valor_redondo             despesa de valor "redondo" e alto, que não repete valor de meses anteriores
  fornecedor_novo           fornecedor sem nenhum lançamento nos meses anteriores, com valor alto
  recorrente_ausente        despesa que aparece em todos os últimos meses e sumiu neste
  valor_atipico             valor muito acima do histórico do mesmo fornecedor
  duplicidade_no_mes        mesmo histórico, mesma NF e mesmo valor lançados mais de uma vez no mês
  uso_fundo                 despesa paga direto de fundo (reserva etc.)
  deficit_conta             conta que pagou bem mais do que recebeu no mês
  inadimplencia_crescente   inadimplência total subiu forte em relação ao mês anterior
"""
import re
import statistics
from typing import Optional

from conciliacao.base import Achado
from conciliacao.regras_gerais.modelo import DadosRegras
from conciliacao.regras_gerais.regras import _CENTAVO, _RE_RETENCAO, _norm, _sem_acento, nf_da_descricao, parcela_da_descricao

_RE_MARKETPLACE = re.compile(
    r"MERCADO\s*PAGO|MERCADO\s*LIVRE|MERCADOLIVRE|AMAZON|MAGAZINE\s*LUIZA|MAGALU|SHOPEE|ALIEXPRESS|KABUM|AMERICANAS|SHEIN|"
    r"CASAS\s*BAHIA|PONTO\s*FRIO|SUBMARINO|PAGSEGURO|PAGSEG\b|PAYPAL|\bPICPAY\b", re.IGNORECASE)

_PADROES = {
    "valor_redondo_min": 2000.0,
    "fornecedor_novo_min": 3000.0,
    "meses_minimos_historico": 2,
    "recorrente_meses": 3,
    "recorrente_valor_min": 500.0,
    "atipico_fator": 2.5,
    "atipico_diferenca_min": 1000.0,
    "duplicidade_valor_min": 100.0,
    "uso_fundo_min": 1000.0,
    "fundos": ["RESERVA"],
    "deficit_contas": ["ORDINARIA", "CONDOMINIO"],   # trechos do nome da conta que paga as despesas correntes
    "deficit_min": 1000.0,
    "inad_crescimento_pct": 20.0,
    "inad_crescimento_min": 1000.0,
    "estabilidade_minima": 0.5,
    "ordinaria_pergunta_min": 20000.0,
}

MAX_ITENS = 12


def _item(l) -> dict:
    return {"descricao": l.descricao, "valor": l.valor, "data": l.data, "codigo": l.codigo, "categoria": l.categoria, "conta": l.conta,
            "pagina": l.pagina, "local": l.local, "bbox": l.bbox}


_RUIDO = {"DEB", "CC", "C", "REF", "NF", "NFE", "NFS", "NFSE", "INST", "COD", "FORNECIMENTO", "PARC", "PARCELA", "PC", "DE", "DA", "DO", "DAS",
          "DOS", "E", "A", "O", "PGTO", "PAGTO", "PAGAMENTO", "REFERENTE", "PROPORCIONAL", "SERV", "SERVICO", "SERVICOS",
          "JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ", "JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO",
          "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO", "LTDA", "ME", "EPP", "SA", "S", "FORN", "FORNEC", "AUT", "NFTS", "REF",
          "MES", "ANO", "KWH", "M3", "FNC", "RECIBO"}


def _chave_fornecedor(l) -> str:
    """Identidade do FORNECEDOR (não da rubrica, da unidade ou do mês): os 2 primeiros termos significativos do nome, sem nº de NF/RGI/
    instalação, mês, 'DEB C/C', 'REF' etc. — que mudam entre meses e formatos e geravam falso 'fornecedor novo'/'sumiu'."""
    def termos(txt: str) -> list:
        return [t for t in re.sub(r"\d+", " ", _norm(txt)).split() if t not in _RUIDO and len(t) > 1]

    if l.fornecedor and termos(l.fornecedor):
        return " ".join(termos(l.fornecedor)[:2])
    partes = [x.strip() for x in re.split(r"\s+-\s+", l.descricao or "") if x.strip()]
    ordem = ([partes[1], partes[-1], partes[0]] + partes[2:-1]) if len(partes) >= 3 else partes   # 'Rubrica - FORNECEDOR - ...' ou '... - NF - FORNECEDOR'
    for trecho in ordem:                      # 1º trecho com nome utilizável (os de só nº/mês/ruído são pulados)
        t = termos(trecho)
        if t:
            return " ".join(t[:2])
    return termos(l.descricao or "")[0] if termos(l.descricao or "") else _norm(l.descricao)


def estabilidade_fornecedores(hist: list) -> Optional[float]:
    """Parcela das chaves de fornecedor do mês mais recente do histórico que também aparecem no mês anterior a ele (None se não há 2 meses).
    Mede se, NESTE formato, o nome do fornecedor é um identificador confiável entre meses."""
    h = [x for x in hist if x is not None and x.lancamentos]
    if len(h) < 2:
        return None
    a = {_chave_fornecedor(l) for l in _lancamentos_validos(h[0])}
    b = {_chave_fornecedor(l) for l in _lancamentos_validos(h[1])}
    return len(a & b) / len(a) if a else None


_RE_EVENTUAL = re.compile(r"F[EÉ]RIAS|13\s*[ºO°]?\s*(?:SAL|PROP)|DECIMO|RESCIS|I\.?\s?P\.?\s?T\.?\s?U|ADIANTAMENTO|ISEN[CÇ][AÃ]O|\bCUSTAS\b|\bAPROP\b", re.IGNORECASE)


def _eventual(l) -> bool:
    """Férias, 13º, rescisão, IPTU: pagamentos que não se repetem todo mês por natureza — não são 'fornecedor novo' nem 'valor atípico'."""
    return bool(_RE_EVENTUAL.search(_sem_acento(l.descricao or "")))


_MES_NUM = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}
_RE_COMPETENCIA = re.compile(
    r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[A-Z]*\.?\s*[/.\-]\s*(\d{4}|\d{2})\b|\b(0?[1-9]|1[0-2])\s*/\s*(20\d{2})\b", re.IGNORECASE)


def _competencias(lancamentos: list) -> list:
    """Competências ('mês/ano') citadas nas descrições, em ordem cronológica e sem repetir (ex.: ['jul/2026', 'ago/2026', 'set/2026'])."""
    achadas: dict = {}
    for l in lancamentos:
        m = _RE_COMPETENCIA.search(_sem_acento(l.descricao or ""))
        if not m:
            continue
        if m.group(1):
            mes, ano = _MES_NUM[m.group(1).upper()], int(m.group(2))
        else:
            mes, ano = int(m.group(3)), int(m.group(4))
        ano = ano + 2000 if ano < 100 else ano
        achadas[(ano, mes)] = f"{[k for k, v in _MES_NUM.items() if v == mes][0].lower()}/{ano}"
    return [achadas[k] for k in sorted(achadas)]


def _competencias_num(lancamentos: list) -> list:
    """[((ano, mes), 'mês/ano'), ...] ordenado, das competências citadas nas descrições."""
    achadas: dict = {}
    for l in lancamentos:
        m = _RE_COMPETENCIA.search(_sem_acento(l.descricao or ""))
        if not m:
            continue
        if m.group(1):
            mes, ano = _MES_NUM[m.group(1).upper()], int(m.group(2))
        else:
            mes, ano = int(m.group(3)), int(m.group(4))
        ano = ano + 2000 if ano < 100 else ano
        achadas[(ano, mes)] = f"{[k for k, v in _MES_NUM.items() if v == mes][0].lower()}/{ano}"
    return [(k, achadas[k]) for k in sorted(achadas)]


def _parecido(a: str, b: str) -> bool:
    """Nomes de fornecedor quase iguais (diferença de 1-2 letras: 'JJS SOLUCOES' x 'JS SOLUCOES') — mesmo fornecedor digitado diferente."""
    if not a or not b or abs(len(a) - len(b)) > 2:
        return False
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.88


_RE_NATUREZA = re.compile(r"^(INSTALA\w*|IMPLANTA\w*|MANUT\w*|LOCA\w*|REPAR\w*|CONSERT\w*|REFORM\w*|TROCA\w*|PROJETO\w*|COMPRA\w*|MATERIA\w*|"
                          r"ADIANT\w*|OBRA\w*|CONTRAT\w*|SUBSTITUI\w*)$")


def _objeto(l, chave) -> set:
    """Palavras da descrição que dizem O QUE foi pago (sem o nome do fornecedor, números, meses e ruído)."""
    termos = [t for t in re.sub(r"\d+", " ", _norm(l.descricao or "")).split() if t not in _RUIDO and len(t) > 1]
    return {t for t in termos if t not in set(chave(l).split())}


def _semelhante(a, b, chave) -> bool:
    """Dois lançamentos do mesmo fornecedor são do MESMO tipo de serviço? Natureza diferente (instalação x manutenção x locação...) ou objeto
    sem nenhuma palavra em comum (postagens x tarifas) = comparação inválida."""
    oa, ob = _objeto(a, chave), _objeto(b, chave)
    na = {t[:5] for t in oa if _RE_NATUREZA.match(t)}
    nb = {t[:5] for t in ob if _RE_NATUREZA.match(t)}
    if na and nb and not (na & nb):
        return False
    ra = {t[:6] for t in oa if not _RE_NATUREZA.match(t)}      # raiz de 6 letras: ELEVADOR = ELEVADORES
    rb = {t[:6] for t in ob if not _RE_NATUREZA.match(t)}
    if not ra or not rb:
        return True
    return len(ra & rb) / len(ra | rb) >= 0.34


def _estrutural(l) -> bool:
    c = _norm(l.categoria)
    return c.startswith(("TRANSFERENCIA", "APLICACAO RESGATE")) or bool(_RE_RETENCAO.search(_sem_acento(l.descricao or "")))


def _lancamentos_validos(d: DadosRegras) -> list:
    return [l for l in d.lancamentos if l.valor > _CENTAVO and not _estrutural(l)]


def regra_gestor(dados: DadosRegras, anterior: Optional[DadosRegras], historico: list, cont, cfg: Optional[dict] = None,
                 por_rubrica: bool = False) -> tuple[list[Achado], list[str]]:
    """(achados, notas) — notas = o que NÃO pôde ser verificado e por quê (vai para 'Verificações realizadas')."""
    cfg = {**_PADROES, **(cfg or {})}
    desativar = set(cfg.get("desativar") or [])
    notas: list[str] = []
    hist = [h for h in historico if h is not None and h.lancamentos]
    atuais = _lancamentos_validos(dados)
    achados: list[Achado] = []
    est = estabilidade_fornecedores(hist)
    if est is None:
        motivo = "menos de 2 meses anteriores lidos no mesmo formato"
    elif est < cfg["estabilidade_minima"]:
        motivo = (f"neste formato de arquivo o nome do fornecedor não se repete de forma identificável de um mês para o outro "
                  f"(só {est * 100:.0f}% dos fornecedores do último mês aparecem no mês anterior)")
    else:
        motivo = None
    if motivo:
        desativar |= {"fornecedor_novo", "recorrente_ausente", "valor_atipico"}
        notas.append(f"fornecedor novo, despesa recorrente ausente e valor acima do histórico do fornecedor não verificados: {motivo}")

    chave = _chave_fornecedor

    def novo(verificacao, itens, linha, valor, **extra):
        achados.append(Achado(
            id=cont.proximo(), tipo="observacao_gestor", severidade_sugerida="atencao",
            regra_aplicada=f"gestor_{verificacao}", linha_demonstrativo=linha, valor_encontrado=round(valor, 2) if valor is not None else None,
            detalhes={"verificacao": verificacao, "total_itens": len(itens), "lancamentos": [_item(l) for l in itens[:MAX_ITENS]], **extra}))

    por_mes = {h.mes: {chave(l) for l in _lancamentos_validos(h)} for h in hist}
    historico_chaves = set().union(*por_mes.values()) if por_mes else set()

    if "compra_marketplace" not in desativar:
        itens = [l for l in atuais if _RE_MARKETPLACE.search(_sem_acento(l.descricao or "")) or _RE_MARKETPLACE.search(_sem_acento(l.fornecedor or ""))]
        if itens:
            novo("compra_marketplace", itens, "Compras em marketplace / intermediador", sum(l.valor for l in itens))

    alvos_ord = list(map(_norm, cfg["deficit_contas"]))

    def _pergunta_ordinaria(itens) -> dict:
        """Despesa de valor alto paga pela conta Ordinária: o gestor pergunta se o valor deve mesmo sair dela (ou de fundo/obras)."""
        altos = [l for l in itens if l.valor >= cfg["ordinaria_pergunta_min"] and any(t in _norm(l.conta) for t in alvos_ord)]
        if not altos:
            return {}
        saldo = next((c.saldo_atual for c in dados.contas if any(t in _norm(c.nome) for t in alvos_ord)
                      and not _norm(c.nome).startswith("CONSOLIDADO")), None)
        return {"pergunta_ordinaria": [{"descricao": l.descricao, "valor": l.valor, "conta": l.conta} for l in altos],
                "saldo_ordinaria": None if saldo is None else round(saldo, 2)}

    valores_antes = {round(l.valor, 2) for h in hist for l in _lancamentos_validos(h)}   # valor idêntico em mês anterior = valor fixo recorrente

    def _redondo(l) -> bool:
        return (l.valor >= cfg["valor_redondo_min"] and round(l.valor * 100) % 10000 == 0
                and round(l.valor, 2) not in valores_antes and not parcela_da_descricao(l.descricao)
                and not nf_da_descricao(l.descricao or ""))     # com nº de NF na descrição o valor veio da nota: redondo não é indício

    ids_novo: set = set()
    if "fornecedor_novo" not in desativar and len(por_mes) >= cfg["meses_minimos_historico"]:
        itens = [l for l in atuais if l.valor >= cfg["fornecedor_novo_min"] and chave(l) not in historico_chaves and not _eventual(l)
                 and not any(_parecido(chave(l), h) for h in historico_chaves)]
        if itens:
            ids_novo = {id(l) for l in itens}
            novo("fornecedor_novo", itens, "Fornecedores sem lançamento nos meses anteriores", sum(l.valor for l in itens),
                 minimo=cfg["fornecedor_novo_min"], meses_lidos=len(por_mes),
                 redondos=[l.valor for l in itens if _redondo(l)], **_pergunta_ordinaria(itens))

    if "valor_redondo" not in desativar and hist:
        # o lançamento que já saiu como "fornecedor novo" (e é redondo) não gera um 2º alerta: a informação vai no mesmo
        itens = [l for l in atuais if _redondo(l) and id(l) not in ids_novo]
        if itens:
            novo("valor_redondo", itens, "Despesas de valor redondo", sum(l.valor for l in itens), minimo=cfg["valor_redondo_min"],
                 **_pergunta_ordinaria(itens))

    if "recorrente_ausente" not in desativar and len(hist) >= cfg["recorrente_meses"]:
        ultimos = hist[:cfg["recorrente_meses"]]
        em_todos = set.intersection(*[por_mes[h.mes] for h in ultimos])
        atuais_chaves = {chave(l) for l in _lancamentos_validos(dados)}
        faltando = []
        for k in sorted(em_todos - atuais_chaves):
            if any(_parecido(k, a) for a in atuais_chaves):
                continue                                   # o mesmo fornecedor com o nome digitado diferente neste mês
            vals = [l.valor for h in ultimos for l in _lancamentos_validos(h) if chave(l) == k]
            amostra = [l for l in _lancamentos_validos(ultimos[0]) if chave(l) == k]
            if not vals or statistics.median(vals) < cfg["recorrente_valor_min"] or not amostra:
                continue
            if any((p := parcela_da_descricao(l.descricao)) and p[0] >= p[1] for l in amostra):
                continue                                   # série de parcelas que terminou
            faltando.append((k, amostra[0], statistics.median(vals)))
        if faltando:
            achados.append(Achado(
                id=cont.proximo(), tipo="observacao_gestor", severidade_sugerida="atencao", regra_aplicada="gestor_recorrente_ausente",
                linha_demonstrativo="Despesas recorrentes ausentes neste mês", valor_encontrado=round(sum(v for _, _, v in faltando), 2),
                detalhes={"verificacao": "recorrente_ausente", "total_itens": len(faltando), "meses_comparados": [h.mes for h in ultimos],
                          "ausentes": [{"descricao": l.descricao, "mediana": round(v, 2), "categoria": l.categoria} for _, l, v in faltando[:MAX_ITENS]],
                          "lancamentos": []}))

    if "valor_atipico" not in desativar and hist:
        # Compara semelhante com semelhante: o mesmo fornecedor pode prestar serviços de natureza diferente (instalação x manutenção) e o nome
        # abreviado ("DESPESAS COM ...") junta objetos que nada têm a ver (postagens x tarifas). Cada grupo é comparado só com os
        # lançamentos do histórico que têm o mesmo fornecedor E o mesmo tipo de serviço (ver _semelhante).
        grupos: list = []
        for l in atuais:
            if parcela_da_descricao(l.descricao) or _eventual(l):
                continue
            for rep, membros in grupos:
                if chave(rep) == chave(l) and _semelhante(rep, l, chave):
                    membros.append(l)
                    break
            else:
                grupos.append((l, [l]))
        itens, medianas = [], []
        for rep, ls in grupos:
            k = chave(rep)
            v = sum(x.valor for x in ls)
            vs = []
            for h in hist:
                s = sum(x.valor for x in _lancamentos_validos(h) if chave(x) == k and _semelhante(rep, x, chave))
                if s > _CENTAVO:
                    vs.append(s)
            if len(vs) < 2:
                # Sem histórico comparável do mesmo serviço não dá para falar em "valor acima do histórico", mas várias competências pagas
                # juntas no mês (valores iguais, com meses anteriores) continuam sendo um fato do próprio arquivo.
                comps0 = _competencias_num(ls)
                valores0 = [x.valor for x in ls]
                mes_num0 = (int(dados.mes[:4]), int(dados.mes[5:7]))
                # (pagar no mês a competência do mês anterior é o normal; só vale quando 2+ competências são de meses ANTERIORES ao atual)
                if (len(ls) >= 2 and len(comps0) >= 2 and sum(1 for ym, _ in comps0 if ym < mes_num0) >= 2
                        and (max(valores0) - min(valores0)) <= 0.15 * (sum(valores0) / len(valores0))):
                    datas0: dict = {}
                    for x in ls:
                        datas0[x.data or "sem data"] = datas0.get(x.data or "sem data", 0) + 1
                    itens += ls
                    medianas.append({"descricao": k, "valor": round(v, 2), "mediana": None, "acumulo": True, "sem_comparacao": True, "n": len(ls),
                                     "valor_unitario": round(sum(valores0) / len(valores0), 2), "competencias": [r for _, r in comps0], "datas": datas0})
                continue
            m = statistics.median(vs)
            if m > _CENTAVO and v >= cfg["atipico_fator"] * m and v - m >= cfg["atipico_diferenca_min"]:
                itens += ls
                item = {"descricao": k, "valor": round(v, 2), "mediana": round(m, 2)}
                # Total alto porque vários meses foram pagos de uma vez (cada lançamento no valor mensal de sempre): não é aumento de valor,
                # é pagamento acumulado de competências anteriores — a pergunta certa é o motivo de pagarem juntos.
                # Só é "acúmulo" quando os lançamentos têm praticamente o mesmo valor (a mensalidade de sempre) e citam competências diferentes;
                # fornecedor com serviços de valores variados (honorários + acordos) não é acúmulo de mensalidades.
                comps = _competencias_num(ls)
                valores = [l.valor for l in ls]
                datas: dict = {}
                for l in ls:
                    datas[l.data or "sem data"] = datas.get(l.data or "sem data", 0) + 1
                mes_atual_num = (int(dados.mes[:4]), int(dados.mes[5:7]))
                anteriores = [rotulo for (ym, rotulo) in comps if ym < mes_atual_num]
                if len(ls) >= 2 and len(comps) >= 2 and (max(valores) - min(valores)) <= 0.15 * (sum(valores) / len(valores)):
                    unit = sum(valores) / len(valores)
                    item.update(acumulo=True, n=len(ls), valor_unitario=round(unit, 2),
                                competencias=[r for _, r in comps], datas=datas,
                                sem_comparacao=abs(unit - m) > 0.15 * m)     # só diz "valor mensal de sempre" quando a mediana confirma
                elif len(anteriores) >= 2:
                    item.update(competencias_anteriores=anteriores, n=len(ls), datas=datas)
                medianas.append(item)
        if itens:
            novo("valor_atipico", itens, "Valores acima do histórico do fornecedor", sum(l.valor for l in itens), fator=cfg["atipico_fator"],
                 medianas=medianas[:MAX_ITENS])

    if "apropriacao_despesa" not in desativar:
        aprop = [l for l in dados.lancamentos if re.search(r"\bAPROP\b", _sem_acento(l.descricao or ""), re.IGNORECASE)]
        # Estorno + relançamento do mesmo valor e mesma NF (ex.: -40.000 numa subconta e +40.000 em outra): reclassificação sem efeito líquido.
        por_nf: dict = {}
        for l in dados.lancamentos:
            nf = nf_da_descricao(l.descricao or "")
            if nf:
                por_nf.setdefault((chave(l), nf), []).append(l)
        pares, reclass = [], []
        for ls in por_nf.values():
            negs = [l for l in ls if l.valor < 0 and abs(l.valor) >= 500]
            for n_ in negs:
                par = next((p for p in ls if p.valor > 0 and abs(p.valor + n_.valor) <= 0.01 and id(p) not in {id(x) for x in pares}), None)
                if par is not None:
                    pares += [n_, par]
                    if _norm(n_.categoria) != _norm(par.categoria):
                        reclass.append({"de": n_.categoria, "para": par.categoria, "valor": par.valor})
        ids_aprop = {id(l) for l in aprop}
        aprop = aprop + [l for l in pares if id(l) not in ids_aprop]
        if aprop:
            series: dict = {}
            for l in aprop:
                p = parcela_da_descricao(re.sub(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)", r"PARC \1/\2", l.descricao or ""))
                if p:
                    series.setdefault((nf_da_descricao(l.descricao) or "", p[1]), set()).add(p[0])
            novo("apropriacao_despesa", aprop, "Apropriações de despesa", sum(l.valor for l in aprop),
                 estornos=[l.valor for l in aprop if l.valor < 0], tem_aprop=bool(ids_aprop), reclassificacoes=reclass,
                 parcelas_juntas=[{"nf": k[0], "total": k[1], "parcelas": sorted(v)} for k, v in series.items() if len(v) >= 2])

    if "duplicidade_no_mes" not in desativar:
        grupos: dict = {}
        for l in atuais:
            if l.valor < cfg["duplicidade_valor_min"] or parcela_da_descricao(l.descricao):
                continue
            grupos.setdefault((_norm(l.descricao), round(l.valor, 2)), []).append(l)
        for (_, v), ls in grupos.items():
            if len(ls) >= 2 and nf_da_descricao(ls[0].descricao):      # sem nº de NF, lançamentos idênticos costumam ser unidades/funcionários distintos
                novo("duplicidade_no_mes", ls, ls[0].categoria, v * len(ls), valor_unitario=v, vezes=len(ls))

    if "uso_fundo" not in desativar:
        itens = [l for l in atuais if l.valor >= cfg["uso_fundo_min"] and any(f in _norm(l.conta) for f in map(_norm, cfg["fundos"]))]
        if itens:
            novo("uso_fundo", itens, "Despesas pagas direto de fundo", sum(l.valor for l in itens), minimo=cfg["uso_fundo_min"],
                 contas=sorted({l.conta for l in itens}))

    if "deficit_conta" not in desativar:
        alvos = list(map(_norm, cfg["deficit_contas"]))
        for c in dados.contas:
            if any(t in _norm(c.nome) for t in alvos) and not _norm(c.nome).startswith("CONSOLIDADO") and c.debitos - c.creditos >= cfg["deficit_min"] and c.debitos > c.creditos * 1.05:
                achados.append(Achado(
                    id=cont.proximo(), tipo="observacao_gestor", severidade_sugerida="atencao", regra_aplicada="gestor_deficit_conta",
                    linha_demonstrativo=c.nome, valor_encontrado=round(c.debitos - c.creditos, 2),
                    detalhes={"verificacao": "deficit_conta", "conta": c.nome, "creditos": round(c.creditos, 2), "debitos": round(c.debitos, 2),
                              "saldo_anterior": round(c.saldo_anterior, 2), "saldo_atual": round(c.saldo_atual, 2), "pagina": c.pagina, "lancamentos": []}))

    if "inadimplencia_crescente" not in desativar and dados.indicadores and anterior is not None and anterior.indicadores:
        a, b = dados.indicadores.get("inad"), anterior.indicadores.get("inad")
        if a is not None and b is not None and b > _CENTAVO and a - b >= cfg["inad_crescimento_min"] and (a - b) / b * 100 >= cfg["inad_crescimento_pct"]:
            serie = [(h.mes, h.indicadores["inad"]) for h in hist if h.indicadores and h.indicadores.get("inad") is not None][:4]
            achados.append(Achado(
                id=cont.proximo(), tipo="observacao_gestor", severidade_sugerida="atencao", regra_aplicada="gestor_inadimplencia_crescente",
                linha_demonstrativo="Inadimplência total", valor_encontrado=round(a, 2),
                detalhes={"verificacao": "inadimplencia_crescente", "atual": round(a, 2), "anterior": round(b, 2), "variacao_pct": round((a - b) / b * 100, 1),
                          "serie": [{"mes": m, "inad": round(v, 2)} for m, v in serie], "lancamentos": []}))
    return achados, notas
