"""
Prints de evidência para prestações de contas em PLANILHA (XLSX).

O relatório mostra, para cada divergência, um recorte do arquivo de origem. Em PDF isso é um
recorte da página; planilha não tem página, então este módulo desenha as linhas relevantes
(com o número da linha e a letra da coluna do Excel, para o leitor achar no arquivo) numa
página PDF mínima, e devolve o recorte + os retângulos de destaque no formato que
`render.preparar_evidencia_extra` já entende.

Só lê o arquivo de prestação de contas. Nunca dashboards.
"""
import re
import unicodedata
from pathlib import Path
from typing import Optional

from conciliacao.regras_gerais.extratores.habitacional_xlsx import _ler_linhas, _num

_ALT_LINHA = 12.0
_FONTE = 7.2
_LARG_NUM = 30.0
_MAX_CHARS = 110
_cache: dict = {}


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def _linhas(caminho: Path) -> list:
    chave = str(caminho)
    if chave not in _cache:
        _cache[chave] = _ler_linhas(Path(caminho))
    return _cache[chave]


def _letra(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _fmt(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(v, int):
        return str(v)
    if hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    t = re.sub(r"\s+", " ", str(v)).strip()
    if re.fullmatch(r"-?\d+\.\d+", t):         # número gravado como texto ('1424.3')
        return _fmt(float(t))
    return t if len(t) <= _MAX_CHARS else t[:_MAX_CHARS - 1] + "…"


def _latin(s: str) -> str:
    return s.replace("—", "-").replace("–", "-").replace("…", "...").encode("latin-1", "replace").decode("latin-1")


def recorte_pdf(caminho: Path, linhas: list, destacar: list, destino: Path, legenda_arquivo: str = "",
                cabecalho: Optional[int] = None) -> Optional[dict]:
    """Planilha XLSX: ver recorte_linhas."""
    return recorte_linhas(_linhas(caminho), linhas, destacar, destino, cabecalho=cabecalho)


def recorte_linhas(dados: list, linhas: list, destacar: list, destino: Path, legenda_arquivo: str = "",
                   cabecalho: Optional[int] = None) -> Optional[dict]:
    """Desenha as `linhas` (números 1-based da planilha/tabela; `dados[n-1]` = linha n) numa página PDF em `destino`.
    `destacar`: números das linhas a marcar. `cabecalho`: linha de títulos de coluna mostrada antes.
    Devolve {"bbox": [...], "destaques": [[...]]} (pontos, y para baixo) ou None se não houver o que mostrar."""
    import fitz
    linhas = [n for n in sorted(set(linhas)) if 1 <= n <= len(dados)]
    if not linhas:
        return None
    mostrar = ([cabecalho] if cabecalho and cabecalho < linhas[0] else []) + linhas
    cols = sorted({j for n in mostrar for j, v in enumerate(dados[n - 1]) if _fmt(v) != ""})
    if not cols:
        return None
    larg = {}
    for j in cols:
        m = max(len(_fmt(dados[n - 1][j])) if j < len(dados[n - 1]) else 0 for n in mostrar)
        larg[j] = max(22.0, min(m * _FONTE * 0.58 + 12, 520.0))
    total_l = max(_LARG_NUM + sum(larg.values()) + 8, 430.0)   # largura mínima: recorte estreito não é ampliado nem estoura o cartão
    cab_h = _ALT_LINHA + 4
    # linhas "puladas" entre trechos não contíguos viram uma linha de reticências
    seq: list = []
    ant = None
    for n in mostrar:
        if ant is not None and n != ant + 1:
            seq.append(None)
        seq.append(n)
        ant = n
    alt = cab_h + len(seq) * _ALT_LINHA + 6
    doc = fitz.open()
    pg = doc.new_page(width=max(total_l, 200), height=alt)
    # linha de letras de coluna
    x = _LARG_NUM
    pg.draw_rect(fitz.Rect(0, 0, pg.rect.width, cab_h), color=None, fill=(0.93, 0.95, 0.97))
    pg.insert_text((4, cab_h - 5), "linha", fontsize=_FONTE, fontname="helv", color=(0.35, 0.4, 0.45))
    pos_x = {}
    for j in cols:
        pos_x[j] = x
        pg.insert_text((x + 3, cab_h - 5), _letra(j), fontsize=_FONTE, fontname="helv", color=(0.35, 0.4, 0.45))
        x += larg[j]
    destaques = []
    y = cab_h
    for n in seq:
        if n is None:
            pg.insert_text((_LARG_NUM + 3, y + _ALT_LINHA - 3), "...", fontsize=_FONTE, fontname="helv", color=(0.5, 0.5, 0.5))
            y += _ALT_LINHA
            continue
        pg.draw_line((0, y), (pg.rect.width, y), color=(0.88, 0.9, 0.92), width=0.4)
        pg.insert_text((4, y + _ALT_LINHA - 3), str(n), fontsize=_FONTE, fontname="helv", color=(0.35, 0.4, 0.45))
        linha = dados[n - 1]
        for j in cols:
            v = _fmt(linha[j]) if j < len(linha) else ""
            if not v:
                continue
            numerico = isinstance(linha[j], (int, float)) or re.fullmatch(r"-?[\d.]+,\d{2}", v) is not None
            f = "hebo" if n == cabecalho else "helv"
            t = _latin(v)
            if numerico:
                w = fitz.get_text_length(t, fontname=f, fontsize=_FONTE)
                pg.insert_text((pos_x[j] + larg[j] - w - 3, y + _ALT_LINHA - 3), t, fontsize=_FONTE, fontname=f)
            else:
                pg.insert_text((pos_x[j] + 3, y + _ALT_LINHA - 3), t, fontsize=_FONTE, fontname=f)
        if n in destacar:
            destaques.append([1.0, y + 0.5, pg.rect.width - 1, y + _ALT_LINHA - 0.5])   # a linha inteira, do nº da linha até a última coluna
        y += _ALT_LINHA
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(destino))
    doc.close()
    return {"bbox": [0, 0, float(max(total_l, 200)), float(alt)], "destaques": destaques}


# ── localização das linhas de cada tipo de achado ────────────────────────────

def _n(local) -> Optional[int]:
    m = re.search(r"linha\s+(\d+)", str(local or ""))
    return int(m.group(1)) if m else None


def _cabecalho_despesas(dados: list, n: int) -> Optional[int]:
    for i in range(n - 2, -1, -1):
        if dados[i] and _norm(dados[i][0]).startswith(("N LANCTO", "N LAN")):
            return i + 1
    return None


def _agrupar(linhas: list, folga: int = 3) -> list:
    grupos: list = []
    for n in sorted(set(linhas)):
        if grupos and n - grupos[-1][-1] <= folga:
            grupos[-1].append(n)
        else:
            grupos.append([n])
    return grupos


def linha_do_lancamento(caminho: Path, codigo, valor) -> Optional[int]:
    """Linha do Demonstrativo de Despesas com o nº de lançamento `codigo` e o `valor`."""
    dados = _linhas(caminho)
    achou = None
    for i, r in enumerate(dados):
        if not r or str(r[0]).strip() != str(codigo).strip():
            continue
        for c in r[1:]:
            v = _num(c)
            if v is not None and valor is not None and abs(abs(v) - abs(valor)) < 0.011:
                return i + 1
        if achou is None:
            achou = i + 1
    return achou


def _bloco_posicao(dados: list, conta) -> Optional[tuple]:
    """(linha inicial, linha final) 1-based do bloco 'Posição Financeira' da conta (de 'POSICAO FINANCEIRA' até 'SALDO ATUAL')."""
    alvo = _norm(conta)
    if not alvo:
        return None
    for i, r in enumerate(dados):
        if r and r[0] and _norm(r[0]) == alvo and not any(str(x or "").strip() for x in r[1:]):
            for k in range(i + 1, min(i + 40, len(dados))):
                if dados[k] and _norm(dados[k][0]).startswith("POSICAO FINANCEIRA"):
                    ini = k + 1
                    fim = ini
                    for kk in range(ini, min(ini + 40, len(dados))):
                        fim = kk + 1
                        if dados[kk] and _norm(dados[kk][0]).startswith("SALDO ATUAL"):
                            break
                    return ini, fim
    return None


def _linhas_com(dados: list, ini: int, fim: int, prefixos: tuple) -> list:
    """Linhas (1-based) do intervalo cujo 1º campo começa com um dos prefixos."""
    return [k + 1 for k in range(ini - 1, fim) if dados[k] and dados[k][0] and _norm(dados[k][0]).startswith(prefixos)]


def planos(caminho: Path, achado, registro=None) -> list[dict]:
    """Lista de planos de recorte [{"linhas": [...], "destacar": [...], "cabecalho": n|None, "legenda": str}]."""
    d = achado.detalhes or {}
    dados = _linhas(caminho)
    out: list[dict] = []
    t = achado.tipo

    if t == "previsto_realizado_inconsistente":
        ini = _n(d.get("local"))
        if ini:
            fim = _n((d.get("difere_posicao") or {}).get("local")) or _n(d.get("local_posicao")) or ini + 12
            fim = min(fim, ini + 30)
            destac = [fim]
            for k in range(ini + 1, fim):
                r = dados[k - 1]
                if r and not str(r[0] or "").strip() and any(_num(c) is not None for c in r):
                    destac.append(k)       # linha de total impresso da tabela
                    break
            out.append({"linhas": list(range(ini, fim + 1)), "destacar": destac, "cabecalho": None,
                        "legenda": f"Resumo de Emissão (Previsto x Realizado) e, abaixo, a Posição Financeira — conta {d.get('conta') or ''}"})
    elif t == "receita_negativa":
        itens = [_n(i.get("local")) for i in d.get("itens", [])]
        for g in _agrupar([n for n in itens if n])[:3]:
            out.append({"linhas": list(range(max(1, g[0] - 1), g[-1] + 2)), "destacar": g, "cabecalho": None,
                        "legenda": "Linha de receita com valor negativo"})
    elif t in ("subconta_atipica", "lancamento_em_outra_subconta"):
        locais = [_n(i.get("local")) for i in d.get("lancamentos", [])]
        for g in _agrupar([n for n in locais if n])[:3]:
            out.append({"linhas": list(range(max(1, g[0] - 2), g[-1] + 2)), "destacar": g,
                        "cabecalho": _cabecalho_despesas(dados, g[0]),
                        "legenda": "Lançamento(s) na subconta " + str(d.get("categoria_atual") or d.get("categoria") or achado.linha_demonstrativo or "")})
    elif t == "rendimento_desproporcional":
        bloco = _bloco_posicao(dados, d.get("conta"))
        if bloco:
            ini, fim = bloco
            dest = [k + 1 for k in range(ini - 1, fim) if dados[k] and _norm(dados[k][0]).startswith("RENDIMENTO")]
            if not dest:      # sem linha de rendimento: marca o total creditado e o saldo, que mostram que nada foi creditado
                dest = _linhas_com(dados, ini, fim, ("TOTAIS", "SALDO ATUAL"))
            out.append({"linhas": list(range(ini, fim + 1)), "destacar": dest, "cabecalho": None,
                        "legenda": f"Posição Financeira da conta {d.get('conta')}"
                                   + ("" if any(_norm(dados[k - 1][0]).startswith("RENDIMENTO") for k in dest if dados[k - 1] and dados[k - 1][0]) else " — não há linha de rendimento")})
    elif t in ("movimento_entre_contas", "continuidade_saldo", "saldo_negativo_persistente", "saldo_negativo") \
            or (t == "observacao_gestor" and d.get("verificacao") == "deficit_conta"):
        if t == "continuidade_saldo":
            contas, chaves, rotulo = [c["nome"] for c in d.get("contas", [])][:3], ("SALDO ANTERIOR",), "saldo anterior"
        elif t.startswith("saldo_negativo"):
            contas, chaves, rotulo = [c["nome"] for c in d.get("contas", [])][:3], ("SALDO ATUAL",), "saldo atual"
        elif t == "movimento_entre_contas":
            contas, chaves, rotulo = [d.get("conta")], ("SALDO ANTERIOR", "TOTAIS", "SALDO ATUAL"), "saldos e movimento"
        else:
            contas, chaves, rotulo = [d.get("conta")], ("TOTAIS", "SALDO ATUAL"), "créditos e débitos"
        for conta in contas:
            bloco = _bloco_posicao(dados, conta)
            if bloco:
                ini, fim = bloco
                out.append({"linhas": list(range(ini, fim + 1)), "destacar": _linhas_com(dados, ini, fim, chaves), "cabecalho": None,
                            "legenda": f"Posição Financeira da conta {conta} ({rotulo})"})
    elif t == "parcelas_mesmo_mes":
        locais = [_n(p.get("local")) for p in d.get("parcelas", [])]
        for g in _agrupar([n for n in locais if n], folga=40)[:1]:
            out.append({"linhas": sorted(set(g)), "destacar": g, "cabecalho": _cabecalho_despesas(dados, g[0]), "legenda": "Parcelas pagas no mesmo mês"})
    elif t == "observacao_gestor" and d.get("verificacao") == "recorrente_ausente":
        for x in d.get("ausentes", [])[:3]:
            n = _n(x.get("local"))
            if n and x.get("arquivo"):
                out.append({"linhas": [n - 1, n, n + 1], "destacar": [n], "cabecalho": None, "arquivo": x["arquivo"],
                            "legenda": f"Lançamento do mês anterior ({x.get('mes')}) que não aparece neste mês — {x['descricao'][:60]}"})
    elif t == "observacao_gestor":
        locais = [_n(i.get("local")) for i in d.get("lancamentos", [])]
        for g in _agrupar([n for n in locais if n], folga=1)[:3]:
            out.append({"linhas": list(range(max(1, g[0] - 1), g[-1] + 2)), "destacar": g, "cabecalho": _cabecalho_despesas(dados, g[0]),
                        "legenda": "Lançamento(s) citado(s) nesta observação"})
    elif t in ("conta_concessionaria_nao_anexada", "despesa_negativa"):
        ns = []
        for i in d.get("itens", []):
            pg, n = i.get("pagina"), None
            if isinstance(pg, int) and 1 <= pg <= len(dados):          # no extrator de planilha a "página" é o nº da linha do Excel
                if any(isinstance(c, (int, float)) and abs(abs(c) - abs(i.get("valor") or 0)) < 0.011 for c in (dados[pg - 1] or [])):
                    n = pg
            ns.append(n or linha_do_lancamento(caminho, i.get("codigo"), i.get("valor")))
        for g in _agrupar([n for n in ns if n], folga=2)[:3]:
            out.append({"linhas": list(range(max(1, g[0] - 1), g[-1] + 2)), "destacar": g, "cabecalho": _cabecalho_despesas(dados, g[0]),
                        "legenda": "Lançamento(s) com valor negativo na listagem de despesas" if t == "despesa_negativa" else "Lançamento(s) de concessionária"})
    elif t in ("sem_comprovante", "divergencia_valor", "duplicidade", "sem_lancamento_correspondente", "cnpj_ausente", "nota_fiscal_ausente",
               "conteudo_nao_verificavel", "atraso_pagamento") and registro is not None:
        # No extrator de planilha o "código" e a "página" do registro são o número da própria linha do Excel.
        n = None
        pg = getattr(registro, "pagina", None)
        if isinstance(pg, int) and 1 <= pg <= len(dados):
            linha = dados[pg - 1] or []
            if any((_num(c) is not None and abs(abs(_num(c)) - abs(registro.valor or 0)) < 0.011) for c in linha if not isinstance(c, str) or re.fullmatch(r"-?[\d.]+", c.strip() or "x")):
                n = pg
        if n is None:
            n = linha_do_lancamento(caminho, getattr(registro, "codigo", None), getattr(registro, "valor", None))
        if n:
            out.append({"linhas": [n - 1, n, n + 1], "destacar": [n], "cabecalho": _cabecalho_despesas(dados, n),
                        "legenda": "Lançamento no Demonstrativo de Despesas"})
    return out


# ── Planilhas .xls: Lello (HTML/MHTML — "tabela T, linha R") e Auxiliadora (BIFF — "aba 'X', linha N") ──────────────────────

_cache_xls: dict = {}


def _fonte_xls(caminho: Path) -> dict:
    """{'tipo': 'mhtml'|'biff', 'tabelas': {tabela: [linhas]}} (mhtml) ou {'abas': {nome: [linhas]}} (biff). Linha n = índice n-1."""
    chave = str(caminho)
    if chave in _cache_xls:
        return _cache_xls[chave]
    f: dict = {}
    try:
        import xlrd
        wb = xlrd.open_workbook(chave)
        f = {"tipo": "biff", "abas": {ws.name: [[ws.cell_value(r, c) for c in range(ws.ncols)] for r in range(ws.nrows)] for ws in wb.sheets()}}
    except Exception:
        try:
            from conciliacao.regras_gerais.extratores import lello_mhtml as L
            tabs: dict = {}
            for ti, ri, cel in L._linhas(L._texto_html(Path(caminho))):
                t = tabs.setdefault(ti, [])
                while len(t) < ri - 1:
                    t.append([])
                t.append(list(cel))
            f = {"tipo": "mhtml", "tabelas": tabs}
        except Exception:
            f = {}
    _cache_xls[chave] = f
    return f


def _ref_local(local) -> tuple:
    """('tabela', T, N) | ('aba', nome, N) | (None, None, N) a partir do texto de localização do extrator."""
    s = str(local or "")
    n = re.search(r"linha\s+(\d+)", s)
    n = int(n.group(1)) if n else None
    t = re.search(r"tabela\s+(\d+)", s)
    if t:
        return ("tabela", int(t.group(1)), n)
    a = re.search(r"aba\s+'([^']+)'", s) or re.search(r"aba\s+([^,]+),", s)
    if a:
        return ("aba", a.group(1).strip(), n)
    return (None, None, n)


def _rows_ref(fonte: dict, tipo, chave) -> list:
    if tipo == "tabela":
        return fonte.get("tabelas", {}).get(chave, [])
    if tipo == "aba":
        for nome, rows in fonte.get("abas", {}).items():
            if _norm(nome) == _norm(chave):
                return rows
    return []


def _bloco_conta_xls(fonte: dict, conta) -> Optional[tuple]:
    """(rows, ini, fim) 1-based do bloco 'Posição Financeira' da conta numa fonte .xls."""
    alvo = _norm(conta)
    if not alvo or not fonte:
        return None
    if fonte["tipo"] == "mhtml":
        tabs = fonte["tabelas"]
        for ti in sorted(tabs):
            rows = tabs[ti]
            if rows and rows[0] and _norm(rows[0][0]) == alvo:
                for tj in (ti + 1, ti + 2):
                    r2 = tabs.get(tj) or []
                    if any(r and r[0] and _norm(r[0]).startswith("POSICAO FINANCEIRA") for r in r2[:4]):
                        return r2, 1, len(r2)
        return None
    for nome, rows in fonte["abas"].items():
        if not _norm(nome).startswith("DEMONST") or "CONTAS" not in _norm(nome):
            continue
        for i, r in enumerate(rows):
            if r and r[0] and _norm(r[0]) == alvo and i + 1 < len(rows) and rows[i + 1] and _norm(rows[i + 1][0]).startswith("POSICAO FINANCEIRA"):
                fim = i + 1
                for k in range(i + 2, min(i + 40, len(rows))):
                    if k + 1 < len(rows) and rows[k + 1] and _norm(rows[k + 1][0]).startswith("POSICAO FINANCEIRA"):
                        break
                    fim = k + 1
                return rows, i + 1, fim
    return None


def _rotulo(r) -> str:
    """1º campo preenchido da linha (nas tabelas HTML o rótulo pode estar numa coluna que não é a A)."""
    for c in r or []:
        if str(c or "").strip():
            return _norm(c)
    return ""


def _destacar_prefixos(rows: list, ini: int, fim: int, prefixos: tuple) -> list:
    return [k + 1 for k in range(ini - 1, min(fim, len(rows))) if _rotulo(rows[k]).startswith(prefixos)]


def planos_xls(caminho: Path, achado, registro=None, pasta_meses: Optional[Path] = None) -> list[dict]:
    """Planos de recorte para .xls — cada plano traz as linhas já lidas em "dados" (índice n-1 = linha n)."""
    fonte = _fonte_xls(Path(caminho))
    if not fonte:
        return []
    d = achado.detalhes or {}
    t = achado.tipo
    out: list[dict] = []

    def _por_locais(locais: list, legenda: str, folga: int = 1) -> None:
        por_ref: dict = {}
        for loc in locais:
            tipo, chave, n = _ref_local(loc)
            if n:
                por_ref.setdefault((tipo, chave), []).append(n)
        for (tipo, chave), ns in list(por_ref.items())[:3]:
            rows = _rows_ref(fonte, tipo, chave)
            if not rows:
                continue
            for g in _agrupar(ns, folga=folga)[:2]:
                out.append({"dados": rows, "linhas": list(range(max(1, g[0] - 1), min(len(rows), g[-1] + 1) + 1)), "destacar": g, "cabecalho": None,
                            "legenda": legenda})

    def _por_contas(contas: list, prefixos: tuple, rotulo: str) -> None:
        for conta in contas[:3]:
            b = _bloco_conta_xls(fonte, conta)
            if b:
                rows, ini, fim = b
                out.append({"dados": rows, "linhas": list(range(ini, fim + 1)), "destacar": _destacar_prefixos(rows, ini, fim, prefixos), "cabecalho": None,
                            "legenda": f"Posição Financeira da conta {conta} ({rotulo})"})

    if t in ("subconta_atipica", "lancamento_em_outra_subconta"):
        _por_locais([i.get("local") for i in d.get("lancamentos", [])], "Lançamento(s) na subconta " + str(d.get("categoria_atual") or d.get("categoria") or ""))
    elif t == "receita_negativa":
        _por_locais([i.get("local") for i in d.get("itens", [])] or [d.get("local")], "Linha de receita com valor negativo")
    elif t == "parcelas_mesmo_mes":
        _por_locais([p.get("local") for p in d.get("parcelas", [])], "Parcelas pagas no mesmo mês", folga=40)
    elif t == "observacao_gestor" and d.get("verificacao") == "recorrente_ausente":
        for x in d.get("ausentes", [])[:3]:
            arq = x.get("arquivo")
            if not arq or not x.get("local"):
                continue
            f2 = _fonte_xls(Path(pasta_meses or Path(caminho).parent) / arq)
            tipo, chave, n = _ref_local(x["local"])
            rows = _rows_ref(f2, tipo, chave) if f2 else []
            if rows and n:
                out.append({"dados": rows, "linhas": list(range(max(1, n - 1), min(len(rows), n + 1) + 1)), "destacar": [n], "cabecalho": None, "arquivo": arq,
                            "legenda": f"Lançamento do mês anterior ({x.get('mes')}) que não aparece neste mês — {x['descricao'][:60]}"})
    elif t == "observacao_gestor" and d.get("verificacao") == "deficit_conta":
        _por_contas([d.get("conta")], ("TOTAIS", "SALDO ATUAL"), "créditos e débitos")
    elif t == "observacao_gestor":
        _por_locais([i.get("local") for i in d.get("lancamentos", [])], "Lançamento(s) citado(s) nesta observação")
    elif t == "movimento_entre_contas":
        _por_contas([d.get("conta")], ("SALDO ANTERIOR", "TOTAIS", "SALDO ATUAL"), "saldos e movimento")
    elif t == "continuidade_saldo":
        _por_contas([c["nome"] for c in d.get("contas", [])], ("SALDO ANTERIOR",), "saldo anterior")
    elif t in ("saldo_negativo_persistente", "saldo_negativo"):
        _por_contas([c["nome"] for c in d.get("contas", [])], ("SALDO ATUAL",), "saldo atual")
    elif t == "divergencia_valor" and "repetido" in str(achado.regra_aplicada):
        # Demonstrativo de Despesas repetido no arquivo: o print mostra as linhas de TOTAL de cada cópia
        for nome_aba in [n for n in fonte.get("abas", {}) if "DESPESAS" in _norm(n)][:1]:
            rows = fonte["abas"][nome_aba]
            tot = [i + 1 for i, r in enumerate(rows) if _rotulo(r).startswith("TOTAL")]
            for n in tot[:3]:
                out.append({"dados": rows, "linhas": list(range(max(1, n - 1), min(len(rows), n + 1) + 1)), "destacar": [n], "cabecalho": None,
                            "legenda": "Linha de total do Demonstrativo de Despesas (o bloco se repete no arquivo)"})
    elif t == "despesa_negativa":
        for it in d.get("itens", [])[:3]:
            alvo = _norm(it.get("descricao"))[:32]
            if not alvo:
                continue
            achou = []
            if fonte["tipo"] == "mhtml":
                for ti, rows in fonte["tabelas"].items():
                    achou += [(ti, ri + 1) for ri, r in enumerate(rows) if alvo in " ".join(_norm(c) for c in r)]
            else:
                for nome_aba, rows in fonte["abas"].items():
                    achou += [(nome_aba, ri + 1) for ri, r in enumerate(rows) if alvo in " ".join(_norm(c) for c in r)]
            for ref in sorted({x for x, _ in achou}, key=str)[:1]:
                ns = [n for x, n in achou if x == ref]
                rows = fonte["tabelas"][ref] if fonte["tipo"] == "mhtml" else fonte["abas"][ref]
                out.append({"dados": rows, "linhas": list(range(max(1, ns[0] - 1), min(len(rows), ns[0] + 1) + 1)), "destacar": [ns[0]], "cabecalho": None,
                            "legenda": "Lançamento com valor negativo na listagem de despesas"})
    elif t in ("duplicidade", "sem_comprovante", "divergencia_valor", "nota_fiscal_ausente", "conteudo_nao_verificavel", "atraso_pagamento") and registro is not None            and (registro.descricao or "").strip():
        # arquivo sem nº de linha no registro: localiza a(s) linha(s) pelo texto da descrição do lançamento
        alvo = _norm(registro.descricao)[:32]
        achou = []
        if fonte["tipo"] == "mhtml":
            for ti, rows in fonte["tabelas"].items():
                for ri, r in enumerate(rows):
                    if alvo and alvo in " ".join(_norm(c) for c in r):
                        achou.append((ti, ri + 1))
        else:
            for nome_aba, rows in fonte["abas"].items():
                for ri, r in enumerate(rows):
                    if alvo and alvo in " ".join(_norm(c) for c in r):
                        achou.append((nome_aba, ri + 1))
        for ref in sorted({a for a, _ in achou}, key=str)[:1]:
            ns = [n for a, n in achou if a == ref]
            rows = fonte["tabelas"][ref] if fonte["tipo"] == "mhtml" else fonte["abas"][ref]
            for g in _agrupar(ns, folga=2)[:2]:
                out.append({"dados": rows, "linhas": list(range(max(1, g[0] - 1), min(len(rows), g[-1] + 1) + 1)), "destacar": g, "cabecalho": None,
                            "legenda": "Lançamento no demonstrativo"})
    elif t == "rendimento_desproporcional":
        conta = d.get("conta")
        b = _bloco_conta_xls(fonte, conta)
        if b:
            rows, ini, fim = b
            dest = _destacar_prefixos(rows, ini, fim, ("RENDIMENTO",)) or _destacar_prefixos(rows, ini, fim, ("TOTAIS", "SALDO ATUAL"))
            out.append({"dados": rows, "linhas": list(range(ini, fim + 1)), "destacar": dest, "cabecalho": None,
                        "legenda": f"Posição Financeira da conta {conta} (rendimento)"})
    return out
