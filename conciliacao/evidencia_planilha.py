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
    """Desenha as `linhas` (números 1-based da planilha) numa página PDF em `destino`.
    `destacar`: números das linhas a marcar. `cabecalho`: linha de títulos de coluna mostrada antes.
    Devolve {"bbox": [...], "destaques": [[...]]} (pontos, y para baixo) ou None se não houver o que mostrar."""
    import fitz
    dados = _linhas(caminho)
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
    total_l = _LARG_NUM + sum(larg.values()) + 8
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
            destaques.append([_LARG_NUM - 1, y + 0.5, pg.rect.width - 1, y + _ALT_LINHA - 0.5])
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
        conta = _norm(d.get("conta"))
        ini = None
        for i, r in enumerate(dados):
            if r and r[0] and _norm(r[0]) == conta and not any(str(x or "").strip() for x in r[1:]):
                for k in range(i + 1, min(i + 14, len(dados))):
                    if dados[k] and _norm(dados[k][0]).startswith("POSICAO FINANCEIRA"):
                        ini = k + 1
                        break
                if ini:
                    break
        if ini:
            fim = ini
            for k in range(ini, min(ini + 40, len(dados))):
                fim = k + 1
                if dados[k] and _norm(dados[k][0]).startswith("SALDO ATUAL"):
                    break
            dest = [k + 1 for k in range(ini - 1, fim) if dados[k] and _norm(dados[k][0]).startswith("RENDIMENTO")]
            out.append({"linhas": list(range(ini, fim + 1)), "destacar": dest, "cabecalho": None,
                        "legenda": f"Posição Financeira da conta {d.get('conta')}"
                                   + ("" if dest else " — não há linha de rendimento")})
    elif t in ("sem_comprovante", "divergencia_valor", "duplicidade", "sem_lancamento_correspondente", "cnpj_ausente") and registro is not None:
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
