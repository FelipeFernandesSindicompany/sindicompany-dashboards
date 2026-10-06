"""
Extrator das regras gerais — Top Nine (Moema Top Nine; administradora Conister, sistema Consvicta "W0xx").

Cadastrado como lirba_pdf no condominios.json, mas o PDF é a "Pasta Digital" da Conister (≈130-185 páginas, texto
extraível, mesmas telas W0xx da família Consvicta). Telas usadas (confirmado nos 15 meses abr/2025-jun/2026):
  W016B  "Resumo Financeiro" (pág. 6): por conta (CONTA ORDINÁRIA, FUNDO DE OBRAS) Saldo ant., Créditos*, Débitos*, Saldo final.
         (*) "Inclui transferência entre contas".
  W015A  "Demonstrativo de Receitas e Despesas da Conta X, Agrupado pelo nível 2" (pág. 7-8): grupos de receita/despesa por conta
         e o total de despesas da conta — usado para o rendimento por conta e para conferir a soma.
  W015D  "Demonstrativo de Despesas "X"; Detalhado; Com conta categoria" (pág. 10-11): UMA linha por lançamento:
         código da conta categoria (2.1.1) + nome da subconta + histórico + valor; agrupado por 2.1 Com Pessoal, 2.2 Consumo...
         Linhas que quebram continuam na linha seguinte (começando na margem).
  W020B  "Demonstrativo de Receitas Analítico" (pág. 13): grupo (Rateio Ordinário, Rendimento de Investimento, Fundo de Obras) >
         linhas "N cobranças | competência | valor" e as aplicações automáticas (rendimento).
  W011A  "Comparativo de Jul/AAAA com os próximos 11 meses" (pág. 14-15): lista TODAS as subcontas (sem código) — usada só para separar
         o nome da subconta do histórico na linha do W015D ("2.3.18 Monitoramento Portaria virtual - ...").
`categoria` do lançamento = "<código> <subconta>" (ex.: "2.1.1 Salário"); `conta` = a conta do cabeçalho do W015D.
Conferências (viram `avisos`): Σ lançamentos de cada conta == "Total de Despesas" do W015D da conta == Débitos do W016B
(quando o W016B inclui transferência entre contas, a diferença aparece como aviso e é explicada no relatório do grupo).
"""
import re
import unicodedata
from pathlib import Path
from typing import Optional

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CENT = 0.011
_RE_NUM = re.compile(r"^\(?-?\d{1,3}(?:\.\d{3})*,\d{2}\)?-?$|^\(?-?\d+,\d{2}\)?-?$")
_RE_COD3 = re.compile(r"^\d+\.\d+\.\d+$")


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


def _marca_parcela(desc: str) -> str:
    """Conister escreve parcela como "2 de 4", "11/11", "Parc. 11/12" — acrescenta "[PARC n/total]" quando falta a palavra PARC."""
    if re.search(r"\bPARC", desc, re.I):
        return desc
    m = re.search(r"(?<![\d/.,])(\d{1,2})\s+de\s+(\d{1,2})(?![\d/.,])", desc)
    if not m:
        m = re.search(r"(?<![\d/.,])(\d{1,2})/(\d{1,2})(?![\d/.,])", desc)
    if m:
        n, t = int(m.group(1)), int(m.group(2))
        if 1 <= n <= t <= 36 and t >= 2:
            return f"{desc} [PARC {n:02d}/{t:02d}]"
    return desc


def aplicar_config_receitas_negativas(dados: DadosRegras, condo: dict) -> None:
    """Opcional, por condomínio (config/validacao_balancetes.json › "regras" › "receita_negativa"):
        {"ignorar_tipos": ["baixa_inadimplencia"], "ignorar_descricao": ["DESCONTO ESTACIONAMENTO"]}
    Retira de `dados.receitas` as linhas NEGATIVAS cujo `tipo` esteja em ignorar_tipos ou cuja descrição case com algum regex de
    ignorar_descricao — para formatos em que certa linha negativa é estrutural e se repete todo mês. Sem essa configuração nada é retirado
    (a regra 4 vê tudo, com o sinal impresso). O que foi retirado fica registrado em `dados.avisos`."""
    cfg = ((condo or {}).get("regras") or {}).get("receita_negativa") or {}
    tipos = set(cfg.get("ignorar_tipos") or [])
    padroes = [re.compile(p, re.IGNORECASE) for p in (cfg.get("ignorar_descricao") or [])]
    if not tipos and not padroes:
        return
    fora = [r for r in dados.receitas if r.valor < 0 and (r.tipo in tipos or any(p.search(r.descricao or "") for p in padroes))]
    if fora:
        dados.receitas = [r for r in dados.receitas if r not in fora]
        dados.avisos.append(f"{len(fora)} linha(s) de receita negativa (R$ {sum(r.valor for r in fora):,.2f}) não foram enviadas à regra de receita "
                            "negativa por configuração (regras.receita_negativa.ignorar_tipos/ignorar_descricao)")


