"""
Extrator das regras gerais — Consvicta (empresa `consvicta_pdf`: Gardens Living Club I).

O "Livro de prestação de contas" da Consvicta (500+ páginas; maior parte comprovantes e cobranças) traz o balancete nas
primeiras páginas, no relatório **W020A "Demonstrativo de Receitas e Despesas Analítico"** (+ W016B "Resumo Financeiro"):

    Saldo em 30/06/2026          Ordinária / Fundo de Reserva / Locações / Medidores de Gás / total
    Receitas                     grupo (xx,xx%) > [subgrupo] > "N cobranças | competência | % | valor"   ... Total de Receitas
    Despesas                     grupo (xx,xx%) > subgrupo > [sub-subgrupo] > lançamento: "Fornecedor - descrição | liquidação |
                                 documento | % | valor"                                                      ... Total de Despesas
    Saldo em 31/07/2026

É o demonstrativo ANALÍTICO que é lido (não o gráfico "Distribuição das Despesas" — W037E — que traz só os 14 maiores
lançamentos + "Outros", nem o W015A comparativo). Particularidades:

  * O W020A é CONSOLIDADO: as quatro contas (Ordinária, Fundo de Reserva, Locações, Medidores de Gás) aparecem juntas e o
    livro não informa a conta de cada receita/despesa. Por isso `receitas`/`lancamentos` usam a conta
    "CONSOLIDADO (todas as contas)" — que fecha com Total de Receitas / Total de Despesas — e o rendimento por conta NÃO
    é verificável (cobertura["rendimentos"] = False). As quatro contas do W016B (saldo ant., créditos*, débitos*, saldo final;
    "*" = inclui transferência entre contas) são listadas só para consulta;
  * a transferência entre contas (ex.: Ordinária -> Locações, 3.549,75 em jul/26) está embutida no "Débitos*" do W016B e
    NÃO aparece no demonstrativo analítico (nem como receita nem como despesa) — não há lançamento dela para ler;
  * receitas com valor negativo existem no demonstrativo, impressas entre parênteses ("(4,00)" Tarifa Bancária,
    "(8,78)" Pagamento a Maior, "(150,00)" Vaga de Moto): são lidas com o sinal impresso;
  * a hierarquia usa indentação: nível 1 = "Nome (xx,xx%)"; nível 2 = nome sem %; nível 3 = nome recuado para trás
    (ex.: "Medicina do Trabalho" > "LTCAT-PGR"); "Total de X" fecha o nível de X. Histórico longo continua na linha de baixo,
    encostada na margem.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

CONSOLIDADO = "CONSOLIDADO (todas as contas)"
_RE_NUM = re.compile(r"^\(?-?\d{1,3}(?:\.\d{3})*,\d{2}\)?$")
_RE_HDR_PCT = re.compile(r"^(.+?)\s+\((-?[\d.]+,\d{2})%\)$")
_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _num(s: str):
    s = (s or "").strip()
    if not _RE_NUM.match(s):
        return None
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    v = float(s.strip("()-").replace(".", "").replace(",", "."))
    return -v if neg else v


def _norm(s: str) -> str:
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s.upper())).strip()


def _linhas(page, tol: float = 3.0) -> list[dict]:
    ws = sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    linhas: list[dict] = []
    for w in ws:
        yc = (w[1] + w[3]) / 2
        if linhas and abs(yc - linhas[-1]["yc"]) <= tol:
            linhas[-1]["w"].append(w)
        else:
            linhas.append({"yc": yc, "w": [w]})
    for l in linhas:
        l["w"].sort(key=lambda w: w[0])
        l["texto"] = " ".join(w[4] for w in l["w"])
        l["x0"] = l["w"][0][0]
        l["bbox"] = (round(min(w[0] for w in l["w"]), 1), round(min(w[1] for w in l["w"]), 1),
                     round(max(w[2] for w in l["w"]), 1), round(max(w[3] for w in l["w"]), 1))
    return linhas


def _valor_direita(linha: dict, x_min: float = 520.0):
    ws = linha["w"]
    if ws and ws[-1][0] >= x_min:
        v = _num(ws[-1][4])
        if v is not None:
            return v
    return None


def _tipo_receita(grupo: str) -> str:
    g = _norm(grupo)
    if "RENDIMENTO" in g or "APLICACAO" in g:
        return "rendimento"
    if re.search(r"MULTA|JUROS|ATUALIZACAO MONETARIA|ACRESCIMO", g):
        return "multa_juros"
    if "TRANSFER" in g:
        return "transferencia"
    if re.search(r"TAXA DE CONDOMINIO|FUNDO DE RESERVA|RESERVA DE ESPACOS|CONTA DE CONSUMO|TAXA DE LEITURA|RATEIO|BONIFICACAO", g):
        return "cota"
    return "outra"


def _contas_w016b(pag: int, linhas: list) -> list:
    """Contas do W016B (Resumo Financeiro): nome | saldo ant. | créditos* | débitos* | saldo final. O nome pode continuar na linha de baixo."""
    contas = []
    for i, l in enumerate(linhas):
        nums = [(_num(w[4]), w) for w in l["w"] if _num(w[4]) is not None]
        nome = " ".join(w[4] for w in l["w"] if _num(w[4]) is None).strip()
        if len(nums) >= 4 and nome and not _norm(nome).startswith("SALDO FINAL"):
            if i + 1 < len(linhas):
                prox = linhas[i + 1]
                if abs(prox["yc"] - l["yc"]) <= 14 and not any(_num(w[4]) is not None for w in prox["w"]) and prox["texto"].strip().endswith(")")                         and nome.count("(") > nome.count(")"):
                    nome = f"{nome} {prox['texto'].strip()}"
            v = [n for n, _ in nums[-4:]]
            contas.append(ContaMes(nome=nome, saldo_anterior=v[0], creditos=v[1], debitos=abs(v[2]), saldo_atual=v[3], pagina=pag))
    return contas


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        doc = fitz.open(str(caminho))
        try:
            return self._ler(doc, dados, mes)
        finally:
            doc.close()

    def _ler(self, doc, dados: DadosRegras, mes: str) -> DadosRegras:
        # 1. páginas do W020A (a partir da 1ª página com o título, até "Total de Despesas" + saldo final)
        paginas = []
        w016b = None
        achou = False
        fim = False
        for i in range(min(len(doc), 60)):
            linhas = _linhas(doc[i])
            topo = " ".join(l["texto"] for l in linhas[:3]).upper()
            if "W016B" in topo and w016b is None:
                w016b = (i + 1, linhas)
            if "W020A" in topo:
                achou = True
            if achou and not fim:
                paginas.append((i + 1, linhas))
                if any(re.match(r"^Total de Despesas\s+100,00%", l["texto"]) for l in linhas):
                    fim = True                          # o saldo final vem na mesma página (ou no topo da próxima)
            elif achou and fim and w016b is not None:
                break
            elif achou and fim and i > paginas[-1][0] + 6:
                break
        if not paginas:
            return self._ler_gerencer(doc, dados, mes)

        # período do cabeçalho
        cab = " ".join(l["texto"] for l in paginas[0][1][:6])
        mper = re.search(r"Entre (\d{2})/(\d{2})/(\d{4}) e (\d{2})/(\d{2})/(\d{4})", cab)
        if mper:
            d1, m1, a1, d2, m2, a2 = mper.groups()
            if f"{a1}-{m1}" != mes or f"{a2}-{m2}" != mes:
                dados.avisos.append(f"o W020A deste livro traz o período {d1}/{m1}/{a1} a {d2}/{m2}/{a2}, diferente do mês {mes[5:]}/{mes[:4]}")

        modo = None                      # "rec" | "desp" | "fim"
        stack: list[str] = []
        total_rec = total_desp = None
        saldo_ini = saldo_fim = None
        ultimo = None                    # último lançamento/receita lido (para continuação de texto)
        docs: dict[int, str] = {}
        pend_saldo = None                # "ini" | "fim": linhas "Conta valor" que se seguem a "Saldo em dd/mm/aaaa"
        for pag, linhas in paginas:
            for l in linhas:
                t = l["texto"].strip()
                tn = _norm(t)
                if l["bbox"][1] > 770 or re.fullmatch(r"\d+ DE \d+", tn):
                    continue
                if tn.startswith(("W020A", "DEMONSTRATIVO DE RECEITAS", "ENTRE ")):
                    continue
                if tn.startswith("SALDO EM"):
                    pend_saldo = "ini" if saldo_ini is None and modo is None else "fim"
                    continue
                if pend_saldo:
                    v = _valor_direita(l, 100.0)
                    ws = l["w"]
                    if v is not None and len(ws) == 1:             # total (só o número)
                        if pend_saldo == "ini":
                            saldo_ini = (saldo_ini or {}) | {"__total__": v}
                        else:
                            saldo_fim = (saldo_fim or {}) | {"__total__": v}
                            if modo == "fim":
                                pend_saldo = None
                        continue
                    if v is not None and len(ws) >= 2:
                        nome = " ".join(w[4] for w in ws[:-1])
                        if pend_saldo == "ini":
                            saldo_ini = (saldo_ini or {}) | {nome: v}
                        else:
                            saldo_fim = (saldo_fim or {}) | {nome: v}
                        continue
                    if tn.startswith("RECEITAS") or tn.startswith("MOV LIQUIDO"):
                        pend_saldo = None
                if tn.startswith("RECEITAS") and "COMPETENCIA" in tn:
                    modo, stack, ultimo, pend_saldo = "rec", [], None, None
                    continue
                if tn.startswith("DESPESAS") and "LIQUIDACAO" in tn:
                    modo, stack, ultimo = "desp", [], None
                    continue
                if re.match(r"^Total de Receitas\s+100,00%", t):
                    total_rec = _valor_direita(l)
                    modo, stack, ultimo = None, [], None
                    continue
                if re.match(r"^Total de Despesas\s+100,00%", t):
                    total_desp = _valor_direita(l)
                    modo, stack, ultimo = "fim", [], None
                    continue
                if tn.startswith("MOV LIQUIDO"):
                    continue
                if modo not in ("rec", "desp"):
                    continue

                ws = l["w"]
                valor = _valor_direita(l)
                if tn.startswith("TOTAL DE "):
                    nome_total = re.sub(r"\s+\(?-?[\d.]+,\d{2}\)?%?.*$", "", t[len("Total de "):]).strip()
                    nt = _norm(nome_total)
                    for idx in range(len(stack) - 1, -1, -1):
                        if _norm(stack[idx]) == nt:
                            stack = stack[:idx]
                            break
                    ultimo = None
                    continue
                if valor is None:
                    mh = _RE_HDR_PCT.match(t)
                    if mh:
                        stack = [mh.group(1).strip()]            # nível 1
                        ultimo = None
                    elif l["x0"] < 36 and ultimo is not None:    # continuação do histórico do item anterior
                        ultimo.descricao += " " + t
                    elif l["x0"] < 36:
                        pass
                    elif l["x0"] >= 43 and len(stack) >= 1:
                        stack = stack[:1] + [t]                  # nível 2
                        ultimo = None
                    elif len(stack) >= 2:
                        stack = stack[:2] + [t]                  # nível 3 (recuo menor que o nível 2)
                        ultimo = None
                    continue

                # linha com valor = folha
                esq = [w for w in ws if w[0] < 300]
                rotulo = " ".join(w[4] for w in esq).strip()
                meio = [w[4] for w in ws if 300 <= w[0] < 520 and _num(w[4]) is None and not w[4].endswith("%")]
                caminho = " › ".join(stack[:2]) if stack else "(sem grupo)"          # grupo › subgrupo (o 3º nível é só detalhe)
                if modo == "rec":
                    comp = " ".join(meio).strip()
                    desc = f"{rotulo} {comp}".strip()
                    r = LinhaReceita(conta=CONSOLIDADO, descricao=f"{stack[-1] if stack else ''} — {desc}".strip(" —"), valor=valor,
                                     tipo=_tipo_receita(stack[0] if stack else rotulo), pagina=pag, bbox=l["bbox"])
                    dados.receitas.append(r)
                    ultimo = r
                else:
                    data = next((w[4] for w in ws if 300 <= w[0] < 365 and _RE_DATA.match(w[4])), None)
                    doc_ = " ".join(w[4] for w in ws if 365 <= w[0] < 470 and not _RE_DATA.match(w[4]) and _num(w[4]) is None).strip()
                    lanc = LancamentoDespesa(descricao=rotulo, valor=valor, categoria=caminho,
                                             conta=CONSOLIDADO, data=data, codigo=None, pagina=pag, bbox=l["bbox"])
                    docs[id(lanc)] = doc_
                    dados.lancamentos.append(lanc)
                    ultimo = lanc

        # o documento (NF-..., Fatura-...) vai no fim da descrição, depois da continuação do histórico
        for lanc in dados.lancamentos:
            if docs.get(id(lanc)):
                lanc.descricao = f"{lanc.descricao} {docs[id(lanc)]}".strip()

        # 2. W016B: contas
        if w016b:
            dados.contas.extend(_contas_w016b(*w016b))
        soma_rec = round(sum(r.valor for r in dados.receitas), 2)
        soma_desp = round(sum(x.valor for x in dados.lancamentos), 2)
        dados.contas.insert(0, ContaMes(
            nome=CONSOLIDADO, saldo_anterior=(saldo_ini or {}).get("__total__", 0.0), saldo_atual=(saldo_fim or {}).get("__total__", 0.0),
            creditos=total_rec if total_rec is not None else soma_rec, debitos=total_desp if total_desp is not None else soma_desp,
            pagina=paginas[0][0]))
        if total_rec is not None and abs(soma_rec - total_rec) > 0.011:
            dados.avisos.append(f"receitas lidas somam {soma_rec:,.2f}, mas o 'Total de Receitas' impresso é {total_rec:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        if total_desp is not None and abs(soma_desp - total_desp) > 0.011:
            dados.avisos.append(f"despesas lidas somam {soma_desp:,.2f}, mas o 'Total de Despesas' impresso é {total_desp:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        if saldo_ini and saldo_fim and total_rec is not None and total_desp is not None:
            esperado = saldo_ini.get("__total__", 0.0) + total_rec - total_desp
            if abs(esperado - saldo_fim.get("__total__", 0.0)) > 0.011:
                dados.avisos.append("saldo inicial + receitas - despesas não fecha com o saldo final impresso do W020A")

        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": False, "lancamentos": bool(dados.lancamentos)}
        if not dados.receitas:
            dados.motivos_nao_cobertos["receitas"] = "não consegui ler as receitas do W020A"
        dados.motivos_nao_cobertos["rendimentos"] = ("o livro Consvicta é consolidado: lista os 'Rendimentos de Aplicação' do mês sem dizer em qual das contas "
                                                    "(Ordinária, Fundo de Reserva, Locações, Medidores de Gás) cada um foi creditado")
        if not dados.lancamentos:
            dados.motivos_nao_cobertos["lancamentos"] = "não consegui ler as despesas do W020A"
        return dados

    # ── livro anterior a mai/2026 (administradora Gerencer; mesmo software: relatórios W015C/W015D/W014A/W016B) ──
    def _ler_gerencer(self, doc, dados: DadosRegras, mes: str) -> DadosRegras:
        """nov/25-abr/26: o livro NÃO tem o W020A analítico. W015C (Demonstrativo de Receitas) traz as receitas por plano de
        contas ("- Taxa Condominial  73,95%  229.309,78"), W015D (Demonstrativo de Despesas) as despesas por plano (uma linha por
        conta do plano, sem os pagamentos) e W014A ("Todas as despesas") lista cada documento mas sem a subconta. Só as receitas
        são lidas (valor com o sinal impresso); despesas ficam fora para não comparar planos com lançamentos individuais."""
        pag_w015c = None
        linhas_w015c = []
        w016b = None
        for i in range(min(len(doc), 20)):
            linhas = _linhas(doc[i])
            topo = " ".join(l["texto"] for l in linhas[:3]).upper()
            if "W015C" in topo:
                pag_w015c = i + 1
                linhas_w015c = linhas
            if "W016B" in topo and w016b is None:
                w016b = (i + 1, linhas)
        if pag_w015c is None:
            for k in ("receitas", "rendimentos", "lancamentos"):
                dados.motivos_nao_cobertos[k] = "não encontrei o W020A nem o W015C (Demonstrativo de Receitas) nas primeiras páginas do livro"
            return dados
        stack: list[str] = []
        total_rec = None
        em_transf = False
        for l in linhas_w015c:
            t = l["texto"].strip()
            tn = _norm(t)
            if l["bbox"][1] > 770:
                continue
            if tn.startswith("TRANSFERENCIAS ENTRE CONTAS"):
                em_transf = True
                continue
            if em_transf:
                continue
            valor = _valor_direita(l)
            if re.match(r"^Total de - Receitas", t):
                total_rec = valor
                continue
            if tn.startswith("TOTAL DE"):
                continue
            if valor is None:
                m = re.match(r"^-\s+(.+)$", t)
                if m:
                    nivel = 1 if l["x0"] < 40 else 2
                    stack = stack[:nivel - 1] + [m.group(1).strip()]
                continue
            m = re.match(r"^-\s+(.+?)\s+-?[\d.]+,\d{2}%\s+\(?-?[\d.]+,\d{2}\)?$", t)
            rotulo = m.group(1).strip() if m else t
            dados.receitas.append(LinhaReceita(
                conta=CONSOLIDADO, descricao=f"{stack[-1] if stack else ''} — {rotulo}".strip(" —"), valor=valor,
                tipo=_tipo_receita(rotulo), pagina=pag_w015c, bbox=l["bbox"]))
        if w016b:
            dados.contas.extend(_contas_w016b(*w016b))
        soma_rec = round(sum(r.valor for r in dados.receitas), 2)
        if total_rec is not None and abs(soma_rec - total_rec) > 0.011:
            dados.avisos.append(f"receitas lidas somam {soma_rec:,.2f}, mas o 'Total de Receitas' impresso é {total_rec:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": False, "lancamentos": False}
        dados.motivos_nao_cobertos = {
            "receitas": "não consegui ler o Demonstrativo de Receitas (W015C) deste livro",
            "rendimentos": ("o livro (administradora anterior a mai/2026) lista 'Rendimentos de Aplicações' consolidado, sem dizer a conta creditada"),
            "lancamentos": ("este livro (nov/25-abr/26, administradora Gerencer) traz o Demonstrativo de Despesas só por conta do plano (sem os pagamentos) e a lista "
                            "'Todas as despesas' sem subconta — não dá para checar sem identificação, parcelas e subcontas; a leitura por lançamento existe "
                            "a partir do livro Consvicta (mai/2026)"),
        }
        if not dados.receitas:
            dados.cobertura["receitas"] = False
        dados.avisos.append("livro no formato Gerencer (W015C/W015D/W014A): só as receitas por plano de contas foram lidas; as 'Transferências entre contas' "
                            "(linhas (+)/(-)) não foram tratadas como receita")
        return dados
