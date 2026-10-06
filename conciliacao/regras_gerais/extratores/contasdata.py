"""
Extrator das regras gerais — PDF ContasData/Lirba ("Prestação de Contas" com índice,
"Voltar ao índice" no rodapé, comprovantes anexos).

O mesmo software imprime, para cada condomínio, os blocos:
  * Resumo Financeiro Contábil  — por conta: saldo anterior, créditos, débitos, saldo atual;
  * Posição Financeira          — por conta: saldo anterior, créditos (por categoria), débitos
                                  (por categoria), saldo atual (linhas "TOTAIS");
  * Demonstrativo de Receitas   — conta > categoria > um recibo por linha (valor com sinal);
  * Demonstrativo de Despesas   — conta > subconta ("TOTAL DA CONTA <subconta>") > [rubrica] >
                                  lançamentos, um por linha (nº do lançamento, data, histórico, valor).
Os comprovantes (centenas de páginas, escaneados) NUNCA são lidos: só as páginas desses blocos.

Cada condomínio muda só detalhes (colunas, nomes de contas/subcontas, se há "Nº lancto." à
esquerda ou o código à direita, se o Demonstrativo de Receitas lista recibos ou só categorias).
Por isso o extrator é guiado pela GEOMETRIA da página (posição das colunas lida no cabeçalho de
cada página), não por posições fixas.

O que o extrator devolve (modelo.py):
  contas       — Resumo Financeiro Contábil (+ rendimento = soma das linhas de rendimento da conta)
  receitas     — uma linha por recibo do Demonstrativo de Receitas, COM SINAL; sem recibos
                 (ex.: Plano & Mooca) usa as linhas de crédito da Posição Financeira
  lancamentos  — um por linha do Demonstrativo de Despesas; `categoria` = a subconta
                 ("TOTAL DA CONTA <subconta>"), `conta` = a conta do Resumo (ORDINÁRIA, FUNDO...)
Também anexa em cada lançamento os atributos informativos `rubrica` (nível abaixo da subconta,
quando o arquivo tem) e `conta_arquivo`; o modelo não os exige.

Extensão por subclasse: `Extrator` é dividido em métodos pequenos (`_reconhecer`,
`_classificar_paginas`, `_ler_resumo`, `_ler_posicao_financeira`, `_ler_receitas`,
`_ler_despesas`, `_conferir`); uma subclasse sobrescreve só o que muda.

Se o arquivo não for ContasData levanta ValueError("formato não reconhecido como ContasData").
"""
import re
import unicodedata
from pathlib import Path
from typing import Optional

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CENTAVO = 0.011
_RE_DINHEIRO = re.compile(r"^[-(]?\d+(?:\.\d{3})*,\d{2}[-)]?$")
_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_PCT = re.compile(r"^-?\d+,\d{2}%$")
_RUIDO = {"ContasData", "Doctos"}


# ── utilidades ───────────────────────────────────────────────────────────────

def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", _sem_acento(s).upper())).strip()


def _num(s: str) -> float:
    """'1.234,56' -> 1234.56 ; '-4,50' / '(4,50)' / '4,50-' -> -4.5."""
    neg = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    v = float(s.strip("()-").replace(".", "").replace(",", "."))
    return -v if neg else v


def _limpar(s: str) -> str:
    """NFC e espaço comum no lugar do espaço sem quebra (alguns arquivos imprimem 'Voltar<NBSP>ao<NBSP>índice')."""
    return unicodedata.normalize("NFC", s).replace(chr(0xA0), " ")


