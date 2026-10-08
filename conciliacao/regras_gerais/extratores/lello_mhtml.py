"""
Extrator das regras gerais — Lello "prestacaocontas_NNNN_AAAA_MM.xls" (na verdade HTML/MHTML).

Condomínios: hub_home_club_tatuape, residencial_villa_park_osasco, splendor_square (empresa_gestora = lello_xls).

O arquivo é uma sequência de tabelas HTML (ou, quando salvo pelo Excel como "página da Web",
um arquivo-moldura `.xls` + `<nome>_arquivos/sheet001.htm` com UMA tabela só — caso do Splendor
jun/2026). Como a ordem das linhas é a mesma nos dois casos, o extrator trata o arquivo como um
fluxo único de linhas e reconhece as seções pelos marcadores:

  "Resumo Financeiro Contábil"      conta | saldo anterior | crédito | débito | saldo atual
  <CONTA> + "Resumo emissão" ...    (previsto x realizado — NÃO usado)
  "Posição Financeira" (por conta)  linhas de crédito/débito da conta; é daqui que vêm o rendimento
                                    da conta e as linhas que NÃO aparecem nos demonstrativos
                                    (TRANSFERÊNCIAS, APLICAÇÃO / RESGATE, IR/IOF)
  "DEMONSTRATIVO DE DESPESAS"       conta > GRUPO > subconta > lançamentos (data | histórico | valor),
                                    com "Total <SUB>", "<GRUPO> Total:", "Total ORDINARIA" ...
  "DEMONSTRATIVO DE RECEITAS"       seção > recibos (data | unidade | recibo | vencto | histórico | valor),
                                    "TOTAL <SEÇÃO>" e "TOTAL <cód> <CONTA>" (a conta só aparece NO FIM do bloco)

Mapeamento para o modelo
  receitas     cada recibo/linha do Demonstrativo de Receitas (sinal como impresso) + as linhas de crédito
               que só existem na Posição Financeira (transferência, aplicação/resgate)
  contas       Resumo Financeiro Contábil; `rendimento` = linha "rendimento aplic. financeira" (crédito)
               da Posição Financeira da conta
  lancamentos  cada linha do Demonstrativo de Despesas; `categoria` = SUBCONTA (nível mais fino, como no
               arquivo, ex.: "elevador", "elevador - extra"); o GRUPO vai em `local`

Conferência da extração (`verificar_extracao` compara lançamentos x ContaMes.debitos)
  O débito de uma conta no Resumo inclui movimentos que NÃO são despesa e que o Demonstrativo não lista:
  TRANSFERÊNCIAS e APLICAÇÃO / RESGATE (e o Resumo já abate o IR/IOF s/ resgate do débito e do crédito).
  Por isso `ContaMes.debitos` recebe o total de DESPESAS da conta (= "Total <CONTA>" do Demonstrativo)
  quando — e só quando — o Resumo fecha ao centavo com despesas + movimentos da Posição Financeira;
  nesse caso entra um aviso curto "Conferência: ...". Se não fecha, `debitos` fica como o Resumo imprime
  e `verificar_extracao` acusa a diferença de verdade.

Parcelas: o Lello escreve "ref. 02/04 ...", "ref, 3/10 ..." ou "1/2 ..." (início do histórico) para parcela
n de t; como a regra procura "PARC n/t", o extrator ACRESCENTA " (PARC n/t)" ao fim da descrição nesses casos.
"""
import re
import unicodedata
from pathlib import Path
from typing import Optional

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CENTAVO = 0.011


# ── utilidades ───────────────────────────────────────────────────────────────

