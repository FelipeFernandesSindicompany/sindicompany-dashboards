"""
Extrator das regras gerais — NYC (Cond. Edifício NYC, Berrini; administradora Manager ADM / sistema Webware).

O condomínio chega em DOIS formatos de PDF com o MESMO conteúdo (confirmado jul/2026 e em todos os meses):
  1. "Pasta Digital" da Manager ADM (`Prestação de Contas MM.AAAA.pdf`, 50-100 MB, ~415 pág.; é o arquivo que o Admin
     recebe): capa + índice "Demonstrativo de Contas / Receitas / Despesas" no layout ContasData. As seções úteis
     repetem o título em toda página ("Demonstrativo de Receitas", "Demonstrativo de Despesas",
     "Resumo Financeiro Contábil"); o resto (comprovantes, devedores, correspondência) é ignorado.
  2. Impressão da tela Webware `MMAAAA.pdf` (2-3 MB, ~43 pág.): as mesmas tabelas em sequência, sem repetir o título.
O extrator lê os dois com a mesma lógica (as colunas vêm do cabeçalho "Data ... Histórico ... Valor [Total]" de cada
seção, não de posições fixas; só o espaçamento de linha que separa "histórico que quebrou" de "cabeçalho de subconta"
é calibrado por layout).

Estrutura lida:
  contas        "Resumo Financeiro Contábil": ORDINARIA / FUNDO DE OBRAS / FUNDO DE FUNCIONARIOS com Saldo anterior,
                Créditos, Débitos e Saldo atual (a ORDINARIA tem saldo CONTÁBIL devedor; os fundos são credores).
  receitas      "Demonstrativo de Receitas": conta > categoria (RECEBIMENTO DE COTAS EM ATRASO, TAXA CONDOMINIAL MENSAL,
                GAS, AGUA, LUZ, RECEITA FINANCEIRA, JUROS...) > uma linha por recibo (data, unidade, recibo,
                vencimento, histórico, valor COM SINAL). Fecha em "TOTAL GERAL".
  lancamentos   "Demonstrativo de Despesas": conta > grupo (PESSOAL, CONSUMO, CONTRATOS, MANUTENCAO, IMPOSTOS E TAXAS,
                OUTROS...) > subconta (SALARIOS, AGUA, TERCEIRIZACAO LIMPEZA...) > lançamentos (data, histórico, valor);
                a última linha de cada subconta traz o total e o %; fecha em "TOTAL DAS DESPESAS".
                `categoria` = "GRUPO > SUBCONTA" (BOMBAS existe em CONTRATOS e em MANUTENCAO).
Conferências (viram `avisos` se não fecharem): Σ receitas == TOTAL GERAL; Σ lançamentos == TOTAL DAS DESPESAS;
Σ por subconta == total impresso da subconta; créditos/débitos de cada conta do Resumo == Σ das linhas dela.
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


_TIPO_RECEITA = [
    ("RECEITA FINANCEIRA", "rendimento"), ("RENDIMENTO", "rendimento"),
    ("JUROS", "multa_juros"), ("MULTA", "multa_juros"), ("ATUALIZACAO MONETARIA", "multa_juros"),
    ("COTAS", "cota"), ("TAXA CONDOMINIAL", "cota"),
]


def _tipo_receita(categoria: str) -> str:
    n = _norm(categoria)
    for chave, tipo in _TIPO_RECEITA:
        if chave in n:
            return tipo
    return "outra"


_RE_MES_ABREV = re.compile(r"(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\w*/?\d*")


def _fornecedor(historico: str) -> Optional[str]:
    """O fornecedor é o último trecho do histórico ("JUL/26 - NF 1553741 - VILA VELHA SERVICOS"). Sem separador " - "
    (ex.: "TARIFA BANCARIA", "CARTÃO DE PONTO") o arquivo não traz fornecedor."""
    partes = [p.strip() for p in re.split(r"\s+[-–]\s+", historico) if p.strip()]
    if len(partes) < 2:
        return None
    ult = partes[-1]
    if re.fullmatch(r"[\d/.,\s]+", ult) or _RE_MES_ABREV.fullmatch(_norm(ult).replace(" ", "")):
        return None
    return ult if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", ult)) >= 3 else None


def _marca_parcela(historico: str) -> str:
    """NYC escreve parcelas como "02/02", "04/06" (sem a palavra PARC). Acrescenta "[PARC n/total]" para as regras
    reconhecerem a série. "dd/mm" de data é descartado exigindo n <= total <= 36 e total >= 2 (um dia 25/06 não passa)."""
    if re.search(r"\bPARC", historico, re.I):
        return historico
    for m in re.finditer(r"(?<![\d/])(\d{2})/(\d{2})(?![\d/])", historico):
        n, t = int(m.group(1)), int(m.group(2))
        if 1 <= n <= t <= 36 and t >= 2:
            return f"{historico} [PARC {n:02d}/{t:02d}]"
    return historico


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    # ── leitura ──────────────────────────────────────────────────────────────
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        doc = fitz.open(str(caminho))
        totais: dict = {}
        contas: list[ContaMes] = []
        try:
            pasta_digital = any("Voltar ao índice" in doc[i].get_text() for i in range(min(len(doc), 4)))
            self._ler(doc, pasta_digital, dados, contas, totais)
        finally:
            doc.close()
        dados.contas = contas

        # o arquivo declara o período no cabeçalho: avisa se não é o mês pedido (ex.: 052025.pdf traz 06/2025)
        if totais.get("periodo") and totais["periodo"] != mes:
            dados.avisos.append(f"o arquivo declara o período {totais['periodo'][5:]}/{totais['periodo'][:4]}, "
                                f"diferente do mês pedido ({mes[5:]}/{mes[:4]}) — o arquivo pode estar trocado")

        # rendimento por conta = Σ linhas da categoria RECEITA FINANCEIRA (líquido da provisão de IR)
        por_nome = {_norm(c.nome): c for c in contas}
        for r in dados.receitas:
            if r.tipo == "rendimento":
                c = por_nome.get(_norm(r.conta))
                if c is not None:
                    c.rendimento = round(c.rendimento + r.valor, 2)

        self._conferir(dados, contas, totais)
        com_rend = [c for c in contas if abs(c.rendimento) > _CENT]
        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": bool(contas) and len(com_rend) >= 2,
                           "lancamentos": bool(dados.lancamentos)}
        if not dados.receitas:
            dados.motivos_nao_cobertos["receitas"] = "o 'Demonstrativo de Receitas' não foi encontrado/legível neste PDF"
        if not dados.lancamentos:
            dados.motivos_nao_cobertos["lancamentos"] = "o 'Demonstrativo de Despesas' não foi encontrado/legível neste PDF"
        if not dados.cobertura["rendimentos"]:
            quais = ", ".join(c.nome for c in com_rend) or "nenhuma"
            dados.motivos_nao_cobertos["rendimentos"] = (
                f"neste mês o rendimento da aplicação (RENTAB.INVEST ... menos a provisão de IR) foi lançado em apenas {len(com_rend)} "
                f"conta(s) ({quais}); a ORDINARIA tem saldo contábil devedor e o balancete não distribui o rendimento entre "
                "as contas — não há proporcionalidade a conferir")
        aplicar_config_receitas_negativas(dados, self.condo)
        return dados

    # ── varredura das páginas ────────────────────────────────────────────────
    def _ler(self, doc, pasta_digital: bool, dados: DadosRegras, contas: list, totais: dict):
        modo = None                      # None | "receitas" | "despesas" | "resumo"
        cab: dict = {}                   # colunas do último cabeçalho de cada seção
        st = {"conta": "ORDINARIA", "cat": "", "grupo": "", "sub": "", "espera_grupo": False}
        nomes_contas: set = set()
        # Histórico que quebra em 2-3 linhas fica a ~6,7 pt (Webware, linhas a 18-22 pt) ou ~7,9 pt (Pasta Digital, linhas a
        # ~10 pt) da linha-âncora; um cabeçalho de subconta ocupa uma linha inteira. Medido nos dois layouts, todos os meses.
        gap_max = 8.5 if pasta_digital else 12.0
        for pi in range(len(doc)):
            texto_pag = doc[pi].get_text()
            if pasta_digital and not re.search(r"Demonstrativo de (?:Receitas|Despesas)|Resumo Financeiro Cont[áa]bil", texto_pag):
                modo = None
                continue
            linhas = []
            for yc, ws in _linhas(doc[pi]):
                t = _texto(ws)
                if "webware.com.br" in t or "Voltar ao índice" in t or t.startswith("Condomínio:"):
                    continue
                if (pasta_digital and yc < 90) or (not pasta_digital and yc < 30):
                    continue
                linhas.append((yc, ws))
            # blocos: linhas consecutivas a <= gap_max formam UM item (âncora + histórico quebrado) ou um cabeçalho de duas linhas
            blocos: list[list] = []
            for ln in linhas:
                if blocos and ln[0] - blocos[-1][-1][0] <= gap_max:
                    blocos[-1].append(ln)
                else:
                    blocos.append([ln])
            for bloco in blocos:
                modo = self._bloco(bloco, modo, cab, st, nomes_contas, dados, contas, totais, pi + 1)

    def _bloco(self, bloco, modo, cab, st, nomes_contas, dados, contas, totais, pagina):
        textos = [_texto(ws) for _, ws in bloco]
        tn = _norm(textos[0])
        # mudança de seção / metadados
        # (no Pasta Digital o título se repete em toda página: só zera o estado quando a seção MUDA)
        if re.match(r"^DEMONSTRATIVO DE RECEITAS\b", tn) and _num(bloco[0][1][-1][4]) is None:
            if modo != "receitas":
                st.update(cat="", conta="ORDINARIA")
            return "receitas"
        if re.match(r"^DEMONSTRATIVO DE DESPESAS\b", tn) and _num(bloco[0][1][-1][4]) is None:
            if modo != "despesas":
                st.update(grupo="", sub="", espera_grupo=True, conta="ORDINARIA")
            return "despesas"
        if tn.startswith("RESUMO FINANCEIRO CONTABIL"):
            return "resumo"
        if tn.startswith("PERIODO"):
            if "periodo" not in totais:
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s*[àa]\s*(\d{2})/(\d{2})/(\d{4})", textos[0])
                if m:
                    totais["periodo"] = f"{m.group(6)}-{m.group(5)}"
            return modo
        if modo == "resumo":
            for yc, ws in bloco:
                t2 = _norm(_texto(ws))
                if t2.startswith("CONCILIACAO BANCARIA") or t2.startswith("DEMONSTRATIVO"):
                    return None
                nums = [_num(w[4]) for w in ws if _num(w[4]) is not None]
                nome = " ".join(w[4] for w in ws if _num(w[4]) is None).strip()
                if len(nums) == 4 and nome and _norm(nome) != "TOTAL" and not t2.startswith("CONTA SALDO"):
                    contas.append(ContaMes(nome=nome, saldo_anterior=nums[0], creditos=nums[1], debitos=nums[2],
                                           saldo_atual=nums[3], pagina=pagina))
                    nomes_contas.add(_norm(nome))
            return modo
        if modo not in ("receitas", "despesas"):
            return modo
        # cabeçalho de colunas
        if "HISTORICO" in tn and tn.startswith(("DATA", "N LANCTO")):
            cab["rec" if modo == "receitas" else "desp"] = {w[4]: w for w in bloco[0][1]}
            return modo
        if tn.startswith("TOTAL") and not any(_RE_DATA.match(w[4]) for _, ws in bloco for w in ws[:2]):
            self._total(modo, bloco[0][1], st, nomes_contas, totais)
            return modo
        anc = [k for k, (yc, ws) in enumerate(bloco)
               if ws[0][0] < 200 and any(_RE_DATA.match(w[4]) for w in ws[:2]) and any(_num(w[4]) is not None for w in ws)]
        if anc:
            for k in anc:
                # várias âncoras no mesmo bloco (linhas coladas): cada uma leva as linhas de texto mais próximas dela
                alvo = bloco if len(anc) == 1 else [ln for j, ln in enumerate(bloco)
                                                    if j == k or (j not in anc and min(anc, key=lambda a: abs(bloco[a][0] - ln[0])) == k)]
                if modo == "receitas":
                    self._receita(alvo, alvo.index(bloco[k]), cab.get("rec", {}), st, pagina, dados)
                else:
                    self._despesa(alvo, alvo.index(bloco[k]), cab.get("desp", {}), st, pagina, dados, totais)
            return modo
        if any(_num(w[4]) is not None for _, ws in bloco for w in ws):
            return modo
        nome = " ".join(t.strip() for t in textos).strip()
        self._cabecalho(modo, nome, st, nomes_contas)
        return modo

    # ── cabeçalhos de conta / grupo / subconta / categoria ───────────────────
    @staticmethod
    def _cabecalho(modo, nome, st, nomes_contas):
        eh_conta = _norm(nome) in nomes_contas or _norm(nome) == "ORDINARIA" or _norm(nome).startswith("FUNDO DE ")
        if modo == "receitas":
            if eh_conta:
                st["conta"], st["cat"] = nome, ""
            else:
                st["cat"] = nome
            return
        if eh_conta:
            st.update(conta=nome, grupo="", sub="", espera_grupo=True)
        elif st["espera_grupo"]:
            st.update(grupo=nome, sub="", espera_grupo=False)
        else:
            st["sub"] = nome

    @staticmethod
    def _total(modo, ws, st, nomes_contas, totais):
        t = _texto(ws)
        v = next((_num(w[4]) for w in reversed(ws) if _num(w[4]) is not None), None)
        tn = _norm(t)
        if modo == "receitas":
            if tn.startswith("TOTAL GERAL"):
                totais["receitas"] = v
            return
        if tn.startswith("TOTAL DAS DESPESAS"):
            totais["despesas"] = v
        elif tn.startswith("TOTAL DA CONTA"):
            m = re.match(r"^TOTAL DA CONTA\s+(.+?)\s+-?[\d.]+,\d{2}(?:\s+[\d.,]+%)?$", t, re.I)
            nome = _norm(m.group(1)) if m else ""
            if nome in nomes_contas or nome.startswith("ORDINARIA") or nome.startswith("FUNDO DE "):
                st["espera_grupo"] = False
            else:                          # fechou um grupo (PESSOAL...): o próximo cabeçalho é outro grupo
                st["espera_grupo"], st["sub"] = True, ""

    # ── Demonstrativo de Receitas: uma âncora = uma linha de recibo ───────────
    def _receita(self, bloco, k, cab, st, pagina, dados):
        yc, ws = bloco[k]
        xval = cab["Valor"][0] if "Valor" in cab else 500
        xhist = next((cab[h][0] for h in cab if _norm(h) == "HISTORICO"), 300)
        valores = [w for w in ws if _num(w[4]) is not None and w[0] >= xval - 40]
        if not valores:
            return
        vt = valores[-1]
        data_tok = next((w for w in ws if _RE_DATA.match(w[4])), None)
        partes = [w for j, (y2, ws2) in enumerate(bloco) for w in ws2
                  if w[0] >= xhist - 5 and w is not vt and not (j == k and _RE_DATA.match(w[4]))]
        partes.sort(key=lambda w: (round((w[1] + w[3]) / 6), w[0]))
        hist = re.sub(r"\s+", " ", " ".join(w[4] for w in partes)).strip()
        unidade = " ".join(w[4] for w in ws if 0 < w[0] < xhist - 5 and not _RE_DATA.match(w[4])).strip()
        categoria = st["cat"]
        dados.receitas.append(LinhaReceita(
            conta=st["conta"], descricao=(f"{categoria} - {hist}".strip(" -") + (f" (un. {unidade})" if unidade else "")),
            valor=_num(vt[4]), tipo=_tipo_receita(categoria), data=data_tok[4] if data_tok else None, pagina=pagina,
            bbox=(ws[0][0], min(w[1] for w in ws), vt[2], max(w[3] for w in ws))))

    # ── Demonstrativo de Despesas ────────────────────────────────────────────
    def _despesa(self, bloco, k, cab, st, pagina, dados, totais):
        yc, ws = bloco[k]
        xval = cab["Valor"][0] if "Valor" in cab else 600
        xhist = next((cab[h][0] for h in cab if _norm(h) == "HISTORICO"), 150)
        data_tok = next(w for w in ws if _RE_DATA.match(w[4]))
        numericos = [w for w in ws if _num(w[4]) is not None and w[0] >= xval - 25]
        if not numericos:
            return
        vt = numericos[0]
        total_sub = _num(numericos[1][4]) if len(numericos) > 1 else None
        partes = [w for j, (y2, ws2) in enumerate(bloco) for w in ws2
                  if w[0] >= xhist - 5 and not _RE_DATA.match(w[4]) and (j != k or w[0] < vt[0] - 1)]
        partes.sort(key=lambda w: (round((w[1] + w[3]) / 6), w[0]))
        hist = re.sub(r"\s+", " ", " ".join(w[4] for w in partes)).strip()
        seq = next((w[4] for w in ws if re.fullmatch(r"\d{4}", w[4]) and w[0] > 520), None)
        cat = f"{st['grupo']} > {st['sub']}" if st["grupo"] else (st["sub"] or "SEM SUBCONTA")
        dados.lancamentos.append(LancamentoDespesa(
            descricao=_marca_parcela(hist), valor=_num(vt[4]), categoria=cat, conta=st["conta"],
            codigo=seq, data=data_tok[4], fornecedor=_fornecedor(hist), pagina=pagina,
            bbox=(ws[0][0], min(w[1] for w in ws), vt[2], max(w[3] for w in ws))))
        if total_sub is not None:
            totais.setdefault("tot_sub", []).append((st["conta"], cat, total_sub))

    # ── conferências ─────────────────────────────────────────────────────────
    def _conferir(self, dados: DadosRegras, contas: list, totais: dict):
        s_rec = round(sum(r.valor for r in dados.receitas), 2)
        if totais.get("receitas") is not None and abs(s_rec - totais["receitas"]) > _CENT:
            dados.avisos.append(f"Σ receitas lidas ({s_rec:,.2f}) difere de TOTAL GERAL das receitas ({totais['receitas']:,.2f})")
        s_des = round(sum(l.valor for l in dados.lancamentos), 2)
        if totais.get("despesas") is not None and abs(s_des - totais["despesas"]) > _CENT:
            dados.avisos.append(f"Σ lançamentos lidos ({s_des:,.2f}) difere de TOTAL DAS DESPESAS ({totais['despesas']:,.2f})")
        vistos = set()
        for (conta, cat, tot) in totais.get("tot_sub", []):
            if (conta, cat) in vistos:
                continue
            vistos.add((conta, cat))
            soma = round(sum(l.valor for l in dados.lancamentos if l.categoria == cat and l.conta == conta), 2)
            if abs(soma - tot) > _CENT:
                dados.avisos.append(f"subconta {cat}: lançamentos somam {soma:,.2f} mas o total impresso é {tot:,.2f}")
        for c in contas:
            cred = round(sum(r.valor for r in dados.receitas if _norm(r.conta) == _norm(c.nome)), 2)
            if dados.receitas and abs(cred - c.creditos) > _CENT:
                dados.avisos.append(f"conta {c.nome}: Σ receitas lidas ({cred:,.2f}) ≠ créditos do Resumo Financeiro ({c.creditos:,.2f})")
            if dados.lancamentos:
                deb = round(sum(l.valor for l in dados.lancamentos if _norm(l.conta) == _norm(c.nome)), 2)
                if abs(deb - c.debitos) > _CENT:
                    dados.avisos.append(f"conta {c.nome}: Σ lançamentos lidos ({deb:,.2f}) ≠ débitos do Resumo Financeiro ({c.debitos:,.2f})")
