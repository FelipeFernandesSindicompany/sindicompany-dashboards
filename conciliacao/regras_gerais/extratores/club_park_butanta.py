"""
Extrator das regras gerais — Club Park Butantã (GCONT).

O cadastro diz `lirba_pdf`, mas o PDF NÃO é ContasData: é o relatório "W0xx" da GCONT (Resumo Financeiro por grupo de
saldo + 'Demonstrativo Analítico "<grupo>"'), o mesmo software do I-Gloo Alphaville. A leitura completa está em
`extratores/gcont.py`; este módulo faz o despacho por id e lê a VARIANTE RESUMIDA da prestação de contas (53 páginas,
sem comprovantes, a partir de set/2026), que traz só:

  W009A/W009D  Previsto x Realizado e acumulado (por categoria)          -> previsto/realizado da cota do mês
  W002B        Inadimplência por unidade ("N unidades inadimplentes ... TOTAL")
  W018L        Caixa com previsão de saldo (livro caixa: data, descrição, D/C, valor, saldo) + Resumo (saldo inicial/final)
  W023C        Saldo das contas na data
  W078A        Despesas por categoria (vencimento, liquidação, fornecedor, categoria - complemento, competência, valor)

A conta de cada despesa não vem no arquivo (o livro caixa é do caixa todo): `conta` = "CAIXA". Nada é inventado: o que a
variante não permite ler (rendimento por conta, comprovantes, notas fiscais) fica fora da cobertura, com o motivo.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.extratores.contasdata import _norm
from conciliacao.regras_gerais.extratores.gcont import Extrator as _Gcont
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_RE_VALOR = re.compile(r"^-?[\d.]+,\d{2}$")
_RE_DATA4 = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_DATA2 = re.compile(r"^\d{2}/\d{2}/\d{2}$")
_RE_COMPET = re.compile(r"^\d{2}/\d{4}$")
_CODIGO_PAGINA = re.compile(r"^(W\d{3}[A-Z])\b")
_RODAPE_Y = 770.0
_RE_N_DE_M = re.compile(r"(?:^|[\s-])(\d{1,2}) de (\d{1,2})\s*\.?\s*$", re.IGNORECASE)


def _marca_parcela(texto: str) -> str:
    """A GCONT escreve a parcela no fim do complemento como "- 1 de 3"; as regras gerais reconhecem "PARC 1/3": acrescenta a marca."""
    m = _RE_N_DE_M.search(texto or "")
    if m and "PARC" not in (texto or "").upper() and 1 <= int(m.group(1)) <= int(m.group(2)) <= 99:
        return f"{texto} PARC {int(m.group(1))}/{int(m.group(2))}"
    return texto


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


class Extrator(_Gcont):
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        caminho = Path(caminho)
        if caminho.suffix.lower() == ".pdf":
            with fitz.open(str(caminho)) as doc:
                inicios = []
                for i, p in enumerate(doc):
                    m = _CODIGO_PAGINA.match(p.get_text()[:40])
                    if m:
                        inicios.append((i, m.group(1)))
                # cada relatório W0xx vai da página que traz o código até a anterior ao próximo (as seguintes não repetem o código)
                codigos: dict = {}
                for k, (i, cod) in enumerate(inicios):
                    fim = inicios[k + 1][0] if k + 1 < len(inicios) else len(doc)
                    codigos.setdefault(cod, []).extend(range(i, fim))
                if {"W018L", "W023C", "W078A"} <= set(codigos) and "W016B" not in codigos:
                    dados = DadosRegras(mes=mes, arquivo=caminho.name)
                    self._extrair_resumo(doc, codigos, mes, dados)
                    return dados
        dados = super().extrair(caminho, mes)
        for l in dados.lancamentos:
            l.descricao = _marca_parcela(l.descricao)
        return dados

    def para_historico(self, caminho: Path, mes: str, dados_mes: DadosRegras, dados_atual: DadosRegras):
        """Mês anterior em prestação COMPLETA relido como a resumida: a mesma listagem "Despesas por categoria" (fornecedor, categoria bruta,
        complemento), para fornecedor novo/valor acima do histórico/subcontas compararem nomes iguais. As tarifas bancárias vêm do mês lido
        pelo extrator completo (a listagem não as traz)."""
        import fitz

        if getattr(dados_atual, "variante", None) != "resumo" or Path(caminho).suffix.lower() != ".pdf":
            return None
        with fitz.open(str(caminho)) as doc:
            inicios = []
            for i, p in enumerate(doc):
                m = _CODIGO_PAGINA.match(p.get_text()[:40])
                if m:
                    inicios.append((i, m.group(1)))
            paginas = []
            for k, (i, cod) in enumerate(inicios):
                if cod == "W078A":
                    paginas = list(range(i, inicios[k + 1][0] if k + 1 < len(inicios) else len(doc)))
                    break
            if not paginas:
                return None
            cats = sorted({_ws(_norm(k)) for k in ((self.condo.get("parser_config") or {}).get("cat_map") or {})}, key=len, reverse=True)
            lanc = self._ler_despesas(doc, paginas, cats)
        if not lanc:
            return None
        for l in dados_mes.lancamentos:
            if _norm(l.categoria or "").startswith("DESPESAS BANCARIAS") or _norm(l.descricao or "").startswith("DESPESAS BANCARIAS"):
                l.categoria = "DESPESAS BANCARIAS"       # no completo a tarifa vem sob "DESPESAS GERAIS E ADMINISTRATIVAS"; aqui, como no livro caixa
                lanc.append(l)
        h = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        h.lancamentos, h.receitas, h.contas, h.variante = lanc, dados_mes.receitas, dados_mes.contas, "resumo"
        h.cobertura, h.indicadores = dict(dados_mes.cobertura), dados_mes.indicadores
        return h

    def categoria_canonica(self, nome: str) -> str:
        """Categoria do arquivo -> categoria canônica do condomínio (cat_map do cadastro); sem correspondência, o próprio nome."""
        mapa = (self.condo.get("parser_config") or {}).get("cat_map") or {}
        normalizado = {_ws(_norm(k)): v for k, v in mapa.items()}
        return normalizado.get(_ws(_norm(nome)), nome)

    # ── variante resumida ────────────────────────────────────────────────────────────────────────────────────
    def _extrair_resumo(self, doc, codigos: dict, mes: str, dados: DadosRegras) -> None:
        dados.variante = "resumo"
        dados.avisos.append(
            "arquivo na versão resumida da prestação de contas (53 páginas: previsto x realizado, inadimplência, livro caixa, saldo das contas e "
            "despesas por categoria): sem as páginas de comprovante e sem o resumo financeiro por conta — o saldo é o do caixa todo")
        p0 = codigos["W078A"][0]
        m = re.search(r"Entre\s+\d{2}/(\d{2})/(\d{4})\s+e", doc[p0].get_text())
        if m and f"{m.group(2)}-{m.group(1)}" != mes:
            dados.avisos.append(f"o período impresso no arquivo é {m.group(1)}/{m.group(2)}, não {mes[5:7]}/{mes[:4]}")
        cats = sorted({_ws(_norm(k)) for k in ((self.condo.get("parser_config") or {}).get("cat_map") or {})}, key=len, reverse=True)

        dados.lancamentos = self._ler_despesas(doc, codigos["W078A"], cats)
        creditos, debitos, resumo = self._ler_livro_caixa(doc, codigos["W018L"], dados)
        contas_w023 = self._ler_saldos_contas(doc, codigos["W023C"][0])
        dados.indicadores = self._indicadores(doc, codigos)

        # conta única "caixa": saldo inicial/final do livro caixa; os saldos por conta (W023C) conferem com o final
        if resumo:
            dados.contas = [ContaMes(nome="CAIXA (todas as contas)", saldo_anterior=resumo["ini"], creditos=resumo["cred"],
                                     debitos=resumo["deb"], saldo_atual=resumo["fim"], pagina=codigos["W018L"][-2] + 1)]
            if abs(resumo["ini"] + resumo["cred"] - resumo["deb"] - resumo["fim"]) > 0.011:
                dados.avisos.append("o Resumo do livro caixa não fecha (saldo inicial + créditos − débitos ≠ saldo final)")
            if contas_w023:
                soma = round(sum(v for _, v in contas_w023), 2)
                if abs(soma - resumo["fim"]) > 0.011:
                    dados.avisos.append(f"a soma dos saldos por conta (W023C: {soma:,.2f}) não bate com o saldo final do livro caixa ({resumo['fim']:,.2f})")
                dados.avisos.append("saldos por conta em " + "; ".join(f"{n} {v:,.2f}" for n, v in contas_w023))
                for n, v in contas_w023:
                    if v < -0.005:
                        dados.contas.append(ContaMes(nome=n, saldo_atual=v, saldo_anterior=v, pagina=codigos["W023C"][0] + 1))
        # conferências de fechamento entre as partes do próprio arquivo
        if resumo and abs(sum(l.valor for l in dados.lancamentos) - resumo["deb"]) > 0.011:
            dados.avisos.append(f"a soma das despesas por categoria ({sum(l.valor for l in dados.lancamentos):,.2f}) difere dos débitos do "
                                f"livro caixa ({resumo['deb']:,.2f})")
        rend = [r for r in dados.receitas if r.tipo == "rendimento"]
        if rend:
            def _br(v):
                return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            maior = max(rend, key=lambda r: r.valor)
            outros = [r for r in rend if r is not maior]
            dados.rendimento_sem_conta = {
                "total": round(sum(r.valor for r in rend), 2), "lancamentos": len(rend),
                "contas": [{"nome": n, "saldo": v} for n, v in contas_w023],
                "linhas_maiores": [{"valor": maior.valor, "data": maior.data, "pagina": maior.pagina}],
                "detalhe": f"{maior.descricao.strip()} R$ {_br(maior.valor)} em {maior.data[:5]}"
                           + (f" e mais {len(outros)} lançamentos de rendimento de aplicação, somando R$ {_br(sum(r.valor for r in outros))}" if outros else "")}
        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": False, "lancamentos": bool(dados.lancamentos)}
        dados.motivos_nao_cobertos["rendimentos"] = (
            "o livro caixa traz o rendimento das aplicações do caixa todo, sem dizer em qual conta foi creditado — não há como comparar o "
            "rendimento entre contas")

    def livro_caixa_com_links(self, caminho: Path) -> list:
        """Linhas de DÉBITO do livro caixa (W018L) com o link do portal da GCONT que cada uma traz: [{"data" dd/mm/aaaa, "desc", "valor", "uri",
        "pagina"}]. Linha sem link (tarifa bancária) vem com uri None."""
        import fitz

        out: list = []
        with fitz.open(str(caminho)) as doc:
            inicios = []
            for i, pg in enumerate(doc):
                m = _CODIGO_PAGINA.match(pg.get_text()[:40])
                if m:
                    inicios.append((i, m.group(1)))
            paginas = []
            for k, (i, cod) in enumerate(inicios):
                if cod == "W018L":
                    paginas = list(range(i, inicios[k + 1][0] if k + 1 < len(inicios) else len(doc)))
            blocos: list = []
            for i in paginas:
                ws = [w for w in doc[i].get_text("words") if w[1] < _RODAPE_Y]
                y_stop = min((w[1] for w in ws if w[4] == "Contas" and w[0] < 60), default=None)
                for w in sorted(ws, key=lambda w: (round(w[1] / 3), w[0])):
                    if y_stop is not None and w[1] >= y_stop - 1:
                        break
                    if w[0] < 62 and _RE_DATA2.match(w[4]):
                        blocos.append({"pg": i, "top": w[1], "bot": 9999.0, "w": []})
                    if blocos:
                        blocos[-1]["w"].append(w)
            for k, b in enumerate(blocos):
                if k + 1 < len(blocos) and blocos[k + 1]["pg"] == b["pg"]:
                    b["bot"] = blocos[k + 1]["top"]
            for b in blocos:
                dc = next((w[4] for w in b["w"] if 375 < w[0] < 420 and w[4] in ("D", "C")), None)
                vs = [w for w in b["w"] if 420 < w[0] < 497 and _RE_VALOR.match(w[4])]
                if dc != "D" or not vs:
                    continue
                uri = None
                for l in doc[b["pg"]].get_links():
                    u = l.get("uri") or ""
                    if "idParcela=" in u and b["top"] - 2 <= l["from"][1] < b["bot"]:
                        uri = u
                        break
                d = b["w"][0][4]
                out.append({"data": f"{d[:6]}20{d[6:]}", "desc": _ws(" ".join(w[4] for w in b["w"] if 90 < w[0] < 370)),
                            "valor": _num(vs[0][4]), "uri": uri, "pagina": b["pg"] + 1})
        return out

    # W078A — despesas por categoria ----------------------------------------------------------------------------
    def _ler_despesas(self, doc, paginas: list, cats: list) -> list:
        blocos: list = []          # cada um: {"w": [(pagina, y, x0, texto)], "pg": pagina}
        for i in paginas:
            ws = [w for w in doc[i].get_text("words") if w[1] < _RODAPE_Y]
            cab = [w for w in ws if w[4] == "Vencimento"]
            y_ini = (cab[0][1] + 5) if cab else -1.0
            for w in sorted(ws, key=lambda w: (round(w[1] / 3), w[0])):
                if w[1] < y_ini:
                    continue
                if w[0] < 90 and _RE_DATA4.match(w[4]) and w[0] < 60:
                    blocos.append({"w": [], "pg": i + 1, "ini": (i, w[1])})
                if not blocos:
                    continue
                blocos[-1]["w"].append((i, w[1], w[0], w[4], w[3], w[2]))
        out = []
        for b in blocos:
            col = {"venc": [], "liq": [], "forn": [], "cat": [], "comp": [], "val": []}
            for pg, y, x, t, y1, x1 in b["w"]:
                k = ("venc" if x < 88 else "liq" if x < 145 else "forn" if x < 297 else "cat" if x < 450 else "comp" if x < 520 else "val")
                col[k].append((pg, y, x, t, y1, x1))
            comp_ws = [w for w in col["comp"] if _RE_COMPET.match(w[3])]
            vals = [w for w in col["val"] if _RE_VALOR.match(w[3])]
            if not comp_ws or not vals:
                continue
            cy = comp_ws[0]
            v = next((w for w in vals if w[0] == cy[0] and abs(w[1] - cy[1]) < 4), None)
            if v is None:
                continue
            junta = lambda lst: _ws(" ".join(w[3] for w in lst))
            texto_cat = junta(col["cat"])
            norm = _ws(_norm(texto_cat))
            cat = next((c for c in cats if norm.startswith(c)), None)
            if cat:
                # volta ao texto original: consome palavras até a categoria normalizada fechar
                palavras = texto_cat.split()
                n_pal = next((n for n in range(1, len(palavras) + 1) if _ws(_norm(" ".join(palavras[:n]))) == cat), len(cat.split()))
                nome_cat, compl = " ".join(palavras[:n_pal]), " ".join(palavras[n_pal:]).lstrip("- ").strip()
            else:
                partes = texto_cat.split(" - ", 1)
                nome_cat, compl = partes[0].strip(), (partes[1].strip() if len(partes) > 1 else "")
            venc, liq = junta(col["venc"][:1]), junta(col["liq"][:1])
            forn = junta(col["forn"])
            l = LancamentoDespesa(descricao=_marca_parcela(_ws(f"{nome_cat} - {compl}")) + f" - {forn}" if compl else f"{nome_cat} - {forn}", valor=_num(v[3]),
                                  categoria=nome_cat, conta="CAIXA", data=liq or venc or None, fornecedor=forn,
                                  pagina=b["pg"], local=f"W078A, página {b['pg']}")
            # recorte da linha na 1ª página em que ela aparece (print do lançamento); o total do dia (valor sem competência) fica de fora
            pg0 = b["w"][0][0]
            da_linha = [w for w in b["w"] if w[0] == pg0 and not (w[2] >= 520 and _RE_VALOR.match(w[3]) and w[:4] != v[:4])]
            l.bbox = (min(w[2] for w in da_linha), min(w[1] for w in da_linha), max(w[5] for w in da_linha), max(w[4] for w in da_linha))
            l.vencimento = venc or None
            l.competencia = comp_ws[0][3]
            l.complemento = compl
            out.append(l)
        return out

    # W018L — livro caixa -----------------------------------------------------------------------------------------
    def _ler_livro_caixa(self, doc, paginas: list, dados: DadosRegras):
        blocos: list = []
        fim = False
        for i in paginas:
            ws = [w for w in doc[i].get_text("words") if w[1] < _RODAPE_Y]
            y_stop = min((w[1] for w in ws if w[4] == "Contas" and w[0] < 60), default=None)
            for w in sorted(ws, key=lambda w: (round(w[1] / 3), w[0])):
                if y_stop is not None and w[1] >= y_stop - 1:
                    fim = True
                    break
                if w[0] < 62 and _RE_DATA2.match(w[4]):
                    blocos.append({"pg": i + 1, "w": []})
                if blocos:
                    blocos[-1]["w"].append(w)
            if fim:
                break
        creditos = debitos = 0.0
        for b in blocos:
            desc_ws = [w for w in b["w"] if 90 < w[0] < 370]
            data = b["w"][0][4]
            dc = next((w[4] for w in b["w"] if 375 < w[0] < 420 and w[4] in ("D", "C")), None)
            vs = [w for w in b["w"] if 420 < w[0] < 497 and _RE_VALOR.match(w[4])]
            desc = _ws(" ".join(w[4] for w in desc_ws))
            if desc.startswith("Saldo Anterior") or dc is None or not vs:
                continue
            valor = _num(vs[0][4])
            if dc == "C":
                creditos += valor
                tn = _norm(desc)
                tipo = "rendimento" if "RENDIMENTO" in tn else "cota" if tn.startswith("COBRANCA") else "outra"
                dados.receitas.append(LinhaReceita(conta="CAIXA", descricao=desc, valor=valor, tipo=tipo, data=f"{data[:6]}20{data[6:]}",
                                                   pagina=b["pg"]))
            else:
                debitos += valor
                if _norm(desc).startswith("DESPESAS BANCARIAS"):
                    # tarifa debitada pelo banco: está no livro caixa mas não na listagem "Despesas por categoria" (W078A)
                    l = LancamentoDespesa(descricao=desc, valor=valor, categoria="DESPESAS BANCARIAS", conta="CAIXA",
                                          data=f"{data[:6]}20{data[6:]}", fornecedor="Banco", pagina=b["pg"],
                                          local=f"W018L, página {b['pg']}")
                    l.vencimento = l.data
                    l.competencia = None
                    l.complemento = ""
                    dados.lancamentos.append(l)
        resumo = next((r for r in (self._resumo_caixa(doc, i) for i in reversed(paginas)) if r), None)
        if resumo:
            if abs(creditos - resumo["cred"]) > 0.011:
                dados.avisos.append(f"os créditos lidos do livro caixa ({creditos:,.2f}) não batem com o Resumo ({resumo['cred']:,.2f})")
            if abs(debitos - resumo["deb"]) > 0.011:
                dados.avisos.append(f"os débitos lidos do livro caixa ({debitos:,.2f}) não batem com o Resumo ({resumo['deb']:,.2f})")
        return creditos, debitos, resumo

    @staticmethod
    def _resumo_caixa(doc, pagina: int):
        ls = [l.strip() for l in doc[pagina].get_text().splitlines() if l.strip()]
        out = {}
        for k, l in enumerate(ls):
            if k + 1 >= len(ls) or not _RE_VALOR.match(ls[k + 1]):
                continue
            v = _num(ls[k + 1])
            if l.startswith("Saldo Inicial"):
                out["ini"] = v
            elif l.startswith("Créditos (+)"):
                out["cred"] = v
            elif l.startswith("Débitos (-)"):
                out["deb"] = v
            elif l.startswith("Saldo Final"):
                out["fim"] = v
        return out if {"ini", "cred", "deb", "fim"} <= set(out) else None

    # W023C — saldo das contas ---------------------------------------------------------------------------------------
    @staticmethod
    def _ler_saldos_contas(doc, pagina: int) -> list:
        ls = [l.strip() for l in doc[pagina].get_text().splitlines() if l.strip()]
        out = []
        for k, l in enumerate(ls):
            if k + 1 < len(ls) and _RE_VALOR.match(ls[k + 1]) and not _RE_VALOR.match(l) and not l.startswith(("Saldo", "W0")):
                out.append((l, _num(ls[k + 1])))
        return out

    # W009A / W002B — previsto x realizado, inadimplência ---------------------------------------------------------
    @staticmethod
    def _indicadores(doc, codigos: dict):
        prev = real = inad = None
        for i in codigos.get("W009A", []):
            ls = [l.strip() for l in doc[i].get_text().splitlines() if l.strip()]
            for k, l in enumerate(ls):
                if re.match(r"^Cota do M[êe]s$", l) and k + 2 < len(ls) and _RE_VALOR.match(ls[k + 1]) and _RE_VALOR.match(ls[k + 2]):
                    prev, real = _num(ls[k + 1]), _num(ls[k + 2])
                    break
            if prev is not None:
                break
        for i in codigos.get("W002B", []):
            t = doc[i].get_text()
            m = re.search(r"(\d+) unidades? inadimplentes?\s*\([\d,]+%\)\s*\n\s*([\d.]+,\d{2})", t)
            if m:
                inad = _num(m.group(2))
        if prev is None and inad is None:
            return None
        return {"prev": prev or 0.0, "real": real or 0.0, "inad": inad, "inadProc": 0.0}
