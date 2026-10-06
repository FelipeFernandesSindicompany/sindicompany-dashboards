"""
Extrator das regras gerais — DataDigitus "Balancete consolidado" (empresa `datadigitus_pdf`: Cap D'Antibes, Maison du Rhône).

(Serra da Mantiqueira está cadastrada com esta empresa mas o PDF dela é FL Condomínios/Consvicta — formato diferente, de outro
extrator: aqui ela devolve "não coberto" com o motivo.)

PDF impresso do navegador ("Print Preview"), paisagem, com camada de texto. Seções, em ordem:

  Resumo Financeiro Contábil     CONTA | Saldo Anterior | Créditos | Débitos | Saldo Atual (uma linha por conta; TOTAL GERAL)
  Demonstrativo de Despesas      "NNN - CONTA X" > grupo (TERCEIRIZACAO, SALARIOS...) > linhas "data | histórico | valor";
                                 o subtotal do grupo (Maison: "14.519,30  23,50%") fecha cada grupo; "TOTAL DA CONTA X" fecha a conta
  Demonstrativo de Receitas      (Maison) por recibo: "Data Unidade Recibo Vcto | Plano Histórico Valor" — uma linha por plano
                                 (001 CONDOMINIO, 002 FUNDO DE RESERVA, 006 PROVISAO 13 SAL/FERIAS, 070 PARCELA...) + MULTAS, JUROS,
                                 + "OUTRAS RECEITAS" (LUCRO APLICAÇÃO por plano de aplicação) ... "TOTAL DAS RECEITAS"
  Demonstrativo Financeiro por Conta  (Cap D'Antibes) por conta: "Posição Financeira" com Débito/Crédito: Da emissão do período,
                                 De condôminos em atraso, Antecipações, Multas, Juros e Correção, Outras Receitas (= rendimento
                                 nas contas de aplicação), Despesas do Período
  Relatório de Pendências        (Maison; ignorado)

Particularidades confirmadas nos arquivos reais:
  * a conta do Maison "006 - PROV.13O SAL/FERIAS" não tem a palavra CONTA no cabeçalho (nem no Resumo: "PROV.13O SAL/FERIAS");
  * o subtotal do grupo no Maison vem com "%" na mesma linha ("14.519,30 23,50%") — o valor do subtotal NÃO é lançamento;
  * Cap D'Antibes: a conta OBRAS ("002 - CONTA OBRAS") e a "054 - CONTA I.P.T.U." têm Demonstrativo próprio (subcontas SERVIÇOS PRESTADOS /
    IMPOSTOS E TAXAS dentro delas); "TOTAL GERAL DAS DESPESAS" soma TODAS as contas; os débitos do Resumo fecham com cada conta;
  * o histórico longo quebra em 2 linhas e a data/valor ficam CENTRALIZADOS na célula (a linha da data cai entre as duas linhas
    do histórico) — cada linha de texto sem data é associada à data MAIS PRÓXIMA (≤ 1,15 da altura de uma palavra) e as demais linhas
    sem data são cabeçalhos de grupo;
  * Cap D'Antibes: os PDFs de abr/2025 a mar/2026 são IMPRESSÃO EM IMAGEM (sem camada de texto: 0 caracteres em todas as páginas);
    só abr-jul/2026 têm texto. Os de imagem NÃO são lidos (OCR erra vírgulas — "104,41" virou "10441" — e confunde os cabeçalhos
    de grupo em fundo cinza, então não fecharia com o Resumo): cobertura False com o motivo.
"""
import re
import statistics
from pathlib import Path

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_RE_VALOR = re.compile(r"^\(?-?\d{1,3}(?:\.\d{3})*,\d{2}\)?-?$")
_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_CONTA_HDR = re.compile(r"^(\d{3})\s*-\s*(.+)$")


def _num(s: str):
    s = (s or "").strip()
    if not _RE_VALOR.match(s):
        return None
    neg = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
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
        l["yc"] = sum((w[1] + w[3]) / 2 for w in l["w"]) / len(l["w"])
        l["texto"] = " ".join(w[4] for w in l["w"])
        l["bbox"] = (round(min(w[0] for w in l["w"]), 1), round(min(w[1] for w in l["w"]), 1),
                     round(max(w[2] for w in l["w"]), 1), round(max(w[3] for w in l["w"]), 1))
    return linhas


