"""
Extrator das regras gerais — Addomus ("Pasta de Prestação de Contas", PDF de ~330 páginas com texto).
Condomínio do formato: spazio_jardins_da_orla (empresa_gestora = addomus_pdf).

O que o arquivo traz e de onde sai cada dado (confirmado em Spazio jun/2026 e jul/2026):
  contas        "Demonstrativo de Receitas e Despesas" (resumo, ~pág. 20-21), tabela DISPONÍVEL: uma linha
                por FUNDO (Ordinário, Reserva, Obras, Salão de Festas, Consumo individual, Garantidora) com
                Saldo inicial / Créditos / Débitos / Transferências / Saldo final. É o nível em que o Addomus
                distribui o rendimento ("Rendimento Líquido do CDB p/ Fundo de Obras" ...), por isso as
                "contas" das regras são os fundos. Débitos = despesas pagas pelo fundo (as transferências
                entre fundos ficam na coluna Transferências).
  receitas      "Demonstrativo Analítico de Receitas e Despesas" (~45 pág.): seções 1.x (Cotas, Rendimento,
                Ressarcimento de consumo, Fundos, Espaços...) com uma linha por recibo, valor COM SINAL
                (as baixas "Inadimplência da Pro-Sindico de Mmm/AA recuperada em Mmm/AA" vêm negativas).
  lancamentos   o mesmo Analítico, seções 2.x: Data | Descrição | Fornecedor | Documento "cód (NF)" | Período | Valor,
                agrupadas pela subconta folha (2.1.5.1 Portaria, 2.2.1 Energia elétrica...). O fundo pagador
                (`conta`) vem da tela "Despesa" do mesmo lançamento (campo Código == Documento do Analítico;
                tabela "Composição da Despesa": conta contábil / conta disponibilidade / valor).
Conferências feitas na leitura (viram `avisos` se não fecharem):
  Σ receitas == "Total de 1 - RECEITAS";  Σ lançamentos == "Total de 2 - DESPESAS";
  Σ rendimento por fundo == "1.1.2 - Rendimento de Investimentos".
"""
import re
import unicodedata
from pathlib import Path
from typing import Optional

from conciliacao.regras_gerais.extratores.top_nine import aplicar_config_receitas_negativas
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CENT = 0.011
_SEM_FUNDO = "FUNDO NÃO IDENTIFICADO"
_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_NUM = re.compile(r"^\(?-?\d{1,3}(?:\.\d{3})*,\d{2}\)?-?$|^\(?-?\d+,\d{2}\)?-?$")
_RE_COD = re.compile(r"^\d+(?:\.\d+)*$")


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
    """Palavras da página agrupadas por linha visual: [(y_centro, [(x0,y0,x1,y1,texto,...), ...]), ...]."""
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


def _ultimo_num(ws) -> Optional[float]:
    return next((_num(w[4]) for w in reversed(ws) if _num(w[4]) is not None), None)


