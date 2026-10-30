"""
Extrator das regras gerais — Cinque Terre Residenza (Grupo Light / Habitacional).

Os meses em planilha (`prestacao_contas_N_AAAA.xlsx`) são lidos pelo extrator Habitacional. Em set/2026 o arquivo veio como PDF ESCANEADO de
5 páginas (impressão em imagem, sem texto) com as mesmas seções da planilha, mas só o resumo:

  Demonstrativo de Despesas    conta (centralizada) > grupo (PESSOAL, CONSUMOS...) > subgrupo > "Nº lancto. | Data | Histórico | Valor | Total";
                               o Total fecha o subgrupo no último lançamento; "TOTAL DA CONTA <grupo>" fecha o grupo; "TOTAL DA CONTA <conta>"
                               (margem esquerda) fecha a conta; "TOTAL DAS DESPESAS" fecha tudo
  Posição Financeira por conta Débito | Crédito: saldo anterior, receitas por rótulo (COTAS ATRASADAS, RENDIMENTO...), transferências, despesas
                               por grupo, TOTAIS, saldo atual
  Conciliação Bancária         saldo de C/C e aplicações (fecha com o total do Resumo)
  Resumo Financeiro Contábil   saldo anterior | créditos | débitos | saldo atual de cada conta (+ TOTAL)

NÃO traz o Demonstrativo de Receitas por unidade, o Resumo de Emissão (previsto x realizado), inadimplência nem comprovantes.

A leitura é por OCR POSICIONAL (ver `_ocr_posicional`: 5 leituras em resoluções diferentes, valor mais comum por coluna) e NADA é aceito às
cegas: cada número é conferido pelas somas que o próprio arquivo declara (subgrupo = Total; grupo, conta, total geral; Posição Financeira x
Resumo; Conciliação Bancária x Resumo). O que não fechar vira aviso ("OCR: ...").

Convenções iguais às do extrator Habitacional (para comparar com os meses em planilha): `categoria` = grupo (PESSOAL...), `conta` = nome do
Resumo; o débito da conta no Resumo inclui a TRANSFERÊNCIA ENTRE CONTAS enviada, que não é despesa — `debitos` é reduzido desse valor;
linha lançada a DÉBITO na Posição que não é grupo de despesa nem transferência (ex.: RESSARCIMENTO) é receita negativa.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.extratores import habitacional_xlsx as _hab
from conciliacao.regras_gerais.extratores._ocr_posicional import (DPI, DPI_TRIAGEM, DPIS_VOTO, _linhas, _norm, _ocr_palavras, gravar_pesquisavel, votar_valores)
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

MAX_PAGINAS = 30
_COL_VALOR_MAX = 0.76          # no Demonstrativo: número com canto direito antes disto = coluna Valor; depois = coluna Total
_COL_DEBITO_MAX = 0.88         # na Posição Financeira: antes disto = coluna Débito; depois = Crédito
_GAP_CONTINUACAO = 8.7         # linha de texto a menos de 8,7 pt da anterior (item) é continuação do histórico; a partir disso é cabeçalho
_RE_COD = re.compile(r"^\d{7,8}$")
_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RUIDO = ("DEMONSTRATIVO DE DESPESAS", "PERIODO", "PAGINA", "CONDOMINIO", "GRUPO", "ADMINISTRADORA", "NO LANCTO", "POSICAO FINANCEIRA")


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Extrator(_hab.Extrator):
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        caminho = Path(caminho)
        if caminho.suffix.lower() == ".pdf":
            import fitz

            doc = fitz.open(str(caminho))
            try:
                sem_texto = sum(len(doc[i].get_text().strip()) for i in range(min(len(doc), 5))) <= 200
                n = len(doc)
            finally:
                doc.close()
            if sem_texto:
                return self._extrair_ocr(caminho, mes, n)
        return super().extrair(caminho, mes)

    # ── PDF escaneado ────────────────────────────────────────────────────────────────────────────────────────
    def _extrair_ocr(self, caminho: Path, mes: str, n_paginas: int) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=caminho.name)
        indices = list(range(min(n_paginas, MAX_PAGINAS)))
        nao = {k: "OCR indisponível nesta máquina (tesseract/idioma 'por') — o PDF é uma impressão em imagem" for k in ("receitas", "rendimentos", "lancamentos")}
        principal = _ocr_palavras(caminho, indices, DPI)
        if not principal:
            dados.motivos_nao_cobertos = nao
            return dados
        outras = [_ocr_palavras(caminho, indices, d) for d in (DPI_TRIAGEM,) + DPIS_VOTO]
        d_ = fitz.open(str(caminho))
        try:
            larguras = {i: float(d_[i].rect.width) for i in indices}
        finally:
            d_.close()
        paginas = []
        for i in indices:
            ls = _linhas(principal.get(i, []))
            votar_valores(ls, [_linhas(o.get(i, [])) for o in outras], 0.30 * larguras[i])
            paginas.append((i + 1, larguras[i], ls))
        if not any("DEMONSTRATIVO DE DESPESAS" in _norm(l["texto"]) for _, _, ls in paginas for l in ls[:12]):
            dados.motivos_nao_cobertos = {k: "o PDF é uma impressão em imagem e não reconheci nele o Demonstrativo de Despesas / Posição Financeira"
                                          for k in ("receitas", "rendimentos", "lancamentos")}
            return dados

        resumo = self._ler_resumo(paginas)
        lanc, totais, grupos_por_conta = self._ler_despesas(paginas)
        pos = self._ler_posicao(paginas)
        banco = self._ler_conciliacao(paginas)
        self._montar(dados, resumo, lanc, totais, grupos_por_conta, pos, banco)
        gravar_pesquisavel(caminho, paginas)
        return dados

    @staticmethod
    def _valores(l: dict) -> list[float]:
        return [t[0] for t in l.get("_vs", [])]

    @staticmethod
    def _eh_ruido(l: dict) -> bool:
        tn = _norm(l["texto"])
        return tn.startswith(_RUIDO) or tn in ("", "C", "I") or len(tn) < 2

    # Resumo Financeiro Contábil: [(nome, ant, cred, deb, atual, pagina)], total
    def _ler_resumo(self, paginas) -> dict:
        em = False
        contas, total = [], None
        for pag, W, ls in paginas:
            for l in ls:
                tn = _norm(l["texto"])
                if tn.startswith("RESUMO FINANCEIRO CONTABIL"):
                    em = True
                    continue
                if not em:
                    continue
                v = self._valores(l)
                if len(v) < 4:
                    continue
                nome = " ".join(w["t"] for w in l["w"] if w["x0"] < min(t[2][0] for t in l["_vs"]) - 1).strip()
                if _norm(nome) == "TOTAL":
                    total = v[-4:]
                    continue
                if nome:
                    contas.append((nome, *v[-4:], pag))
        return {"contas": contas, "total": total}

    # Demonstrativo de Despesas
    def _ler_despesas(self, paginas):
        em = False
        conta = grupo = None
        # limite direito da coluna Histórico: o histórico só quebra em 2 linhas quando a 1ª chega perto dele
        lim = 0.0
        for _, _, ls_ in paginas:
            for l in ls_:
                ws_, v_ = l["w"], l.get("_vs", [])
                if len(ws_) >= 2 and _RE_COD.match(ws_[0]["t"]) and _RE_DATA.match(ws_[1]["t"]) and v_:
                    xv = min(t[2][0] for t in v_) - 1
                    lim = max(lim, max([w["x1"] for w in ws_[2:] if w["x1"] <= xv + 1] or [0.0]))
        pend = None                                  # último item (para continuação do histórico) e a altura da última linha dele
        sub: list = []                               # itens do subgrupo corrente (conferência com o Total)
        itens: list = []
        grupos: dict = {}                            # (conta, grupo) -> {"itens", "total", "pag"}
        totais: dict = {"conta": {}, "geral": None, "avisos": []}
        grupos_por_conta: dict = {}
        for pag, W, ls in paginas:
            pend = None
            for l in ls:
                tn = _norm(l["texto"])
                if tn.startswith("DEMONSTRATIVO DE DESPESAS") and not em:
                    em = True
                    continue
                if not em or self._eh_ruido(l):
                    continue
                v = l.get("_vs", [])
                x0 = l["x0"]
                if tn.startswith("TOTAL DAS DESPESAS"):
                    totais["geral"] = v[-1][0] if v else None
                    em = False
                    continue
                if tn.startswith("TOTAL DA CONTA"):
                    if v:
                        if x0 < 90:                                        # margem esquerda = total da CONTA
                            totais["conta"][conta] = abs(v[-1][0])
                            conta, grupo, sub = None, None, []
                        elif (conta, grupo) in grupos:
                            grupos[(conta, grupo)]["total"] = abs(v[-1][0])
                        sub = []
                    pend = None
                    continue
                if not v and x0 > 200 and not re.search(r"\d", tn):          # nome da conta, centralizado
                    conta = self._canon(tn) or l["texto"].strip()
                    grupo, sub, pend = None, [], None
                    continue
                if not v and 95 <= x0 <= 125 and not re.search(r"\d", tn):    # grupo
                    grupo = l["texto"].strip()
                    grupos.setdefault((conta, grupo), {"itens": [], "total": None, "pag": pag})
                    grupos_por_conta.setdefault(conta, set()).add(_norm(grupo))
                    sub, pend = [], None
                    continue
                ws = l["w"]
                if len(ws) >= 2 and _RE_COD.match(ws[0]["t"]) and _RE_DATA.match(ws[1]["t"]) and v:
                    x_val = min(t[2][0] for t in v) - 1
                    desc = " ".join(w["t"] for w in ws[2:] if w["x1"] <= x_val + 1)
                    item = {"cod": ws[0]["t"], "data": ws[1]["t"], "desc": desc, "valor": abs(v[0][0]), "pag": pag,
                            "bbox": [l["x0"], l["top"], l["x1"], l["bottom"]], "yc": l["yc"],
                            "x1d": max([w["x1"] for w in ws[2:] if w["x1"] <= x_val + 1] or [0.0])}
                    total = abs(v[1][0]) if len(v) > 1 else None
                elif not _RE_COD.match(ws[0]["t"]) and v and x0 >= 140 and len(v) == 2:
                    # item sem nº/data (ex.: "TARIFAS BANCARIAS 733,49 733,49")
                    x_val = min(t[2][0] for t in v) - 1
                    item = {"cod": None, "data": None, "desc": " ".join(w["t"] for w in ws if w["x1"] <= x_val + 1), "valor": abs(v[0][0]), "pag": pag,
                            "bbox": [l["x0"], l["top"], l["x1"], l["bottom"]], "yc": l["yc"],
                            "x1d": max([w["x1"] for w in ws if w["x1"] <= x_val + 1] or [0.0])}
                    total = abs(v[1][0])
                else:
                    item = None
                if item is not None:
                    if conta is None or grupo is None:
                        totais["avisos"].append(f"OCR: lançamento {item['cod']} (página {pag}) sem conta/grupo identificado")
                        continue
                    grupos[(conta, grupo)]["itens"].append(item)
                    sub.append(item["valor"])
                    pend = item
                    if total is not None:
                        if abs(sum(sub) - total) > 0.011:
                            totais["avisos"].append(f"OCR: itens do subgrupo que termina em '{item['desc'][:40]}' (página {pag}) somam {_fmt(sum(sub))}, mas o Total impresso é {_fmt(total)}")
                        sub = []
                    continue
                # continuação do histórico: perto da linha anterior E (tem dígito — NF, data, parcela — OU a linha anterior chegou ao limite da coluna);
                # um nome de subgrupo (MANUT.BOMBAS...) também fica a ~8 pt, mas não tem dígito e vem depois de uma linha que não encheu a coluna
                if (not v and pend is not None and x0 >= 140 and l["yc"] - pend["yc"] <= _GAP_CONTINUACAO
                        and (re.search(r"\d", l["texto"]) or pend["x1d"] >= lim - 45)):
                    pend["desc"] = (pend["desc"] + " " + l["texto"].strip()).strip()   # continuação do histórico
                    pend["x1d"] = max(l["x1"] - 0.0, 0.0) if l["x1"] < lim + 20 else pend["x1d"]
                    pend["yc"] = l["yc"]
                    pend["bbox"][3] = max(pend["bbox"][3], l["bottom"])
                    pend["bbox"][2] = max(pend["bbox"][2], l["x1"])
                    continue
                if not v:                                                  # cabeçalho de subgrupo
                    pend = None
        return grupos, totais, grupos_por_conta

    @staticmethod
    def _canon(tn: str) -> str | None:
        return tn or None

    # Posição Financeira por conta + Conciliação Bancária
    def _ler_posicao(self, paginas) -> dict:
        em = False
        conta = None
        pos: dict = {}
        for pag, W, ls in paginas:
            for l in ls:
                tn = _norm(l["texto"])
                if tn.startswith("TOTAL DAS DESPESAS"):
                    em = True
                    continue
                if not em:
                    continue
                if tn.startswith(("CONCILIACAO BANCARIA", "RESUMO FINANCEIRO")):
                    conta = None
                    continue
                v = l.get("_vs", [])
                if not v and l["x0"] > 200 and not re.search(r"\d", tn) and not tn.startswith(("POSICAO", "SALDO")):
                    if l["texto"].strip() == conta:               # o bloco da conta atravessa a página: o cabeçalho se repete no topo da seguinte
                        continue
                    conta = l["texto"].strip()
                    pos[conta] = {"linhas": [], "ant": None, "atual": None, "totais": None, "pag": pag}
                    continue
                if conta is None or not v or self._eh_ruido(l):
                    continue
                p = pos[conta]
                if tn.startswith("TOTAIS"):
                    p["totais"] = (v[0][0], v[1][0]) if len(v) >= 2 else (0.0, v[0][0])
                    continue
                x_ini = min(t[2][0] for t in v) - 1
                rotulo = " ".join(w["t"] for w in l["w"] if w["x1"] <= x_ini + 1).strip()
                rn = _norm(rotulo)
                if rn.startswith("SALDO ANTERIOR"):
                    p["ant"] = -abs(v[-1][0]) if "DEVEDOR" in rn else abs(v[-1][0]) if v[-1][0] >= 0 else v[-1][0]
                    continue
                if rn.startswith("SALDO ATUAL"):
                    p["atual"] = -abs(v[-1][0]) if "DEVEDOR" in rn else v[-1][0]
                    continue
                for val, x1, bb in v:
                    debito = x1 < _COL_DEBITO_MAX * W
                    p["linhas"].append((rotulo, abs(val) if debito else val, debito, pag, (l["x0"], l["top"], l["x1"], l["bottom"])))
        return pos

    def _ler_conciliacao(self, paginas) -> dict:
        em = False
        out = {"linhas": [], "total": None}
        for pag, W, ls in paginas:
            for l in ls:
                tn = _norm(l["texto"])
                if tn.startswith("CONCILIACAO BANCARIA"):
                    em = True
                    continue
                if tn.startswith("RESUMO FINANCEIRO"):
                    em = False
                if not em or not l.get("_vs"):
                    continue
                if tn.startswith("VALOR TOTAL"):
                    out["total"] = l["_vs"][-1][0]
                else:
                    out["linhas"].append((l["texto"], l["_vs"][-1][0]))
        return out

    # junta tudo no modelo, conferindo as somas
    def _montar(self, dados: DadosRegras, resumo: dict, grupos: dict, totais: dict, grupos_por_conta: dict, pos: dict, banco: dict):
        av = dados.avisos
        av.append("PDF escaneado (impressão em imagem) de 5 páginas: números lidos por OCR e conferidos pelas somas do próprio arquivo; "
                  "não traz o Demonstrativo de Receitas por unidade, o Resumo de Emissão (previsto x realizado), a inadimplência nem comprovantes")
        av.extend(totais["avisos"])
        nomes = [c[0] for c in resumo["contas"]]

        def _casar(nome: str) -> str | None:
            return _hab._casar_conta(nome, nomes) or next((n for n in nomes if _norm(n) == _norm(nome)), None)

        contas = {n: ContaMes(nome=n, saldo_anterior=a, creditos=c, debitos=d, saldo_atual=s, pagina=pag) for n, a, c, d, s, pag in resumo["contas"]}
        # o OCR escreve o mesmo fornecedor de dois jeitos no mesmo arquivo ("ANDRA SA" / "ANDRASA"): une pela grafia mais comum, para a série de
        # parcelas e o histórico de fornecedores não se partirem
        def _fornecedor(desc: str) -> str:
            return re.split(r"\s+-\s+NF|\s+-\s+|\.\s", desc, maxsplit=1)[0].strip()

        grafias: dict[str, dict[str, int]] = {}
        for g in grupos.values():
            for i in g["itens"]:
                f = _fornecedor(i["desc"])
                if len(f) >= 6:
                    grafias.setdefault(re.sub(r"[^A-Z0-9]", "", _norm(f)), {}).setdefault(f, 0)
                    grafias[re.sub(r"[^A-Z0-9]", "", _norm(f))][f] += 1
        for g in grupos.values():
            for i in g["itens"]:
                f = _fornecedor(i["desc"])
                cand = grafias.get(re.sub(r"[^A-Z0-9]", "", _norm(f)))
                if f and cand and len(cand) > 1:
                    i["desc"] = i["desc"].replace(f, max(cand, key=cand.get), 1)
        # lançamentos
        por_conta_desp: dict[str, float] = {}
        for (cta_raw, grp), g in grupos.items():
            cta = _casar(cta_raw) or cta_raw
            s = round(sum(i["valor"] for i in g["itens"]), 2)
            if g["total"] is not None and abs(s - g["total"]) > 0.011:
                av.append(f"OCR: itens do grupo {grp} ({cta}) somam {_fmt(s)}, mas o total impresso é {_fmt(g['total'])} (página {g['pag']})")
            por_conta_desp[cta] = round(por_conta_desp.get(cta, 0.0) + s, 2)
            for i in g["itens"]:
                dados.lancamentos.append(LancamentoDespesa(
                    descricao=re.sub(r"\s+", " ", i["desc"]).strip(), valor=i["valor"], categoria=grp, conta=cta, codigo=i["cod"], data=i["data"],
                    pagina=i["pag"], local=f"OCR, página {i['pag']}", bbox=tuple(round(x, 1) for x in i["bbox"])))
        for cta_raw, t in totais["conta"].items():
            cta = _casar(cta_raw) or cta_raw
            if abs(por_conta_desp.get(cta, 0.0) - t) > 0.011:
                av.append(f"OCR: despesas da conta {cta} somam {_fmt(por_conta_desp.get(cta, 0.0))}, mas o TOTAL DA CONTA impresso é {_fmt(t)}")
        if totais["geral"] is not None and abs(sum(por_conta_desp.values()) - totais["geral"]) > 0.011:
            av.append(f"OCR: despesas lidas somam {_fmt(sum(por_conta_desp.values()))}, mas o TOTAL DAS DESPESAS impresso é {_fmt(totais['geral'])}")
        grupos_norm = {_casar(c) or c: g for c, g in grupos_por_conta.items()}

        # Posição Financeira -> receitas
        transf_saida: dict[str, float] = {}
        for cta_raw, p in pos.items():
            cta = _casar(cta_raw) or cta_raw
            c = contas.get(cta)
            if c is None:
                av.append(f"OCR: a conta '{cta_raw}' da Posição Financeira não está no Resumo Financeiro Contábil")
                continue
            cred = deb = 0.0
            for rotulo, val, debito, pag, bb in p["linhas"]:
                rn = _norm(rotulo)
                eh_transf = bool(_hab._RE_TRANSF.search(rn))
                if debito:
                    deb += val
                    if eh_transf:
                        transf_saida[cta] = round(transf_saida.get(cta, 0.0) + val, 2)
                    elif rn in grupos_norm.get(cta, set()):
                        pass                                              # grupo de despesa (total do grupo na Posição)
                    else:                                                 # débito que não é despesa nem transferência: receita negativa
                        dados.receitas.append(LinhaReceita(conta=cta, descricao=f"{rotulo} (estorno/desconto lançado a débito)", valor=-val,
                                                           tipo=_hab._tipo_receita(rotulo, cta), pagina=pag, bbox=tuple(round(x, 1) for x in bb)))
                else:
                    cred += val
                    dados.receitas.append(LinhaReceita(conta=cta, descricao=rotulo, valor=val, tipo="transferencia" if eh_transf else _hab._tipo_receita(rotulo, cta),
                                                       pagina=pag, bbox=tuple(round(x, 1) for x in bb)))
            # conferências: Posição x Resumo
            if p["ant"] is not None and abs(p["ant"] - c.saldo_anterior) > 0.011:
                av.append(f"OCR: saldo anterior da conta {cta} na Posição Financeira ({_fmt(p['ant'])}) difere do Resumo ({_fmt(c.saldo_anterior)})")
            if p["atual"] is not None and abs(p["atual"] - c.saldo_atual) > 0.011:
                av.append(f"OCR: saldo atual da conta {cta} na Posição Financeira ({_fmt(p['atual'])}) difere do Resumo ({_fmt(c.saldo_atual)})")
            esperado = round((p["ant"] or 0.0) + cred - deb, 2)
            if p["atual"] is not None and abs(esperado - p["atual"]) > 0.011:
                av.append(f"OCR: na conta {cta}, saldo anterior + créditos - débitos da Posição Financeira ({_fmt(esperado)}) não fecha com o saldo atual ({_fmt(p['atual'])})")
            if p["totais"] is not None and (abs(p["totais"][0] - deb) > 0.011 or abs(p["totais"][1] - cred - (p["ant"] or 0.0)) > 0.011):
                av.append(f"OCR: TOTAIS da Posição Financeira da conta {cta} ({_fmt(p['totais'][0])} / {_fmt(p['totais'][1])}) não fecham com as linhas lidas "
                          f"({_fmt(deb)} / {_fmt(cred + (p['ant'] or 0.0))})")
            itens = [r for r in dados.receitas if r.conta == cta]
            if len(itens) == 1 and _norm(itens[0].descricao).startswith("RECEBIMENTOS"):
                c.rendimento_nao_informado = True                         # recebimentos não discriminados: não dá para dizer se houve rendimento
                av.append(f"a conta {cta} traz os recebimentos em uma linha só: não é possível ver se houve rendimento no mês")
        # contas
        for c in contas.values():
            c.rendimento = round(sum(r.valor for r in dados.receitas if r.conta == c.nome and r.tipo == "rendimento"), 2)
            if transf_saida.get(c.nome):
                c.debitos = round(c.debitos - transf_saida[c.nome], 2)
                av.append(f"conta {c.nome}: o débito do Resumo inclui R$ {_fmt(transf_saida[c.nome])} de transferência entre contas, que não é despesa do "
                          f"Demonstrativo; 'debitos' reduzido desse valor para a conferência dos lançamentos")
        dados.contas = list(contas.values())
        if resumo["total"] is not None:
            soma = [round(sum(getattr(c, k) for c in contas.values()), 2) for k in ("saldo_anterior", "creditos", "debitos", "saldo_atual")]
            debt = round(sum(r[3] for r in resumo["contas"]), 2)
            if abs(debt - resumo["total"][2]) > 0.011 or abs(soma[0] - resumo["total"][0]) > 0.011 or abs(soma[3] - resumo["total"][3]) > 0.011:
                av.append(f"OCR: o TOTAL do Resumo Financeiro ({' / '.join(_fmt(x) for x in resumo['total'])}) não fecha com a soma das contas lidas")
        if banco["total"] is not None and resumo["total"] is not None:
            soma_b = round(sum(v for _, v in banco["linhas"]), 2)
            if abs(soma_b - banco["total"]) > 0.011 or abs(banco["total"] - resumo["total"][3]) > 0.011:
                av.append(f"OCR: a Conciliação Bancária ({_fmt(banco['total'])}; linhas somam {_fmt(soma_b)}) não fecha com o saldo atual do Resumo ({_fmt(resumo['total'][3])})")

        achou_pos = bool(pos)
        dados.cobertura = {"receitas": achou_pos and bool(contas), "rendimentos": achou_pos and bool(contas), "lancamentos": bool(dados.lancamentos)}
        if not achou_pos:
            dados.motivos_nao_cobertos["receitas"] = dados.motivos_nao_cobertos["rendimentos"] = "não li a Posição Financeira por conta no PDF escaneado"
        if not dados.lancamentos:
            dados.motivos_nao_cobertos["lancamentos"] = "não li o Demonstrativo de Despesas no PDF escaneado"
