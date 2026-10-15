"""Leitura das linhas de uma aba .xls (xlrd) tolerando cópias repetidas do mesmo bloco.

Caso real (Patrícia, ago/2026, Auxiliadora): a aba "Demonstrativo de Despesas" veio com o MESMO bloco de despesas
da conta Ordinária repetido 9 vezes, idêntico, e o "TOTAL DE DESPESAS" declarado é 9 × o total de um bloco
(R$ 720.245,34 = 9 × R$ 80.027,26, que é o débito real da Ordinária). Lido como está, cada lançamento aparece 9 vezes.

`linhas_sem_copias` devolve as linhas com UM só bloco (mantendo o "TOTAL DE DESPESAS" declarado) e informa quantas cópias
havia. Só deduplica quando TODAS as cópias são idênticas; se diferirem em qualquer linha, não mexe em nada.
"""
import re


def _txt(v) -> str:
    return str(v if v is not None else "").strip()


def _num_br(v):
    s = re.sub(r"[^\d,.\-]", "", _txt(v))
    if not s:
        return None
    try:
        return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)
    except ValueError:
        return None


def linhas_sem_copias(ws, ncols: int = 4):
    """-> (linhas, info). `linhas` = [(índice_da_linha_0based, [valores das `ncols` colunas])]; `info` = None ou
    {"copias": n, "total_declarado": valor_do_TOTAL_DE_DESPESAS, "total_de_um_bloco": total_declarado / n}."""
    todas = [(r, [ws.cell_value(r, c) if c < ws.ncols else "" for c in range(ncols)]) for r in range(ws.nrows)]
    cabecalhos = [i for i, (_, row) in enumerate(todas) if _txt(row[1]) == "Valor" and len(row) > 2]
    if not cabecalhos:
        return todas, None
    primeiro = tuple(_txt(x) for x in todas[cabecalhos[0]][1])
    inicios = [i for i, (_, row) in enumerate(todas) if tuple(_txt(x) for x in row) == primeiro]
    if len(inicios) < 2:
        return todas, None

    def _bloco(i0, i1):
        itens = [tuple(_txt(x) for x in row) for _, row in todas[i0:i1]]
        itens = [t for t in itens if any(t) and not t[0].upper().startswith("TOTAL DE DESPESAS")]
        return itens

    blocos = [_bloco(a, b) for a, b in zip(inicios, inicios[1:] + [len(todas)])]
    if any(b != blocos[0] for b in blocos[1:]):
        return todas, None                      # cópias diferentes entre si: não é repetição, não mexe
    total_idx = next((i for i, (_, row) in enumerate(todas) if _txt(row[0]).upper().startswith("TOTAL DE DESPESAS")), None)
    declarado = _num_br(todas[total_idx][1][1]) if total_idx is not None else None
    # prefixo + 1º bloco (até a 2ª cópia) + a linha do TOTAL DE DESPESAS declarado
    mantidas = todas[:inicios[1]] + ([todas[total_idx]] if total_idx is not None and total_idx >= inicios[1] else [])
    info = {"copias": len(inicios), "total_declarado": declarado,
            "total_de_um_bloco": round(declarado / len(inicios), 2) if declarado else None}
    return mantidas, info