def _fmt(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class _Linha:
    """Uma linha visual da página: palavras (x0, y0, x1, y1, texto) da esquerda para a direita."""
    __slots__ = ("y", "pal", "pg")

    def __init__(self, y, pal, pg):
        self.y, self.pal, self.pg = y, pal, pg

    @property
    def texto(self) -> str:
        return " ".join(w[4] for w in self.pal)

    @property
    def x0(self) -> float:
        return self.pal[0][0]

    @property
    def x1(self) -> float:
        return self.pal[-1][2]

    @property
    def bbox(self) -> tuple:
        return (min(w[0] for w in self.pal), min(w[1] for w in self.pal),
                max(w[2] for w in self.pal), max(w[3] for w in self.pal))

    def dinheiro(self) -> list:
        return [w for w in self.pal if _RE_DINHEIRO.match(w[4])]


def _agrupar_linhas(palavras, pg, tol=3.0) -> list:
    ws = [w for w in palavras if w[4] not in _RUIDO]
    ws.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    grupos, cur, cy = [], [], None
    for w in ws:
        y = (w[1] + w[3]) / 2
        if cy is None or abs(y - cy) <= tol:
            cur.append(w)
            cy = y if cy is None else (cy + y) / 2
        else:
            grupos.append(cur)
            cur, cy = [w], y
    if cur:
        grupos.append(cur)
    out = []
    for g in grupos:
        g.sort(key=lambda w: w[0])
        out.append(_Linha(sum((w[1] + w[3]) / 2 for w in g) / len(g),
                          [(w[0], w[1], w[2], w[3], _limpar(w[4])) for w in g], pg))
    return out


class _Pagina:
    __slots__ = ("n", "texto", "tipo", "_page", "_linhas")

    def __init__(self, n, page, texto):
        self.n, self._page, self.texto, self.tipo, self._linhas = n, page, texto, "outro", None

    @property
    def linhas(self) -> list:
        if self._linhas is None:
            self._linhas = _agrupar_linhas(self._page.get_text("words"), self.n)
        return self._linhas


# ── o extrator ───────────────────────────────────────────────────────────────

class Extrator:
    #: nível usado em LancamentoDespesa.categoria: "subconta" ("TOTAL DA CONTA <subconta>"),
    #: "rubrica" (linha abaixo, quando existe) ou "caminho" ("subconta › rubrica").
    NIVEL_CATEGORIA = "subconta"

    def __init__(self, condo: dict):
        self.condo = condo or {}
        cfg = (self.condo.get("parser_config") or {}).get("regras_gerais") or {}
        self.nivel = cfg.get("nivel_categoria", self.NIVEL_CATEGORIA)

    # -- ponto de entrada ----------------------------------------------------
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        caminho = Path(caminho)
        if caminho.suffix.lower() != ".pdf":
            raise ValueError("formato não reconhecido como ContasData")
        doc = fitz.open(str(caminho))
        try:
            self._nome_condominio = None
            paginas = self._classificar_paginas(doc)
            dados = DadosRegras(mes=mes, arquivo=caminho.name)
            if sum(len(p.texto) for p in paginas[:30]) < 300:
                motivo = ("o PDF é só imagem (sem camada de texto): a leitura exigiria OCR e não há texto confiável para ler "
                          "receitas, rendimentos e lançamentos")
                dados.motivos_nao_cobertos = {"receitas": motivo, "rendimentos": motivo, "lancamentos": motivo}
                dados.avisos.append(motivo)
                return dados
            completo = self._reconhecer(paginas)
            self._periodo_confere(paginas, mes, dados)
            if not completo:
                motivo = ("o arquivo é ContasData mas não traz o Resumo Financeiro Contábil, o Demonstrativo de Receitas "
                          "nem o de Despesas (só índice, gráficos e relação de devedores)")
                dados.motivos_nao_cobertos = {"receitas": motivo, "rendimentos": motivo, "lancamentos": motivo}
                dados.avisos.append(motivo)
                return dados
            contas = self._ler_resumo(paginas, dados)
            pf = self._ler_posicao_financeira(paginas, dados, contas)
            if not contas:
                contas = self._contas_da_posicao(pf)
            por_nome = {_norm(c.nome): c for c in contas}
            dados.contas = contas
            self._ler_receitas(paginas, dados, por_nome, pf)
            self._ler_despesas(paginas, dados, por_nome, pf)
            self._definir_cobertura(dados, contas)
            self._conferir(dados)
            return dados
        finally:
            doc.close()

    # -- reconhecimento do formato --------------------------------------------
    def _classificar_paginas(self, doc) -> list:
        paginas = []
        for i, page in enumerate(doc):
            t = _limpar(page.get_text("text"))
            p = _Pagina(i + 1, page, t)
            p.tipo = self._tipo_pagina(t)
            paginas.append(p)
            if i < 12 and not getattr(self, "_nome_condominio", None):
                m = re.search(r"Condom[ií]nio:\s*\d+\s*-\s*([^\n]+)", t)
                if m:
                    self._nome_condominio = _norm(m.group(1))
        return paginas

    def _tipo_pagina(self, t: str) -> str:
        cab = t[:900]
        if "Comprovante de Despesa" in t[:260] or len(t) < 120 or re.search(r"^\s*[ÍI]ndice\s*$", t[:400], re.M):
            return "outro"
        if re.search(r"Demonstrativo de Despesas", cab, re.I) and re.search(r"Hist[óo]rico", t):
            return "despesas"
        if re.search(r"Demonstrativo de Receitas", cab, re.I) and re.search(r"Hist[óo]rico|Recebido", t):
            return "receitas"
        if re.search(r"Posi[çc][ãa]o Financeira|Resumo Financeiro Cont[áa]bil|Resumo de Receitas|TOTAIS|SALDO ATUAL", t):
            return "contas"
        return "outro"

    def _reconhecer(self, paginas: list) -> bool:
        """Confirma que o arquivo é do software ContasData (marcas do software: 'Voltar ao índice' no rodapé,
        'ContasData' na marca d'água, índice 'Prestação de Contas', 'Nº lancto.'). Levanta ValueError se não for.
        Devolve False quando é ContasData mas não traz os demonstrativos (arquivo parcial, só gráficos/devedores)."""
        inicio = "\n".join(p.texto for p in paginas[:40])
        marcas = re.search(r"Voltar ao [íi]ndice|ContasData|N[ºo°] lancto", inicio, re.I)
        indice = re.search(r"Presta[çc][ãa]o de Contas", inicio) and re.search(r"Condom[ií]nio:\s*\d+\s*-", inicio)
        if not (marcas and indice):
            raise ValueError("formato não reconhecido como ContasData")
        todo = "\n".join(p.texto for p in paginas if p.tipo != "outro")
        resumo = re.search(r"Resumo Financeiro Cont[áa]bil", todo, re.I)
        total_conta = re.search(r"TOTAL DA CONTA", todo, re.I)
        despesas = any(p.tipo == "despesas" for p in paginas)
        return bool(resumo and total_conta and despesas)

    def _periodo_confere(self, paginas: list, mes: str, dados: DadosRegras) -> None:
        """O arquivo pode estar com o nome do mês errado: compara 'Período:' impresso com `mes`."""
        for p in paginas[:12]:
            m = re.search(r"Per[íi]odo:\s*(\d{2})/(\d{2})/(\d{4})\s*a\s*(\d{2})/(\d{2})/(\d{4})", p.texto)
            if m:
                ano, mm = int(m.group(6)), int(m.group(5))
                if f"{ano}-{mm:02d}" != mes:
                    dados.avisos.append(f"o período impresso no arquivo é {mm:02d}/{ano}, não {mes[5:7]}/{mes[:4]}")
                return

    # -- Resumo Financeiro Contábil -------------------------------------------
    def _ler_resumo(self, paginas: list, dados: DadosRegras) -> list:
        contas: list[ContaMes] = []
        em_resumo = False
        for p in paginas:
            if p.tipo not in ("contas", "despesas", "receitas") and not (em_resumo and len(p.texto) > 150):
                continue                              # (a tabela pode continuar numa página sem marcadores)
            for l in p.linhas:
                if re.match(r"^Resumo Financeiro Cont[áa]bil", l.texto, re.I) and re.search(r"Saldo\s+anterior", l.texto, re.I):
                    em_resumo = True                 # (o cabeçalho se repete quando a tabela atravessa a página)
                    continue
                if not em_resumo:
                    continue
                if l.texto.upper().startswith("TOTAL"):
                    return contas
                din = l.dinheiro()
                if len(din) >= 4 and l.texto[:1].isalpha():
                    v = [_num(w[4]) for w in din[-4:]]
                    nome = " ".join(w[4] for w in l.pal if w[2] < din[-4][0] - 0.5).strip()
                    if nome and _norm(nome) not in {_norm(c.nome) for c in contas}:
                        contas.append(ContaMes(nome=nome, saldo_anterior=v[0], creditos=v[1], debitos=v[2],
                                               saldo_atual=v[3], pagina=p.n))
        return contas

    def _contas_da_posicao(self, pf: dict) -> list:
        return [ContaMes(nome=b["nome"], saldo_anterior=b["saldo_anterior"], saldo_atual=b["saldo_atual"],
                         creditos=b["tot_cred"], debitos=b["tot_deb"], pagina=b["pagina"]) for b in pf.values()]

    # -- Posição Financeira ---------------------------------------------------
    def _ler_posicao_financeira(self, paginas: list, dados: DadosRegras, contas: Optional[list] = None) -> dict:
        """{nome_norm: {nome, saldo_anterior, saldo_atual, tot_cred, tot_deb, creditos: [..], debitos: [..], pagina}}
        creditos/debitos = [(descricao, valor, pagina, bbox)]; valor com o sinal em que a coluna o põe
        (uma categoria de CRÉDITO impressa na coluna Débito entra em `creditos` com sinal negativo)."""
        blocos: dict = {}
        atual = None
        col = None
        nome_visto = None            # último nome de conta impresso (o bloco pode começar na página seguinte)
        for p in paginas:
            if p.tipo != "contas":
                continue
            ls = p.linhas
            for i, l in enumerate(ls):
                t = l.texto
                if self._parece_nome_conta(l):
                    nome_visto = t.strip()
                if re.match(r"^Posi[çc][ãa]o Financeira\b", t):
                    col = self._colunas_pf(ls, i) or col
                    if atual is None or atual["fechado"] or (nome_visto and _norm(nome_visto) != _norm(atual["nome"])):
                        nome = nome_visto
                        if nome:
                            atual = {"nome": nome, "saldo_anterior": 0.0, "saldo_atual": 0.0, "tot_cred": 0.0,
                                     "tot_deb": 0.0, "creditos": [], "debitos": [], "pagina": p.n, "fechado": False,
                                     "_ordem": []}
                            blocos[_norm(nome)] = atual
                    continue
                if atual is None or atual["fechado"] or col is None:
                    continue
                self._linha_pf(atual, l, col, p.n)
        resumo = {_norm(c.nome): c for c in (contas or [])}
        for chave, b in blocos.items():
            self._separar_creditos_negativos(b, resumo.get(chave))
        return blocos

    def _colunas_pf(self, ls: list, i: int) -> Optional[dict]:
        cred = deb = None
        for l in ls[i:i + 3]:
            for w in l.pal:
                if w[4].startswith("Cr") and "dito" in w[4]:
                    cred = w[2]
                if w[4].startswith("D") and "bito" in w[4]:
                    deb = w[2]
        return {"cred": cred, "deb": deb} if cred and deb else None

    def _parece_nome_conta(self, l: _Linha) -> bool:
        """Nome de conta impresso sozinho e centralizado (cabeçalho do bloco da conta)."""
        t = l.texto.strip()
        return (l.x0 > 150 and abs((l.x0 + l.x1) / 2 - 312) <= 45 and len(l.pal) <= 8 and not l.dinheiro()
                and not re.match(r"^(Resumo|Realizado|Previsto|Posi|Conta|Saldo|TOTAL)", t, re.I)
                and _norm(t) != getattr(self, "_nome_condominio", None))

    def _linha_pf(self, b: dict, l: _Linha, col: dict, pg: int) -> None:
        t = l.texto
        up = _sem_acento(t).upper()
        din = l.dinheiro()
        if not din:
            return
        if up.startswith("SALDO ANTERIOR"):
            v = _num(din[-1][4])
            devedor = "DEVEDOR" in up or abs(din[-1][2] - col["deb"]) < abs(din[-1][2] - col["cred"])
            b["saldo_anterior"] = -abs(v) if devedor and v else v
            return
        if up.startswith("SALDO ATUAL"):
            v = _num(din[-1][4])
            b["saldo_atual"] = -abs(v) if "DEVEDOR" in up and v else v
            b["fechado"] = True
            return
        if up.startswith("TOTAIS"):
            vs = sorted(din, key=lambda w: w[2])
            if len(vs) >= 2:
                a, c = _num(vs[0][4]), _num(vs[1][4])
                b["tot_deb"], b["tot_cred"] = (a, c) if col["deb"] < col["cred"] else (c, a)
            return
        w = din[-1]
        desc = " ".join(x[4] for x in l.pal if x[2] < din[0][0] - 0.5).strip()
        if not desc:
            return
        lado = "cred" if abs(w[2] - col["cred"]) <= abs(w[2] - col["deb"]) else "deb"
        b["_ordem"].append((lado, desc.strip(" '`´\""), _num(w[4]), pg, l.bbox))

    def _separar_creditos_negativos(self, b: dict, conta: Optional[ContaMes] = None) -> None:
        """A Posição Financeira lista créditos e depois débitos. Uma categoria de CRÉDITO com valor negativo é
        impressa na coluna Débito, no meio dos créditos (Platinum: 'OUTROS LANÇAMENTOS 27,89'); mas uma
        transferência de verdade (débito) também pode aparecer ali (Blue Sky: 'TRANSFERÊNCIA' da aplicação).
        Quem decide é o Resumo Financeiro Contábil: o subconjunto das linhas ambíguas que, tratadas como crédito
        negativo, faz os créditos da Posição fecharem com os créditos do Resumo."""
        ordem = b.pop("_ordem")
        ult_cred = max((i for i, o in enumerate(ordem) if o[0] == "cred"), default=-1)
        ambiguas = [i for i, o in enumerate(ordem) if o[0] == "deb" and i < ult_cred]
        negativas: set = set()
        if ambiguas and conta is not None:
            soma_cred = sum(o[2] for o in ordem if o[0] == "cred")
            import itertools
            for n in range(0, min(len(ambiguas), 5) + 1):
                achou = next((c for c in itertools.combinations(ambiguas, n)
                              if abs(soma_cred - sum(ordem[i][2] for i in c) - conta.creditos) <= _CENTAVO), None)
                if achou is not None:
                    negativas = set(achou)
                    break
        elif ambiguas:
            negativas = set(ambiguas)
        for i, (lado, desc, v, pg, bbox) in enumerate(ordem):
            if lado == "cred":
                b["creditos"].append((desc, v, pg, bbox))
            elif i in negativas:
                b["creditos"].append((desc, -abs(v), pg, bbox))
            else:
                b["debitos"].append((desc, v, pg, bbox))

    # -- Demonstrativo de Receitas --------------------------------------------
    @staticmethod
    def _rodape(l: _Linha) -> bool:
        """Rodapé da página (Gerente / Emitido em / Voltar ao índice)."""
        return l.y >= 830 or re.match(r"^(Gerente:|Emitido em|Voltar ao|Sindico|Síndico)", l.texto) is not None

    def _colunas_cabecalho(self, ls: list, *obrigatorias) -> Optional[tuple]:
        """(índice da linha de cabeçalho, {palavra: (x0, x1)}) — linha com 'Histórico' e 'Valor'."""
        for i, l in enumerate(ls[:30]):
            nomes = {w[4].rstrip(".").lower(): (w[0], w[2]) for w in l.pal}
            if "histórico" in nomes and "valor" in nomes and all(o in nomes for o in obrigatorias):
                return i, nomes
        return None

    def _ler_receitas(self, paginas: list, dados: DadosRegras, contas: dict, pf: dict) -> None:
        """Receitas = uma linha por recibo do Demonstrativo de Receitas (com sinal). Cada conta é lida da MELHOR
        fonte disponível, a que fecha ao centavo com os créditos dela no Resumo Financeiro Contábil:
          1. recibos (Demonstrativo de Receitas com histórico) [+ seção Transferências];
          2. 'Resumo de Receitas'/'Resumo de Recebimentos' (uma linha por categoria);
          3. Posição Financeira (uma linha por categoria de crédito).
        Crédito que só existe na Posição Financeira (ex.: transferência recebida) completa a conta."""
        transf = self._transferencias = self._ler_transferencias(paginas)
        recibos = self._receitas_recibos(paginas, contas)
        orfas = [it for it in recibos if not it.conta]            # recibos fora de qualquer conta (tabela parcial)
        recibos = [it for it in recibos if it.conta]
        extras_neg = [it for it in orfas if it.valor < 0]
        resumo = self._ler_resumo_receitas(paginas, contas)
        recebimentos = self._ler_resumo_recebimentos(paginas, contas)
        if resumo and not recibos:
            extras_neg += self._negativos_recebido(paginas, contas)
        posicao = self._receitas_da_posicao(pf, contas)
        fontes = [("recibos", recibos), ("resumo de receitas", resumo), ("resumo de recebimentos", recebimentos),
                  ("posição financeira", posicao)]
        trans_cred = self._receitas_de_transferencias(transf)
        escolhidas: list = []
        avisos: list[str] = []
        for chave, c in contas.items():
            melhor = None
            for nome_fonte, itens in fontes:
                base = [it for it in itens if _norm(it.conta) == chave]
                if not base:
                    continue
                tr = [it for it in trans_cred if _norm(it.conta) == chave]
                for variante in (base, base + tr, base + self._completar_conta(base, c, pf.get(chave)),
                                 base + tr + self._completar_conta(base + tr, c, pf.get(chave))):
                    erro = abs(sum(x.valor for x in variante) - c.creditos)
                    if erro <= _CENTAVO:
                        melhor = (0.0, nome_fonte, variante)
                        break
                    if melhor is None or erro < melhor[0]:
                        melhor = (erro, nome_fonte, variante)
                if melhor and melhor[0] <= _CENTAVO:
                    break
            if melhor is None:
                tr = [it for it in trans_cred if _norm(it.conta) == chave]
                if tr or abs(c.creditos) > _CENTAVO:
                    melhor = (abs(c.creditos - sum(x.valor for x in tr)), "nenhuma", tr)
                    if abs(c.creditos) > _CENTAVO:
                        avisos.append(f"receitas da conta {c.nome}: não foi possível ler as receitas (créditos do Resumo "
                                      f"{_fmt(c.creditos)})")
            if abs(c.creditos) <= _CENTAVO and (melhor is None or melhor[0] > _CENTAVO):
                melhor = (0.0, "vazio", [])           # conta sem créditos (ex.: só débito negativo/estorno)
            if melhor is not None:
                if melhor[0] > _CENTAVO and melhor[1] != "nenhuma":
                    soma = sum(x.valor for x in melhor[2])
                    avisos.append(f"receitas da conta {c.nome}: as linhas lidas ({melhor[1]}) somam {_fmt(soma)}, créditos do "
                                  f"Resumo {_fmt(c.creditos)} (diferença {_fmt(soma - c.creditos)})")
                escolhidas += melhor[2]
        conhecidas = {_norm(it.conta) for it in escolhidas}
        escolhidas += [it for it in trans_cred if _norm(it.conta) not in contas and _norm(it.conta) not in conhecidas]
        escolhidas += extras_neg
        dados.receitas = escolhidas
        dados.avisos += avisos
        for it in escolhidas:
            c = contas.get(_norm(it.conta))
            if c is not None and it.tipo == "rendimento":
                c.rendimento = round(c.rendimento + it.valor, 2)

    def _receitas_recibos(self, paginas: list, contas: dict) -> list:
        """Demonstrativo de Receitas com histórico: conta > categoria > uma linha por recibo."""
        itens: list[LinhaReceita] = []
        conta = cat = None
        for p in [x for x in paginas if x.tipo == "receitas"]:
            ls = p.linhas
            cab = self._colunas_cabecalho(ls)
            if not cab:
                continue
            ihead, nomes = cab
            val1, hist0 = nomes["valor"][1], nomes["histórico"][0]
            for l in ls[ihead + 1:]:
                if self._rodape(l):
                    continue
                t, up = l.texto, _sem_acento(l.texto).upper()
                if up.startswith("TRANSFERENCIAS") and l.x0 < 70 and not l.dinheiro():
                    break                           # o resto da página é a seção 'Transferências' (lida à parte)
                if up.startswith("TOTAL"):
                    continue
                din = [w for w in l.dinheiro() if abs(w[2] - val1) <= 9]
                data = next((w[4] for w in l.pal if _RE_DATA.match(w[4]) and w[0] < hist0 - 150), None)
                if din and (data or l.x0 >= 100) and len(l.pal) > 1:      # linha só com o valor = subtotal
                    hist = " ".join(w[4] for w in l.pal if w[0] >= hist0 - 3 and w[2] < din[0][0] - 0.5 and w not in din)
                    unid = " ".join(w[4] for w in l.pal if 150 <= w[0] < hist0 - 60 and not _RE_DATA.match(w[4]))
                    it = LinhaReceita(conta=conta or "", descricao=hist.strip(), valor=_num(din[-1][4]),
                                      tipo=self._tipo_receita(cat or "", hist), data=data, pagina=p.n, bbox=l.bbox)
                    it.categoria, it.unidade = cat or "", unid
                    itens.append(it)
                elif not din and not data and l.x0 >= hist0 - 3 and itens:
                    itens[-1].descricao = (itens[-1].descricao + " " + t).strip()
                    itens[-1].bbox = _unir_bbox(itens[-1].bbox, l.bbox)
                elif not din and not data and l.x0 < 70:
                    conta = self._conta_do_resumo(t, contas)
                elif not din and not data and 70 <= l.x0 < 100:
                    cat = t
        for it in itens:
            if it.unidade and it.valor < 0:
                it.descricao = f"{it.descricao} (unidade {it.unidade})"
        return itens

    def _ler_resumo_recebimentos(self, paginas: list, contas: dict) -> list:
        """'Resumo de Recebimentos' (Blue Sky/Rio Bonito): conta com recuo à esquerda, uma linha por categoria,
        'TOTAL <categoria/conta>' e 'TOTAL GERAL RECEITAS'. Atravessa páginas."""
        out: list = []
        conta, ativo = None, False
        for p in paginas:
            if "Comprovante de Despesa" in p.texto[:260] or len(p.texto) < 150:
                continue
            if not ativo and not re.search(r"^Resumo de Recebimentos\s*$", p.texto, re.M):
                continue
            for l in p.linhas:
                t, up = l.texto.strip(), _sem_acento(l.texto).upper()
                if self._rodape(l):
                    continue
                if not ativo:
                    ativo = bool(re.match(r"^Resumo de Recebimentos\s*$", t))
                    continue
                if l.y < 92:
                    continue
                if up.startswith("TOTAL GERAL") or up.startswith("TRANSFERENCIAS"):
                    ativo = False
                    break
                if up.startswith("TOTAL"):
                    continue
                din = l.dinheiro()
                if not din and l.x0 < 100 and len(l.pal) <= 8:
                    conta = self._conta_do_resumo(t, contas)
                elif din and l.x0 >= 100 and conta:
                    desc = " ".join(w[4] for w in l.pal if w[2] < din[-1][0] - 0.5).strip()
                    if desc:
                        r = LinhaReceita(conta=conta, descricao=desc, valor=_num(din[-1][4]),
                                         tipo=self._tipo_receita(desc, desc), pagina=p.n, bbox=l.bbox)
                        r.categoria = desc
                        out.append(r)
        return out

    @staticmethod
    def _novo_estado_transf() -> dict:
        return {"ativo": False, "conta": None, "cred": None, "deb": None, "entradas": []}

    def _ler_transferencias(self, paginas: list) -> dict:
        """Seção 'Transferências' (transferência entre contas), impressa no fim do Demonstrativo de Receitas, no
        fim do Demonstrativo de Despesas ou numa página própria — varre todas as páginas que trazem o título."""
        st = self._novo_estado_transf()
        for p in paginas:
            if "Comprovante de Despesa" in p.texto[:260] or re.search(r"^\s*[ÍI]ndice\s*$", p.texto[:400], re.M):
                continue
            if not st["ativo"] and not re.search(r"^Transfer[êe]ncias\s*$", p.texto, re.M):
                continue
            for l in p.linhas:
                if self._rodape(l) or (st["ativo"] and l.y < 110):
                    continue
                self._linha_transferencia(l, _sem_acento(l.texto).upper(), st)
        vistos: dict = {}                    # a mesma tabela pode vir impressa nos dois demonstrativos (páginas diferentes)
        unicas = []
        for e in st["entradas"]:
            k = (e["lado"], _norm(e["conta"]), e["data"], round(e["valor"], 2))
            if k not in vistos or vistos[k] == e["pg"]:
                vistos.setdefault(k, e["pg"])
                unicas.append(e)
        st["entradas"] = unicas
        return st

    def _linha_transferencia(self, l: _Linha, up: str, st: dict) -> bool:
        """Seção 'Transferências' (depois de TOTAL GERAL RECEITAS ou de TOTAL DAS DESPESAS): transferência entre
        contas, com colunas Débito/Crédito. Lado Débito = saída da conta (vira lançamento); lado Crédito =
        receita tipo 'transferencia'. Devolve True se a linha pertence a essa seção."""
        if not st["ativo"]:
            if up.startswith("TRANSFERENCIAS") and l.x0 < 70 and not l.dinheiro():
                st["ativo"] = True
                return True
            return False
        din = l.dinheiro()
        nomes = {w[4].lower(): w for w in l.pal}
        if up.startswith("TOTAL GERAL"):
            st["ativo"] = False
            return True
        if up.startswith(("TOTAL DAS TRANSF", "TOTAL DA CONTA")):
            return True
        if "débito" in nomes and "crédito" in nomes:
            st["deb"], st["cred"] = nomes["débito"][2], nomes["crédito"][2]
            return True
        data = next((w[4] for w in l.pal if _RE_DATA.match(w[4])), None)
        if din and st["cred"] and (data or l.x0 >= 100):          # (há arquivos sem a coluna Data nesta tabela)
            w = din[-1]
            lado = "cred" if abs(w[2] - st["cred"]) <= abs(w[2] - st["deb"]) else "deb"
            desc = " ".join(x[4] for x in l.pal if x[0] >= 100 and x[2] < din[0][0] - 0.5 and not _RE_DATA.match(x[4])
                            and not re.match(r"^\d{6,9}$", x[4])).strip()
            nl = next((x[4] for x in l.pal if re.match(r"^\d{6,9}$", x[4]) and x[2] < 110), None)
            st["entradas"].append({"lado": lado, "conta": st["conta"] or "", "data": data, "desc": desc, "valor": _num(w[4]),
                                   "pg": l.pg, "bbox": l.bbox, "codigo": nl})
            return True
        if not din and not data and l.x0 < 140 and not up.startswith("TOTAL"):
            st["conta"] = l.texto.strip()
        elif not din and not data and st["entradas"] and l.x0 >= 150:
            e = st["entradas"][-1]                   # continuação do histórico
            e["desc"] = (e["desc"] + " " + l.texto).strip()
            e["bbox"] = _unir_bbox(e["bbox"], l.bbox)
        return True

    def _receitas_de_transferencias(self, st: dict) -> list:
        out = []
        for e in st["entradas"]:
            if e["lado"] == "cred":
                r = LinhaReceita(conta=e["conta"], descricao=e["desc"], valor=e["valor"], tipo="transferencia",
                                 data=e["data"], pagina=e["pg"], bbox=e["bbox"])
                r.categoria = "TRANSFERÊNCIA"
                out.append(r)
        return out

    def _ler_resumo_receitas(self, paginas: list, contas: dict) -> list:
        """'Resumo de Receitas' de cada conta (linhas de categoria + 'Total'), usado quando o arquivo não
        imprime o Demonstrativo de Receitas por recibo com histórico (ex.: Plano & Mooca)."""
        out: list = []
        nome, ativo = None, False
        for p in paginas:
            if p.tipo not in ("contas", "receitas"):
                continue
            for l in p.linhas:
                t = l.texto.strip()
                if self._parece_nome_conta(l):
                    nome, ativo = t, False
                    continue
                if re.match(r"^Resumo de Receitas", t, re.I):
                    ativo = True
                    continue
                if not ativo:
                    continue
                if re.match(r"^(Resumo|Demonstrativo|Posi)", t, re.I) or _sem_acento(t).upper().startswith("TOTAL"):
                    ativo = False
                    continue
                din = l.dinheiro()
                if din:
                    desc = " ".join(w[4] for w in l.pal if w[2] < din[-1][0] - 0.5).strip()
                    if desc:
                        r = LinhaReceita(conta=self._conta_do_resumo(nome or "", contas), descricao=desc,
                                         valor=_num(din[-1][4]), tipo=self._tipo_receita(desc, desc), pagina=p.n,
                                         bbox=l.bbox)
                        r.categoria = desc
                        out.append(r)
        return out

    def _negativos_recebido(self, paginas: list, contas: dict) -> list:
        """Lista de recibos (Unidade | Recibo | Valor | Multa/Desc. | Recebido) sem histórico: guarda só os
        recibos com valor recebido negativo (para a regra de receita negativa)."""
        out: list = []
        nome = None
        for p in paginas:
            if p.tipo not in ("contas", "receitas"):
                continue
            ls = p.linhas
            rec1 = None
            for l in ls:
                if self._parece_nome_conta(l):
                    nome = l.texto.strip()
                    continue
                nomes = {w[4].rstrip(".").lower(): w for w in l.pal}
                if "recebido" in nomes and "unidade" in nomes:
                    rec1 = nomes["recebido"][2]
                    continue
                if rec1 is None:
                    continue
                din = [w for w in l.dinheiro() if abs(w[2] - rec1) <= 9]
                if din and _num(din[-1][4]) < 0 and re.match(r"^\d", l.texto):
                    ref = " ".join(w[4] for w in l.pal if w[2] < din[-1][0] - 150 + 100 and not _RE_DINHEIRO.match(w[4]))
                    r = LinhaReceita(conta=self._conta_do_resumo(nome or "", contas), descricao=f"Recibo {ref}".strip(),
                                     valor=_num(din[-1][4]), tipo="cota", pagina=p.n, bbox=l.bbox)
                    r.categoria = "RECIBO"
                    out.append(r)
        return out

    def _completar_conta(self, itens: list, c: ContaMes, bloco: Optional[dict]) -> list:
        """Crédito que existe na Posição Financeira mas não aparece nas receitas lidas (ex.: 'TRANSFERENCIA' vinda
        de outra conta, que não é recibo): se as categorias que faltam somam exatamente a diferença da conta,
        completam a conta (tipo pela descrição)."""
        if not bloco:
            return []
        falta = round(c.creditos - sum(x.valor for x in itens), 2)
        if abs(falta) <= _CENTAVO:
            return []
        cats = {_norm(getattr(x, "categoria", "") or x.descricao) for x in itens}
        cand = [x for x in bloco["creditos"]
                if _norm(x[0]) not in cats and not _norm(x[0]).startswith(("SALDO", "TOTAIS"))]
        extras = []
        for desc, v, pg, bbox in (_subconjunto(cand, falta) or []):
            r = LinhaReceita(conta=c.nome, descricao=f"{desc} (Posição Financeira)", valor=v,
                             tipo=self._tipo_receita(desc, desc), pagina=pg, bbox=bbox)
            r.categoria = desc
            extras.append(r)
        return extras

    def _receitas_da_posicao(self, pf: dict, contas: dict) -> list:
        out = []
        for chave, b in pf.items():
            c = contas.get(chave)
            nome = c.nome if c else b["nome"]
            for desc, v, pg, bbox in b["creditos"]:
                if _norm(desc).startswith(("SALDO", "TOTAIS")):
                    continue
                out.append(LinhaReceita(conta=nome, descricao=desc, valor=v, tipo=self._tipo_receita(desc, desc),
                                        pagina=pg, bbox=bbox))
        return out

    def _tipo_receita(self, categoria: str, historico: str) -> str:
        h, c = _norm(historico), _norm(categoria)
        if "TRANSFER" in h or "TRANSFER" in c:
            return "transferencia"
        if "RENDIM" in h or "RENDIM" in c:
            return "rendimento"
        for k in ("MULTA", "JURO", "ATUALIZ", "CORRECAO MONET"):
            if k in h or k in c:
                return "multa_juros"
        for k in ("COTA", "CONDOM", "EMISSAO", "FDO", "FUNDO", "REC "):
            if k in c or k in h:
                return "cota"
        return "outra"

    def _conta_do_resumo(self, nome: str, contas: dict) -> str:
        c = contas.get(_norm(nome))
        return c.nome if c else nome.strip()

    # -- Demonstrativo de Despesas -------------------------------------------
    def _ler_despesas(self, paginas: list, dados: DadosRegras, contas: dict, pf: Optional[dict] = None) -> None:
        eventos = []
        for p in self._paginas_despesas(paginas):
            ls = p.linhas
            cab = self._colunas_cabecalho(ls, "total")
            if not cab:
                continue
            ihead, nomes = cab
            col = {"hist0": nomes["histórico"][0], "val1": nomes["valor"][1], "tot1": nomes["total"][1]}
            for l in ls[ihead + 1:]:
                if self._rodape(l):
                    continue
                ev = self._evento_despesa(l, col, p.n)
                if ev:
                    eventos.append(ev)
                    if ev[0] == "fim":              # depois de 'TOTAL DAS DESPESAS' só pode vir a seção Transferências
                        break
            if eventos and eventos[-1][0] == "fim":
                break
        lancs, avisos = self._montar_lancamentos(eventos, contas)
        transf = getattr(self, "_transferencias", None) or self._novo_estado_transf()
        for e in transf["entradas"]:
            if e["lado"] == "deb":
                x = LancamentoDespesa(descricao=e["desc"], valor=e["valor"], categoria="TRANSFERÊNCIA ENTRE CONTAS",
                                      conta=self._conta_do_resumo(e["conta"], contas), codigo=e["codigo"], data=e["data"],
                                      pagina=e["pg"], bbox=e["bbox"])
                x.rubrica, x.conta_arquivo = None, e["conta"]
                lancs.append(x)
        lancs += self._completar_debitos_com_posicao(lancs, contas, pf or {}, avisos)
        dados.lancamentos = lancs
        dados.avisos += avisos

    def _completar_debitos_com_posicao(self, lancs: list, contas: dict, pf: dict, avisos: list) -> list:
        """Débito da conta no Resumo que o Demonstrativo de Despesas não lista (transferência para outra conta
        ou para a aplicação, que não é despesa mas está no débito): se as linhas de DÉBITO da Posição Financeira
        que não são subcontas lidas somam exatamente a diferença, entram como lançamentos com a descrição
        impressa (ex.: 'TRANSFERENCIA'). Não fechando, avisa."""
        extras = []
        for chave, c in contas.items():
            doc = [x for x in lancs if _norm(x.conta) == chave]
            falta = round(c.debitos - sum(x.valor for x in doc), 2)
            if abs(falta) <= _CENTAVO:
                continue
            ja = {_norm(x.categoria) for x in doc} | {_norm(getattr(x, "categoria_base", "")) for x in doc}
            cand = [x for x in pf.get(chave, {}).get("debitos", [])
                    if _norm(x[0]) not in ja and not _norm(x[0]).startswith(("SALDO", "TOTAIS"))]
            achou = _subconjunto(cand, falta)
            if not achou:
                continue
            for desc, v, pg, bbox in achou:
                x = LancamentoDespesa(descricao=f"{desc} (Posição Financeira — não consta do Demonstrativo de Despesas)",
                                      valor=v, categoria=desc.strip(), conta=c.nome, pagina=pg, bbox=bbox)
                x.rubrica, x.conta_arquivo = None, c.nome
                extras.append(x)
        return extras

    def _paginas_despesas(self, paginas: list) -> list:
        """Primeira sequência de páginas consecutivas do Demonstrativo de Despesas que traz 'TOTAL DA CONTA'
        (outras páginas com o mesmo título — Resumo no fim do arquivo, despesas cronológicas — ficam de fora)."""
        corrida: list = []
        for p in paginas:
            if p.tipo == "despesas" and (not corrida or corrida[-1].n == p.n - 1):
                corrida.append(p)
                continue
            if corrida and any(re.search(r"TOTAL DA CONTA", x.texto, re.I) for x in corrida):
                break
            corrida = [p] if p.tipo == "despesas" else []
        return corrida

    def _evento_despesa(self, l: _Linha, col: dict, pg: int):
        t = l.texto
        up = _sem_acento(t).upper()
        if up.startswith("TOTAL DAS DESPESAS") or up.startswith("TOTAL GERAL"):
            return ("fim", None, l)
        din = l.dinheiro()
        val = next((w for w in din if abs(w[2] - col["val1"]) <= 9), None)
        tot = next((w for w in din if abs(w[2] - col["tot1"]) <= 9), None)
        if up.startswith("TOTAL DA CONTA"):
            tk = next((w for w in din if w[2] > col["tot1"] - 25), None)
            nome = " ".join(w[4] for w in l.pal if w[2] < (tk[0] if tk else 1e9) - 0.5)
            nome = re.sub(r"^TOTAL DA CONTA\s*", "", nome, flags=re.I).strip()
            return ("total", (nome, _num(tk[4]) if tk else None), l)
        if val is not None:
            data = next((w[4] for w in l.pal if _RE_DATA.match(w[4]) and w[0] < col["hist0"] - 5), None)
            codigo = next((w[4] for w in l.pal if re.match(r"^\d{4}$", w[4]) and w[0] > col["tot1"] + 20), None)
            nl = next((w[4] for w in l.pal if re.match(r"^\d{6,9}$", w[4]) and w[2] < col["hist0"] - 30), None)
            desc = " ".join(w[4] for w in l.pal
                            if w[0] >= col["hist0"] - 3 and w[2] <= val[0] + 1 and w is not val and w is not tot
                            and not _RE_DATA.match(w[4]) and not _RE_PCT.match(w[4])
                            and not (w[0] > col["tot1"] + 20))
            desc = re.sub(r"\s+", " ", desc).strip()
            return ("lanc", {"data": data, "valor": _num(val[4]), "total": _num(tot[4]) if tot else None,
                             "codigo": nl or codigo, "desc": desc, "pagina": pg}, l)
        if din or _RE_DATA.match(l.pal[0][4]):
            return ("outro", None, l)
        if l.x0 >= col["hist0"] + 25 and abs((l.x0 + l.x1) / 2 - 312) <= 45 and len(l.pal) <= 8:
            return ("conta", t.strip(), l)                      # nome da conta, centralizado na página
        if l.x0 < col["hist0"] - 12:
            return ("grupo", t.strip(), l)
        return ("texto", t.strip(), l)

    def _montar_lancamentos(self, eventos: list, contas: dict):
        lancs: list[LancamentoDespesa] = []
        avisos: list[str] = []
        conta_atual = None
        pend: list = []           # lançamentos da subconta ainda aberta
        grupos_conta: list = []   # [(subconta, total)] da conta atual
        texto: list = []
        prev = [None]             # último lançamento lido
        rubrica = [None]

        def anexar(l, t):
            if prev[0] is not None:
                prev[0].descricao = (prev[0].descricao + " " + t).strip()
                prev[0].bbox = _unir_bbox(prev[0].bbox, l.bbox)

        def esvaziar_texto(proximo_e_lanc: bool):
            if not texto:
                return
            if proximo_e_lanc and (prev[0] is None or prev[0]._fechado):
                if prev[0] is None:
                    rubrica[0] = " ".join(t for t, _ in texto)
                else:
                    for t, l in texto[:-1]:
                        anexar(l, t)
                    rubrica[0] = texto[-1][0]
            else:
                for t, l in texto:
                    anexar(l, t)
            texto.clear()

        grupo_hdr = [None]        # subconta do último cabeçalho de grupo impresso
        ini_conta = [0]           # índice em `lancs` onde a conta atual começa

        def fechar_subconta(nome=None):
            for x in pend:
                x.categoria_base = nome or x._grupo or conta_atual or ""
            lancs.extend(pend)
            pend.clear()
            prev[0] = None
            rubrica[0] = None

        def conferir_conta(nome, valor):
            if valor is None:
                return
            soma = round(sum(x.valor for x in lancs[ini_conta[0]:]), 2)
            if abs(soma - valor) > _CENTAVO:
                avisos.append(f"conta {nome}: lançamentos somam {_fmt(soma)}, total da conta {_fmt(valor)}")

        for kind, dado, l in eventos:
            if kind == "texto":
                texto.append((dado, l))
                continue
            if kind == "lanc":
                esvaziar_texto(True)
                x = LancamentoDespesa(descricao=dado["desc"], valor=dado["valor"], categoria="",
                                      conta=self._conta_do_resumo(conta_atual or "ORDINÁRIA", contas),
                                      codigo=dado["codigo"], data=dado["data"], pagina=dado["pagina"], bbox=l.bbox)
                x._fechado = dado["total"] is not None
                x._grupo = grupo_hdr[0]
                x.rubrica = rubrica[0]
                x.conta_arquivo = conta_atual
                pend.append(x)
                prev[0] = x
                continue
            esvaziar_texto(False)
            if kind == "grupo":
                if pend and _norm(dado) != _norm(grupo_hdr[0] or ""):   # grupo novo sem 'TOTAL DA CONTA' do anterior
                    fechar_subconta()
                if not pend:
                    rubrica[0] = None
                grupo_hdr[0] = dado
                continue
            if kind == "conta":
                if pend:
                    avisos.append(f"lançamentos sem 'TOTAL DA CONTA' antes da conta {dado}")
                    fechar_subconta()
                conta_atual, grupo_hdr[0], ini_conta[0] = dado, None, len(lancs)
                continue
            if kind == "total":
                nome, valor = dado
                total_da_conta = (_norm(nome) == _norm(conta_atual or "")
                                  and not (pend and grupo_hdr[0] and _norm(grupo_hdr[0]) == _norm(conta_atual or "")))
                if pend and not total_da_conta:                     # fecha uma subconta
                    soma = round(sum(x.valor for x in pend), 2)
                    if valor is not None and abs(soma - valor) > _CENTAVO:
                        avisos.append(f"subconta {nome}: lançamentos somam {_fmt(soma)}, 'TOTAL DA CONTA' {_fmt(valor)}")
                    fechar_subconta(nome)
                    grupo_hdr[0] = None
                else:
                    if pend:                                        # conta sem 'TOTAL' por subconta (só cabeçalhos)
                        fechar_subconta()
                    conferir_conta(nome, valor)
                    grupo_hdr[0] = None
        if pend:
            avisos.append("lançamentos no fim do demonstrativo sem 'TOTAL DA CONTA'")
            fechar_subconta(rubrica[0] or conta_atual or "")
        for x in lancs:
            sub = getattr(x, "categoria_base", "") or ""
            rub = getattr(x, "rubrica", None)
            x.categoria = (rub or sub) if self.nivel == "rubrica" else (f"{sub} › {rub}" if self.nivel == "caminho" and rub else sub)
        return lancs, avisos

    # -- cobertura e conferências ---------------------------------------------
    def _definir_cobertura(self, dados: DadosRegras, contas: list) -> None:
        dados.cobertura = {
            "receitas": bool(dados.receitas),
            "rendimentos": bool(contas) and bool(dados.receitas),
            "lancamentos": bool(dados.lancamentos),
        }
        if not dados.cobertura["receitas"]:
            dados.motivos_nao_cobertos["receitas"] = "não foi possível ler o Demonstrativo de Receitas nem a Posição Financeira"
        if not dados.cobertura["rendimentos"]:
            dados.motivos_nao_cobertos["rendimentos"] = "o arquivo não traz o Resumo Financeiro Contábil ou as receitas por conta"
        if not dados.cobertura["lancamentos"]:
            dados.motivos_nao_cobertos["lancamentos"] = "não foi possível ler o Demonstrativo de Despesas"

    def _conferir(self, dados: DadosRegras) -> None:
        """Avisos informativos da extração (a conferência oficial é regras.verificar_extracao)."""
        if not dados.contas:
            dados.avisos.append("Resumo Financeiro Contábil não encontrado")


def _subconjunto(cands: list, alvo: float, max_n: int = 4) -> Optional[list]:
    """Menor subconjunto das linhas (descricao, valor, ...) cuja soma é `alvo` (±0,01); None se não há."""
    import itertools
    for n in range(1, min(max_n, len(cands)) + 1):
        for comb in itertools.combinations(cands, n):
            if abs(sum(x[1] for x in comb) - alvo) <= _CENTAVO:
                return list(comb)
    return None


def _unir_bbox(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
