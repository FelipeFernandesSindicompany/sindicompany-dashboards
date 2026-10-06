"""
Extrator das regras gerais — PDF "Balancete Mensal" (administradoras Iello e Lello).

Condomínios deste formato: giardino_d_italia, vita_parque (iello_pdf) e jau_1894 (lello_pdf) —
os três usam exatamente o mesmo template de 2-3 páginas:

    Balancete Mensal / "<código> - <CONDOMÍNIO>" / Período dd/mm/aaaa até dd/mm/aaaa
    COMPOSIÇÃO DE ARRECADAÇÃO           (visão por origem do dinheiro; só totais por categoria)
    RESUMO DE ACORDOS
    COMPOSIÇÃO RECEITAS ORDINÁRIAS      (créditos da conta ordinária "CONTA CONDOMINIO", por categoria)
    COMPOSIÇÃO DESPESAS ORDINÁRIA       (débitos da conta ordinária, por CATEGORIA — sem lançamentos)
    RECEBIMENTO DE CONTAS EXTRAORDINÁRIAS (créditos das demais contas, por categoria, sem dividir por conta)
    DESPESAS DE CONTAS EXTRAORDINÁRIAS  (débitos por conta extraordinária — só o total de cada conta)
    RESUMO DE INADIMPLÊNCIA
    RESUMO FINANCEIRO                   (por conta: saldo anterior, créditos, débitos, saldo final)

O que o arquivo NÃO traz (e portanto não é inventado aqui):
  - lançamentos individuais de despesa (fornecedor, NF, parcela, data): só categorias com total;
  - linha de rendimento/aplicação financeira: os créditos dos fundos são só arrecadação;
  - receitas por unidade/recibo.
Por isso: cobertura["receitas"]=True (linhas de receita com sinal), ["rendimentos"]=False e
["lancamentos"]=False, cada qual com o motivo.

As categorias de despesa e as contas ficam disponíveis (para uma futura regra de subcontas em
nível de categoria) em atributos extras do objeto devolvido — `dados.categorias_despesa` e
`dados.totais_secoes` —, sem alterar o modelo.

Conferências internas (viram `avisos` só quando FALHAM):
  soma da COMPOSIÇÃO DESPESAS ORDINÁRIA = "TOTAL" = débito da conta ordinária;
  soma das receitas ordinárias = "TOTAL" = crédito da conta ordinária;
  soma de RECEBIMENTO DE CONTAS EXTRAORDINÁRIAS = soma dos créditos das demais contas;
  soma de DESPESAS DE CONTAS EXTRAORDINÁRIAS = soma dos débitos das demais contas;
  linha "SALDO FINAL" = soma das contas; saldo ant. + créditos + débitos = saldo final em cada conta;
  período impresso = mês pedido.
"""
import re
import unicodedata
from pathlib import Path

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LinhaReceita

