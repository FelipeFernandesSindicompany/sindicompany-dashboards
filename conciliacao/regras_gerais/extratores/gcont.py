"""
Extrator das regras gerais — PDF "W0xx" da GCONT/HSA ("Prestação de contas" com Resumo Financeiro,
"Demonstrativo Analítico" por grupo de saldo, "Movimentação Analítica" por conta).

NÃO é o ContasData: o software imprime códigos de relatório no topo de cada página (W016B Resumo Financeiro,
W020A Demonstrativo Analítico, W020H Movimentação Analítica...), rodapé "HSA CONDOMÍNIOS" ou "ADMINISTRADORA GCONT"
e valores negativos entre parênteses "(81,18)". Usado por:

  * i_gloo_alphaville (HSA Condomínios)   — um 'Demonstrativo Analítico "<grupo de saldo>"' por grupo
    (Ordinária, Fundo Reserva, Fundo de Obras, Benfeitorias, Gás, Água...): receitas por categoria (uma linha por
    competência) e despesas lançamento a lançamento (fornecedor, liquidação, documento, valor);
  * parque_saint_afonso (GCONT)           — um único 'Demonstrativo de Receitas e Despesas Analítico' (categorias, sem
    conta) + uma 'Movimentação Analítica "<conta>"' por conta (razão: data, descrição, valor, saldo). A conta de cada
    lançamento vem do razão; a categoria, do analítico;
  * (club_park_butanta usa o mesmo software, mas tem extrator próprio de outro responsável.)

O que NÃO se lê: PDFs escaneados (alguns meses do Parque Saint Afonso são imagem com camada OCR cheia de erros de
dígito). Nesse caso a conferência aritmética falha e o extrator devolve cobertura False com o motivo, nunca valores
inventados.

Estrutura devolvida (modelo.py): contas = tabela do Resumo Financeiro (grupos de saldo, ou contas); receitas = uma
linha por linha de receita do analítico (com sinal; "(81,18)" = -81,18); lancamentos = um por despesa liquidada;
`categoria` = "<categoria> › <subgrupo>" (a categoria é a linha com a porcentagem "(61,05%)"; o subgrupo, o último
cabeçalho antes do lançamento).
"""
import re
from pathlib import Path
from typing import Optional

from conciliacao.regras_gerais.extratores.contasdata import (
    _Linha, _Pagina, _agrupar_linhas, _fmt, _limpar, _norm, _num, _sem_acento, _unir_bbox, _RE_DATA, _RE_DINHEIRO,
)
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CENTAVO = 0.011
_RE_CODIGO = re.compile(r"^W0\d\d[A-Z]\b")
_RE_PCT_CAT = re.compile(r"\(\s*-?\d+,\d{2}\s*%\s*\)\s*$")