def _ruido_pagina(l: dict) -> bool:
    t = l["texto"]
    return bool(re.match(r"^\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2}", t) or "Print Preview" in t or t.startswith("about:blank")
                or re.fullmatch(r"\d+/\d+", t) or "Software DataDigitus" in t or re.match(r"^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}", t))


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    # ── entrada ──────────────────────────────────────────────────────────────
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        doc = fitz.open(str(caminho))
        try:
            paginas = []
            for i in range(len(doc)):
                paginas.append((i + 1, doc[i].rect.width, _linhas(doc[i])))
        finally:
            doc.close()
        total_linhas = sum(len(p[2]) for p in paginas)
        if total_linhas < 20:
            motivo = ("o PDF deste mês é uma impressão em imagem (sem camada de texto) — o OCR não é confiável para somas em R$ "
                      "(vírgulas e cabeçalhos de grupo errados) e não fecharia com o Resumo Financeiro")
            dados.motivos_nao_cobertos = {k: motivo for k in ("receitas", "rendimentos", "lancamentos")}
            dados.avisos.append("PDF sem texto (impressão em imagem): regras gerais não verificadas neste mês")
            return dados
        texto_all = " ".join(l["texto"] for _, _, ls in paginas for l in ls[:40])
        if "DataDigitus" not in " ".join(l["texto"] for _, _, ls in paginas for l in ls) and "Resumo Financeiro Contábil" not in texto_all:
            motivo = ("este PDF não é o 'Balancete consolidado' DataDigitus (sem Resumo Financeiro Contábil / Demonstrativo de Despesas); "
                      "o formato é outro (ex.: Serra da Mantiqueira = FL Condomínios/Consvicta) e precisa de extrator próprio")
            dados.motivos_nao_cobertos = {k: motivo for k in ("receitas", "rendimentos", "lancamentos")}
            return dados

        self._resumo(dados, paginas)
        achou_desp = self._despesas(dados, paginas)
        self._falta_debito = self._debitos_sem_lancamento(dados) if achou_desp else {}
        achou_rec = self._receitas_maison(dados, paginas)
        achou_pos = self._posicao_financeira(dados, paginas)
        if achou_desp:
            self._transferencias(dados)
        self._rendimentos_e_conferencias(dados, achou_rec, achou_pos)

        dados.cobertura = {"receitas": bool(achou_rec or achou_pos), "rendimentos": bool(dados.contas) and bool(achou_rec or achou_pos),
                           "lancamentos": achou_desp and bool(dados.lancamentos)}
        if not dados.cobertura["receitas"]:
            dados.motivos_nao_cobertos["receitas"] = "o PDF não traz o Demonstrativo de Receitas nem a Posição Financeira por conta"
        if not dados.cobertura["rendimentos"]:
            dados.motivos_nao_cobertos["rendimentos"] = "não consegui ler as contas (Resumo Financeiro Contábil) ou as receitas por conta"
        if not dados.cobertura["lancamentos"]:
            dados.motivos_nao_cobertos["lancamentos"] = "o PDF não traz o Demonstrativo de Despesas com lançamentos"
        return dados

    # ── Resumo Financeiro Contábil ───────────────────────────────────────────
    def _resumo(self, dados: DadosRegras, paginas):
        secao = []                               # linhas (com a largura da página) do Resumo, em ordem
        dentro = False
        for pag, W, linhas in paginas:
            for l in linhas:
                if _ruido_pagina(l):
                    continue
                tn = _norm(l["texto"])
                if tn.startswith("RESUMO FINANCEIRO CONTABIL"):
                    dentro = True
                    continue
                if dentro and tn.startswith("DEMONSTRATIVO"):
                    dentro = False
                if dentro:
                    secao.append((pag, W, l))
            if secao and not dentro:
                break
        for i, (pag, W, l) in enumerate(secao):
            ws = l["w"]
            nums = [w for w in ws if _num(w[4]) is not None and w[0] > 0.30 * W]
            nome = " ".join(w[4] for w in ws if _num(w[4]) is None).strip()
            if len(nums) < 4:
                continue
            if not nome:
                # nome longo quebrado em 2 linhas: a linha de números fica no meio (centralizada) e o texto, acima e abaixo
                partes = []
                for j in (i - 1, i + 1):
                    if 0 <= j < len(secao):
                        pl = secao[j][2]
                        if abs(pl["yc"] - l["yc"]) <= 12 and not any(_num(w[4]) is not None and w[0] > 0.30 * W for w in pl["w"])                                 and not _norm(pl["texto"]).startswith(("CONTA SALDO", "TOTAL")):
                            partes.append((pl["yc"], pl["texto"].strip()))
                nome = " ".join(t for _, t in sorted(partes)).strip()
            if _norm(nome).startswith("TOTAL GERAL"):
                break
            if not nome or re.fullmatch(r"CONTA", nome.upper()):
                continue
            v = [_num(w[4]) for w in nums[-4:]]
            dados.contas.append(ContaMes(nome=nome, saldo_anterior=v[0], creditos=v[1], debitos=abs(v[2]), saldo_atual=v[3], pagina=pag))

    # ── Demonstrativo de Despesas ────────────────────────────────────────────
    def _despesas(self, dados: DadosRegras, paginas) -> bool:
        em_desp = False
        conta = None
        grupo = None
        achou = False
        for pag, W, linhas in paginas:
            linhas = [l for l in linhas if not _ruido_pagina(l)]
            # a) classifica palavras
            for l in linhas:
                ws = l["w"]
                l["datas"] = [w for w in ws if w[0] < 0.13 * W and _RE_DATA.match(w[4])]
                l["valores"] = [w for w in ws if w[0] >= 0.74 * W and _num(w[4]) is not None]
                l["hist"] = [w for w in ws if w not in l["datas"] and w not in l["valores"] and 0.13 * W <= w[0] < 0.74 * W]
                l["pct"] = [w for w in ws if w[4].endswith("%")]
            # b) limiar de "mesma célula": a data/valor ficam centralizados e as linhas de texto da célula ficam a ~0,5 altura
            #    de palavra dela; cabeçalho de grupo e subtotal ficam a >= 1,5 altura da linha de data mais próxima
            alturas = [w[3] - w[1] for l in linhas for w in l["w"] if re.search(r"\d|[A-Za-z]", w[4])]
            h = statistics.median(alturas) if alturas else 10.0
            limiar = 1.15 * h
            # c) associa linhas de texto sem data à data mais próxima
            celulas = {id(l): {"linhas": [l], "tem_data": True} for l in linhas if l["datas"]}
            avulsas = []
            for l in linhas:
                if l["datas"]:
                    continue
                if l["hist"] or l["valores"]:
                    prox = min((d for d in linhas if d["datas"]), key=lambda d: abs(d["yc"] - l["yc"]), default=None)
                    if prox is not None and abs(prox["yc"] - l["yc"]) <= limiar:
                        celulas[id(prox)]["linhas"].append(l)
                        continue
                avulsas.append(l)
            # d) percorre em ordem vertical
            eventos = sorted([(c["linhas"][0]["yc"], "cel", c) for c in celulas.values()] + [(a["yc"], "av", a) for a in avulsas], key=lambda e: e[0])
            for _, tipo, obj in eventos:
                if tipo == "av":
                    l = obj
                    t = l["texto"].strip()
                    tn = _norm(t)
                    if tn.startswith("DEMONSTRATIVO DE DESPESAS"):
                        em_desp, conta, grupo = True, None, None
                        achou = True
                        continue
                    if tn.startswith("DEMONSTRATIVO") or tn.startswith("RELATORIO DE PENDENCIAS") or tn.startswith("RESUMO FINANCEIRO"):
                        em_desp = False
                        continue
                    if not em_desp:
                        continue
                    if tn.startswith("TOTAL GERAL DAS DESPESAS"):
                        em_desp = False
                        continue
                    m = _RE_CONTA_HDR.match(t)
                    if m and not l["valores"]:
                        conta = m.group(2).strip()
                        grupo = None
                        continue
                    if tn.startswith("TOTAL DA CONTA") or tn.startswith("DATA HISTORICO VALOR") or tn.startswith("PERIODO DE"):
                        grupo = None if tn.startswith("TOTAL DA CONTA") else grupo
                        continue
                    if l["valores"] and not l["hist"]:
                        grupo = None                   # subtotal do grupo (Cap: só o valor; Maison: valor + "xx,xx%")
                        continue
                    if l["hist"] and not l["valores"]:
                        grupo = " ".join(w[4] for w in l["hist"]).strip()      # cabeçalho de grupo
                    continue
                # célula com data = lançamento
                if not em_desp:
                    continue
                c = obj
                ls = sorted(c["linhas"], key=lambda x: x["yc"])
                dl = next(x for x in ls if x["datas"])
                valores = [w for x in ls for w in x["valores"]]
                if not valores:
                    continue
                valor = _num(valores[-1][4])
                texto = " ".join(" ".join(w[4] for w in x["hist"]) for x in ls).strip()
                bb = (min(x["bbox"][0] for x in ls), min(x["bbox"][1] for x in ls), max(x["bbox"][2] for x in ls), max(x["bbox"][3] for x in ls))
                dados.lancamentos.append(LancamentoDespesa(
                    descricao=texto, valor=valor, categoria=grupo or "SEM GRUPO", conta=conta or "", data=dl["datas"][0][4],
                    pagina=pag, bbox=tuple(round(v, 1) for v in bb)))
        return achou

    # ── Demonstrativo de Receitas (Maison) ───────────────────────────────────
    def _receitas_maison(self, dados: DadosRegras, paginas) -> bool:
        em_rec = False
        achou = False
        linhas_plano: list = []
        for pag, W, linhas in paginas:
            for l in linhas:
                if _ruido_pagina(l):
                    continue
                t = l["texto"].strip()
                tn = _norm(t)
                if tn.startswith("DEMONSTRATIVO DE RECEITAS"):
                    em_rec, achou = True, True
                    continue
                if not em_rec:
                    continue
                if tn.startswith("TOTAL DAS RECEITAS"):
                    em_rec = False
                    continue
                ws = l["w"]
                vals = [w for w in ws if w[0] >= 0.74 * W and _num(w[4]) is not None]
                if not vals:
                    continue
                cod = next((w for w in ws if re.fullmatch(r"\d{3}", w[4]) and 150 <= w[0] < 0.6 * W), None)
                if cod is None:
                    continue                           # total do recibo / subtotal da seção (só o número)
                hist = " ".join(w[4] for w in ws if w[0] > cod[0] and w not in vals).strip()
                data = next((w[4] for w in ws if _RE_DATA.match(w[4]) and w[0] < 100), None)
                linhas_plano.append((cod[4], hist, _num(vals[-1][4]), data, pag, l["bbox"]))
        if not achou:
            return False
        # plano -> conta: pelo valor (a soma de cada plano fecha com os créditos de exatamente uma conta) e, se não der, pelo nome
        soma_plano: dict[str, float] = {}
        for cod, _, v, *_ in linhas_plano:
            soma_plano[cod] = round(soma_plano.get(cod, 0.0) + v, 2)
        mapa: dict[str, str] = {}
        usadas: set[str] = set()
        for cod, s in soma_plano.items():
            cand = [c.nome for c in dados.contas if abs(c.creditos - s) < 0.011 and c.nome not in usadas]
            if len(cand) == 1:
                mapa[cod] = cand[0]
                usadas.add(cand[0])
        # conta de aplicação cujo crédito = rendimento + transferência recebida (o débito sem lançamento de outra conta)
        transf = list(getattr(self, "_falta_debito", {}).values())
        for cod, s_ in soma_plano.items():
            if cod in mapa:
                continue
            cand = [c.nome for c in dados.contas if c.nome not in usadas and any(abs((c.creditos - s_) - t) < 0.011 for t in transf)]
            if len(cand) == 1:
                mapa[cod] = cand[0]
                usadas.add(cand[0])
        for cod in soma_plano:
            if cod in mapa:
                continue
            hist = next((h for c, h, *_ in linhas_plano if c == cod), "")
            dicas = [("CONDOMINIO", "ORDIN"), ("FUNDO DE RESERVA", "FUNDO DE RESERVA"), ("PROVISAO", "PROV"), ("SEGURANCA", "SEGURANCA")]
            for chave, parte in dicas:
                if chave in _norm(hist):
                    cand = [c.nome for c in dados.contas if parte in _norm(c.nome) and "APLICA" not in _norm(c.nome) and c.nome not in usadas]
                    if len(cand) == 1:
                        mapa[cod] = cand[0]
                        usadas.add(cand[0])
                        break
        for cod, hist, v, data, pag, bb in linhas_plano:
            h = _norm(hist)
            if re.search(r"LUCRO|RENDIMENT|APLICA", h):
                tipo = "rendimento"
            elif "MULTA" in h or "JUROS" in h:
                tipo = "multa_juros"
            elif re.search(r"CONDOMINIO|FUNDO DE RESERVA|PROVISAO|PARCELA", h):
                tipo = "cota"
            else:
                tipo = "outra"
            dados.receitas.append(LinhaReceita(conta=mapa.get(cod, f"plano {cod}"), descricao=f"{cod} {hist}".strip(), valor=v, tipo=tipo,
                                               data=data, pagina=pag, bbox=tuple(round(x, 1) for x in bb)))
        sem = [c for c in soma_plano if c not in mapa]
        if sem:
            dados.avisos.append("não consegui ligar o(s) plano(s) " + ", ".join(sem) + " a uma conta do Resumo; receitas dele(s) ficaram como 'plano NNN'")
        return True

    # ── transferências entre contas (débito sem lançamento -> crédito sem receita) ──
    @staticmethod
    def _debitos_sem_lancamento(dados: DadosRegras) -> dict:
        """{conta_norm: valor}: parte do débito da conta no Resumo que não é lançamento do Demonstrativo de Despesas."""
        soma: dict[str, float] = {}
        for l in dados.lancamentos:
            soma[_norm(l.conta)] = round(soma.get(_norm(l.conta), 0.0) + l.valor, 2)
        falta = {}
        for c in dados.contas:
            f = round(c.debitos - soma.get(_norm(c.nome), 0.0), 2)
            if f > 0.011:
                falta[_norm(c.nome)] = f
        return falta

    def _transferencias(self, dados: DadosRegras):
        """Transferência para outra conta (ex.: Ordinária -> aplicação) está no DÉBITO da conta que envia e no CRÉDITO da que
        recebe, mas não é despesa nem receita do demonstrativo. Quando o valor casa ao centavo, o débito da conta que envia é
        reduzido (fica só o gasto), a perna que recebe entra em `receitas` como tipo 'transferencia' e um aviso explica."""
        por = {_norm(c.nome): c for c in dados.contas}
        soma_rec: dict[str, float] = {}
        for r in dados.receitas:
            soma_rec[_norm(r.conta)] = round(soma_rec.get(_norm(r.conta), 0.0) + r.valor, 2)
        for nome, f in list(self._falta_debito.items()):
            envia = por[nome]
            excessos = {n: round(c.creditos - soma_rec.get(n, 0.0), 2) for n, c in por.items() if n != nome}
            dest = [n for n, e in excessos.items() if abs(e - f) < 0.011]
            if len(dest) != 1:
                pares = [(a, b) for a in excessos for b in excessos if a < b and abs(excessos[a] + excessos[b] - f) < 0.011 and excessos[a] > 0.011 and excessos[b] > 0.011]
                dest = list(pares[0]) if len(pares) == 1 else []
            if not dest:
                continue
            for n in dest:
                c = por[n]
                dados.receitas.append(LinhaReceita(conta=c.nome, descricao=f"transferência recebida de {envia.nome}", valor=excessos[n],
                                                   tipo="transferencia", pagina=c.pagina))
                soma_rec[n] = round(soma_rec.get(n, 0.0) + excessos[n], 2)
            dados.avisos.append(f"o débito da conta {envia.nome} no Resumo ({envia.debitos:,.2f}) inclui {f:,.2f} que não são lançamentos do Demonstrativo de Despesas: "
                                f"transferência para {' e '.join(por[n].nome for n in dest)} (o mesmo valor aparece como crédito dela) — considerei só o gasto"
                                .replace(",", "X").replace(".", ",").replace("X", "."))
            envia.debitos = round(envia.debitos - f, 2)

    # ── Demonstrativo Financeiro por Conta (Cap D'Antibes) ───────────────────
    def _posicao_financeira(self, dados: DadosRegras, paginas) -> bool:
        em_sec = False
        conta = None
        em_pos = False
        achou = False
        col_deb = col_cred = None
        saidas: dict[str, float] = {}
        for pag, W, linhas in paginas:
            for l in linhas:
                if _ruido_pagina(l):
                    continue
                t = l["texto"].strip()
                tn = _norm(t)
                if tn.startswith("DEMONSTRATIVO FINANCEIRO POR CONTA"):
                    em_sec, achou, conta, em_pos = True, True, None, False
                    continue
                if not em_sec:
                    continue
                m = _RE_CONTA_HDR.match(t)
                if m and not [w for w in l["w"] if _num(w[4]) is not None and w[0] > 0.5 * W]:
                    conta, em_pos = m.group(2).strip(), False
                    continue
                if tn.startswith("POSICAO FINANCEIRA"):
                    em_pos = True
                    for w in l["w"]:
                        if _norm(w[4]) == "DEBITO":
                            col_deb = w[2]
                        elif _norm(w[4]) == "CREDITO":
                            col_cred = w[2]
                    continue
                if tn.startswith("SALDO ATUAL"):
                    em_pos = False
                    continue
                if not em_pos or conta is None or col_deb is None or col_cred is None:
                    continue
                vals = [w for w in l["w"] if _num(w[4]) is not None]
                if not vals:
                    continue
                rotulo = " ".join(w[4] for w in l["w"] if _num(w[4]) is None).strip()
                rn = _norm(rotulo)
                if not rotulo or rn.startswith(("SALDO ANTERIOR", "TOTAIS", "DESPESAS DO PERIODO", "RECEITA REALIZADA")):
                    continue
                v = vals[-1]
                if abs(v[2] - col_deb) < abs(v[2] - col_cred):       # valor na coluna Débito
                    if rn.startswith("TRANSFERIDO PARA"):
                        saidas[_norm(conta)] = saidas.get(_norm(conta), 0.0) + abs(_num(v[4]))
                    continue
                if rn.startswith("TRANSFERIDO DA"):
                    tipo = "transferencia"
                elif ("APLICA" in _norm(conta) and rn.startswith("OUTRAS RECEITAS")) or "RENDIMENT" in rn:
                    tipo = "rendimento"
                elif re.match(r"^(MULTAS?|JUROS)", rn):
                    tipo = "multa_juros"
                elif rn.startswith(("DA EMISSAO", "DE CONDOMINOS", "ANTECIPACO")):
                    tipo = "cota"
                else:
                    tipo = "outra"
                dados.receitas.append(LinhaReceita(conta=conta, descricao=rotulo, valor=_num(v[4]), tipo=tipo, pagina=pag,
                                                   bbox=tuple(round(x, 1) for x in l["bbox"])))
        # transferência enviada: está no débito da conta no Resumo, mas não é despesa
        por = {_norm(c.nome): c for c in dados.contas}
        for nome, valor in saidas.items():
            c = por.get(nome)
            if c is not None and valor > 0.005:
                dados.avisos.append(f"o débito da conta {c.nome} no Resumo ({c.debitos:,.2f}) inclui transferência para outra conta ({valor:,.2f}); "
                                    f"considerei só o gasto ({c.debitos - valor:,.2f})".replace(",", "X").replace(".", ",").replace("X", "."))
                c.debitos = round(c.debitos - valor, 2)
        if saidas and hasattr(self, "_falta_debito"):
            self._falta_debito = {k: v for k, v in self._falta_debito.items() if k not in saidas}
        return achou

    # ── rendimento por conta e conferências ──────────────────────────────────
    def _rendimentos_e_conferencias(self, dados: DadosRegras, achou_rec: bool, achou_pos: bool):
        por = {_norm(c.nome): c for c in dados.contas}
        for r in dados.receitas:
            c = por.get(_norm(r.conta))
            if r.tipo == "rendimento" and c is not None:
                c.rendimento += r.valor
        soma: dict[str, float] = {}
        for r in dados.receitas:
            soma[_norm(r.conta)] = round(soma.get(_norm(r.conta), 0.0) + r.valor, 2)
        for c in dados.contas:
            if (achou_rec or achou_pos) and abs(soma.get(_norm(c.nome), 0.0) - c.creditos) > 0.011:
                dados.avisos.append(f"receitas lidas da conta {c.nome} somam {soma.get(_norm(c.nome), 0.0):,.2f}, mas os créditos no Resumo são {c.creditos:,.2f}"
                                    .replace(",", "X").replace(".", ",").replace("X", "."))
        # conta do Demonstrativo de Despesas = nome do Resumo? (o cabeçalho "001 - CONTA ORDINÁRIA - ITAÚ..." é igual ao do Resumo)
        nomes = {_norm(c.nome) for c in dados.contas}
        for nome in {l.conta for l in dados.lancamentos}:
            if _norm(nome) not in nomes:
                dados.avisos.append(f"o Demonstrativo de Despesas tem a conta '{nome}', que não aparece no Resumo Financeiro Contábil")