def _tipo_receita(grupo: str) -> str:
    n = _norm(grupo)
    if "RENDIMENTO" in n:
        return "rendimento"
    if "JURO" in n or "MULTA" in n or "ATUALIZACAO" in n:
        return "multa_juros"
    if "RATEIO" in n or "COTA" in n or "CONDOMINIO" in n or "TAXA" in n:
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
            n_cab = min(len(doc), 40)                      # as telas do balancete ficam no começo do PDF
            tipos = {}
            for i in range(n_cab):
                t = doc[i].get_text()[:200]
                m = re.search(r"\bW\d{3}[A-Z]\b", t)
                if m:
                    tipos.setdefault(m.group(0), []).append(i)
            totais: dict = {}
            contas = self._ler_resumo(doc, tipos.get("W016B", []), dados)
            nomes_sub = self._nomes_subcontas(doc, tipos.get("W011A", []))
            rend_conta, grupos_conta = self._ler_w015a(doc, tipos.get("W015A", []), totais)
            self._ler_w015d(doc, tipos.get("W015D", []), nomes_sub, dados, totais)
            self._ler_w020b(doc, tipos.get("W020B", []), grupos_conta, dados, totais)
        finally:
            doc.close()
        for c in contas:
            c.rendimento = round(rend_conta.get(_norm(c.nome), 0.0), 2)
        dados.contas = contas
        self._conferir(dados, contas, totais)
        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": len([c for c in contas if abs(c.rendimento) > _CENT]) >= 2,
                           "lancamentos": bool(dados.lancamentos)}
        if not dados.receitas:
            dados.motivos_nao_cobertos["receitas"] = "a tela W020B (Demonstrativo de Receitas Analítico) não foi encontrada neste PDF"
        if not dados.lancamentos:
            dados.motivos_nao_cobertos["lancamentos"] = "a tela W015D (Demonstrativo de Despesas Detalhado) não foi encontrada neste PDF"
        if not dados.cobertura["rendimentos"]:
            quais = ", ".join(f"{c.nome} {c.rendimento:,.2f}" for c in contas if abs(c.rendimento) > _CENT) or "nenhuma"
            dados.motivos_nao_cobertos["rendimentos"] = (
                f"o rendimento das aplicações automáticas é creditado em uma única conta neste mês ({quais}); as demais contas "
                "não recebem rendimento — não há distribuição entre contas para conferir a proporcionalidade")
        aplicar_config_receitas_negativas(dados, self.condo)
        return dados

    # ── W016B: Resumo Financeiro ─────────────────────────────────────────────
    def _ler_resumo(self, doc, paginas, dados) -> list:
        contas = []
        for i in paginas:
            em_tabela = False
            for yc, ws in _linhas(doc[i]):
                tn = _norm(_texto(ws))
                if tn.startswith("CONTA SALDO ANT"):
                    em_tabela = True
                    continue
                if not em_tabela:
                    continue
                if tn.startswith("SALDO FINAL"):
                    break
                nums = [_num(w[4]) for w in ws if _num(w[4]) is not None]
                nome = " ".join(w[4] for w in ws if _num(w[4]) is None).strip()
                if len(nums) == 4 and nome:
                    contas.append(ContaMes(nome=nome, saldo_anterior=nums[0], creditos=nums[1], debitos=abs(nums[2]),
                                           saldo_atual=nums[3], pagina=i + 1))
        return contas

    # ── W011A: nomes das subcontas ───────────────────────────────────────────
    def _nomes_subcontas(self, doc, paginas) -> list:
        nomes = set()
        if not paginas:
            return []
        i0 = paginas[0]
        for i in range(i0, min(i0 + 4, len(doc))):
            for yc, ws in _linhas(doc[i]):
                nums = [w for w in ws if _num(w[4]) is not None]
                if len(nums) < 8:
                    continue
                nome = []
                for w in ws:
                    if _num(w[4]) is not None:
                        break
                    nome.append(w[4])
                nm = " ".join(nome).strip()
                if nm and not _norm(nm).startswith(("TOTAL", "SALDO", "MOV", "MEDIA")):
                    nomes.add(nm)
        return sorted(nomes, key=len, reverse=True)

    # ── W015A: totais por conta (rendimento, soma de despesas) ───────────────
    def _ler_w015a(self, doc, paginas, totais):
        rend = {}
        grupos_conta: dict[str, str] = {}       # nome do grupo de receita -> conta
        for i in paginas:
            txt = doc[i].get_text()
            m = re.search(r'da Conta\s+"([^"]+)"', txt)
            conta = m.group(1).strip() if m else "CONTA ORDINÁRIA"
            em_receitas = False
            for yc, ws in _linhas(doc[i]):
                t = _texto(ws)
                tn = _norm(t)
                if tn == "RECEITAS":
                    em_receitas = True
                    continue
                if tn == "DESPESAS":
                    em_receitas = False
                    continue
                v = next((_num(w[4]) for w in reversed(ws) if _num(w[4]) is not None), None)
                if v is None:
                    continue
                if tn.startswith("TOTAL DE DESPESAS"):
                    totais.setdefault("despesas_conta", {})[_norm(conta)] = v
                elif tn.startswith("TOTAL DE RECEITAS"):
                    totais.setdefault("receitas_conta", {})[_norm(conta)] = v
                elif em_receitas and not tn.startswith(("SALDO", "MOV")):
                    nome = re.sub(r"\s*[\d.,%]+$", "", " ".join(w[4] for w in ws if _num(w[4]) is None and not w[4].endswith("%"))).strip()
                    grupos_conta[_norm(nome)] = conta
                    if "RENDIMENTO" in tn:
                        rend[_norm(conta)] = rend.get(_norm(conta), 0.0) + v
        return rend, grupos_conta

    # ── W015D: lançamentos ───────────────────────────────────────────────────
    def _ler_w015d(self, doc, paginas, nomes_sub, dados, totais):
        brutos: list[dict] = []
        for i in paginas:
            txt = doc[i].get_text()
            m = re.search(r'Despesas\s+"([^"]+)"', txt)
            conta = m.group(1).strip() if m else "CONTA ORDINÁRIA"
            cur = None
            for yc, ws in _linhas(doc[i]):
                if yc < 90 or yc > 770:
                    continue
                t = _texto(ws)
                valor_tok = next((w for w in reversed(ws) if _num(w[4]) is not None and w[0] > 480), None)
                eh_linha = _RE_COD3.match(ws[0][4]) and ws[0][0] < 70 and valor_tok is not None
                if eh_linha:
                    corpo = [w for w in ws[1:] if w is not valor_tok]
                    cur = {"cod": ws[0][4], "tokens": [w[4] for w in corpo], "valor": _num(valor_tok[4]), "conta": conta,
                           "pagina": i + 1, "bbox": (ws[0][0], min(w[1] for w in ws), valor_tok[2], max(w[3] for w in ws))}
                    brutos.append(cur)
                    continue
                if _norm(t).startswith("TOTAL DE"):
                    cur = None
                    continue
                # continuação: linha na margem (x0 < 40) logo abaixo de um lançamento, sem valor
                if cur is not None and ws[0][0] < 40 and valor_tok is None and not _RE_COD3.match(ws[0][4]) and not re.match(r"^\d+(\.\d+)?$", ws[0][4]):
                    cur["tokens"].extend(w[4] for w in ws)
                    continue
                if cur is not None and valor_tok is None and ws[0][0] < 40:
                    cur["tokens"].extend(w[4] for w in ws)
                    continue
                cur = None
        # nome da subconta: prefixo mais longo da lista do W011A; senão prefixo comum entre as linhas do mesmo código
        por_cod: dict[str, list] = {}
        for b in brutos:
            por_cod.setdefault(b["cod"], []).append(b)
        for b in brutos:
            texto = " ".join(b["tokens"])
            nome = next((n for n in nomes_sub if _norm(texto).startswith(_norm(n))), None)
            if nome is None:
                outros = [" ".join(o["tokens"]).split() for o in por_cod[b["cod"]]]
                comum = []
                for ws_ in zip(*outros):
                    if len(set(ws_)) == 1:
                        comum.append(ws_[0])
                    else:
                        break
                nome = " ".join(comum) if len(outros) > 1 and comum else (b["tokens"][0] if b["tokens"] else "")
            # descrição = o texto impresso depois do código (subconta + histórico). Linhas como "2.1.20 FGTS Maio/2026 (Jun/26)"
            # só têm mês e número no histórico: sem o nome da subconta a regra de subcontas não teria como reconhecer a despesa.
            hist = re.sub(r"\s+", " ", texto).strip(" -")
            dados.lancamentos.append(LancamentoDespesa(
                descricao=_marca_parcela(hist), valor=b["valor"], categoria=f"{b['cod']} {nome}".strip(), conta=b["conta"],
                codigo=None, data=None, pagina=b["pagina"], bbox=b["bbox"]))

    # ── W020B: receitas ──────────────────────────────────────────────────────
    def _ler_w020b(self, doc, paginas, grupos_conta, dados, totais):
        for i in paginas:
            grupo = ""
            for yc, ws in _linhas(doc[i]):
                if yc < 90 or yc > 770:
                    continue
                t = _texto(ws)
                tn = _norm(t)
                if tn.startswith("TOTAL DE RECEITAS"):
                    totais["receitas"] = next((_num(w[4]) for w in reversed(ws) if _num(w[4]) is not None), None)
                    continue
                if tn.startswith("TOTAL DE"):
                    continue
                valor_tok = next((w for w in reversed(ws) if _num(w[4]) is not None and w[0] > 480), None)
                if valor_tok is None:
                    if ws[0][0] < 42 and not tn.startswith(("RECEITAS", "ENTRE")):
                        grupo = t.strip()
                    continue
                comp = next((w[4] for w in ws if re.fullmatch(r"\d{2}/\d{4}", w[4])), None)
                desc = " ".join(w[4] for w in ws if w is not valor_tok and w[4] != comp).strip()
                conta = grupos_conta.get(_norm(grupo)) or "CONTA ORDINÁRIA"
                dados.receitas.append(LinhaReceita(
                    conta=conta, descricao=f"{grupo} - {desc}" + (f" (comp. {comp})" if comp else ""), valor=_num(valor_tok[4]),
                    tipo=_tipo_receita(grupo), pagina=i + 1, bbox=(ws[0][0], min(w[1] for w in ws), valor_tok[2], max(w[3] for w in ws))))

    # ── conferências ─────────────────────────────────────────────────────────
    def _conferir(self, dados, contas, totais):
        s_rec = round(sum(r.valor for r in dados.receitas), 2)
        if totais.get("receitas") is not None and abs(s_rec - totais["receitas"]) > _CENT:
            dados.avisos.append(f"Σ receitas lidas ({s_rec:,.2f}) difere de 'Total de Receitas' do W020B ({totais['receitas']:,.2f})")
        for c in contas:
            s_lanc = round(sum(l.valor for l in dados.lancamentos if _norm(l.conta) == _norm(c.nome)), 2)
            tot = totais.get("despesas_conta", {}).get(_norm(c.nome))
            if tot is not None and abs(s_lanc - tot) > _CENT:
                dados.avisos.append(f"conta {c.nome}: Σ lançamentos do W015D ({s_lanc:,.2f}) difere do 'Total de Despesas' do W015A ({tot:,.2f})")
            if abs(s_lanc - c.debitos) > _CENT:
                dados.avisos.append(f"conta {c.nome}: Σ lançamentos ({s_lanc:,.2f}) difere dos Débitos* do W016B ({c.debitos:,.2f}) — o W016B inclui transferência entre contas")
            s_rec_c = round(sum(r.valor for r in dados.receitas if _norm(r.conta) == _norm(c.nome)), 2)
            if abs(s_rec_c - c.creditos) > _CENT:
                dados.avisos.append(f"conta {c.nome}: Σ receitas ({s_rec_c:,.2f}) difere dos Créditos* do W016B ({c.creditos:,.2f}) — o W016B inclui transferência entre contas")