class Extrator:
    #: nível usado em LancamentoDespesa.categoria: "topo" (categoria com a porcentagem: PESSOAL, Consumo, GERAIS...),
    #: "rubrica" (último cabeçalho antes do lançamento) ou "caminho" ("topo › rubrica"). A rubrica vai sempre em `.rubrica`.
    NIVEL_CATEGORIA = "topo"

    def __init__(self, condo: dict):
        self.condo = condo or {}
        cfg = (self.condo.get("parser_config") or {}).get("regras_gerais") or {}
        self.nivel = cfg.get("nivel_categoria", self.NIVEL_CATEGORIA)

    # -- ponto de entrada ----------------------------------------------------
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        caminho = Path(caminho)
        if caminho.suffix.lower() != ".pdf":
            raise ValueError("formato não reconhecido como GCONT/HSA")
        doc = fitz.open(str(caminho))
        try:
            paginas = self._paginas(doc)
            dados = DadosRegras(mes=mes, arquivo=caminho.name)
            if sum(len(p.texto) for p in paginas[:30]) < 300:
                return self._sem_leitura(dados, "o PDF é só imagem (sem camada de texto): a leitura exigiria OCR e não há "
                                                "texto confiável para ler receitas e lançamentos")
            legivel = self._reconhecer(paginas)
            if not legivel:
                return self._sem_leitura(dados, "o arquivo é um PDF digitalizado (imagem com camada de OCR sem os relatórios "
                                                "legíveis): não há texto confiável para ler receitas e lançamentos")
            self._periodo_confere(paginas, mes, dados)
            contas = self._ler_resumo(paginas)
            if len(contas) < 1:
                return self._sem_leitura(dados, "o texto do arquivo não é legível (PDF digitalizado: o Resumo Financeiro "
                                                "não pôde ser lido)")
            dados.contas = contas
            por_nome = {_norm(c.nome): c for c in contas}
            grupos = self._blocos_analiticos(paginas)
            razao = self._ler_razao(paginas)
            if not grupos:
                return self._sem_leitura(dados, "o texto do arquivo não é legível (PDF digitalizado: o Demonstrativo "
                                                "Analítico não pôde ser lido)")
            self._montar(dados, grupos, razao, por_nome)
            self._conferir(dados, por_nome)
            return dados
        finally:
            doc.close()

    @staticmethod
    def _sem_leitura(dados: DadosRegras, motivo: str) -> DadosRegras:
        dados.cobertura = {"receitas": False, "rendimentos": False, "lancamentos": False}
        dados.motivos_nao_cobertos = {k: motivo for k in dados.cobertura}
        dados.avisos.append(motivo)
        return dados

    # -- páginas --------------------------------------------------------------
    def _paginas(self, doc) -> list:
        out = []
        for i, page in enumerate(doc):
            p = _Pagina(i + 1, page, _limpar(page.get_text("text")))
            out.append(p)
        return out

    def _reconhecer(self, paginas: list) -> bool:
        """ValueError se não for GCONT/HSA. Devolve False quando é (o rodapé/ capa dizem GCONT ou HSA) mas o texto não traz os
        relatórios W0xx legíveis — PDF digitalizado com camada de OCR."""
        inicio = "\n".join(p.texto for p in paginas if len(p.texto) > 150)
        nomes = re.search(r"HSA CONDOM[ÍI]NIOS|ADMINISTRADORA GCONT|G\s?C\s?O?\s?N\s?T|gcont\.net\.br", inicio, re.I)
        if not nomes:
            raise ValueError("formato não reconhecido como GCONT/HSA")
        return bool(re.search(r"^W0\d\d[A-Z]\s", inicio, re.M) and re.search(r"Resumo Financeiro", inicio))

    def _periodo_confere(self, paginas: list, mes: str, dados: DadosRegras) -> None:
        for p in paginas:
            m = re.search(r"(?:Entre|De)\s+(\d{2})/(\d{2})/(\d{4})\s+(?:e|at[ée])\s+(\d{2})/(\d{2})/(\d{4})", p.texto)
            if m:
                ano, mm = int(m.group(6)), int(m.group(5))
                if f"{ano}-{mm:02d}" != mes:
                    dados.avisos.append(f"o período impresso no arquivo é {mm:02d}/{ano}, não {mes[5:7]}/{mes[:4]}")
                return

    # -- Resumo Financeiro ------------------------------------------------------
    def _ler_resumo(self, paginas: list) -> list:
        """Tabela 'Grupos de saldo' (ou, se não houver, 'Conta'): nome | saldo ant. | créditos | débitos | saldo final."""
        for p in paginas:
            if not re.search(r"^Resumo Financeiro\s*$", p.texto, re.M) or "Saldo ant" not in p.texto:
                continue
            tabelas: dict = {}
            atual = None
            for l in p.linhas:
                t = l.texto.strip()
                if re.match(r"^(Conta|Grupos de saldo)\b", t) and "Saldo ant" in t:
                    atual = t.split()[0] if t.startswith("Conta") else "Grupos"
                    tabelas[atual] = []
                    continue
                if atual is None:
                    continue
                if re.match(r"^Saldo final", t):
                    atual = None
                    continue
                din = l.dinheiro()
                if len(din) >= 4 and t[:1].isalpha():
                    v = [_num(w[4]) for w in din[-4:]]
                    nome = " ".join(w[4] for w in l.pal if w[2] < din[-4][0] - 0.5).strip()
                    tabelas[atual].append(ContaMes(nome=nome, saldo_anterior=v[0], creditos=v[1], debitos=v[2],
                                                   saldo_atual=v[3], pagina=p.n))
            if tabelas:
                return tabelas.get("Grupos") or tabelas.get("Conta") or []
        return []

    # -- blocos analíticos --------------------------------------------------------
    def _blocos_analiticos(self, paginas: list) -> list:
        """[(nome_do_grupo|None, [linhas])]: 'Demonstrativo Analítico "<grupo>"' (um bloco por grupo) ou
        'Demonstrativo de Receitas e Despesas Analítico' (bloco único, grupo None). Atravessa páginas sem título."""
        blocos: list = []
        atual = None
        for p in paginas:
            tem_titulo = re.search(r'^Demonstrativo (?:de Receitas e Despesas )?Anal[ií]tico\b', p.texto, re.M)
            topo = p.texto.lstrip()[:12]
            if atual is not None and not tem_titulo and _RE_CODIGO.match(topo):
                atual = None                                        # outro relatório (W0xx) começou
            if not tem_titulo and atual is None:
                continue
            if "Comprovante" in p.texto[:120] or (atual is not None and len(p.texto) < 120):
                atual = None
                continue
            linhas = p.linhas
            if tem_titulo:
                i = next((k for k, l in enumerate(linhas)
                          if re.match(r'^Demonstrativo (?:de Receitas e Despesas )?Anal[ií]tico', l.texto)), None)
                if i is None:
                    continue
                m = re.match(r'^Demonstrativo Anal[ií]tico\s+"(.+)"\s*$', linhas[i].texto)
                atual = (m.group(1) if m else None, [])
                blocos.append(atual)
                linhas = linhas[i + 1:]
            atual[1].extend(l for l in linhas if not self._rodape(l))
        return blocos

    @staticmethod
    def _rodape(l: _Linha) -> bool:
        t = l.texto
        return (l.y >= 790 or re.match(r"^(HSA CONDOM|ADMINISTRADORA GCONT|Rua |Tel:|\(11\)|\d+ de \d+$)", t) is not None
                or "hsacondominios.com.br" in t or "gcont.net.br" in t)

    def _ler_bloco(self, linhas: list):
        """-> (receitas, despesas, totais): receitas = [(categoria, descricao, valor, pagina, bbox, competencia)],
        despesas = [dict(...)]; totais = {'receitas': v, 'despesas': v, 'saldo_anterior': v, 'saldo_atual': v}."""
        rec, desp = [], []
        tot: dict = {}
        modo = None
        topo = sub = None
        ultimo = None
        saldos = 0
        for l in linhas:
            t = l.texto.strip()
            if not t:
                continue
            din = l.dinheiro()
            mv = next((w for w in din if w[2] >= 540), None)            # coluna Valor (à direita)
            if re.match(r"^Saldo em\b", t):
                if mv:
                    tot["saldo_anterior" if saldos == 0 else "saldo_atual"] = _num(mv[4])
                    saldos += 1
                continue
            if re.match(r"^Receitas\b", t) and "Compet" in t:
                modo, topo, sub, ultimo = "rec", None, None, None
                continue
            if re.match(r"^Despesas\b", t) and "Liquida" in t:
                modo, topo, sub, ultimo = "desp", None, None, None
                continue
            if re.match(r"^Total de RECEITAS\s+\(?-?\d", t, re.I):
                tot["receitas"] = _num(mv[4]) if mv else None
                modo = None
                continue
            if re.match(r"^Total de DESPESAS\s+\(?-?\d", t, re.I):
                tot["despesas"] = _num(mv[4]) if mv else None
                modo = None
                continue
            if re.match(r"^(Mov\. L[íi]quido|Total de )", t) or modo is None:
                continue
            if modo == "rec":
                comp = next((w[4] for w in l.pal if 355 <= w[0] < 440 and (re.match(r"^\d{2}/\d{4}$", w[4]) or w[4] == "Acordo")), None)
                if mv and (comp or l.x0 >= 44):
                    desc = " ".join(w[4] for w in l.pal if w[2] < (comp and next(x[0] for x in l.pal if x[4] == comp) or mv[0]) - 0.5)
                    cat = sub or topo or ""
                    rec.append((cat, desc.strip(), _num(mv[4]), l.pg, l.bbox, comp))
                elif not mv:
                    if _RE_PCT_CAT.search(t):
                        topo, sub = _RE_PCT_CAT.sub("", t).strip(), None
                    elif l.x0 > 33:
                        sub = t
                continue
            # despesas
            if mv and not t.startswith("Total"):
                data = next((w[4] for w in l.pal if _RE_DATA.match(w[4]) and 296 <= w[0] < 360), None)
                doc = " ".join(w[4] for w in l.pal if 362 <= w[0] < 466 and w[4] != data and not w[4].endswith("%"))
                corte = min([w[0] for w in l.pal if w[4] == data] + [w[0] for w in l.pal if 362 <= w[0] < 466] + [mv[0]])
                desc = " ".join(w[4] for w in l.pal if w[2] <= corte + 0.5 and w[0] < 296 and w is not mv)
                x = {"desc": desc.strip(), "valor": _num(mv[4]), "data": data, "doc": doc.strip(), "pg": l.pg,
                     "bbox": l.bbox, "topo": topo, "sub": sub}
                desp.append(x)
                ultimo = x
            elif not mv:
                if _RE_PCT_CAT.search(t):
                    topo, sub, ultimo = _RE_PCT_CAT.sub("", t).strip(), None, None
                elif l.x0 <= 33 and ultimo is not None:                # continuação da descrição do lançamento
                    ultimo["desc"] = (ultimo["desc"] + " " + t).strip()
                    ultimo["bbox"] = _unir_bbox(ultimo["bbox"], l.bbox)
                elif l.x0 > 33:
                    sub, ultimo = t, None
        return rec, desp, tot

    # -- razão por conta (Saint Afonso) ------------------------------------------------
    def _ler_razao(self, paginas: list) -> dict:
        """'Movimentação Analítica "<conta>"': {conta: [dict(data, desc, valor, pg, bbox)]} (débito = valor negativo)."""
        out: dict = {}
        conta = None
        col_valor = None
        for p in paginas:
            m = re.search(r'^Movimenta[çc][ãa]o Anal[ií]tica\s+"(.+)"\s*$', p.texto, re.M)
            if m:
                conta, col_valor = m.group(1), None
                out.setdefault(conta, [])
            elif conta is None or _RE_CODIGO.match(p.texto.lstrip()[:12]) or "Comprovante" in p.texto[:120]:
                conta = None if (_RE_CODIGO.match(p.texto.lstrip()[:12])) else conta
                if conta is None:
                    continue
            if conta is None:
                continue
            for l in p.linhas:
                if self._rodape(l):
                    continue
                nomes = {w[4]: w for w in l.pal}
                if "Descrição" in nomes and "Valor" in nomes:
                    col_valor = nomes["Valor"][2]
                    continue
                if col_valor is None:
                    continue
                din = [w for w in l.dinheiro() if abs(w[2] - col_valor) <= 10]
                data = next((w[4] for w in l.pal if _RE_DATA.match(w[4]) and w[0] < 90), None)
                if data and din:
                    desc = " ".join(w[4] for w in l.pal if 95 <= w[0] < din[0][0] - 0.5)
                    out[conta].append({"data": data, "desc": desc.strip(), "valor": _num(din[-1][4]), "pg": l.pg, "bbox": l.bbox})
                elif not l.dinheiro() and not data and 95 <= l.x0 < 400 and out[conta]:
                    out[conta][-1]["desc"] = (out[conta][-1]["desc"] + " " + l.texto).strip()
                    out[conta][-1]["bbox"] = _unir_bbox(out[conta][-1]["bbox"], l.bbox)
        return out

    # -- montagem -------------------------------------------------------------------
    def _montar(self, dados: DadosRegras, grupos: list, razao: dict, contas: dict) -> None:
        por_grupo = any(g[0] for g in grupos)
        for nome, linhas in grupos:
            rec, desp, tot = self._ler_bloco(linhas)
            conta = self._conta(nome, contas) if nome else None
            for cat, desc, v, pg, bbox, comp in rec:
                r = LinhaReceita(conta=conta or "", descricao=f"{cat}: {desc}" + (f" ({comp})" if comp else ""), valor=v,
                                 tipo=self._tipo_receita(cat, desc), pagina=pg, bbox=bbox)
                r.categoria = cat
                dados.receitas.append(r)
            for x in desp:
                topo, sub = x["topo"] or "", x["sub"] or ""
                if self.nivel == "caminho" and topo and sub and _norm(topo) != _norm(sub):
                    cat = f"{topo} › {sub}"
                elif self.nivel == "rubrica":
                    cat = sub or topo
                else:                                  # "topo": a categoria com a porcentagem (a lista de subgrupos muda todo mês)
                    cat = topo or sub
                texto = x["desc"] + (f" {x['doc']}" if x["doc"] else "")
                l = LancamentoDespesa(descricao=texto.strip(), valor=x["valor"], categoria=cat, conta=conta or "",
                                      data=x["data"], pagina=x["pg"], bbox=x["bbox"], codigo=x["doc"] or None)
                l.rubrica, l.conta_arquivo = sub or None, nome
                dados.lancamentos.append(l)
            if nome and conta is not None:
                c = contas.get(_norm(conta))
                if c is not None and tot.get("despesas") is not None and abs(sum(x["valor"] for x in desp) - tot["despesas"]) > _CENTAVO:
                    dados.avisos.append(f"{nome}: lançamentos somam {_fmt(sum(x['valor'] for x in desp))}, "
                                        f"'Total de DESPESAS' {_fmt(tot['despesas'])}")
        if not por_grupo:
            self._distribuir_por_conta(dados, razao, contas)
        for r in dados.receitas:
            c = contas.get(_norm(r.conta))
            if c is not None and r.tipo == "rendimento":
                c.rendimento = round(c.rendimento + r.valor, 2)
        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": bool(dados.contas) and bool(dados.receitas),
                           "lancamentos": bool(dados.lancamentos)}

    def _conta(self, nome: str, contas: dict) -> str:
        c = contas.get(_norm(nome))
        return c.nome if c else nome

    def _distribuir_por_conta(self, dados: DadosRegras, razao: dict, contas: dict) -> None:
        """Demonstrativo único (sem conta): a conta de cada lançamento vem do razão 'Movimentação Analítica' (data +
        valor); as receitas passam a ser as linhas de crédito do razão (uma por lançamento bancário, com a conta)."""
        pool: dict = {}
        for conta, itens in razao.items():
            for it in itens:
                pool.setdefault((it["data"], round(abs(it["valor"]), 2), it["valor"] < 0), []).append((conta, it))
        for l in dados.lancamentos:
            chave = (l.data, round(abs(l.valor), 2), l.valor > 0)
            cand = pool.get(chave)
            if cand:
                l.conta = self._conta(cand.pop(0)[0], contas)
        # receita NEGATIVA do analítico (estorno de locação, desconto...) aparece no razão como débito: casa pelo valor
        for r in dados.receitas:
            if r.valor < 0:
                cand = pool.get((None, None, True)) or []
                for chave, restantes in pool.items():
                    if chave[2] and chave[1] == round(-r.valor, 2) and restantes:
                        r.conta = self._conta(restantes.pop(0)[0], contas)
                        break
        # débitos do razão que não são despesa categorizada do analítico (transferência entre contas...)
        for (_, _, debito), restantes in pool.items():
            if not debito:
                continue
            for conta, it in restantes:
                transf = bool(re.search(r"transf", it["desc"], re.I))
                x = LancamentoDespesa(descricao=it["desc"], valor=abs(it["valor"]),
                                      categoria="TRANSFERÊNCIA ENTRE CONTAS" if transf else "SEM CATEGORIA NO ANALÍTICO",
                                      conta=self._conta(conta, contas), data=it["data"], pagina=it["pg"], bbox=it["bbox"])
                x.rubrica, x.conta_arquivo = None, conta
                dados.lancamentos.append(x)
        sem = [l for l in dados.lancamentos if not l.conta]
        if sem:
            ref = next((c.nome for c in contas.values() if c.debitos > 0), next(iter(c.nome for c in contas.values()), ""))
            for l in sem:
                l.conta = ref
            dados.avisos.append(f"{len(sem)} lançamento(s) sem correspondente no razão por conta: atribuídos à conta {ref}")
        if razao:
            novas = []
            for conta, itens in razao.items():
                for it in itens:
                    if it["valor"] > 0:
                        r = LinhaReceita(conta=self._conta(conta, contas), descricao=it["desc"], valor=it["valor"],
                                         tipo=self._tipo_receita(it["desc"], it["desc"]), data=it["data"],
                                         pagina=it["pg"], bbox=it["bbox"])
                        r.categoria = it["desc"]
                        novas.append(r)
            dados.receitas = novas + [r for r in dados.receitas if r.valor < 0]
        else:
            for r in dados.receitas:
                r.conta = r.conta or next(iter(c.nome for c in contas.values()), "")

    def _tipo_receita(self, categoria: str, descricao: str) -> str:
        c, d = _norm(categoria), _norm(descricao)
        if "TRANSFER" in c or "TRANSFER" in d:
            return "transferencia"
        if re.search(r"\bREND", c) or re.search(r"\bREND", d):
            return "rendimento"
        if any(k in c or k in d for k in ("MULTA", "JURO", "ATUALIZ", "HONORAR")):
            return "multa_juros"
        if any(k in c or k in d for k in ("COTA", "CONDOM", "FUNDO", "RATEIO")):
            return "cota"
        return "outra"

    # -- conferência ------------------------------------------------------------------
    def _conferir(self, dados: DadosRegras, contas: dict) -> None:
        """Valida a leitura contra o Resumo Financeiro (créditos e débitos de cada conta/grupo).

        * Receita negativa entra no Resumo ou como MENOS crédito ('Isenção', 'Pagamento a menor') ou como DÉBITO
          ('IR Investimentos'): procura-se a combinação que fecha.
        * O que sobra por conta é transferência entre contas/grupos de saldo (o Resumo diz '(*) Inclui transferência'), que
          o analítico não detalha: vale como explicação quando a soma das sobras de débito é igual à das sobras de crédito
          (a transferência sai de uma conta e entra em outra). Se não for igual, a leitura não é confiável (ex.: PDF
          digitalizado com OCR) e a cobertura vira False."""
        import itertools

        sd: dict = {}
        pos: dict = {}
        neg: dict = {}
        for l in dados.lancamentos:
            sd[_norm(l.conta)] = sd.get(_norm(l.conta), 0.0) + l.valor
        for r in dados.receitas:
            if r.valor >= 0:
                pos[_norm(r.conta)] = pos.get(_norm(r.conta), 0.0) + r.valor
            else:
                neg.setdefault(_norm(r.conta), []).append(-r.valor)
        sobra_cred: dict = {}
        sobra_deb: dict = {}
        for n, c in contas.items():
            p_, ns = pos.get(n, 0.0), neg.get(n, [])
            melhor = None
            for k in (range(len(ns) + 1) if len(ns) <= 10 else (0,)):
                for comb in itertools.combinations(range(len(ns)), k):
                    liq = sum(ns[i] for i in comb)
                    rc = c.creditos - (p_ - liq)                 # crédito do Resumo que as receitas lidas não explicam
                    rd = c.debitos - (sd.get(n, 0.0) + sum(ns) - liq)
                    e = abs(rc) + abs(rd)
                    if melhor is None or e < melhor[0]:
                        melhor = (e, rc, rd)
            if melhor is not None:
                sobra_cred[n], sobra_deb[n] = round(melhor[1], 2), round(melhor[2], 2)
        tc, td = round(sum(sobra_cred.values()), 2), round(sum(sobra_deb.values()), 2)
        limite = max(10.0, 0.005 * sum(c.debitos for c in contas.values()))
        com_sobra = [(contas[n].nome, sobra_cred[n], sobra_deb[n]) for n in contas
                     if abs(sobra_cred[n]) > _CENTAVO or abs(sobra_deb[n]) > _CENTAVO]
        if not com_sobra:
            return
        if abs(tc - td) <= 2 * _CENTAVO:
            partes = "; ".join(f"{nome}: " + ", ".join(x for x in (
                f"+{_fmt(c_)} de crédito" if c_ > 0.011 else (f"{_fmt(c_)} de crédito" if c_ < -0.011 else ""),
                f"+{_fmt(d_)} de débito" if d_ > 0.011 else (f"{_fmt(d_)} de débito" if d_ < -0.011 else "")) if x)
                for nome, c_, d_ in com_sobra)
            dados.avisos.append("o Resumo Financeiro inclui transferência entre contas/grupos de saldo que o analítico não "
                                f"detalha (créditos e débitos extras se anulam: {_fmt(tc)}): {partes}")
            return
        for nome, c_, d_ in com_sobra:
            dados.avisos.append(f"{nome}: o Resumo tem {_fmt(c_)} de crédito e {_fmt(d_)} de débito além do que foi lido")
        if abs(td) > limite or abs(tc) > limite:
            motivo = ("a leitura do texto não fecha com o Resumo Financeiro (provável PDF digitalizado com OCR): créditos "
                      f"não explicados {_fmt(tc)}, débitos não explicados {_fmt(td)}")
            self._sem_leitura(dados, motivo)
            dados.receitas, dados.lancamentos = [], []