_CENTAVO = 0.011
_NUM = r"\(?-?\d{1,3}(?:\.\d{3})*,\d{2}-?\)?"
_RE_FIM_VALOR = re.compile(rf"^(?P<nome>.+?)\s+(?P<val>{_NUM})\s*$")
_RE_QUATRO = re.compile(rf"^(?P<nome>.+?)\s+(?P<a>{_NUM})\s+(?P<b>{_NUM})\s+(?P<c>{_NUM})\s+(?P<d>{_NUM})\s*$")
_RE_PERIODO = re.compile(r"Per[ií]odo\s+(\d{2})/(\d{2})/(\d{4})\s+at[eé]\s+(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE)

# cabeçalhos de seção (texto sem acento, maiúsculo) -> chave
_SECOES = [
    (re.compile(r"^COMPOSICAO DE ARRECADACAO"), "arrecadacao"),
    (re.compile(r"^RESUMO DE ACORDOS"), "acordos"),
    (re.compile(r"^COMPOSICAO RECEITAS? ORDINARIAS?"), "rec_ord"),
    (re.compile(r"^COMPOSICAO DESPESAS? ORDINARIAS?"), "desp_ord"),
    (re.compile(r"^RECEBIMENTO DE CONTAS EXTRAORDINARIAS?"), "rec_ext"),
    (re.compile(r"^DESPESAS? DE CONTAS EXTRAORDINARIAS?"), "desp_ext"),
    (re.compile(r"^RESUMO DE INADIMPLENCIA"), "inad"),
    (re.compile(r"^RESUMO FINANCEIRO"), "resumo"),
    (re.compile(r"^SALDO CAIXA LOCAL"), "caixa"),
]
_TITULOS = {
    "arrecadacao": "COMPOSIÇÃO DE ARRECADAÇÃO", "acordos": "RESUMO DE ACORDOS",
    "rec_ord": "COMPOSIÇÃO RECEITAS ORDINÁRIAS", "desp_ord": "COMPOSIÇÃO DESPESAS ORDINÁRIA",
    "rec_ext": "RECEBIMENTO DE CONTAS EXTRAORDINÁRIAS", "desp_ext": "DESPESAS DE CONTAS EXTRAORDINÁRIAS",
    "inad": "RESUMO DE INADIMPLÊNCIA", "resumo": "RESUMO FINANCEIRO",
}
_IGNORAR_CABECALHO = re.compile(r"^(PERIODO\b|BALANCETE\b|DESCRICAO\b|\d+\s*-\s)")
_CONTA_ORDINARIA = ("CONTA CONDOMINIO", "ORDINARIA", "ORDINARIO")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _num(s: str) -> float:
    """'1.234,56' -> 1234.56; '-5,06', '5,06-' e '(5,06)' -> negativo (sinal exatamente como impresso)."""
    t = s.strip()
    neg = t.startswith("-") or t.endswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("()-").replace(".", "").replace(",", ".")
    return -float(t) if neg else float(t)


def _tipo_receita(nome: str) -> str:
    n = _sem_acento(nome).upper()
    if "RENDIMENTO" in n or "APLICACAO" in n or "JUROS S/" in n:
        return "rendimento"
    if "TRANSF" in n:
        return "transferencia"
    if "MULTA" in n or "CORRECAO" in n or "JURO" in n:
        return "multa_juros"
    if "COTA" in n or "ATRASO" in n or "ANTECIP" in n or "ACORDO" in n or "ARRECADA" in n or "DEVEDORES" in n:
        return "cota"
    return "outra"


def _fmt(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    # ── leitura do PDF ───────────────────────────────────────────────────────
    @staticmethod
    def _linhas(caminho: Path) -> list[dict]:
        """Linhas de texto do PDF com página (1-based) e bbox em pontos pdfplumber."""
        import pdfplumber
        out = []
        with pdfplumber.open(str(caminho)) as pdf:
            for pg in pdf.pages:
                for ln in pg.extract_text_lines(return_chars=False):
                    t = (ln.get("text") or "").strip()
                    if t:
                        out.append({"t": t, "pag": pg.page_number,
                                    "bbox": (round(ln["x0"], 2), round(ln["top"], 2), round(ln["x1"], 2), round(ln["bottom"], 2))})
        return out

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        linhas = self._linhas(Path(caminho))
        if not linhas:
            raise ValueError("PDF sem texto extraível (esperado o 'Balancete Mensal' com texto)")
        if not any("BALANCETE MENSAL" in _sem_acento(l["t"]).upper() for l in linhas[:6]):
            raise ValueError("o PDF não parece um 'Balancete Mensal' Iello/Lello (título não encontrado)")

        itens: dict[str, list] = {k: [] for k in _TITULOS}          # linhas "nome valor" por seção
        totais: dict[str, list] = {k: [] for k in _TITULOS}         # linhas "TOTAL valor" por seção
        contas_linhas: list[dict] = []                              # Resumo Financeiro
        saldo_final_linha = None
        periodo = None
        secao = None
        cabecalhos_estranhos: list[str] = []

        for l in linhas:
            t = l["t"]
            up = _sem_acento(t).upper()
            mp = _RE_PERIODO.search(t)
            if mp and periodo is None:
                periodo = mp.groups()
            novo = next((chave for rx, chave in _SECOES if rx.match(up)), None)
            if novo:
                secao = novo
                continue
            if secao is None:
                continue
            if secao == "resumo":
                m4 = _RE_QUATRO.match(t)
                if m4:
                    reg = {"nome": m4["nome"].strip(), "ant": _num(m4["a"]), "cred": _num(m4["b"]), "deb": _num(m4["c"]),
                           "atual": _num(m4["d"]), "pag": l["pag"], "bbox": l["bbox"]}
                    if _sem_acento(reg["nome"]).upper() == "SALDO FINAL":
                        saldo_final_linha = reg
                    else:
                        contas_linhas.append(reg)
                    continue
            mv = _RE_FIM_VALOR.match(t)
            if mv and secao not in ("resumo", "caixa", "inad"):
                nome, val = mv["nome"].strip(), _num(mv["val"])
                if _sem_acento(nome).upper() == "TOTAL":
                    totais[secao].append(val)
                else:
                    itens[secao].append({"nome": nome, "valor": val, "pag": l["pag"], "bbox": l["bbox"]})
                continue
            if mv:
                continue
            if _IGNORAR_CABECALHO.match(up) or secao in ("caixa",):
                continue
            if t.upper() == t and len(t) > 3 and not re.search(r"\d", t) and secao in ("rec_ord", "desp_ord", "rec_ext", "desp_ext", "arrecadacao"):
                cabecalhos_estranhos.append(f"{t} (pág. {l['pag']})")

        # ── contas ──────────────────────────────────────────────────────────
        # `debitos` guardado em valor positivo (o PDF imprime negativo), como nas demais planilhas.
        for r in contas_linhas:
            dados.contas.append(ContaMes(nome=r["nome"], saldo_anterior=r["ant"], saldo_atual=r["atual"],
                                         creditos=r["cred"], debitos=abs(r["deb"]), rendimento=0.0, pagina=r["pag"]))
        conta_ord = next((c for c in dados.contas if any(k in _sem_acento(c.nome).upper() for k in _CONTA_ORDINARIA)), None)
        nome_ord = conta_ord.nome if conta_ord else "CONTA CONDOMINIO"

        # ── receitas (com sinal) ────────────────────────────────────────────
        for it in itens["rec_ord"]:
            dados.receitas.append(LinhaReceita(
                conta=nome_ord, descricao=it["nome"], valor=it["valor"], tipo=_tipo_receita(it["nome"]),
                pagina=it["pag"], local=f"{_TITULOS['rec_ord']}", bbox=it["bbox"]))
        for it in itens["rec_ext"]:
            dados.receitas.append(LinhaReceita(
                conta="CONTAS EXTRAORDINÁRIAS", descricao=it["nome"], valor=it["valor"], tipo=_tipo_receita(it["nome"]),
                pagina=it["pag"], local=f"{_TITULOS['rec_ext']} (o arquivo não separa por conta)", bbox=it["bbox"]))
        # Seções "visão por origem" (arrecadação/acordos) repetem os mesmos valores por outro recorte;
        # não entram como receita (duplicariam o total) — mas um valor NEGATIVO ali também é receita
        # negativa e é registrado.
        for chave in ("arrecadacao", "acordos"):
            for it in itens[chave]:
                ja_lida = any(r.descricao == it["nome"] and abs(r.valor - it["valor"]) < _CENTAVO for r in dados.receitas)
                if it["valor"] < -_CENTAVO and not ja_lida:      # mesma linha já lida na receita ordinária/extraordinária
                    dados.receitas.append(LinhaReceita(
                        conta="COMPOSIÇÃO DE ARRECADAÇÃO" if chave == "arrecadacao" else "RESUMO DE ACORDOS",
                        descricao=it["nome"], valor=it["valor"], tipo=_tipo_receita(it["nome"]),
                        pagina=it["pag"], local=_TITULOS[chave], bbox=it["bbox"]))

        # ── despesas por categoria (extra, fora do modelo) ──────────────────
        dados.categorias_despesa = [
            {"categoria": it["nome"], "valor": -it["valor"], "conta": nome_ord, "pagina": it["pag"]} for it in itens["desp_ord"]]
        dados.totais_secoes = {k: totais[k][-1] if totais[k] else None for k in totais}
        # Mesmas categorias no campo oficial do modelo (regra 8 em nível de categoria,
        # regras.py::regra_subcontas_categorias): {categoria: total do mês}.
        dados.categorias = {}
        for it in itens["desp_ord"]:
            dados.categorias[it["nome"]] = dados.categorias.get(it["nome"], 0.0) + (-it["valor"])

        # ── cobertura ───────────────────────────────────────────────────────
        dados.cobertura = {"receitas": bool(itens["rec_ord"]) and bool(dados.contas), "rendimentos": False, "lancamentos": False}
        if not dados.cobertura["receitas"]:
            dados.motivos_nao_cobertos["receitas"] = "não foi possível localizar a COMPOSIÇÃO RECEITAS ORDINÁRIAS / RESUMO FINANCEIRO no PDF"
        dados.motivos_nao_cobertos["rendimentos"] = (
            "o balancete deste formato não traz rendimento por conta: o Resumo Financeiro mostra só saldo anterior, créditos, "
            "débitos e saldo final de cada conta, sem linha de rendimento/aplicação")
        dados.motivos_nao_cobertos["lancamentos"] = (
            "o balancete deste formato lista só as categorias de despesa com o total de cada uma, sem os lançamentos "
            "individuais (fornecedor, NF, parcela, data)")

        # ── conferências (avisos só se falharem) ────────────────────────────
        av = dados.avisos
        if periodo:
            d1, m1, a1, d2, m2, a2 = periodo
            if f"{a1}-{m1}" != mes or f"{a2}-{m2}" != mes:
                av.append(f"o período impresso no PDF é {d1}/{m1}/{a1} a {d2}/{m2}/{a2}, diferente do mês pedido ({mes[5:]}/{mes[:4]})")
        else:
            av.append("não foi possível ler o período impresso no PDF para confirmar o mês")
        for c in cabecalhos_estranhos:
            av.append(f"linha de cabeçalho não reconhecida no PDF ({c}); a leitura da seção pode estar incompleta")
        if not dados.contas:
            av.append("RESUMO FINANCEIRO não encontrado: sem saldos/créditos/débitos por conta")
            return dados

        def _cmp(rotulo, soma, ref, ref_rotulo):
            if ref is not None and abs(soma - ref) > _CENTAVO:
                av.append(f"{rotulo} somam {_fmt(soma)}, mas {ref_rotulo} é {_fmt(ref)} (diferença de {_fmt(soma - ref)})")

        s_desp = sum(it["valor"] for it in itens["desp_ord"])
        if not itens["desp_ord"]:
            av.append("COMPOSIÇÃO DESPESAS ORDINÁRIA não encontrada")
        else:
            _cmp("as categorias da COMPOSIÇÃO DESPESAS ORDINÁRIA", s_desp, totais["desp_ord"][-1] if totais["desp_ord"] else None, 'o "TOTAL" impresso')
            if conta_ord:
                _cmp("as categorias da COMPOSIÇÃO DESPESAS ORDINÁRIA", -s_desp, conta_ord.debitos, f"o débito da conta {conta_ord.nome} no Resumo Financeiro")
        s_rec = sum(it["valor"] for it in itens["rec_ord"])
        _cmp("as linhas da COMPOSIÇÃO RECEITAS ORDINÁRIAS", s_rec, totais["rec_ord"][-1] if totais["rec_ord"] else None, 'o "TOTAL" impresso')
        if conta_ord:
            _cmp("as linhas da COMPOSIÇÃO RECEITAS ORDINÁRIAS", s_rec, conta_ord.creditos, f"o crédito da conta {conta_ord.nome} no Resumo Financeiro")
        outras = [c for c in dados.contas if c is not conta_ord]
        s_rext = sum(it["valor"] for it in itens["rec_ext"])
        _cmp("as linhas de RECEBIMENTO DE CONTAS EXTRAORDINÁRIAS", s_rext, totais["rec_ext"][-1] if totais["rec_ext"] else None, 'o "TOTAL" impresso')
        _cmp("as linhas de RECEBIMENTO DE CONTAS EXTRAORDINÁRIAS", s_rext, sum(c.creditos for c in outras), "a soma dos créditos das demais contas no Resumo Financeiro")
        s_dext = -sum(it["valor"] for it in itens["desp_ext"])
        _cmp("as linhas de DESPESAS DE CONTAS EXTRAORDINÁRIAS", s_dext, -totais["desp_ext"][-1] if totais["desp_ext"] else None, 'o "TOTAL" impresso')
        _cmp("as linhas de DESPESAS DE CONTAS EXTRAORDINÁRIAS", s_dext, sum(c.debitos for c in outras), "a soma dos débitos das demais contas no Resumo Financeiro")
        if saldo_final_linha:
            for campo, soma in (("ant", sum(c.saldo_anterior for c in dados.contas)), ("cred", sum(c.creditos for c in dados.contas)),
                                ("deb", -sum(c.debitos for c in dados.contas)), ("atual", sum(c.saldo_atual for c in dados.contas))):
                _cmp(f"as contas do Resumo Financeiro (coluna {campo})", soma, saldo_final_linha[campo], 'a linha "SALDO FINAL"')
        for c in dados.contas:
            esperado = c.saldo_anterior + c.creditos - c.debitos
            if abs(esperado - c.saldo_atual) > _CENTAVO:
                av.append(f"conta {c.nome}: saldo anterior + créditos − débitos = {_fmt(esperado)}, mas o saldo final impresso é {_fmt(c.saldo_atual)}")
        return dados
