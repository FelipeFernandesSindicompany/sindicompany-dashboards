"""
Leitura por OCR POSICIONAL de PDF escaneado, compartilhada pelos extratores de balancete em imagem (Cap D'Antibes, Cinque Terre).

  ocr_palavras(pdf, páginas, dpi)   palavras com posição (pontos de PDF), cache em disco por impressão digital do arquivo
  linhas(palavras)                  agrupa em linhas pela altura
  aplicar_votos(...)                o valor de cada linha é o mais comum entre leituras em resoluções diferentes (o OCR erra em lugares
                                    diferentes em cada resolução: '1,13' vira '1713' numa e sai certo em outra)
  valor_da_linha / vl               número em R$ mais à direita da linha (com o vencedor da votação, se houver)

Nada aqui é aceito às cegas: quem usa confere os números pelas somas que o próprio arquivo declara.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from conciliacao.regras_gerais.extratores import datadigitus as _dd

DPI = 300
DPI_TRIAGEM = 150                  # também conta como uma das leituras do voto
DPIS_VOTO = (200, 400)

_RE_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$|^-?\d+,\d{2}$")

def _norm(s: str) -> str:
    return _dd._norm(s)


def _valor(txt: str):
    """Número em R$ lido pelo OCR ('—60 . 000, 00', '1:315;83', '500, 55') -> float, ou None."""
    s = (txt or "").strip().replace("—", "-").replace("–", "-").replace("−", "-")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"(?<=\d):(?=\d{3}\b)", ".", s).replace(";", ",")
    s = re.sub(r"\.(?=\d{2}$)", ",", s)
    if not _RE_VALOR.match(s):
        return None
    neg = s.startswith("-")
    v = float(s.lstrip("-").replace(".", "").replace(",", "."))
    return -v if neg else v


# ── OCR posicional ───────────────────────────────────────────────────────────────────────────────────────────
def _ocr_palavras(doc_path: Path, indices: list[int], dpi: int = DPI) -> dict[int, list[dict]]:
    """{índice_0based: [{"t", "x0", "top", "x1", "bottom"}]} em pontos de PDF (72 dpi), com cache em disco por impressão digital do arquivo."""
    from conciliacao import ocr

    if not ocr.tesseract_disponivel():
        return {}
    imp = ocr._impressao_arquivo(doc_path)
    cache = ocr._cache_do_arquivo(imp)
    faltam = [i for i in indices if f"pos{dpi}|{i}" not in cache]

    def _um(i):
        import fitz
        import pytesseract
        from PIL import Image

        doc = fitz.open(str(doc_path))
        try:
            pix = doc[i].get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            esc = pix.width / float(doc[i].rect.width)
        finally:
            doc.close()
        d = pytesseract.image_to_data(img, lang="por", config="--oem 1 --psm 6", output_type=pytesseract.Output.DICT)
        ws = []
        for k, t in enumerate(d["text"]):
            if t.strip() and float(d["conf"][k]) >= 0:
                x0, top, w, h = d["left"][k], d["top"][k], d["width"][k], d["height"][k]
                ws.append({"t": t.strip(), "x0": round(x0 / esc, 1), "top": round(top / esc, 1),
                           "x1": round((x0 + w) / esc, 1), "bottom": round((top + h) / esc, 1)})
        return i, ws

    if faltam:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, ws in ex.map(_um, faltam):
                ocr._cache_gravar(imp, f"pos{dpi}|{i}", json.dumps(ws, ensure_ascii=False))
    return {i: json.loads(cache[f"pos{dpi}|{i}"]) for i in indices if f"pos{dpi}|{i}" in cache}


def _linhas(ws: list[dict]) -> list[dict]:
    """Agrupa as palavras em linhas pela altura; cada linha: {"texto", "w", "top", "bottom", "x0", "x1"}."""
    if not ws:
        return []
    alt = sorted(w["bottom"] - w["top"] for w in ws)[len(ws) // 2]
    out: list[dict] = []
    for w in sorted(ws, key=lambda w: (w["top"] + w["bottom"]) / 2):
        yc = (w["top"] + w["bottom"]) / 2
        if out and abs(yc - out[-1]["yc"]) <= 0.6 * alt:
            out[-1]["w"].append(w)
            out[-1]["yc"] = sum((x["top"] + x["bottom"]) / 2 for x in out[-1]["w"]) / len(out[-1]["w"])
        else:
            out.append({"yc": yc, "w": [w]})
    for l in out:
        l["w"].sort(key=lambda w: w["x0"])
        l["texto"] = " ".join(w["t"] for w in l["w"])
        l["top"], l["bottom"] = min(w["top"] for w in l["w"]), max(w["bottom"] for w in l["w"])
        l["x0"], l["x1"] = l["w"][0]["x0"], max(w["x1"] for w in l["w"])
    return out


def _valor_da_linha(l: dict, W: float, x_min: float = 0.50):
    """Valor monetário MAIS À DIREITA da linha (palavras coladas pelo OCR com espaços — '60 . 000, 00' — são juntadas) e seu bbox."""
    cauda = [w for w in l["w"] if w["x0"] >= x_min * W and not w["t"].endswith("%")]
    for ini in range(len(cauda)):
        v = _valor("".join(w["t"] for w in cauda[ini:]))
        if v is not None:
            return v, (cauda[ini]["x0"], cauda[ini]["top"], cauda[-1]["x1"], cauda[-1]["bottom"]), cauda[ini]["x0"]
    return None, None, None


def _vl(l: dict, W: float, x_min: float = 0.50):
    """Valor da linha: o votado entre as leituras (`_aplicar_votos`) ou, se a linha não passou por votação, o lido direto."""
    return l["_v"] if "_v" in l else _valor_da_linha(l, W, x_min)


def _aplicar_votos(principal: list[dict], outras: list[list[dict]], W: float):
    """O OCR de uma mesma página em resoluções diferentes erra em lugares diferentes ('1,13' vira '1713' numa e sai certo em outra).
    Cada linha da leitura principal recebe como valor o MAIS COMUM entre as leituras (a linha equivalente nas outras é a de mesma altura)."""
    from collections import Counter

    for l in principal:
        cands = []
        r0 = _valor_da_linha(l, W, 0.55)
        if r0[0] is not None:
            cands.append(r0)
        for ls in outras:
            o = min(ls, key=lambda x: abs(x["yc"] - l["yc"]), default=None)
            if o is not None and abs(o["yc"] - l["yc"]) <= 3.5:
                r = _valor_da_linha(o, W, 0.55)
                if r[0] is not None:
                    cands.append(r)
        if not cands:
            l["_v"] = (None, None, None)
            continue
        cont = Counter(round(abs(c[0]), 2) for c in cands)
        topo = max(cont.values())
        melhor = next(round(abs(c[0]), 2) for c in cands if cont[round(abs(c[0]), 2)] == topo)
        iguais = [c for c in cands if round(abs(c[0]), 2) == melhor]
        negativo = sum(1 for c in iguais if c[0] < 0) * 2 > len(iguais) or (sum(1 for c in iguais if c[0] < 0) * 2 == len(iguais) and iguais[0][0] < 0)
        l["_v"] = (-melhor if negativo else melhor, iguais[0][1], iguais[0][2])


def _tem_pct(l: dict) -> bool:
    return any(re.fullmatch(r"\d{1,3}[,.]\d{2}\s*%", w["t"]) or w["t"].endswith("%") for w in l["w"])




def valores_da_linha(l: dict, x_min: float = 0.0, folga: float = 5.0) -> list[tuple]:
    """TODOS os números em R$ da linha (de x >= x_min), da esquerda para a direita: [(valor, x1, (x0, top, x1, bottom))].
    Palavras coladas pelo OCR com espaços ('60 . 000, 00') são juntadas quando a folga entre elas é menor que `folga` pontos."""
    ws = [w for w in l["w"] if w["x0"] >= x_min and not w["t"].endswith("%")]
    out, i = [], 0
    while i < len(ws):
        achado = None
        for j in range(i, len(ws)):
            if j > i and ws[j]["x0"] - ws[j - 1]["x1"] > folga:
                break
            v = _valor("".join(w["t"] for w in ws[i:j + 1]))
            if v is not None:
                achado = (j, v)
        if achado:
            j, v = achado
            out.append((v, ws[j]["x1"], (ws[i]["x0"], min(w["top"] for w in ws[i:j + 1]), ws[j]["x1"], max(w["bottom"] for w in ws[i:j + 1]))))
            i = j + 1
        else:
            i += 1
    return out


def votar_valores(principal: list[dict], outras: list[list[dict]], x_min: float = 0.0, tol_x: float = 8.0):
    """Cada linha da leitura principal recebe `l["_vs"]`: os números da linha, cada coluna com o valor MAIS COMUM entre as leituras
    (as colunas de uma mesma linha são reconhecidas pela posição do canto direito do número)."""
    from collections import Counter

    for l in principal:
        leituras = [valores_da_linha(l, x_min)]
        for ls in outras:
            o = min(ls, key=lambda x: abs(x["yc"] - l["yc"]), default=None)
            if o is not None and abs(o["yc"] - l["yc"]) <= 3.5:
                leituras.append(valores_da_linha(o, x_min))
        todos = sorted((t for lt in leituras for t in lt), key=lambda t: t[1])
        grupos: list[list] = []
        for t in todos:
            if grupos and abs(t[1] - grupos[-1][-1][1]) <= tol_x:
                grupos[-1].append(t)
            else:
                grupos.append([t])
        res = []
        for g in grupos:
            cont = Counter(round(abs(t[0]), 2) for t in g)
            topo = max(cont.values())
            melhor = next(round(abs(t[0]), 2) for t in g if cont[round(abs(t[0]), 2)] == topo)
            iguais = [t for t in g if round(abs(t[0]), 2) == melhor]
            neg = sum(1 for t in iguais if t[0] < 0) * 2 > len(iguais)
            res.append((-melhor if neg else melhor, sum(t[1] for t in iguais) / len(iguais), iguais[0][2]))
        l["_vs"] = res


def gravar_pesquisavel(caminho: Path, paginas) -> None:
    """Grava ao lado do cache do OCR (`<impressão digital>.busca.pdf`) uma cópia do PDF com o mesmo nº de páginas e TEXTO INVISÍVEL sobre as
    páginas lidas, para o render localizar as linhas dos prints de evidência (`render._pdf_para_busca`); o print em si é recortado do original.
    `paginas`: [(pagina_1based, largura, linhas)]. Os números entram com a leitura votada (`_v` / `_vs`), não a crua do 300 dpi."""
    try:
        import fitz
        from conciliacao import ocr

        alvo = ocr._CACHE_DIR / f"{ocr._impressao_arquivo(caminho)}.busca.pdf"
        src = fitz.open(str(caminho))
        out = fitz.open()
        lidas = {pag: ls for pag, _, ls in paginas}
        fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
        try:
            for i in range(len(src)):
                r = src[i].rect
                p = out.new_page(width=r.width, height=r.height)
                for l in lidas.get(i + 1, []):
                    palavras = l["w"]
                    if l.get("_vs"):
                        x_ini = min(t[2][0] for t in l["_vs"]) - 0.5
                        palavras = [w for w in palavras if w["x0"] < x_ini or w["t"].endswith("%")] + [
                            {"t": fmt(t[0]), "x0": t[2][0], "top": t[2][1], "x1": t[2][2], "bottom": t[2][3]} for t in l["_vs"]]
                    elif "_v" in l and l["_v"][0] is not None and l["_v"][1] is not None:
                        v, vbb, vx = l["_v"]
                        palavras = [w for w in palavras if w["x0"] < vx - 0.5] + [{"t": fmt(v), "x0": vbb[0], "top": vbb[1], "x1": vbb[2], "bottom": vbb[3]}]
                    for w in palavras:
                        larg = max(w["x1"] - w["x0"], 1.0)
                        alt = max(w["bottom"] - w["top"], 4.0)
                        tam = min(alt * 0.8, 11.0)           # altura fixa (linhas coladas não podem se fundir na busca); a largura é ajustada pela matriz
                        comp = fitz.get_text_length(w["t"], fontname="helv", fontsize=tam)
                        if comp <= 0:
                            continue
                        ponto = fitz.Point(w["x0"], w["bottom"] - alt * 0.2)
                        p.insert_text(ponto, w["t"], fontname="helv", fontsize=tam, render_mode=3, morph=(ponto, fitz.Matrix(larg / comp, 1)))
            alvo.parent.mkdir(parents=True, exist_ok=True)
            out.save(str(alvo), garbage=3, deflate=True)
        finally:
            src.close()
            out.close()
    except Exception:
        pass
