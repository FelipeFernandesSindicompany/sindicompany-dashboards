"""
Extrator das regras gerais — SK Condomínios (sk_condominios_pdf; condomínio do formato: reserva_verde).

PDF "Prestação de contas" do sistema da Sk Condominio Ltda (90-195 páginas, texto extraível; boa parte são anexos/comprovantes).
Telas usadas (16 meses, abr/2025-jul/2026; o nome do arquivo traz o mês por extenso abreviado: `Prestacao de contas JUL 2026.pdf`):
  BALANCETE CONTÁBIL MENSAL (pág. 5-6 em jul/2026): Saldo anterior por conta financeira, Receitas e Despesas por plano de contas
         (01 RECEITA > 01.01 Cota condominial > 01.01.01 ...; 02 DESPESA > 02.02 Manutenção e conservação > 02.02.04 ...), "Resumo da
         movimentação financeira" por conta financeira (Banco Inter, APLICAÇÃO F. RESERVA): saldo anterior, créditos, débitos, saldo final.
  RAZÃO POR CONTA CONTÁBIL (pág. 79-80): para cada conta contábil folha (código + nome), TODOS os lançamentos do mês:
         data | histórico "FORNECEDOR - descrição - PARC.: n/total - NF: x - CTA. PGTO: Banco Inter" | valor (despesa NEGATIVA,
         receita positiva), seguidos de "Total débito/crédito" e, no fim, "Total geral crédito" / "Total geral débito".
`categoria` do lançamento = "<código> <conta contábil>" (ex.: "02.02.04 Serviço de manutenção"); `conta` = conta financeira de onde saiu
("CTA. PGTO: Banco Inter" -> "Banco Inter"). Receitas: o histórico (PIX RECEBIDO..., "Rendimento da aplicação"); o rendimento é creditado na
conta financeira "APLICAÇÃO ...". Despesas saem do Razão com o sinal trocado (valor pago positivo).
Conferências (viram `avisos`): Σ receitas == "Total geral crédito"; Σ despesas == "Total geral débito"; por conta financeira Σ == créditos/débitos
do "Resumo da movimentação financeira".
"""
import re
import unicodedata
from pathlib import Path
from typing import Optional

from conciliacao.regras_gerais.extratores.top_nine import aplicar_config_receitas_negativas
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CENT = 0.011
_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_NUM = re.compile(r"^\(?-?\d{1,3}(?:\.\d{3})*,\d{2}\)?-?$|^\(?-?\d+,\d{2}\)?-?$")
_RE_COD = re.compile(r"^\d{2}(?:\.\d{2})+$")


def _num(tok: str) -> Optional[float]:
    t = (tok or "").strip()
    if not _RE_NUM.match(t):
        return None
    neg = t.startswith("-") or t.endswith("-") or (t.startswith("(") and t.endswith(")"))
    v = float(t.strip("()-").replace(".", "").replace(",", "."))
    return -v if neg else v


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", _sem_acento(s).upper())).strip()


def _linhas(page, tol: float = 3.0):
    ws = [w for w in page.get_text("words") if w[4].strip()]
    ws.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list = []
    for w in ws:
        yc = (w[1] + w[3]) / 2
        if rows and abs(rows[-1][0] - yc) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    for r in rows:
        r[1].sort(key=lambda w: w[0])
    return [(r[0], r[1]) for r in rows]


def _texto(ws) -> str:
    return " ".join(w[4] for w in ws)