# destino do rendimento ("p/ Cta Ordinária") -> nome do fundo na tabela DISPONÍVEL
_ALIAS_FUNDO = {
    "CTA ORDINARIA": "Fundo Ordinário", "CONTA ORDINARIA": "Fundo Ordinário", "ORDINARIA": "Fundo Ordinário",
    "CONSUMO D AGUA": "Consumo individual", "CONSUMO DE AGUA": "Consumo individual", "AGUA": "Consumo individual",
    "FUNDO DE RESERVA": "Fundo de Reserva", "FUNDO DE OBRAS": "Fundo de Obras", "SALAO DE FESTAS": "Salão de Festas",
}


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    # ── leitura ──────────────────────────────────────────────────────────────
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        doc = fitz.open(str(caminho))
        try:
            textos = [p.get_text() for p in doc]
            tipo_pag = [self._tipo_pagina(t) for t in textos]
            pag_resumo = [i for i, t in enumerate(tipo_pag) if t == "resumo"]
            pag_analitico = [i for i, t in enumerate(tipo_pag) if t == "analitico"]
            if not pag_analitico:
                dados.motivos_nao_cobertos = {
                    k: "o PDF não traz o 'Demonstrativo Analítico de Receitas e Despesas' (formato Addomus esperado)"
                    for k in ("receitas", "rendimentos", "lancamentos")}
                return dados

            totais: dict = {}
            contas = self._ler_contas(doc, pag_resumo, totais)
            composicao = self._ler_composicoes(textos, tipo_pag)
            dados.receitas, dados.lancamentos = self._ler_analitico(doc, pag_analitico, composicao)

            # rendimento por fundo = soma das linhas "Rendimento Líquido ... p/ <fundo>"
            por_nome = {_norm(c.nome): c for c in contas}
            for r in dados.receitas:
                if r.tipo == "rendimento":
                    c = por_nome.get(_norm(r.conta))
                    if c is not None:
                        c.rendimento = round(c.rendimento + r.valor, 2)
                    else:
                        dados.avisos.append(f"rendimento de {r.valor:,.2f} ('{r.descricao}') não casou com nenhum fundo da tabela DISPONÍVEL")
            dados.contas = contas

            self._conferir(dados, totais)
            dados.cobertura = {"receitas": bool(dados.receitas),
                               "rendimentos": bool(contas) and any(c.rendimento for c in contas),
                               "lancamentos": bool(dados.lancamentos)}
            if not dados.cobertura["receitas"]:
                dados.motivos_nao_cobertos["receitas"] = "nenhuma linha de receita encontrada no Demonstrativo Analítico"
            if not dados.cobertura["rendimentos"]:
                dados.motivos_nao_cobertos["rendimentos"] = ("não foram encontrados a tabela DISPONÍVEL por fundo ou as linhas "
                                                             "'Rendimento Líquido ... p/ <fundo>' no Demonstrativo Analítico")
            if not dados.cobertura["lancamentos"]:
                dados.motivos_nao_cobertos["lancamentos"] = "nenhum lançamento de despesa encontrado no Demonstrativo Analítico"
        finally:
            doc.close()
        aplicar_config_receitas_negativas(dados, self.condo)
        return dados

    @staticmethod
    def _tipo_pagina(texto: str) -> str:
        topo = _norm(texto[:400])
        if "DEMONSTRATIVO ANALITICO DE RECEITAS E DESPESAS" in topo:
            return "analitico"
        if "DEMONSTRATIVO DE RECEITAS E DESPESAS" in topo:
            return "resumo"
        if topo.startswith("SAO PAULO SP") and "DESPESA" in topo[:80] and "COMPOSICAO DA DESPESA" in _norm(texto[:3000]):
            return "despesa"
        if "COMPOSICAO DA DESPESA" in _norm(texto[:3000]) and "CODIGO" in topo:
            return "despesa"
        return "outra"

    # ── contas (fundos) ──────────────────────────────────────────────────────
    def _ler_contas(self, doc, pag_resumo: list, totais: dict) -> list:
        contas: list[ContaMes] = []
        em_disponivel = False
        for i in pag_resumo:
            for yc, ws in _linhas(doc[i]):
                tn = _norm(_texto(ws))
                if tn.startswith("TOTAL DE 1 RECEITAS"):
                    totais["receitas"] = _ultimo_num(ws)
                elif tn.startswith("TOTAL DE 2 DESPESAS"):
                    v = _ultimo_num(ws)
                    totais["despesas"] = abs(v) if v is not None else None
                elif tn.startswith("1 1 2 RENDIMENTO DE INVESTIMENTOS"):
                    totais["rendimento"] = _ultimo_num(ws)
                if tn.startswith("DISPONIVEL"):
                    em_disponivel = True
                    continue
                if not em_disponivel:
                    continue
                if tn.startswith("TOTAL DO DISPONIVEL") or tn.startswith("FINANCEIRO"):
                    em_disponivel = False
                    continue
                nums = [_num(w[4]) for w in ws if _num(w[4]) is not None]
                nome = " ".join(w[4] for w in ws if _num(w[4]) is None).strip()
                if len(nums) == 5 and nome:
                    contas.append(ContaMes(nome=nome, saldo_anterior=nums[0], creditos=nums[1], debitos=abs(nums[2]),
                                           saldo_atual=nums[4], aplicada=None, pagina=i + 1))
        return contas

    # ── composições da tela "Despesa": código -> fundos pagadores ─────────────
    def _ler_composicoes(self, textos: list, tipo_pag: list) -> dict:
        comp: dict[str, dict] = {}
        for i, t in enumerate(textos):
            if tipo_pag[i] != "despesa":
                continue
            m = re.search(r"C[óo]digo:\s*(\d+)", t)
            if not m:
                continue
            info = {"fundos": [], "parcela": None}
            mp = re.search(r"Parcela:\s*(\d+)\s*/\s*(\d+)", t)
            if mp:
                info["parcela"] = (int(mp.group(1)), int(mp.group(2)))
            bloco = t.split("Composição da Despesa", 1)[-1].split("Liquidação", 1)[0]
            # Cada linha da composição termina em "<3.x - Fundo ...> <valor> Sim|Não". O nome da conta contábil
            # pode quebrar em várias linhas ("2.6.6 - ELETR/HIDRAUL/PINTURA/CONS / TRUC") e a conta disponibilidade
            # pode vir na mesma linha da contábil: por isso o texto é achatado e o código da conta contábil é o
            # último "1.x/2.x - ..." visto antes de cada "3.x - <fundo> <valor> Sim|Não".
            plano = re.sub(r"\s+", " ", bloco)
            for mf in re.finditer(r"(?<![\d.])(3\.\d+)\s*-\s*(.+?)\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})\s+(?:Sim|N[ãa]o)\b", plano):
                cods = re.findall(r"(?<![\d.])([12](?:\.\d+)+)\s*-", plano[:mf.start()])
                if cods:
                    info["fundos"].append((cods[-1], mf.group(2).strip(), _num(mf.group(3))))
            comp[m.group(1)] = info
        return comp

    # ── Demonstrativo Analítico ──────────────────────────────────────────────
    def _ler_analitico(self, doc, paginas: list, composicao: dict):
        receitas: list[LinhaReceita] = []
        lancs: list[LancamentoDespesa] = []
        pilha: list[tuple[str, str]] = []       # cabeçalhos abertos [(código, nome)]
        eh_despesa = False
        for i in paginas:
            linhas = [(yc, ws) for yc, ws in _linhas(doc[i]) if 70 < yc < 805]
            anc = [k for k, (yc, ws) in enumerate(linhas)
                   if _RE_DATA.match(ws[0][4]) and ws[0][0] < 40 and any(_num(w[4]) is not None and w[2] > 535 for w in ws)]
            extras: dict[int, list] = {k: [] for k in anc}
            for k, (yc, ws) in enumerate(linhas):
                if k in extras:
                    continue
                t = _texto(ws)
                if self._eh_cabecalho(ws) or ws[0][4].upper().startswith("TOTAL") or _norm(t).startswith("DATA DESCRICAO"):
                    continue
                perto = [a for a in anc if abs(linhas[a][0] - yc) <= 12]
                if perto and ws[0][0] > 40:
                    extras[min(perto, key=lambda a: abs(linhas[a][0] - yc))].append(ws)
            for k, (yc, ws) in enumerate(linhas):
                if self._eh_cabecalho(ws):
                    mh = re.match(r"^(\d+(?:\.\d+)*)\s*-\s*(.+)$", _texto(ws))
                    cod, nome = mh.group(1), mh.group(2).strip()
                    prof = cod.count(".") + 1
                    pilha = pilha[:prof - 1] + [(cod, nome)]
                    if prof == 1:
                        eh_despesa = cod == "2"
                elif k in extras:
                    self._registra(ws, extras[k], pilha, eh_despesa, i + 1, receitas, lancs, composicao)
        return receitas, lancs

    @staticmethod
    def _eh_cabecalho(ws) -> bool:
        """Linha "2.1.5.1 - Portaria" (código, hífen, nome; sem valor): abre uma seção do plano de contas."""
        if len(ws) < 3 or not _RE_COD.match(ws[0][4]) or ws[1][4] != "-" or ws[0][0] > 60:
            return False
        return not any(_num(w[4]) is not None and w[2] > 535 for w in ws)

    def _registra(self, ws, extras, pilha, eh_despesa, pagina, receitas, lancs, composicao):
        """Monta uma linha (receita ou despesa) a partir da âncora `ws` e das linhas de continuação `extras`."""
        data = ws[0][4]
        valor_tok = next(w for w in reversed(ws) if _num(w[4]) is not None and w[2] > 535)
        valor = _num(valor_tok[4])
        desc_t, forn_t, doc_t = [], [], []
        todos = sorted([w for linha in [ws] + extras for w in linha], key=lambda w: (round((w[1] + w[3]) / 6), w[0]))
        for w in todos:
            if w is valor_tok or (w[4] == data and w[0] < 40):
                continue
            if w[0] < 300:
                desc_t.append(w[4])
            elif w[0] < 420:
                forn_t.append(w[4])
            elif w[0] < 480:
                doc_t.append(w[4])
        descricao, forn, doc = " ".join(desc_t).strip(), " ".join(forn_t).strip(), " ".join(doc_t).strip()
        cod_doc = doc.split()[0] if doc else None
        mnf = re.search(r"\((\d+)\)", doc)
        nf = mnf.group(1) if mnf else None
        folha = pilha[-1] if pilha else ("", "")
        rotulo = f"{folha[0]} - {folha[1]}" if folha[0] else "SEM SUBCONTA"
        bbox = (ws[0][0], min(w[1] for w in ws), valor_tok[2], max(w[3] for w in ws))
        if not eh_despesa:
            tipo = self._tipo_receita(rotulo, descricao)
            conta = self._conta_rendimento(descricao) if tipo == "rendimento" else rotulo
            receitas.append(LinhaReceita(conta=conta, descricao=descricao or rotulo, valor=valor, tipo=tipo,
                                         data=data, pagina=pagina, bbox=bbox))
            return
        fundo, parc = None, None
        info = composicao.get(cod_doc or "")
        if info:
            cand = [f for (cc, f, v) in info["fundos"] if cc == folha[0] and abs(abs(v) - abs(valor)) <= _CENT]
            if not cand:
                cand = [f for (_, f, v) in info["fundos"] if abs(abs(v) - abs(valor)) <= _CENT]
            if not cand and len({f for (_, f, _) in info["fundos"]}) == 1:
                cand = [info["fundos"][0][1]]
            fundo = cand[0] if cand else None
            if info["parcela"] and info["parcela"][1] > 1:
                parc = info["parcela"]
        # A forma de pagamento sai impressa no fim da descrição ("(PIX-CH)", "(Boleto)", "(Déb. Auto)", "(Tributos*)"):
        # muda de um mês para o outro e atrapalharia o reconhecimento da mesma despesa — não faz parte do histórico.
        descricao = re.sub(r"\s*\((?:PIX[- ]?\w*|Boleto|D[ée]b\.? ?Auto|Tributos\*?|Outro|Cheque|TED|DOC|Dinheiro)\)", "", descricao, flags=re.I).strip()
        desc_final = descricao
        if nf:
            desc_final += f" - NF {nf}"
        if parc and not re.search(r"PARC", desc_final, re.I):
            desc_final += f" - PARC {parc[0]}/{parc[1]}"
        # Retenções ("ISS - Sant Anna", "PCC - Conab", "INSS - ...") são pagas ao fisco, mas pertencem à despesa-mãe e à
        # subconta dela: o "fornecedor" do imposto é o órgão, o que não identifica a despesa — a regra de subcontas usa a descrição.
        imposto = bool(re.match(r"^(ISS|PCC|INSS|IRRF|CSRF|PIS|COFINS|CSLL|DARF|GPS|FGTS)\b", descricao, re.I))
        # No Analítico a despesa vem negativa; o modelo guarda o valor pago como positivo (débito da conta).
        lancs.append(LancamentoDespesa(
            descricao=desc_final.strip(), valor=-valor, categoria=rotulo, conta=fundo or _SEM_FUNDO,
            codigo=cod_doc, data=data, fornecedor=None if imposto else (forn or None), pagina=pagina, bbox=bbox))

    @staticmethod
    def _tipo_receita(rotulo: str, descricao: str) -> str:
        n = _norm(rotulo + " " + descricao)
        if "RENDIMENTO" in n:
            return "rendimento"
        if "INADIMPLENCIA" in n and "RECUPERADA EM" in n:
            # baixa contábil da cobrança do Pro-Síndico ("Inadimplência ... de Mai/26 recuperada em Jun/26"):
            # vem NEGATIVA por construção do formato, em todas as classes de receita, todo mês
            return "baixa_inadimplencia"
        if "JUROS" in n or "MULTA" in n:
            return "multa_juros"
        if "COTA" in n:
            return "cota"
        if "TRANSFER" in n:
            return "transferencia"
        return "outra"

    @staticmethod
    def _conta_rendimento(descricao: str) -> str:
        m = re.search(r"\bp/\s*(.+)$", descricao, re.I)
        alvo = _norm(m.group(1)) if m else ""
        return _ALIAS_FUNDO.get(alvo, alvo.title() or "Rendimento (fundo não identificado)")

    # ── conferências ─────────────────────────────────────────────────────────
    def _conferir(self, dados: DadosRegras, totais: dict):
        s_rec = round(sum(r.valor for r in dados.receitas), 2)
        if totais.get("receitas") is not None and abs(s_rec - totais["receitas"]) > _CENT:
            dados.avisos.append(f"Σ receitas lidas ({s_rec:,.2f}) difere de 'Total de 1 - RECEITAS' ({totais['receitas']:,.2f})")
        s_des = round(sum(l.valor for l in dados.lancamentos), 2)
        if totais.get("despesas") is not None and abs(s_des - totais["despesas"]) > _CENT:
            dados.avisos.append(f"Σ lançamentos lidos ({s_des:,.2f}) difere de 'Total de 2 - DESPESAS' ({totais['despesas']:,.2f})")
        s_rend = round(sum(r.valor for r in dados.receitas if r.tipo == "rendimento"), 2)
        if totais.get("rendimento") is not None and abs(s_rend - totais["rendimento"]) > _CENT:
            dados.avisos.append(f"Σ rendimento lido ({s_rend:,.2f}) difere de '1.1.2 - Rendimento de Investimentos' ({totais['rendimento']:,.2f})")
        sem_fundo = [l for l in dados.lancamentos if l.conta == _SEM_FUNDO]
        if sem_fundo:
            dados.avisos.append(f"{len(sem_fundo)} lançamento(s) sem a tela 'Despesa' correspondente no PDF: o fundo pagador não pôde ser lido "
                                f"(R$ {sum(l.valor for l in sem_fundo):,.2f})")