def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _chave(s: str) -> str:
    """Nome comparável: maiúsculas, sem acento, sem pontuação, espaços colapsados."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", _sem_acento(s).upper())).strip()


def _limpa(s) -> str:
    return " ".join(str(s or "").replace("\xa0", " ").split())


_RE_PERC = re.compile(r"\(\s*-?[\d.,]+\s*%\s*\)")


def _num(v) -> Optional[float]:
    """Valor BR de uma célula: '1.234,56', '- 89.120,60', '-10.880,73', '843', '58,3', '3.848,00( 3,65%)'.
    None se não for número."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = _RE_PERC.sub("", str(v)).replace("R$", "").replace(" ", "").replace("\xa0", "")
    if not s:
        return None
    neg = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()-")
    if not re.fullmatch(r"\d[\d.]*(,\d+)?|,\d+", s):
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _fmt(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")

_RE_PARC_INICIO = re.compile(r"^\s*(?:ref[.,]?\s*)?(\d{1,2})\s*/\s*(\d{1,2})\s+(?=\S)", re.IGNORECASE)


def _marca_parcela(descricao: str) -> str:
    """Acrescenta ' (PARC n/t)' quando o histórico usa a notação Lello 'ref. n/t' / 'n/t ...' (parcela n de t)."""
    if re.search(r"\bPARC", descricao, re.IGNORECASE):
        return descricao
    m = _RE_PARC_INICIO.match(descricao)
    if m:
        n, t = int(m.group(1)), int(m.group(2))
        if t >= 2 and 1 <= n <= t <= 60:
            return f"{descricao} (PARC {n}/{t})"
    return descricao


def _tipo_receita(secao: str) -> str:
    c = _chave(secao)
    if "RENDIMENTO" in c:
        return "rendimento"
    if "TRANSFER" in c or "APLICACAO" in c or "RESGATE" in c:
        return "transferencia"
    if "MULTA" in c or "JURO" in c or "ATUALIZACAO" in c:
        return "multa_juros"
    if "EMISSAO" in c or "COTA" in c or "REC PROCESSO" in c or "ANTECIPA" in c:
        return "cota"
    return "outra"


def _eh_ir(label: str) -> bool:
    c = _chave(label)
    return bool(re.match(r"^(IR|IOF|IMPOSTO DE RENDA)\b", c)) or "IR IOF" in c or "IOF" in c.split()


def _eh_movimento(label: str) -> bool:
    c = _chave(label)
    return bool(re.search(r"TRANSFER|APLICACAO|RESGATE|ENTRE CONTAS", c)) and not _eh_ir(label)


# ── leitura do arquivo ───────────────────────────────────────────────────────

def _decodifica(b: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("latin-1", errors="replace")


def _texto_html(caminho: Path) -> str:
    """HTML do próprio arquivo (trata MHTML multipart; UTF-8 ou cp1252)."""
    raw = caminho.read_bytes()
    if re.match(rb"\s*(MIME-Version|From:|Content-Type:\s*multipart)", raw[:400], re.IGNORECASE):
        import email
        msg = email.message_from_bytes(raw)
        partes = [p.get_payload(decode=True) for p in msg.walk() if p.get_content_type() == "text/html"]
        raw = b"\n".join(p for p in partes if p) or raw
    return _decodifica(raw)


def _html_sidecar(caminho: Path, condo: Optional[dict] = None) -> tuple[Optional[str], Optional[str]]:
    """Arquivo-moldura do Excel ("Excel Workbook Frameset", salvo como 'página da Web'): o .xls só tem JavaScript
    e os dados ficam em <nome>_arquivos/sheet*.htm. Procura ao lado do arquivo e, se não achar (o Admin copia só o .xls para
    a pasta input/ da validação), na pasta de prestações do condomínio. (html, nota) ou (None, None)."""
    bases = [caminho.parent]
    try:
        from conciliacao import pasta_prestacao
        pasta = pasta_prestacao.pasta_do_condominio(condo or {})
        if pasta is not None and pasta not in bases:
            bases.append(pasta)
    except Exception:
        pass
    for base in bases:
        for pasta in sorted(base.glob(f"{caminho.stem}_*")):
            folhas = sorted(pasta.glob("sheet*.htm")) if pasta.is_dir() else []
            if folhas:
                html = "\n".join(_decodifica(f.read_bytes()) for f in folhas)
                return html, f"arquivo salvo como 'página da Web' do Excel; dados lidos de {pasta.name}/{folhas[0].name}"
    return None, None


def _tem_resumo(rows) -> bool:
    return any(_chave(c[0]) == "RESUMO FINANCEIRO CONTABIL" for _, _, c in rows)


def _linhas(html: str) -> list[tuple[int, int, list[str]]]:
    """Fluxo único de linhas: (nº da tabela, nº da linha na tabela, células com texto limpo e sem vazios no fim)."""
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    saida = []
    for ti, tabela in enumerate(soup.find_all("table"), 1):
        if tabela.find("table"):
            continue
        for ri, tr in enumerate(tabela.find_all("tr"), 1):
            cel = [_limpa(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            while cel and not cel[-1]:
                cel.pop()
            if cel:
                saida.append((ti, ri, cel))
    return saida


# ── extrator ─────────────────────────────────────────────────────────────────

class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo
        self.cfg = condo.get("parser_config") or {}

    # -- API ------------------------------------------------------------------
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        caminho = Path(caminho)
        if caminho.suffix.lower() == ".pdf":
            # Os condomínios Lello (Hub, Splendor, Villa Park) passaram a enviar também o "Demonstrativo de Contas"
            # em PDF (estilo ContasData, exportação parcial pelo Stimulsoft): mesmo conteúdo, outro formato.
            from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ExtratorContasData

            # O nível de subconta lido no PDF vem da configuração DE CADA CONDOMÍNIO (parser_config.regras_gerais.
            # nivel_categoria em config/validacao_balancetes.json): só é ajustado para os condomínios cujo PDF foi conferido.
            condo = self.condo
            return _ExtratorContasData(condo).extrair(caminho, mes)
        nota = None
        html = _texto_html(caminho)
        rows = _linhas(html)
        if not _tem_resumo(rows):
            html2, nota2 = _html_sidecar(caminho, self.condo)
            if html2:
                html, nota, rows = html2, nota2, _linhas(html2)
        if not _tem_resumo(rows):
            if "Excel Workbook Frameset" in html or "frameset" in html.lower():
                raise ValueError(f"{caminho.name} foi salvo como 'página da Web' do Excel: os dados ficam na pasta "
                                 f"'{caminho.stem}_arquivos' (sheet001.htm), que não está ao lado do arquivo nem na pasta do condomínio. "
                                 f"Envie também essa pasta ou reexporte o balancete do sistema da administradora")
            raise ValueError("Não encontrei o 'Resumo Financeiro Contábil' no arquivo (não parece uma prestação de contas Lello)")
        dados = DadosRegras(mes=mes, arquivo=caminho.name)
        if nota:
            dados.avisos.append(nota)

        self._confere_periodo(html, mes, dados)
        contas = self._resumo(rows)
        pos = self._posicoes(rows, contas)
        rec_linhas, rec_totais = self._demonstrativo_receitas(rows, contas, dados)
        lanc, desp_totais = self._demonstrativo_despesas(rows, contas, dados)

        self._montar_receitas(dados, contas, pos, rec_linhas, rec_totais)
        self._montar_contas(dados, contas, pos, lanc, desp_totais)
        dados.lancamentos = lanc

        tem_pos = bool(pos)
        dados.cobertura = {
            "receitas": bool(rec_linhas) or tem_pos,
            "rendimentos": bool(contas) and tem_pos,
            "lancamentos": bool(lanc),
        }
        if not dados.cobertura["receitas"]:
            dados.motivos_nao_cobertos["receitas"] = "o arquivo não traz o Demonstrativo de Receitas nem a Posição Financeira por conta"
        if not dados.cobertura["rendimentos"]:
            dados.motivos_nao_cobertos["rendimentos"] = "o arquivo não traz o Resumo Financeiro Contábil ou a Posição Financeira por conta"
        if not dados.cobertura["lancamentos"]:
            dados.motivos_nao_cobertos["lancamentos"] = "o arquivo não traz o Demonstrativo de Despesas com lançamentos"
        return dados

    # -- período --------------------------------------------------------------
    @staticmethod
    def _confere_periodo(html: str, mes: str, dados: DadosRegras):
        m = re.search(r"Per[ií]odo:\s*(\d{1,2})\s*/\s*(\d{4})", re.sub(r"<[^>]+>", " ", html))
        if m and f"{int(m.group(2)):04d}-{int(m.group(1)):02d}" != mes:
            dados.avisos.append(f"o período impresso no arquivo é {int(m.group(1)):02d}/{m.group(2)}, diferente do mês informado ({mes[5:]}/{mes[:4]})")

    # -- Resumo Financeiro Contábil -------------------------------------------
    @staticmethod
    def _resumo(rows) -> dict:
        """{chave: ContaMes}, na ordem do arquivo."""
        contas: dict[str, ContaMes] = {}
        for i, (_, _, c) in enumerate(rows):
            if _chave(c[0]) == "RESUMO FINANCEIRO CONTABIL":
                for _, _, r in rows[i + 1:]:
                    if len(r) >= 5 and _chave(r[0]) == "CONTA":
                        continue
                    if len(r) < 5:
                        break
                    if _chave(r[0]) == "TOTAL":
                        break
                    sa, cr, db, at = (_num(x) for x in r[1:5])
                    if None in (sa, cr, db, at):
                        break
                    contas[_chave(r[0])] = ContaMes(nome=r[0].upper(), saldo_anterior=sa, creditos=cr, debitos=db, saldo_atual=at)
                break
        return contas

    # -- Posição Financeira por conta -----------------------------------------
    @staticmethod
    def _posicoes(rows, contas) -> dict:
        """{chave da conta: {"nome", "linhas": [(label, débito, crédito, local)], "tot_deb", "tot_cred"}}"""
        res: dict = {}
        titulo = None
        i = 0
        while i < len(rows):
            ti, ri, c = rows[i]
            prox = rows[i + 1][2] if i + 1 < len(rows) else []
            if len(c) == 1 and prox and (_chave(prox[0]) == "RESUMO EMISSAO" or (_chave(prox[0]) == "CONTA" and len(prox) > 1 and prox[1] == "")):
                titulo = c[0]
            if len(c) == 1 and _chave(c[0]) == "POSICAO FINANCEIRA" and titulo:
                bloco = {"nome": titulo, "linhas": [], "tot_deb": None, "tot_cred": None}
                j = i + 1
                while j < len(rows):
                    tj, rj, r = rows[j]
                    r = r + [""] * (5 - len(r))
                    label = r[1]
                    if r[0] == "" and label:
                        lc = _chave(label)
                        deb, cred = _num(r[3]), _num(r[4])
                        if lc.startswith("SALDO ATUAL"):
                            break
                        if lc.startswith("SALDO ANTERIOR"):
                            pass
                        elif lc == "TOTAIS":
                            bloco["tot_deb"], bloco["tot_cred"] = deb or 0.0, cred or 0.0
                        else:
                            bloco["linhas"].append((label, deb or 0.0, cred or 0.0, f"tabela {tj}, linha {rj}"))
                    elif len(rows[j][2]) == 1 and j > i + 1:
                        break  # novo título: bloco sem "saldo atual"
                    j += 1
                chave = _chave(titulo)
                # título da Posição pode diferir do nome do Resumo (acento/abreviação): tenta casar
                if chave not in contas:
                    cand = [k for k in contas if k.startswith(chave) or chave.startswith(k)]
                    chave = cand[0] if len(cand) == 1 else chave
                res[chave] = bloco
                titulo = None   # um título vale para um bloco só (evita atribuir a Posição de uma conta ao título da anterior)
                i = j
            i += 1
        return res

    # -- Demonstrativo de Receitas --------------------------------------------
    def _demonstrativo_receitas(self, rows, contas, dados):
        """([(conta_chave, secao, ConteudoLinha)], {conta_chave: total impresso}).
        A conta de cada bloco só é conhecida no fim ('TOTAL <cód> <CONTA>'): as linhas ficam pendentes até lá."""
        inicio = next((i for i, (_, _, c) in enumerate(rows) if _chave(c[0]) == "DEMONSTRATIVO DE RECEITAS"), None)
        linhas, totais = [], {}
        if inicio is None:
            return linhas, totais
        pendentes, secao = [], ""
        sec_totais: list[tuple[str, float, float]] = []
        for ti, ri, c in rows[inicio + 1:]:
            c0 = c[0]
            if _chave(c0).startswith("TOTAL RECEITA"):
                break
            if len(c) >= 6 and _RE_DATA.match(c0):
                v = _num(c[5])
                if v is None:
                    continue
                pendentes.append({"secao": secao, "data": c0, "unidade": c[1], "recibo": c[2], "hist": c[4], "valor": v, "local": f"tabela {ti}, linha {ri}"})
            elif len(c) == 1 and _chave(c0) not in ("DATA", ""):
                secao = c0
            elif len(c) >= 3 and c0 == "":
                m = re.match(r"^TOTAL\s+(\d+)\s+(.+)$", c[1], re.IGNORECASE)
                v = _num(c[2])
                if m:  # fecha a conta
                    ck = _chave(m.group(2))
                    if ck not in contas:
                        cand = [k for k in contas if k.startswith(ck) or ck.startswith(k)]
                        ck = cand[0] if len(cand) == 1 else ck
                    for p in pendentes:
                        linhas.append((ck, p))
                    soma = round(sum(p["valor"] for p in pendentes), 2)
                    if v is not None and abs(soma - v) > _CENTAVO:
                        dados.avisos.append(f"Demonstrativo de Receitas, conta {m.group(2).title()}: recibos somam {_fmt(soma)}, total impresso {_fmt(v)}")
                    totais[ck] = v
                    pendentes = []
                else:  # total de seção: confere com as linhas da seção
                    nome = re.sub(r"^TOTAL\s+", "", c[1], flags=re.IGNORECASE)
                    soma = round(sum(p["valor"] for p in pendentes if p["secao"] == secao), 2)
                    if v is not None and abs(soma - v) > _CENTAVO:
                        dados.avisos.append(f"Demonstrativo de Receitas, seção {nome}: recibos somam {_fmt(soma)}, total impresso {_fmt(v)}")
        if pendentes:
            dados.avisos.append(f"Demonstrativo de Receitas: {len(pendentes)} linha(s) no fim do arquivo sem o total da conta; ficaram sem conta")
            for p in pendentes:
                linhas.append(("", p))
        return linhas, totais

    # -- Demonstrativo de Despesas --------------------------------------------
    def _demonstrativo_despesas(self, rows, contas, dados):
        """([LancamentoDespesa], {conta_chave: 'Total <CONTA>' impresso})"""
        inicio = next((i for i, (_, _, c) in enumerate(rows) if _chave(c[0]) == "DEMONSTRATIVO DE DESPESAS"), None)
        lanc: list[LancamentoDespesa] = []
        totais: dict = {}
        if inicio is None:
            return lanc, totais
        conta: Optional[str] = None
        grupo: Optional[str] = None
        sub: Optional[str] = None
        pend: list[LancamentoDespesa] = []

        def nome_conta(nome: str) -> str:
            ck = _chave(nome)
            if ck in contas:
                return contas[ck].nome
            cand = [k for k in contas if k.startswith(ck) or ck.startswith(k)]
            return contas[cand[0]].nome if len(cand) == 1 else nome.upper()

        fim = len(rows)
        corpo = rows[inicio + 1:]
        for idx, (ti, ri, c) in enumerate(corpo):
            c0 = c[0]
            n = len(c)
            if n >= 2 and _chave(c0) == "TOTAL DESPESAS":
                totais["__TOTAL__"] = _num(c[1])
                break
            if n == 3 and _chave(c0) == "DATA":
                continue
            if n == 1:
                if _chave(c0) in ("", "DATA"):
                    continue
                m = re.match(r"^(.+?)\s*-\s*Demonstrativos? de Despesas$", c0, re.IGNORECASE)
                if m:
                    conta, grupo, sub = nome_conta(m.group(1)), None, None
                    continue
                if conta is None:  # primeira conta do arquivo (ORDINÁRIA), sem o sufixo
                    conta = nome_conta(c0)
                    continue
                prox = corpo[idx + 1][2] if idx + 1 < len(corpo) else []
                if len(prox) == 1 and _chave(prox[0]) not in ("", "DATA") and not re.search(r"Demonstrativos? de Despesas$", prox[0], re.IGNORECASE):
                    grupo = c0            # cabeçalho seguido de outro cabeçalho => grupo
                else:
                    sub = c0              # cabeçalho seguido de lançamentos => subconta
                continue
            if n >= 3 and _RE_DATA.match(c0):
                v = _num(c[2])
                if v is None or conta is None:
                    continue
                desc = _marca_parcela(c[1])
                l = LancamentoDespesa(descricao=desc, valor=v, categoria="", conta=conta, data=c0,
                                      local=f"tabela {ti}, linha {ri}" + (f" (grupo {grupo})" if grupo else ""))
                pend.append(l)
                continue
            if n >= 3 and c0 == "" and _chave(c[1]).startswith("TOTAL "):
                cat = sub or re.sub(r"^Total\s+", "", c[1], flags=re.IGNORECASE)
                for l in pend:
                    l.categoria = cat
                lanc.extend(pend)
                pend, sub = [], None
                continue
            if n == 2 and re.search(r"\bTotal:\s*$", c0, re.IGNORECASE):
                grupo = None
                continue
            if n == 2 and re.match(r"^Total\s+\S", c0, re.IGNORECASE):
                if pend:  # lançamentos soltos antes do total da conta (sem subtotal próprio)
                    for l in pend:
                        l.categoria = sub or "SEM SUBCONTA"
                    lanc.extend(pend)
                    pend = []
                totais[_chave(re.sub(r"^Total\s+", "", c0, flags=re.IGNORECASE))] = _num(c[1])
                continue
        if pend:
            for l in pend:
                l.categoria = sub or "SEM SUBCONTA"
            lanc.extend(pend)
            dados.avisos.append(f"Demonstrativo de Despesas: {len(pend)} lançamento(s) sem subconta/total reconhecido")
        return lanc, totais

    # -- receitas -------------------------------------------------------------
    def _montar_receitas(self, dados, contas, pos, rec_linhas, rec_totais):
        """Receitas = recibos do Demonstrativo de Receitas + linhas de crédito que só existem na Posição Financeira.

        O rótulo da Posição nem sempre é igual ao da seção do Demonstrativo ("g - consumo energia" x
        "EMISSÃO DO PERIODO - ENERGIA"), então o pareamento é pelo VALOR: cada linha de crédito da Posição
        é casada, ao centavo, com uma seção do Demonstrativo da mesma conta (rótulo igual desempata);
        o que sobra na Posição (TRANSFERÊNCIAS, APLICAÇÃO / RESGATE...) entra como receita 'somente na Posição'."""
        secoes: dict = {}   # ck -> {chave_da_seção: soma}
        for ck, p in rec_linhas:
            cnome = contas[ck].nome if ck in contas else (ck or "")
            # IR retido no resgate/rendimento faz parte do movimento de aplicação (sinal negativo por natureza)
            tipo = "transferencia" if (_eh_ir(p["secao"]) or _eh_ir(p["hist"])) else _tipo_receita(p["secao"])
            dados.receitas.append(LinhaReceita(
                conta=cnome,
                descricao=f"{p['hist']} [{p['secao'].title()}" + (f"; unid. {p['unidade']}" if p["unidade"] not in ("", "0") else "")
                          + (f"; recibo {p['recibo']}" if p["recibo"] not in ("", "0") else "") + "]",
                valor=p["valor"], tipo=tipo, data=p["data"], local=p["local"]))
            d = secoes.setdefault(ck, {})
            k = _chave(p["secao"])
            d[k] = round(d.get(k, 0.0) + p["valor"], 2)

        for ck, bloco in pos.items():
            cnome = contas[ck].nome if ck in contas else bloco["nome"].upper()
            livres = dict(secoes.get(ck, {}))
            for label, deb, cred, loc in bloco["linhas"]:
                if not cred:
                    continue
                cand = [k for k, v in livres.items() if abs(v - cred) <= _CENTAVO]
                if cand:
                    k = _chave(label) if _chave(label) in cand else cand[0]
                    del livres[k]
                else:
                    dados.receitas.append(LinhaReceita(
                        conta=cnome, descricao=f"{label} [somente na Posição Financeira]", valor=cred,
                        tipo=_tipo_receita(label), local=loc))
            # a soma de tudo que entrou como receita da conta deve fechar com o crédito do Resumo
            c = contas.get(ck)
            if c is not None:
                soma = round(sum(r.valor for r in dados.receitas if _chave(r.conta) == ck), 2)
                irf = round(sum(d for l, d, _, _ in bloco["linhas"] if _eh_ir(l)), 2)
                esperado = round(c.creditos, 2)
                if abs(soma - esperado) > _CENTAVO and abs(soma - irf - esperado) > _CENTAVO:
                    dados.avisos.append(f"{cnome}: receitas lidas somam {_fmt(soma)}, mas o crédito da conta no Resumo é {_fmt(esperado)} (diferença de {_fmt(soma - esperado)})")

    # -- contas ---------------------------------------------------------------
    def _montar_contas(self, dados, contas, pos, lanc, desp_totais):
        soma_lanc: dict = {}
        for l in lanc:
            soma_lanc[_chave(l.conta)] = round(soma_lanc.get(_chave(l.conta), 0.0) + l.valor, 2)
        for ck, c in contas.items():
            bloco = pos.get(ck)
            # rendimento BRUTO creditado na conta: linhas do Demonstrativo de Receitas (o IR retido no resgate/rendimento é
            # lançado com sinal negativo e entra como tipo "transferencia", fora desta soma); sem elas, a Posição Financeira.
            rend_linhas = [r.valor for r in dados.receitas if _chave(r.conta) == ck and r.tipo == "rendimento"]
            if rend_linhas:
                c.rendimento = round(sum(rend_linhas), 2)
            elif bloco:
                c.rendimento = round(sum(cred for l, deb, cred, _ in bloco["linhas"] if "RENDIMENTO" in _chave(l)), 2)

            # débito do Resumo x despesas do Demonstrativo (+ movimentos que não são despesa)
            demo = desp_totais.get(ck)
            if demo is None and ck in soma_lanc:
                demo = soma_lanc[ck]
            if demo is None:
                if c.debitos and bloco is None:
                    dados.avisos.append(f"{c.nome}: débito de {_fmt(c.debitos)} no Resumo, mas a conta não aparece no Demonstrativo de Despesas nem na Posição Financeira")
                continue
            mov_linhas = [(l, d) for l, d, _, _ in (bloco["linhas"] if bloco else []) if d and _eh_movimento(l)]
            mov = round(sum(d for _, d in mov_linhas), 2)
            if abs(c.debitos - demo) <= _CENTAVO:
                continue
            if abs(c.debitos - (demo + mov)) <= _CENTAVO and mov:
                partes = {}
                for l, d in mov_linhas:
                    partes[l] = partes.get(l, 0.0) + d
                det = " + ".join(f"{k} {_fmt(v)}" for k, v in partes.items())
                dados.avisos.append(f"Conferência {c.nome}: débito do Resumo {_fmt(c.debitos)} = despesas {_fmt(demo)} + {det} "
                                    f"(movimento, não é despesa); lançamentos conferidos contra as despesas")
                c.debitos = demo
            else:
                dados.avisos.append(f"{c.nome}: débito no Resumo {_fmt(c.debitos)} não fecha com o Demonstrativo de Despesas {_fmt(demo)}"
                                    + (f" nem com despesas + movimentos ({_fmt(demo + mov)})" if mov else "") + " — diferença sem explicação no arquivo")
        dados.contas = list(contas.values())