def _tipo_receita(descricao: str, cod: str) -> str:
    n = _norm(descricao)
    if "RENDIMENTO" in n or cod.startswith("01.07"):
        return "rendimento"
    if "JURO" in n or "MULTA" in n:
        return "multa_juros"
    if "COTA" in n or "CONDOMINIO" in n:
        return "cota"
    if "TRANSFER" in n:
        return "transferencia"
    return "outra"


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        doc = fitz.open(str(caminho))
        try:
            pag_bal, pag_razao = [], []
            for i in range(len(doc)):
                t = doc[i].get_text()[:140]
                if "BALANCETE CONTÁBIL MENSAL" in t:
                    pag_bal.append(i)
                elif "RAZÃO POR CONTA CONTÁBIL" in t:
                    pag_razao.append(i)
            totais: dict = {}
            contas = self._contas(doc, pag_bal)
            self._razao(doc, pag_razao, contas, dados, totais)
        finally:
            doc.close()
        for r in dados.receitas:
            if r.tipo == "rendimento":
                for c in contas:
                    if _norm(c.nome) == _norm(r.conta):
                        c.rendimento = round(c.rendimento + r.valor, 2)
        dados.contas = contas
        self._conferir(dados, contas, totais)
        com_rend = [c for c in contas if abs(c.rendimento) > _CENT]
        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": len(com_rend) >= 2, "lancamentos": bool(dados.lancamentos)}
        if not dados.receitas:
            dados.motivos_nao_cobertos["receitas"] = "a tela 'Razão por conta contábil' não foi encontrada neste PDF"
        if not dados.lancamentos:
            dados.motivos_nao_cobertos["lancamentos"] = "a tela 'Razão por conta contábil' não foi encontrada neste PDF"
        if not dados.cobertura["rendimentos"]:
            quais = ", ".join(c.nome for c in com_rend) or "nenhuma"
            dados.motivos_nao_cobertos["rendimentos"] = (
                f"o rendimento ('Rendimento da aplicação') é creditado numa única conta financeira ({quais}); o condomínio tem uma conta "
                "corrente e uma aplicação (fundo de reserva) — não há distribuição entre contas para conferir a proporcionalidade")
        aplicar_config_receitas_negativas(dados, self.condo)
        return dados

    # ── contas financeiras ───────────────────────────────────────────────────
    def _contas(self, doc, paginas) -> list:
        contas: list[ContaMes] = []
        atual: Optional[ContaMes] = None
        em_resumo = False
        for i in paginas:
            for yc, ws in _linhas(doc[i]):
                t = _texto(ws)
                tn = _norm(t)
                if tn.startswith("RESUMO DA MOVIMENTACAO FINANCEIRA"):
                    em_resumo = True
                    continue
                if not em_resumo:
                    continue
                v = next((_num(w[4]) for w in reversed(ws) if _num(w[4]) is not None), None)
                if v is None:
                    if tn and not tn.startswith(("VALOR", "SK CONDOMINIO", "PERIODO", "BALANCETE", "RESUMO")) and ws[0][0] < 140:
                        atual = ContaMes(nome=t.strip(), pagina=i + 1)
                        contas.append(atual)
                    continue
                if atual is None:
                    continue
                if tn.startswith("SALDO ANTERIOR"):
                    atual.saldo_anterior = v
                elif tn.startswith("CREDITOS"):
                    atual.creditos = v
                elif tn.startswith("DEBITOS"):
                    atual.debitos = abs(v)
                elif tn.startswith("SALDO FINAL"):
                    atual.saldo_atual = v
        return [c for c in contas if c.nome]

    # ── Razão por conta contábil ─────────────────────────────────────────────
    def _razao(self, doc, paginas, contas, dados, totais):
        if not paginas:
            return
        cod = nome_conta = ""
        cur = None
        aplicacao = next((c.nome for c in contas if "APLIC" in _norm(c.nome)), None)
        corrente = next((c.nome for c in contas if "APLIC" not in _norm(c.nome)), "CONTA CORRENTE")
        for i in paginas:                       # o título "RAZÃO POR CONTA CONTÁBIL" se repete em cada página do razão
            for yc, ws in _linhas(doc[i]):
                if yc < 70 or yc > 810:
                    continue
                t = _texto(ws)
                tn = _norm(t)
                v_tok = next((w for w in reversed(ws) if _num(w[4]) is not None and w[0] > 440), None)
                if tn.startswith("TOTAL GERAL CREDITO"):
                    totais["credito"] = _num(ws[-1][4])
                    continue
                if tn.startswith("TOTAL GERAL DEBITO"):
                    totais["debito"] = _num(ws[-1][4])
                    continue
                if tn.startswith("TOTAL CREDITO") or tn.startswith("TOTAL DEBITO"):
                    cur = None
                    continue
                if tn.startswith(("DATA HISTORICO", "RAZAO", "PERIODO BASE")):
                    continue
                # cabeçalho de conta contábil: "02.02.04   Serviço de manutenção" (centralizado)
                if _RE_COD.match(ws[0][4]) and v_tok is None:
                    cod = ws[0][4]
                    nome_conta = " ".join(w[4] for w in ws[1:]).strip()
                    cur = None
                    continue
                if _RE_DATA.match(ws[0][4]) and v_tok is not None:
                    tokens = [w[4] for w in ws[1:] if w is not v_tok]
                    cur = {"data": ws[0][4], "tokens": tokens, "valor": _num(v_tok[4]), "cod": cod, "nome": nome_conta,
                           "pagina": i + 1, "bbox": (ws[0][0], min(w[1] for w in ws), v_tok[2], max(w[3] for w in ws))}
                    self._registra(cur, dados, aplicacao, corrente, totais)
                    continue
                if cur is not None and v_tok is None and ws[0][0] >= 100 and not _RE_COD.match(ws[0][4]):
                    cur["tokens"].extend(w[4] for w in ws)                 # histórico que quebrou
                    self._atualiza(cur)

    def _registra(self, cur, dados, aplicacao, corrente, totais=None):
        cod, valor = cur["cod"], cur["valor"]
        texto0 = " ".join(cur["tokens"])
        if _norm(cur["nome"]).startswith("TRANSFERENCIA") or _norm(texto0).startswith("TRANSF"):
            # transferência entre contas (03.01): aparece no razão dos dois lados (débito e crédito), mas não é receita nem despesa
            cur["obj"] = None
            if totais is not None:
                totais.setdefault("transferencias", []).append(valor)
            return
        eh_receita = cod.startswith("01") or (not cod.startswith("02") and valor > 0)
        if eh_receita:
            cur["obj"] = LinhaReceita(conta="", descricao="", valor=valor, tipo="outra", data=cur["data"], pagina=cur["pagina"], bbox=cur["bbox"])
            cur["aplicacao"], cur["corrente"] = aplicacao, corrente
            dados.receitas.append(cur["obj"])
        else:
            cur["obj"] = LancamentoDespesa(descricao="", valor=-valor, categoria=f"{cod} {cur['nome']}".strip(), conta=corrente,
                                           codigo=None, data=cur["data"], pagina=cur["pagina"], bbox=cur["bbox"])
            dados.lancamentos.append(cur["obj"])
        self._atualiza(cur)

    @staticmethod
    def _atualiza(cur):
        if cur.get("obj") is None:
            return
        texto = re.sub(r"\s+", " ", " ".join(cur["tokens"])).strip()
        mc = re.search(r"CTA\.?\s*PGTO:\s*(.+)$", texto, re.I)
        conta = mc.group(1).strip() if mc else None
        texto = re.sub(r"\s*-?\s*CTA\.?\s*PGTO:.*$", "", texto, flags=re.I).strip(" -")
        texto = re.sub(r"\bPARC\.?:", "PARC", texto)                 # "PARC.: 16/36" -> "PARC 16/36" (o regex da regra não aceita ":")
        texto = re.sub(r"NF:\s*\(\s*\d+\s*/\s*\d+\s*\)", "", texto).strip(" -")   # "NF: ( 16 / 36 )" é a própria parcela repetida
        obj = cur["obj"]
        obj.descricao = texto
        if isinstance(obj, LancamentoDespesa):
            if conta:
                obj.conta = conta
            partes = [p.strip() for p in re.split(r"\s+-\s+", texto) if p.strip()]
            if len(partes) >= 2:
                obj.fornecedor = partes[0]
        else:
            obj.tipo = _tipo_receita(texto, cur["cod"])
            obj.conta = cur["aplicacao"] if (obj.tipo == "rendimento" and cur["aplicacao"]) else cur["corrente"]

    # ── conferências ─────────────────────────────────────────────────────────
    def _conferir(self, dados, contas, totais):
        s_rec = round(sum(r.valor for r in dados.receitas), 2)
        s_des = round(sum(l.valor for l in dados.lancamentos), 2)
        transf = totais.get("transferencias", [])
        t_cred = round(sum(v for v in transf if v > 0), 2)
        t_deb = round(sum(-v for v in transf if v < 0), 2)
        if transf:
            dados.avisos.append(f"{len(transf)} lançamento(s) de transferência entre contas (R$ {t_deb:,.2f} de débito / R$ {t_cred:,.2f} de crédito, "
                                "conta 03.01) estão no razão e foram ignorados: não são receita nem despesa")
        if totais.get("credito") is not None and abs(s_rec + t_cred - totais["credito"]) > _CENT:
            dados.avisos.append(f"Σ receitas lidas + transferências ({s_rec + t_cred:,.2f}) difere de 'Total geral crédito' ({totais['credito']:,.2f})")
        if totais.get("debito") is not None and abs(s_des + t_deb - abs(totais["debito"])) > _CENT:
            dados.avisos.append(f"Σ lançamentos lidos + transferências ({s_des + t_deb:,.2f}) difere de 'Total geral débito' ({abs(totais['debito']):,.2f})")
        for c in contas:
            cr = round(sum(r.valor for r in dados.receitas if _norm(r.conta) == _norm(c.nome)), 2)
            de = round(sum(l.valor for l in dados.lancamentos if _norm(l.conta) == _norm(c.nome)), 2)
            if abs(cr - c.creditos) > _CENT:
                dados.avisos.append(f"conta {c.nome}: Σ receitas lidas ({cr:,.2f}) difere dos Créditos do resumo ({c.creditos:,.2f})")
            if abs(de - c.debitos) > _CENT:
                dados.avisos.append(f"conta {c.nome}: Σ lançamentos lidos ({de:,.2f}) difere dos Débitos do resumo ({c.debitos:,.2f})")
