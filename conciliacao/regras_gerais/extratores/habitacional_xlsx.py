"""
Extrator das regras gerais — planilha Habitacional (XLSX "prestacao_contas_M_AAAA").

Serve a todos os condomínios do grupo "habitacional" (alvorada, plano_cambuci, cinque_terre_residenza, cores,
elo_elo_duo, go_barra_funda, go_liberdade, living_for_consolacao, onze_22, port_saint_tropez, sublime, victoria,
baturite — meses em planilha — e guaratambe/lfc_xlsx, que usa a mesma estrutura). Confirmado abrindo as
planilhas reais de cada um (abr/2025 a ago/2026).

A planilha é uma única aba com blocos em sequência; cada bloco começa numa linha "Condomínio: ..." seguida do
título. A ORDEM e a presença dos blocos variam por condomínio e por mês (por isso nada aqui depende de linha fixa):

  Resumo Financeiro Contábil   conta | saldo anterior | créditos | débitos | saldo atual (fecha em TOTAL)
  Demonstrações Por Conta      por conta: [Resumo de Emissão] + "Posição Financeira" (linhas com Débito/Crédito);
                               pode vir ANTES do Resumo Financeiro (Elo, Onze 22, Go Liberdade a partir de mai/26)
  Demonstrativo de Despesas    conta > subconta (> subconta) > lançamentos; "TOTAL DA CONTA <x>" fecha cada nível
  Demonstrativo de Receitas    presente em 2 layouts, ausente em outros condomínios:
        A (Alvorada)  Unidade | Recibo | Vencimento | Data | Valor | Multa/Desc. | Recebido  + "Resumo de Recebimentos"
        B (Cinque Terre, Cores, Plano Cambuci, Go Barra Funda, Go Liberdade, Sublime, Living For)
                      conta > grupo > linhas "Data | Bloco/Unidade | Recibo | Vencto | Histórico | Valor"
        (sem)         Baturité, Elo, Onze 22, Port Saint Tropez, Victoria, Guaratambé: só a Posição Financeira
  Transferências               (opcional) histórico das transferências/recebimentos em duplicidade entre contas

Fonte de cada informação:
  contas        Resumo Financeiro Contábil (saldos/créditos/débitos). `debitos` = débito do Resumo MENOS as
                transferências entre contas (que estão dentro do débito do Resumo mas não são despesa do
                Demonstrativo) — assim a soma dos lançamentos fecha com `debitos`; o aviso diz quanto foi tirado.
  receitas      layout B: cada linha do Demonstrativo de Receitas (com sinal). Layouts A e sem-demonstrativo:
                linhas de Crédito da Posição Financeira de cada conta + linhas de DÉBITO que são estorno de receita
                (rótulo "(-) ...", DESCONTO(S), ou rótulo que também existe como crédito no arquivo — ex.: MULTA
                REGULAMENTAR, SEGURO RESIDENCIAL, RENDIMENTO APLICACAO), lançadas com valor NEGATIVO.
                Recibos negativos do Demonstrativo (layout A) também entram.
  rendimento    soma das linhas de receita tipo "rendimento" da conta (líquida de estornos).
  lancamentos   Demonstrativo de Despesas. categoria = subconta como no arquivo (nível com "TOTAL DA CONTA x", o mesmo do
                extrator ContasData); o nível abaixo, quando existe (Living For, Guaratambé, Cores...), vai em `rubrica`.
Conferência embutida: subtotais "TOTAL DA CONTA ..." impressos x soma dos lançamentos lidos (aviso se diferir).
"""
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CENTAVO = 0.011


