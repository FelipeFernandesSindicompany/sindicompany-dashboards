"""
Extrator das regras gerais — Alliz Administração (empresa `alliz_pdf`: Monte Tabor).

PDF com camada de texto (software DataDigitus da Alliz; as 3 primeiras páginas são imagem —
capa/índice — e depois do balancete vêm pendências, acordos, extratos e comprovantes). Só o
início do arquivo interessa; cada seção tem um título "N.N NOME" no topo da página:

  5.4 RESUMO FINANCEIRO            por conta: saldo anterior, receita realizada (detalhada), despesas, saldo atual
                                    + tabela "RESUMO DAS CONTAS DE BALANCETE" (saldo ant / créditos / débitos / saldo atual)
  2.1 (ou 2.2) DEMONSTRATIVO DE DESPESAS   conta > grupo (DESPESAS PESSOAL...) > itens (histórico + valor, SEM data)
  3.2 RELATÓRIO DE RECEBIMENTOS    por conta > período (SEM MULTA, COM MULTA, ATRASADO, ANTECIPADO, ACORDOS, MULTAS, JUROS):
                                    uma linha por recibo ("000011 - NOME" + recibo + histórico + valor)
  3.2 OUTRAS RECEITAS              rendimento (RENDIMENTO/C/C) e transferências entre contas de balancete

Particularidades (documentadas na investigação anterior e confirmadas aqui):
  * o número da seção do Demonstrativo varia entre meses ("2.1" em jul/26 e out-dez/25; "2.2" em jan-jun/26) -> não fixar;
  * o relatório de recebimentos repete "001 - ORDINARIA" e o "RESUMO FINANCEIRO" reaparece em outro layout nas páginas
    29-31 (cópia) -> cada seção é lida só no 1º bloco de páginas consecutivas e ignorada se reaparecer;
  * a transferência entre fundos (ex.: -432,51 FUNDO PESSOAL PROVISAO -> FUNDO RESCISÃO/INDENIZAÇÃO) aparece em "OUTRAS RECEITAS"
    como linha negativa na conta que envia — mas no Resumo é DÉBITO daquela conta (não é receita negativa); só a perna
    positiva (crédito da conta que recebe) entra em `receitas`, tipo "transferencia";
  * Monte Tabor só tem rendimento na conta ORDINARIA ("RENDIMENTO/C/C"); as demais contas não são aplicadas.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_RE_VALOR = re.compile(r"^\(?-?\d{1,3}(?:\.\d{3})*,\d{2}\)?-?$")
_RE_CONTA = re.compile(r"^(\d{3})\s*-\s*(\S.*)$")
_RE_TITULO = re.compile(r"^(\d\.\d)\s+(.+)$")


def _num(s: str):
    """'1.234,56' | '-36.564,17' | '(5,06)' | '5,06-' -> float com sinal; None se não for número BR."""
    s = (s or "").strip()
    if not _RE_VALOR.match(s):
        return None
    neg = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    v = float(s.strip("()-").replace(".", "").replace(",", "."))
    return -v if neg else v


def _linhas(page, tol: float = 3.0) -> list[dict]:
    """Palavras da página agrupadas em linhas visuais (por y), cada uma com texto, palavras e bbox."""
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
        l["bbox"] = (min(w[0] for w in l["w"]), min(w[1] for w in l["w"]), max(w[2] for w in l["w"]), max(w[3] for w in l["w"]))
    return linhas


def _valor_final(linha: dict, x_min: float = 380.0):
    """(valor, palavras_antes) se a linha termina num número BR à direita de x_min; senão (None, todas as palavras)."""
    ws = linha["w"]
    if ws and ws[-1][0] >= x_min:
        v = _num(ws[-1][4])
        if v is not None:
            return v, ws[:-1]
    return None, ws


def _pares(linha: dict, x_min: float = 0.0) -> list:
    """Linha com 1 ou mais pares "rótulo valor" lado a lado (layout em 2 colunas do RESUMO) -> [(rótulo, valor, bbox)]."""
    pares, rot = [], []
    for w in linha["w"]:
        v = _num(w[4]) if w[0] >= x_min else None
        if v is not None:
            pares.append((" ".join(x[4] for x in rot).strip(), v, (round(min(x[0] for x in rot + [w]), 1), round(w[1], 1), round(w[2], 1), round(w[3], 1))))
            rot = []
        else:
            rot.append(w)
    return pares


def _norm(s: str) -> str:
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s.upper())).strip()


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    # ── leitura por seção ────────────────────────────────────────────────────
    def _paginas_por_secao(self, doc, limite: int = 80):
        """[(kind, nº_página_1based, linhas)] só do 1º bloco de cada seção; kinds: resumo, despesas, receb, outras."""
        resultado = []
        concluidas: set[str] = set()
        kind_ant = None
        for i in range(min(len(doc), limite)):
            linhas = _linhas(doc[i])
            if len(linhas) < 5:          # página-imagem (capa/índice) ou comprovante
                continue
            titulo = None
            for l in linhas[:10]:
                m = _RE_TITULO.match(l["texto"])
                if m:
                    titulo = _norm(m.group(2))
                    break
            if titulo is None:
                kind = None
            elif titulo.startswith("RESUMO FINANCEIRO"):
                kind = "resumo"
            elif titulo.startswith("DEMONSTRATIVO DE DESPESAS"):
                kind = "despesas"
            elif titulo.startswith("RELATORIO DE RECEBIMENTOS"):
                kind = "receb"
            elif titulo.startswith("OUTRAS RECEITAS"):
                kind = "outras"
            else:
                kind = "outro"
            if kind != kind_ant:
                if kind_ant in ("resumo", "despesas", "receb", "outras"):
                    concluidas.add(kind_ant)
                kind_ant = kind
            if kind in ("resumo", "despesas", "receb", "outras") and kind not in concluidas:
                resultado.append((kind, i + 1, linhas))
            if kind == "outro" and {"resumo", "despesas", "receb", "outras"} <= concluidas:
                break
        return resultado

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        doc = fitz.open(str(caminho))
        try:
            secoes = self._paginas_por_secao(doc)
        finally:
            pass
        if not secoes:
            doc.close()
            dados.motivos_nao_cobertos = {k: "o PDF não tem as seções do balancete em texto (Resumo Financeiro, Demonstrativo, Recebimentos)"
                                          for k in ("receitas", "rendimentos", "lancamentos")}
            return dados

        self._contas(dados, [s for s in secoes if s[0] == "resumo"])
        achou_receb = self._receitas(dados, [s for s in secoes if s[0] == "receb"])
        achou_outras = self._outras_receitas(dados, [s for s in secoes if s[0] == "outras"])
        achou_desp = self._despesas(dados, [s for s in secoes if s[0] == "despesas"])
        doc.close()

        por_nome = {_norm(c.nome): c for c in dados.contas}
        for r in dados.receitas:
            if r.tipo == "rendimento" and _norm(r.conta) in por_nome:
                por_nome[_norm(r.conta)].rendimento += r.valor
        # transferência enviada a outra conta de balancete está no DÉBITO da conta no Resumo, mas não é despesa
        for nome, valor in getattr(self, "_transf_saida", {}).items():
            c = por_nome.get(nome)
            if c is not None and valor > 0.005:
                dados.avisos.append(f"o débito da conta {c.nome} no Resumo ({c.debitos:,.2f}) inclui transferência para outra conta de balancete "
                                    f"({valor:,.2f}); considerei só o gasto ({c.debitos - valor:,.2f}) para conferir os lançamentos"
                                    .replace(",", "X").replace(".", ",").replace("X", "."))
                c.debitos = round(c.debitos - valor, 2)
        # conferência: receitas lidas x créditos da conta (recibos negativos são linhas extras, já contidas nos subtotais)
        soma: dict[str, float] = {}
        for r in dados.receitas:
            if r.conta != "(recibo)":
                soma[_norm(r.conta)] = soma.get(_norm(r.conta), 0.0) + r.valor
        for c in dados.contas:
            s = soma.get(_norm(c.nome), 0.0)
            if abs(s - c.creditos) > 0.011:
                dados.avisos.append(f"receitas lidas da conta {c.nome} somam {s:,.2f}, mas os créditos da conta no Resumo são {c.creditos:,.2f}"
                                    .replace(",", "X").replace(".", ",").replace("X", "."))

        n_rend = sum(1 for c in dados.contas if c.rendimento > 0.005)
        dados.cobertura = {"receitas": achou_receb, "rendimentos": bool(dados.contas) and achou_receb and achou_outras and n_rend >= 2,
                           "lancamentos": achou_desp and len(dados.lancamentos) > 0}
        if not dados.cobertura["receitas"]:
            dados.motivos_nao_cobertos["receitas"] = "não encontrei o Relatório de Recebimentos neste PDF"
        if not dados.cobertura["rendimentos"]:
            dados.motivos_nao_cobertos["rendimentos"] = (
                "não encontrei o Resumo das Contas e/ou as Outras Receitas (rendimento) neste PDF" if not (dados.contas and achou_receb and achou_outras) else
                f"só {n_rend} conta com rendimento no mês ({', '.join(c.nome for c in dados.contas if c.rendimento > 0.005) or 'nenhuma'}; o condomínio "
                "não tem contas aplicadas — o rendimento é o 'RENDIMENTO/C/C' da conta corrente): não há outra conta para comparar a proporção do saldo")
        if not dados.cobertura["lancamentos"]:
            dados.motivos_nao_cobertos["lancamentos"] = "não encontrei o Demonstrativo de Despesas com itens neste PDF"
        return dados

    # ── Resumo financeiro: tabela de contas ──────────────────────────────────
    def _contas(self, dados: DadosRegras, secoes):
        for _, pag, linhas in secoes:
            dentro = False
            for l in linhas:
                t = _norm(l["texto"])
                if t.startswith("RESUMO DAS CONTAS DE BALANCETE"):
                    dentro = True
                    continue
                if not dentro:
                    continue
                nums = [(_num(w[4]), w) for w in l["w"] if _num(w[4]) is not None]
                nome = " ".join(w[4] for w in l["w"] if _num(w[4]) is None).strip()
                if len(nums) >= 4:
                    if not nome or _norm(nome).startswith("TOTAL"):
                        dentro = False if nome else dentro
                        continue
                    v = [n for n, _ in nums[-4:]]
                    dados.contas.append(ContaMes(nome=nome, saldo_anterior=v[0], creditos=v[1], debitos=abs(v[2]), saldo_atual=v[3], pagina=pag))
            if dados.contas:
                return

    # ── cabeçalho/rodapé de página ───────────────────────────────────────────
    @staticmethod
    def _ruido(t: str) -> bool:
        tn = _norm(t)
        return bool(tn.startswith(("ALLIZ ADMINISTRACAO", "FOLHA", "SOFTWARE")) or _RE_TITULO.match(t) or re.match(r"^\d{4}\s*-\s", t)
                    or re.match(r"^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}", t)
                    or re.match(r"^(JANEIRO|FEVEREIRO|MARCO|ABRIL|MAIO|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO|NOVEMBRO|DEZEMBRO) / \d{4}", tn)
                    or re.fullmatch(r"\d{1,3}", t))

    # ── 3.2 / 3.3 Relatório de recebimentos ──────────────────────────────────
    def _receitas(self, dados: DadosRegras, secoes) -> bool:
        """Receitas por conta = linhas do "RESUMO" no fim do relatório (período sem multa, com multa, atrasado,
        antecipado, acordos, multas, juros; valor com o sinal impresso; fecham com os créditos da conta).
        Além disso, cada recibo com valor negativo (3.2: histórico+valor; 3.3: valor/total) entra como linha própria —
        é assim que uma receita negativa escondida dentro de um subtotal positivo aparece."""
        if not secoes:
            return False
        em_resumo = False
        conta = None
        for _, pag, linhas in secoes:
            unidade = ""
            for l in linhas:
                t = l["texto"].strip()
                tn = _norm(t)
                if self._ruido(t) or tn.startswith("TOTAL DOS RECEBIMENTOS"):
                    continue
                if tn == "RESUMO":
                    em_resumo = True
                    conta = None
                    continue
                m = _RE_CONTA.match(t)
                if em_resumo:
                    pares = _pares(l, 150.0)
                    if m and not pares:
                        conta = m.group(2).strip()
                        continue
                    for desc, valor, bbox in pares:
                        dn = _norm(desc)
                        if not desc or dn.startswith("TOTAL"):
                            continue
                        tipo = "multa_juros" if dn in ("MULTAS", "JUROS E CORRECAO") else ("outra" if "ACORDO" in dn else "cota")
                        dados.receitas.append(LinhaReceita(conta=conta or "", descricao=desc, valor=valor, tipo=tipo, pagina=pag, bbox=bbox))
                    continue
                # antes do RESUMO: só procura recibos negativos
                if re.match(r"^[0-9A-Z]{4,8}\s*-\s*\S", t) and not _RE_CONTA.match(t):
                    unidade = t
                    continue
                if _RE_CONTA.match(t) and len(l["w"]) < 6:
                    continue
                ws = l["w"]
                if ws and re.fullmatch(r"\d{5,9}", ws[0][4]):
                    nums = [(w, _num(w[4])) for w in ws[1:] if _num(w[4]) is not None and w[0] >= 150.0]
                    if nums and nums[-1][1] < 0:
                        v = nums[-1][1]
                        hist = " ".join(w[4] for w in ws[1:] if _num(w[4]) is None).strip()
                        dados.receitas.append(LinhaReceita(
                            conta="(recibo)", descricao=f"recibo {ws[0][4]} {hist} — {unidade}".replace("  ", " ").strip(" —"), valor=v,
                            tipo="cota", pagina=pag, bbox=tuple(round(x, 1) for x in l["bbox"])))
        return True

    # ── 3.2 / 3.3 Outras receitas (rendimento / transferências) ──────────────
    def _outras_receitas(self, dados: DadosRegras, secoes) -> bool:
        """Rendimento (RENDIMENTO/C/C) e transferências entre contas de balancete. Guarda em `self._transf_saida`
        o que cada conta ENVIOU (isso está no débito dela no Resumo e não é despesa)."""
        self._transf_saida: dict[str, float] = {}
        if not secoes:
            return False
        linhas_todas = [(pag, l) for _, pag, ls in secoes for l in ls]
        # a conta das linhas sem cabeçalho de conta (layout 3.3) é a que o RESUMO final diz ter "Outras Receitas"
        conta_outras = None
        em_resumo = False
        c = None
        for pag, l in linhas_todas:
            t, tn = l["texto"].strip(), _norm(l["texto"])
            if tn == "RESUMO":
                em_resumo = True
                continue
            m = _RE_CONTA.match(t)
            if em_resumo and m and _valor_final(l, 150.0)[0] is None:
                c = m.group(2).strip()
            elif em_resumo and tn.startswith("OUTRAS RECEITAS") and c:
                conta_outras = c
        conta = conta_outras
        bloco = ""
        deb = cred = None
        for pag, l in linhas_todas:
            t, tn = l["texto"].strip(), _norm(l["texto"])
            if self._ruido(t):
                continue
            if tn.startswith("TOTAL DE OUTRAS RECEITAS") or tn == "RESUMO":
                break
            if tn == "TOTAL DA CONTA" or tn.startswith("TOTAL DA CONTA"):
                continue
            md = re.search(r"D[ÉE]BITO:\s*\d{3}\s*-\s*(.+?)(?=\s+CR[ÉE]DITO:|$)", t, re.IGNORECASE)
            mc = re.search(r"CR[ÉE]DITO:\s*\d{3}\s*-\s*(.+)$", t, re.IGNORECASE)
            if md or mc:
                if md:
                    deb = md.group(1).strip()
                if mc:
                    cred = mc.group(1).strip()
                continue
            valor, antes = _valor_final(l, 150.0)
            m = _RE_CONTA.match(t)
            if m and valor is None:
                conta, bloco = m.group(2).strip(), ""
                continue
            if valor is None:
                if len(l["w"]) == 1 and _num(l["w"][0][4]) is not None:
                    continue
                bloco = t
                continue
            descricao = " ".join(w[4] for w in antes).strip()
            eh_transf = "TRANSF" in _norm(bloco) or "TRANSF" in _norm(descricao)
            if not descricao:
                continue                              # subtotal do bloco (só o número)
            if eh_transf:
                destino = cred or conta or ""
                if valor < 0:
                    continue                          # perna de saída: é DÉBITO da conta que envia (Resumo), não receita
                if deb:
                    self._transf_saida[_norm(deb)] = self._transf_saida.get(_norm(deb), 0.0) + valor
                dados.receitas.append(LinhaReceita(conta=destino, descricao=f"{descricao or 'TRANSFERENCIAS'} (de {deb or '?'})", valor=valor,
                                                   tipo="transferencia", pagina=pag, bbox=tuple(round(x, 1) for x in l["bbox"])))
                deb = cred = None
                continue
            descricao = re.sub(r"^ALLIZ\s+", "", descricao)      # carimbo "ALLIZ" impresso por cima de algumas linhas
            tipo = "rendimento" if re.search(r"RENDIMENT|APLICA|CDB|POUPAN", _norm(descricao)) else "outra"
            dados.receitas.append(LinhaReceita(conta=conta or "", descricao=descricao, valor=valor, tipo=tipo, pagina=pag,
                                               bbox=tuple(round(x, 1) for x in l["bbox"])))
        return True

    # ── 2.x Demonstrativo de despesas ────────────────────────────────────────
    def _despesas(self, dados: DadosRegras, secoes) -> bool:
        """conta > grupo (linha de texto sem valor logo depois do total do grupo anterior ou do cabeçalho da conta) >
        itens. Um histórico longo quebra em 2 linhas com o valor NA SEGUNDA (confirmado em out/25-fev/26): as linhas
        sem valor dentro do grupo são o começo do próximo item. Total do grupo = linha só de números ("48,14 17.702,04")."""
        if not secoes:
            return False
        conta = None
        grupo = None
        espera_grupo = False
        pend: list[str] = []
        for _, pag, linhas in secoes:
            for l in linhas:
                t = l["texto"].strip()
                tn = _norm(t)
                if tn.startswith("TOTAL GERAL DAS DESPESAS"):
                    return True
                if self._ruido(t):
                    continue
                m = _RE_CONTA.match(t)
                valor, antes = _valor_final(l, 480.0)
                if m and valor is None and len(m.group(1)) == 3:
                    conta = m.group(2).strip()
                    grupo, espera_grupo, pend = None, True, []
                    continue
                if tn.startswith("TOTAL DA CONTA"):
                    grupo, espera_grupo, pend = None, False, []
                    continue
                palavras = [w[4] for w in l["w"]]
                if "%" in palavras or (len(palavras) >= 2 and all(_num(x) is not None for x in palavras)):
                    # total do grupo: o que sobrou sem valor é continuação do último item
                    if pend and dados.lancamentos:
                        dados.lancamentos[-1].descricao += " " + " ".join(pend)
                    grupo, espera_grupo, pend = None, True, []
                    continue
                if valor is None:
                    if len(palavras) == 1 and _num(palavras[0]) is not None:
                        continue
                    if espera_grupo or grupo is None:
                        grupo, espera_grupo, pend = t, False, []
                    else:
                        pend.append(t)
                    continue
                data = None
                if antes and re.fullmatch(r"\d{2}/\d{2}/\d{2,4}", antes[0][4]) and antes[0][0] < 90:
                    data = antes[0][4]
                    if len(data) == 8:
                        data = data[:6] + "20" + data[6:]
                    antes = antes[1:]
                descricao = " ".join(pend + [" ".join(w[4] for w in antes).strip()]).strip()
                pend = []
                if not descricao:
                    continue
                dados.lancamentos.append(LancamentoDespesa(
                    descricao=descricao, valor=valor, categoria=grupo or "SEM GRUPO", conta=conta or "ORDINARIA", data=data,
                    pagina=pag, bbox=tuple(round(x, 1) for x in l["bbox"])))
        return True