def _brl(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ── utilidades ───────────────────────────────────────────────────────────────

def _num(v) -> float | None:
    """Número de uma célula: float/int, BR ('1.234,56', '(5,06)', '-5,06', '5,06-') ou ponto decimal ('1424.3')."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    neg = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()-")
    if not re.fullmatch(r"\d[\d.,]*", s):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _txt(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "strftime"):          # célula de data
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", _sem_acento(s).upper())).strip()


def _chave(s: str) -> str:
    """Só letras/dígitos: 'P/13o.SAL. E FERIAS' e 'P/ 13o.SAL E FERIAS' viram a mesma chave."""
    return re.sub(r"[^A-Z0-9]", "", _sem_acento(s).upper())


_STOP = {"DE", "DA", "DO", "E", "P", "S", "A", "O", "C", "COM", "PARA"}


def _tokens(s: str) -> set:
    return {t for t in _norm(s).split() if t not in _STOP}


def _casar_conta(nome: str, nomes: list[str]) -> str | None:
    """Nome da conta do Resumo Financeiro que corresponde a `nome` (outro bloco do mesmo arquivo), ou None.
    O Resumo é a fonte canônica; o Demonstrativo pode abreviar ('PROVISAO P/ 13o.SALARIO/FERIAS' x
    'PROVISAO P/13o.SAL. E FERIAS'). Ordem: igual, igual sem pontuação, abreviação (um é prefixo do outro),
    mesmos tokens, semelhança de texto >= 0,82 — sempre exigindo candidato único."""
    if not nome:
        return None
    n = _norm(nome)
    for c in nomes:
        if _norm(c) == n:
            return c
    k = _chave(nome)
    for c in nomes:
        if _chave(c) == k:
            return c
    cand = [c for c in nomes if len(k) >= 6 and (_chave(c).startswith(k) or k.startswith(_chave(c))) and min(len(k), len(_chave(c))) >= 6]
    if len(cand) == 1:
        return cand[0]
    t = _tokens(nome)
    cand = [c for c in nomes if t and _tokens(c) and (t <= _tokens(c) or _tokens(c) <= t)]
    if len(cand) == 1:
        return cand[0]
    melhor = sorted(((SequenceMatcher(None, n, _norm(c)).ratio(), c) for c in nomes), reverse=True)
    if melhor and melhor[0][0] >= 0.82 and (len(melhor) == 1 or melhor[0][0] - melhor[1][0] >= 0.05):
        return melhor[0][1]
    return None


_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _so_titulo(r: list) -> str:
    """Texto da linha quando só a coluna A está preenchida (nome de conta/grupo/subconta); senão ''."""
    if not r:
        return ""
    a = _txt(r[0])
    if not a or any(_txt(x) for x in r[1:]):
        return ""
    return a


def _tipo_receita(descricao: str, conta: str = "") -> str:
    d = _sem_acento(descricao).upper()
    if "RENDIMENT" in d or re.search(r"\bREND\b", d):
        return "rendimento"
    if "ATUALIZ" in d and "APLICA" in _sem_acento(conta).upper():
        return "rendimento"      # Baturité: o rendimento das contas "APLICACAO ..." vem como "ATUALIZAÇÃO MONETÁRIA"
    if "TRANSFER" in d:
        return "transferencia"
    if "MULTA" in d or "JURO" in d or "ATUALIZ" in d or "CORRECAO" in d:
        return "multa_juros"
    if re.search(r"COTA|CONDOMIN|EMISSAO|RECEBIMENTOS? DO PERIODO|ANTECIPA|ATRASO|FUNDO|AGUA|GAS|ENERGIA|LUZ|CONSUMO|RATEIO|IPTU|PROC\. COBRANCA|REC\. DE COBRANCA", d):
        return "cota"
    return "outra"


_RE_TRANSF = re.compile(r"TRANSFER|ACERTO CONTABIL", re.IGNORECASE)
_RE_ESTORNO = re.compile(r"^\(-\)|^DESCONT|^ESTORN|^DEVOL", re.IGNORECASE)


# ── leitura da planilha ──────────────────────────────────────────────────────

def _ler_linhas(caminho: Path) -> list[list]:
    import openpyxl
    wb = openpyxl.load_workbook(str(caminho), data_only=True, read_only=True)
    try:
        ws = wb.worksheets[0]
        return [list(row) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _titulo_bloco(linhas: list[list], i: int) -> str:
    """Título do bloco que começa na linha 'Condomínio: ...' (i): texto antes de ' Período'."""
    for j in range(i + 1, min(i + 4, len(linhas))):
        t = _txt(linhas[j][0]) if linhas[j] else ""
        if t:
            return re.split(r"\s+Per[ií]odo\b", t)[0].strip()
    return ""


def _blocos(linhas: list[list]) -> list[tuple[str, int, int]]:
    """[(título normalizado, ini, fim)] — fim exclusivo. Início = linha 'Condomínio: ...'."""
    marcas = [i for i, r in enumerate(linhas) if r and _txt(r[0]).lower().startswith("condomínio:")]
    out = []
    for k, i in enumerate(marcas):
        fim = marcas[k + 1] if k + 1 < len(marcas) else len(linhas)
        out.append((_norm(_titulo_bloco(linhas, i)), i, fim))
    return out


def _achar(blocos, trecho: str):
    trecho = _norm(trecho)
    return [(t, a, b) for t, a, b in blocos if trecho in t]


# ── Resumo Financeiro Contábil ───────────────────────────────────────────────

def _ler_resumo(linhas, ini, fim) -> list[ContaMes]:
    """Contas do Resumo Financeiro. Colunas pelo cabeçalho ('Saldo Anterior', 'Créditos', 'Débitos', 'Saldo Atual')."""
    contas: list[ContaMes] = []
    cols = None
    for i in range(ini, fim):
        r = linhas[i]
        if cols is None:
            if _txt(r[0] if r else None).upper() == "CONTA":
                m = {}
                for j, x in enumerate(r):
                    t = _norm(_txt(x))
                    if t == "SALDO ANTERIOR":
                        m["ant"] = j
                    elif t.startswith("CREDITO"):
                        m["cre"] = j
                    elif t.startswith("DEBITO"):
                        m["deb"] = j
                    elif t == "SALDO ATUAL":
                        m["atu"] = j
                if len(m) == 4:
                    cols = m
            continue
        nome = _txt(r[0] if r else None)
        if not nome:
            continue
        if nome.upper() == "TOTAL":
            break
        g = lambda k: (_num(r[cols[k]]) if cols[k] < len(r) else None) or 0.0
        contas.append(ContaMes(nome=nome, saldo_anterior=g("ant"), creditos=g("cre"), debitos=g("deb"), saldo_atual=g("atu")))
    return contas


# ── Posição Financeira (Demonstrações Por Conta) ─────────────────────────────

_TITULOS_NAO_CONTA = ("RESUMO DE EMISSAO", "RECEITAS PREVISTAS E REALIZADAS", "DEVEDORES E ACORDOS", "TOTAL DE DEVEDORES",
                      "POSICAO FINANCEIRA", "COMPOSICAO", "POSICAO DE CONTAS", "INFORMATIVO")


def _ler_posicoes(linhas, ini, fim) -> dict[str, dict]:
    """{conta: {"linhas": [(rotulo, debito, credito, nº linha 1-based)], "saldo_anterior": x, "saldo_atual": y}}
    para cada conta que tem 'Posição Financeira' (conta sem posição não tem saldo nem movimento)."""
    posicoes: dict[str, dict] = {}
    conta = None
    em_pos = False
    for i in range(ini, fim):
        r = linhas[i]
        if not r:
            continue
        a = _txt(r[0])
        if not a:
            continue
        au = _norm(a)
        deb = _num(r[8]) if len(r) > 8 else None
        cre = _num(r[10]) if len(r) > 10 else None
        if au.startswith("POSICAO FINANCEIRA"):
            em_pos = True
            if conta is not None:
                posicoes.setdefault(conta, {"linhas": [], "saldo_anterior": 0.0, "saldo_atual": 0.0})
            continue
        if em_pos:
            if au.startswith("SALDO ANTERIOR"):
                posicoes[conta]["saldo_anterior"] = (cre or 0.0) - (deb or 0.0)
            elif au.startswith("SALDO ATUAL"):
                posicoes[conta]["saldo_atual"] = (cre or 0.0) - (deb or 0.0)
                em_pos = False
            elif au == "TOTAIS" or a.startswith("-----"):
                continue
            elif deb is not None or cre is not None:
                posicoes[conta]["linhas"].append((a, deb or 0.0, cre or 0.0, i + 1))
            continue
        # fora da Posição: nome de conta = linha só com a coluna A, que não seja subtítulo conhecido
        t = _so_titulo(r)
        if t and not any(au.startswith(x) for x in _TITULOS_NAO_CONTA):
            conta = t
    return posicoes


# ── Demonstrativo de Despesas ────────────────────────────────────────────────

def _categoria(pilha: list[dict], nomes_contas: list[str]) -> tuple[str, str | None]:
    """(categoria, rubrica) do lançamento a partir da pilha conta > subconta [> rubrica].
    `categoria` é a subconta do balancete = o nível que tem "TOTAL DA CONTA x" e que aparece como linha de débito na
    Posição Financeira — o mesmo nível que o extrator de PDF ContasData usa (importante para Port Saint Tropez e Baturité,
    cujo arquivo do mês anterior pode estar no outro formato). O nível abaixo (Living For, Guaratambé, Cores, Plano
    Cambuci, Sublime, Go Barra Funda, Port Saint Tropez: "Salário", "Portaria", "Jardim"...) vai em `rubrica`.
    Quando a subconta é só o nome da própria conta ("PROVISAO P/ 13o.SALARIO/FERIAS" x "PROVISAO P/13o.SAL. E FERIAS",
    que muda de um mês para outro no mesmo arquivo) usa o nome da conta no Resumo — senão a regra de subcontas
    acusaria subconta nova todo mês."""
    conta_canon = _casar_conta(pilha[0]["nome"], nomes_contas) or pilha[0]["nome"]
    if len(pilha) == 1:
        return conta_canon, None
    nome = pilha[1]["nome"]
    if _casar_conta(nome, [conta_canon]) is not None or _casar_conta(nome, [pilha[0]["nome"]]) is not None:
        nome = conta_canon
    resto: list[str] = []
    for n in pilha[2:]:
        if _chave(n["nome"]) != _chave(nome) and (not resto or _chave(resto[-1]) != _chave(n["nome"])):
            resto.append(n["nome"])
    return nome, (" > ".join(resto) or None)


def _ler_despesas(linhas, ini, fim, nomes_contas: list[str], dados: DadosRegras, avisos: list[str],
                  nos_com_lancamento: set) -> tuple[dict, bool]:
    """Preenche dados.lancamentos. Devolve ({conta: total impresso}, achou_cabecalho).
    `nos_com_lancamento` recebe os nomes (normalizados) de todos os títulos que contêm lançamentos — as linhas de débito
    da Posição Financeira usam esses nomes, mesmo quando `categoria` colapsa níveis repetidos."""
    cols = {"cod": 0, "data": 1, "hist": 3, "valor": 7}
    achou = False
    pilha: list[dict] = []
    totais_conta: dict[str, float] = {}
    ultimo = None
    for i in range(ini, fim):
        r = linhas[i]
        if not r:
            continue
        a = _txt(r[0])
        if not achou:
            if _norm(a).startswith("N LANCTO") or _norm(a).startswith("N LAN"):
                for j, x in enumerate(r):
                    t = _norm(_txt(x))
                    if t == "DATA":
                        cols["data"] = j
                    elif t == "HISTORICO":
                        cols["hist"] = j
                    elif t == "VALOR":
                        cols["valor"] = j
                achou = True
            continue
        total_txt = next((_txt(x) for x in r[1:6] if _norm(_txt(x)).startswith("TOTAL D")), "")
        if total_txt:
            tn = _norm(total_txt)
            val = _num(r[cols["valor"]]) if cols["valor"] < len(r) else None
            if tn.startswith("TOTAL DAS DESPESAS"):
                break
            m = re.match(r"TOTAL DA CONTA (.*)$", tn)
            alvo = m.group(1) if m else ""
            # o relatório imprime "TOTAL DA CONTA x" só para os níveis 0 (conta) e 1 (grupo/subconta); o 3º nível,
            # quando existe (Living For, Guaratambé, Go Barra Funda), traz o subtotal na coluna "Total" da última linha.
            # Por isso o total fecha primeiro o nível 1, depois o 0 — importa quando os nomes se repetem
            # (conta "OBRAS/MELHORIAS" > "OBRAS/MELHORIAS" > "Obras/Melhorias").
            k = None
            for cand in (1, 0):
                if cand < len(pilha) and _norm(pilha[cand]["nome"]) == alvo:
                    k = cand
                    break
            if k is None:
                k = next((k for k in range(len(pilha) - 1, -1, -1) if _norm(pilha[k]["nome"]) == alvo), len(pilha) - 1)
            if k >= 0:
                no = pilha[k]
                if val is not None and abs(no["soma"] - val) > _CENTAVO:
                    avisos.append(f"subtotal impresso 'TOTAL DA CONTA {no['nome']}' = {_brl(val)} mas os lançamentos lidos somam {_brl(no['soma'])}")
                if k == 0 and val is not None:
                    totais_conta[no["nome"]] = val
                del pilha[k:]
            continue
        cod = a
        valor = _num(r[cols["valor"]]) if cols["valor"] < len(r) else None
        hist = _txt(r[cols["hist"]]) if cols["hist"] < len(r) else ""
        if cod and re.fullmatch(r"\d+", cod) and valor is not None and pilha:
            conta = pilha[0]["nome"]
            categoria, rubrica = _categoria(pilha, nomes_contas)
            pilha[-1]["n"] += 1          # só a folha conta lançamentos diretos (decide irmão x filho)
            for n in pilha:
                n["soma"] += valor
                nos_com_lancamento.add(_norm(n["nome"]))
            data = _txt(r[cols["data"]]) if cols["data"] < len(r) else ""
            ultimo = LancamentoDespesa(
                descricao=hist, valor=valor, categoria=categoria, conta=conta,
                codigo=cod, data=data if _RE_DATA.match(data) else None, local=f"linha {i + 1}")
            ultimo.rubrica = rubrica        # atributo informativo (como no extrator ContasData); o modelo não o exige
            dados.lancamentos.append(ultimo)
            continue
        if not cod and hist and valor is None and ultimo is not None and ultimo.local == f"linha {i}":
            ultimo.descricao = f"{ultimo.descricao} {hist}".strip()  # histórico quebrado em duas linhas
            ultimo.local = f"linha {i + 1}"
            continue
        t = _so_titulo(r)
        if t and _norm(t) not in ("N LANCTO",):
            if pilha and pilha[-1]["n"] > 0:
                pilha.pop()   # o nó anterior (folha com lançamentos) fecha: este é irmão
            pilha.append({"nome": t, "n": 0, "soma": 0.0})
    # nomes de conta do Demonstrativo -> nome do Resumo
    mapa = {}
    for l in dados.lancamentos:
        if l.conta not in mapa:
            mapa[l.conta] = _casar_conta(l.conta, nomes_contas) or l.conta
        l.conta = mapa[l.conta]
    dados._mapa_contas = mapa  # diagnóstico
    return {mapa.get(k, k): v for k, v in totais_conta.items()}, achou


# ── Transferências (histórico textual) ───────────────────────────────────────

def _ler_transferencias(linhas) -> list[dict]:
    out, vistos = [], set()
    for i, r in enumerate(linhas):
        if r and _norm(_txt(r[0])) == "TRANSFERENCIAS":
            conta = None
            for j in range(i + 1, min(i + 60, len(linhas))):
                rr = linhas[j]
                if not rr:
                    continue
                a = _txt(rr[0])
                an = _norm(a)
                if an.startswith("TOTAL DAS TRANSFER") or an.startswith("TOTAL GERAL") or an.startswith("CONDOMINIO"):
                    break
                if an in ("HISTORICO", "") or an.startswith("TOTAL DA CONTA"):
                    continue
                t = _so_titulo(rr)
                if t:
                    conta = t
                    continue
                deb, cre = (_num(rr[8]) if len(rr) > 8 else None), (_num(rr[10]) if len(rr) > 10 else None)
                if deb is None and cre is None:
                    continue
                m = re.match(r"(\d{2}/\d{2}/\d{4})\s+(.*)$", a)
                item = {"conta": conta, "data": m.group(1) if m else None, "texto": (m.group(2) if m else a).strip(),
                        "debito": deb or 0.0, "credito": cre or 0.0}
                k = (item["conta"], item["data"], item["texto"], item["debito"], item["credito"])
                if k not in vistos:
                    vistos.add(k)
                    out.append(item)
    return out


# ── Demonstrativo de Receitas ────────────────────────────────────────────────

def _ler_receitas_b(linhas, ini, fim, nomes_contas: list[str]) -> list[LinhaReceita] | None:
    """Layout B: 'Data | Bloco/Unidade | Recibo | Vencto | Histórico | Valor', agrupado conta > grupo."""
    cab = None
    for i in range(ini, fim):
        r = linhas[i]
        if r and _txt(r[0]).upper() == "DATA" and any(_norm(_txt(x)) == "HISTORICO" for x in r):
            cab = i
            break
    if cab is None:
        return None
    c_hist = next(j for j, x in enumerate(linhas[cab]) if _norm(_txt(x)) == "HISTORICO")
    c_val = next((j for j, x in enumerate(linhas[cab]) if _norm(_txt(x)) == "VALOR"), 10)
    c_unid = next((j for j, x in enumerate(linhas[cab]) if "UNIDADE" in _norm(_txt(x))), 1)
    out: list[LinhaReceita] = []
    conta, grupo = None, None
    for i in range(cab + 1, fim):
        r = linhas[i]
        if not r:
            continue
        a = _txt(r[0])
        if _norm(a).startswith("TOTAL GERAL") or _norm(_txt(r[c_hist] if c_hist < len(r) else None)).startswith("TOTAL GERAL"):
            break
        t = _so_titulo(r)
        if t:
            prox = next((linhas[j] for j in range(i + 1, min(i + 4, fim)) if linhas[j] and any(_txt(x) for x in linhas[j])), None)
            if prox is not None and _so_titulo(prox):
                conta, grupo = t, None        # dois títulos seguidos: conta, depois grupo
            else:
                grupo = t
            continue
        if _RE_DATA.match(a):
            v = _num(r[c_val]) if c_val < len(r) else None
            if v is None:
                continue
            hist = _txt(r[c_hist]) if c_hist < len(r) else ""
            unid = _txt(r[c_unid]) if c_unid < len(r) else ""
            unid = unid if unid and not re.fullmatch(r"\d+/\s*", unid) else ""
            desc = " — ".join(x for x in (grupo, hist) if x) + (f" (unid. {unid})" if unid else "")
            nome_conta = _casar_conta(conta or "", nomes_contas) or (conta or "")
            out.append(LinhaReceita(conta=nome_conta, descricao=desc, valor=v, tipo=_tipo_receita(f"{grupo or ''} {hist}", nome_conta),
                                    data=a, local=f"linha {i + 1}"))
    return out


def _ler_recibos_a(linhas, ini, fim) -> list[LinhaReceita]:
    """Layout A (Alvorada): recibos 'Unidade | Recibo | Vencimento | Data | Valor | Multa/Desc. | Recebido' e
    'OUTROS RECEBIMENTOS'. Só devolve as linhas com valor NEGATIVO (as positivas já estão nas linhas de crédito da
    Posição Financeira, em totais por conta)."""
    out: list[LinhaReceita] = []
    modo = None
    for i in range(ini, fim):
        r = linhas[i]
        if not r:
            continue
        a = _txt(r[0])
        an = _norm(a)
        if an == "UNIDADE":
            modo = "recibos"
            continue
        if an.startswith("OUTROS RECEBIMENTOS"):
            modo = "outros"
            continue
        if an.startswith("TOTAL") or an.startswith("RESUMO DE RECEBIMENTOS"):
            if an.startswith("RESUMO DE RECEBIMENTOS"):
                break
            continue
        if modo == "recibos" and a:
            v = _num(r[6]) if len(r) > 6 else None
            if v is not None and v < -_CENTAVO:
                out.append(LinhaReceita(conta="", descricao=f"Recibo {_txt(r[1])} — unidade {a}", valor=v, tipo="cota",
                                        data=_txt(r[3]) or None, local=f"linha {i + 1}"))
        elif modo == "outros":
            v = _num(r[6]) if len(r) > 6 else None
            if v is not None and v < -_CENTAVO:
                out.append(LinhaReceita(conta="", descricao=_txt(r[2]) or "Outros recebimentos", valor=v,
                                        tipo=_tipo_receita(_txt(r[2])), data=_txt(r[1]) or None, local=f"linha {i + 1}"))
    return out


# ── Resumo de Emissão (Previsto x Realizado) da conta ordinária ───────────────

def _ler_emissao(linhas) -> dict | None:
    """Primeira tabela "Resumo de Emissão" da planilha (conta ordinária) + o crédito "EMISSÃO DO PERÍODO" da
    Posição Financeira da mesma conta. Colunas fixas do relatório: Previsto = I, Realizado = K."""
    for i, r in enumerate(linhas):
        if not r or not _norm(_txt(r[0])).startswith("RESUMO DE EMISSAO"):
            continue
        conta = ""
        for k in range(i - 1, max(i - 4, -1), -1):
            t = _so_titulo(linhas[k]) if linhas[k] else ""
            if t:
                conta = t
                break
        itens, total, fim = [], None, len(linhas)
        for j in range(i + 1, len(linhas)):
            rr = linhas[j]
            if not rr:
                continue
            a = _txt(rr[0])
            an = _norm(a)
            if an.startswith("POSICAO FINANCEIRA"):
                fim = j
                break
            prev = _num(rr[8]) if len(rr) > 8 else None
            real = _num(rr[10]) if len(rr) > 10 else None
            if prev is None and real is None:
                continue
            if not a:
                total = (prev or 0.0, real or 0.0)      # linha sem rótulo = total impresso da tabela
            elif an.startswith("TOTAL DE DEVEDORES") or "COBRANCA EM" in an and prev == 0 and itens and total is not None:
                continue                                # linhas abaixo do total (cotas em aberto no fim do mês)
            elif total is None:
                itens.append({"descricao": a, "previsto": prev or 0.0, "realizado": real or 0.0, "local": f"linha {j + 1}"})
        posicao = None
        for j in range(fim, min(fim + 40, len(linhas))):
            rr = linhas[j]
            if not rr:
                continue
            an = _norm(_txt(rr[0]))
            if an.startswith("SALDO ATUAL"):
                break
            if an.startswith("EMISSAO DO PERIODO"):
                cre = _num(rr[10]) if len(rr) > 10 else None
                deb = _num(rr[8]) if len(rr) > 8 else None
                posicao = {"valor": round((cre or 0.0) - (deb or 0.0), 2), "local": f"linha {j + 1}"}
                break
        if not itens:
            return None
        prev_t = total[0] if total else round(sum(x["previsto"] for x in itens), 2)
        real_t = total[1] if total else round(sum(x["realizado"] for x in itens), 2)
        return {"conta": conta, "linhas": itens, "previsto": round(prev_t, 2), "realizado": round(real_t, 2),
                "posicao_emissao": posicao, "local": f"linha {i + 1}"}
    return None


# ── extração ─────────────────────────────────────────────────────────────────

def extrair_de_linhas(linhas: list[list], mes: str, arquivo: str = "") -> DadosRegras:
    dados = DadosRegras(mes=mes, arquivo=arquivo)
    avisos = dados.avisos
    blocos = _blocos(linhas)

    # 1. Resumo Financeiro Contábil
    contas: list[ContaMes] = []
    for _, a, b in _achar(blocos, "RESUMO FINANCEIRO CONTABIL"):
        contas = _ler_resumo(linhas, a, b)
        break
    nomes = [c.nome for c in contas]

    # 2. Posição Financeira por conta
    posicoes: dict[str, dict] = {}
    for _, a, b in _achar(blocos, "DEMONSTRACOES POR CONTA"):
        for nome, p in _ler_posicoes(linhas, a, b).items():
            canon = _casar_conta(nome, nomes) or nome
            if canon in posicoes:
                posicoes[canon]["linhas"] += p["linhas"]
            else:
                posicoes[canon] = p
    por_nome = {c.nome: c for c in contas}
    achou_posicao = bool(posicoes)

    # 3. Despesas
    desp = _achar(blocos, "DEMONSTRATIVO DE DESPESAS")
    categorias_despesa: set = set()
    totais_conta, achou_desp = ({}, False)
    if desp:
        totais_conta, achou_desp = _ler_despesas(linhas, desp[0][1], desp[0][2], nomes, dados, avisos, categorias_despesa)

    # 4. Transferências (descrição textual)
    transf = _ler_transferencias(linhas)

    def _texto_transf(conta: str, credito: float | None, debito: float | None):
        for t in transf:
            if _norm(t["conta"] or "") != _norm(conta):
                continue
            if credito is not None and abs(t["credito"] - credito) < _CENTAVO:
                return t
            if debito is not None and abs(t["debito"] - debito) < _CENTAVO:
                return t
        return None

    contas_com_lanc = {l.conta for l in dados.lancamentos}
    # 5. Classifica as linhas da Posição em: receita (+), estorno de receita (−), transferência (saída), despesa
    rotulos_credito = {_norm(l[0]) for p in posicoes.values() for l in p["linhas"] if l[2] > _CENTAVO}
    receitas_pos: list[LinhaReceita] = []
    transf_saida: dict[str, list] = {}   # conta -> [(rótulo, valor)] de linhas de DÉBITO tipo transferência/acerto contábil
    estornos_debito: dict[str, float] = {}
    for conta, p in posicoes.items():
        for rotulo, deb, cre, nl in p["linhas"]:
            rn = _norm(rotulo)
            eh_transf = bool(_RE_TRANSF.search(rn))
            if cre > _CENTAVO or cre < -_CENTAVO:
                t = _texto_transf(conta, cre, None) if (eh_transf or "DUPLIC" in rn) else None
                desc = rotulo + (f" — {t['texto']}" if t else "")
                receitas_pos.append(LinhaReceita(conta=conta, descricao=desc, valor=cre,
                                                 tipo="transferencia" if eh_transf else _tipo_receita(rotulo, conta),
                                                 data=t["data"] if t else None, local=f"linha {nl}"))
            if deb > _CENTAVO or deb < -_CENTAVO:
                if eh_transf:
                    transf_saida.setdefault(conta, []).append((rotulo, deb))
                elif rn in categorias_despesa or rn == "DESPESAS CONF DEMONSTRATIVO ANEXO":
                    pass                                   # despesa (categoria do Demonstrativo)
                elif _RE_ESTORNO.search(rotulo.strip()) or rn in rotulos_credito or conta in contas_com_lanc:
                    estornos_debito[conta] = estornos_debito.get(conta, 0.0) + deb
                    receitas_pos.append(LinhaReceita(conta=conta, descricao=f"{rotulo} (estorno/desconto lançado a débito)", valor=-deb,
                                                     tipo=_tipo_receita(rotulo, conta), local=f"linha {nl}"))

    # 6. Demonstrativo de Receitas
    rec_b = None
    recibos_neg: list[LinhaReceita] = []
    for _, a, b in _achar(blocos, "DEMONSTRATIVO DE RECEITAS"):
        rec_b = _ler_receitas_b(linhas, a, b, nomes)
        if rec_b is None:
            recibos_neg = _ler_recibos_a(linhas, a, b)
        break

    if rec_b:
        # Demonstrativo linha a linha. Ele NÃO lista as transferências entre contas (crédito na conta de destino) nem
        # as contas sem recibos (fundos que só rendem): para cada conta, completa com as linhas da Posição Financeira
        # quando o que falta é exatamente isso; se ainda assim não fecha com o Resumo, usa a Posição Financeira inteira
        # dessa conta (e avisa), preservando os valores negativos do Demonstrativo.
        fonte_receitas = "Demonstrativo de Receitas (linha a linha)"
        por_conta_b: dict[str, list] = {}
        for r in rec_b:
            por_conta_b.setdefault(r.conta, []).append(r)
        dados.receitas = []
        for c in contas:
            det = por_conta_b.pop(c.nome, [])
            pos_c = [r for r in receitas_pos if r.conta == c.nome]
            if not det:
                dados.receitas += pos_c
                continue
            falta = c.creditos - sum(r.valor for r in det)
            transf_c = [r for r in pos_c if r.tipo == "transferencia"]
            if abs(falta) <= _CENTAVO:
                dados.receitas += det
            elif transf_c and abs(falta - sum(r.valor for r in transf_c)) <= _CENTAVO:
                dados.receitas += det + transf_c
            else:
                negativos = [r for r in det if r.valor < -_CENTAVO]
                pos_sem_neg = [r for r in pos_c if not r.descricao.endswith("(estorno/desconto lançado a débito)")] if negativos else pos_c
                dados.receitas += pos_sem_neg + negativos
                avisos.append(f"receitas da conta {c.nome}: o Demonstrativo de Receitas soma R$ {_brl(sum(r.valor for r in det))} e o crédito do "
                              f"Resumo é R$ {_brl(c.creditos)}; usadas as linhas da Posição Financeira dessa conta"
                              + (" (mais os valores negativos do Demonstrativo)" if negativos else ""))
        for sobra in por_conta_b.values():     # recibos de conta que não está no Resumo (nome divergente)
            dados.receitas += sobra
    else:
        dados.receitas = receitas_pos
        for rn in recibos_neg:
            dados.receitas.append(rn)
        fonte_receitas = "Posição Financeira de cada conta"

    # 7. Contas: rendimento, débito ajustado
    for c in contas:
        c.rendimento = round(sum(r.valor for r in dados.receitas if r.conta == c.nome and r.tipo == "rendimento"), 2)
        # Transferência entre contas lançada a débito na Posição Financeira: o Resumo a inclui no débito da conta, mas ela
        # NÃO é despesa do Demonstrativo (vem só no bloco "Transferências": Alvorada dez/2025, Elo jun/2025...). `debitos`
        # é reduzido desse valor para a soma dos lançamentos poder ser conferida; o aviso diz quanto e por quê.
        # (Rótulos que SÃO categoria do Demonstrativo — "TRANSFERENCIAS DE NUMERARIOS" e "ACERTO CONTABIL" da Onze 22/Elo —
        # já estão nos dois lados e ficam como lançamentos normais.)
        for rotulo, valor in transf_saida.get(c.nome, []):
            if _norm(rotulo) in categorias_despesa:
                continue
            c.debitos = round(c.debitos - valor, 2)
            avisos.append(f"conta {c.nome}: o débito do Resumo inclui R$ {_brl(valor)} de '{rotulo}', que não é despesa do "
                          f"Demonstrativo; 'debitos' reduzido desse valor para a conferência dos lançamentos")
    dados.contas = contas

    # 8. Cobertura e motivos
    tem_receitas = bool(contas) and (bool(rec_b) or achou_posicao)
    dados.cobertura = {
        "receitas": tem_receitas,
        "rendimentos": bool(contas) and achou_posicao,
        "lancamentos": achou_desp and len(dados.lancamentos) > 0,
    }
    if not dados.cobertura["receitas"]:
        dados.motivos_nao_cobertos["receitas"] = "a planilha não traz o Resumo Financeiro com a Posição Financeira (ou o Demonstrativo de Receitas) das contas"
    if not dados.cobertura["rendimentos"]:
        dados.motivos_nao_cobertos["rendimentos"] = "a planilha não traz a Posição Financeira por conta, de onde sai o rendimento de cada conta"
    if not dados.cobertura["lancamentos"]:
        if not achou_desp:
            dados.motivos_nao_cobertos["lancamentos"] = "a planilha deste mês não traz o Demonstrativo de Despesas (não há lançamentos para verificar)"
        else:
            dados.motivos_nao_cobertos["lancamentos"] = "o Demonstrativo de Despesas deste mês não tem lançamentos"
    if not _achar(blocos, "DEMONSTRATIVO DE RECEITAS") and tem_receitas:
        # Elo, Onze 22, Port Saint Tropez, Baturité e Go Liberdade (a partir de mai/26) não trazem recibo a recibo: só as
        # linhas de crédito/débito por rótulo da Posição Financeira. Um recibo negativo escondido dentro de um total
        # ("RECEBIMENTOS DO PERIODO") não aparece; um estorno/desconto lançado como linha própria aparece.
        avisos.append("o arquivo não traz o Demonstrativo de Receitas (recibo a recibo): receitas negativas só são detectadas "
                      "quando lançadas como linha própria na Posição Financeira de cada conta")
    dados.emissao = _ler_emissao(linhas)
    dados._fonte_receitas = fonte_receitas  # diagnóstico (não é campo do modelo)
    return dados


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        caminho = Path(caminho)
        if caminho.suffix.lower() not in (".xlsx", ".xlsm"):
            raise ValueError(f"extrator Habitacional lê planilha XLSX; recebeu {caminho.suffix or 'arquivo sem extensão'}")
        return extrair_de_linhas(_ler_linhas(caminho), mes, caminho.name)
