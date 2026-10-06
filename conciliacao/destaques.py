"""
Onde marcar o erro numa evidência — localiza TEXTO (valor, data) dentro do
recorte que o relatório mostra e devolve os retângulos a destacar.

Duas fontes, conforme o que a página tem:
  - texto nativo (pdfplumber.extract_words): PDFs "de verdade" — Addomus, a
    capa/listagem da maioria dos formatos, GCONT antigo;
  - OCR (tesseract, image_to_data = caixa de cada palavra): páginas que são
    UMA IMAGEM escaneada — comprovantes Itaú do GCONT novo, ContasData/Lirba,
    GK, Palm Beach. Só roda quando o texto nativo da região não achou nada.

As coordenadas devolvidas ficam no espaço do recorte da evidência: pontos de
página (mesma convenção do pdfplumber, origem no topo-esquerdo) para
evidência de PDF; pixels da imagem para evidência "imagem" (ver
render.preparar_evidencia_externa). render.inserir_evidencias_* converte pro
retângulo final do relatório.

Nunca lança: qualquer falha (tesseract ausente, página ilegível) devolve [] e
a evidência sai sem destaque, como sempre saiu.
"""
import io
import re
from pathlib import Path

_PAD = 1.8  # folga, em pontos/pixels, ao redor da palavra marcada


def _norma(texto: str) -> str:
    """Só o que identifica um número/data: dígitos, vírgula, ponto, barra. Tira
    "R$", espaços e pontuação solta que o OCR gruda no valor."""
    return re.sub(r"[^\d,./]", "", texto or "")


def _rects_de_palavras(palavras: list[tuple], termos: list[str]) -> list[tuple]:
    """palavras: [(texto, x0, top, x1, bottom)]. Devolve o retângulo de cada
    palavra cujo conteúdo numérico é IGUAL a um dos termos (igualdade, não
    "contém" — 1.491,99 não pode marcar 11.491,99)."""
    alvos = {_norma(t) for t in termos if _norma(t)}
    saida = []
    for texto, x0, top, x1, bottom in palavras:
        if _norma(texto) in alvos:
            saida.append((x0 - _PAD, top - _PAD, x1 + _PAD, bottom + _PAD))
    return saida


_PALAVRAS_POR_PAGINA: dict = {}


def _palavras_texto_pdf(pdf_origem: Path, pagina: int, bbox: tuple) -> list[tuple]:
    from conciliacao.pdf_cache import pdf_plumber_aberto

    # extract_words de uma página densa leva segundos; vários achados caem na
    # mesma página de listagem — extrai uma vez e filtra o recorte em memória.
    chave = (str(pdf_origem), pagina)
    if chave not in _PALAVRAS_POR_PAGINA:
        with pdf_plumber_aberto(pdf_origem) as pdf:
            if not (1 <= pagina <= len(pdf.pages)):
                return []
            _PALAVRAS_POR_PAGINA[chave] = [
                (w["text"], w["x0"], w["top"], w["x1"], w["bottom"])
                for w in pdf.pages[pagina - 1].extract_words()
            ]
    x0, top, x1, bottom = bbox
    return [
        w for w in _PALAVRAS_POR_PAGINA[chave]
        if w[1] >= x0 - 1 and w[3] <= x1 + 1 and w[2] >= top - 1 and w[4] <= bottom + 1
    ]


def _palavras_ocr(imagem, escala_x: float, escala_y: float, origem_x: float, origem_y: float) -> list[tuple]:
    """OCR com caixa por palavra. `escala_*` converte pixel -> unidade do
    recorte (pontos ou 1.0 pra pixel), somando a origem do recorte."""
    from conciliacao import ocr

    if not ocr.tesseract_disponivel():
        return []
    import pytesseract

    d = pytesseract.image_to_data(imagem, lang="por", output_type=pytesseract.Output.DICT)
    saida = []
    for i, texto in enumerate(d["text"]):
        if not texto.strip():
            continue
        x0 = origem_x + d["left"][i] * escala_x
        top = origem_y + d["top"][i] * escala_y
        saida.append((texto, x0, top, x0 + d["width"][i] * escala_x, top + d["height"][i] * escala_y))
    return saida


def _palavras_ocr_pdf(pdf_origem: Path, pagina: int, bbox: tuple, dpi: int = 220) -> list[tuple]:
    import fitz
    from PIL import Image

    x0, top, x1, bottom = bbox
    doc = fitz.open(str(pdf_origem))
    try:
        pix = doc[pagina - 1].get_pixmap(dpi=dpi, clip=fitz.Rect(x0, top, x1, bottom))
        imagem = Image.open(io.BytesIO(pix.tobytes("png")))
    finally:
        doc.close()
    pt_por_px = 72.0 / dpi
    return _palavras_ocr(imagem, pt_por_px, pt_por_px, x0, top)


_PALAVRAS_PAGINA_DENSA = 120   # acima disso, a evidência é uma listagem, não um comprovante
_PALAVRAS_NATIVAS_PAGINA_ESCANEADA = 40  # abaixo disso o corpo da página é uma imagem
_LINHAS_CONTEXTO = 3


def _palavras_da_evidencia(ev: dict, ocr: bool = False) -> tuple[list[tuple], bool]:
    """(palavras, veio_de_texto_nativo) do recorte da evidência, no espaço dela.
    `ocr=True` ignora o texto nativo e lê a imagem — páginas escaneadas costumam
    ter só um cabeçalho em texto nativo e o corpo inteiro numa imagem."""
    if ev.get("tipo") == "pdf":
        pdf, pagina, bbox = Path(ev["pdf_origem"]), ev["pagina_origem"], ev["bbox"]
        if not ocr:
            nativas = _palavras_texto_pdf(pdf, pagina, bbox)
            if nativas:
                return nativas, True
        return _palavras_ocr_pdf(pdf, pagina, bbox), False
    if ev.get("tipo") == "imagem":
        from PIL import Image

        with Image.open(ev["arquivo"]) as img:
            imagem = img.convert("RGB")
        ev["bbox"] = (0.0, 0.0, float(imagem.width), float(imagem.height))  # espaço = pixels
        ev["usou_ocr"] = True
        return _palavras_ocr(imagem, 1.0, 1.0, 0.0, 0.0), False
    return [], False


def _linha_inteira(palavras: list[tuple], rect: tuple) -> tuple:
    """Estende o retângulo de uma palavra até as bordas da linha dela."""
    x0, top, x1, bottom = rect
    da_linha = [w for w in palavras if abs(w[2] - (top + _PAD)) < 2.5]
    if not da_linha:
        return rect
    return (min(w[1] for w in da_linha) - _PAD, top, max(w[3] for w in da_linha) + _PAD, bottom)


def _recortar_em_torno(ev: dict, palavras: list[tuple], rect: tuple) -> dict | None:
    """Evidência nova, só com a linha do achado + algumas de contexto (inteiras,
    sem meia linha cortada). None se não der pra recortar."""
    from conciliacao import render

    altura = rect[3] - rect[1]
    contexto = altura * (_LINHAS_CONTEXTO + 0.6)
    esq = max(0.0, min(w[1] for w in palavras) - 4)
    dir_ = max(w[3] for w in palavras) + 4
    topo, base = rect[1] - contexto, rect[3] + contexto
    for _ in range(6):
        mudou = False
        for _, _, wtop, _, wbottom in palavras:
            if wtop < topo < wbottom:
                topo, mudou = wtop - 0.5, True
            if wtop < base < wbottom:
                base, mudou = wbottom + 0.5, True
        if not mudou:
            break
    return render.preparar_evidencia_vetorial(
        Path(ev["pdf_origem"]), ev["pagina_origem"], bbox_override=(esq, max(0.0, topo), dir_, base)
    )


def aplicar(ev: dict, termos: list[str], linha_inteira: bool = False, permitir_ocr: bool = True) -> dict:
    """
    Marca na evidência `ev` os `termos` (valor/data como aparecem no documento).
    Devolve a evidência a usar: a própria (com ev["destaque"]) ou, quando ela é
    uma PÁGINA DENSA de listagem (texto nativo, dezenas de linhas) e o termo foi
    achado, uma versão recortada na linha + contexto — letra legível em vez
    de uma página inteira miniaturizada.
    `linha_inteira`: marca a linha toda (achados sobre o LANÇAMENTO, ex.: sem
    comprovante) em vez de só o valor (achados sobre o VALOR).
    `permitir_ocr=False`: só texto nativo (quem chama limita o OCR por relatório,
    ~10 s por página). Quando o OCR é usado, `ev["usou_ocr"]` fica True.
    Nunca lança; sem termo achado devolve `ev` sem destaque.
    """
    termos = [t for t in termos if _norma(t)]
    if not termos or ev.get("tipo") not in ("pdf", "imagem"):
        return ev
    if ev.get("tipo") == "imagem" and not permitir_ocr:
        return ev
    try:
        palavras, nativo = _palavras_da_evidencia(ev)
        rects = _rects_de_palavras(palavras, termos)
        # OCR só quando o corpo da página é imagem (pouco texto nativo: só
        # cabeçalho). Página com muito texto nativo onde o termo não apareceu é
        # uma listagem em que o valor está formatado de outro jeito — OCR ali é
        # ~10 s jogados fora por achado (Fatto: 27 achados estouraram 15 min).
        if (not rects and nativo and ev.get("tipo") == "pdf" and permitir_ocr
                and len(palavras) < _PALAVRAS_NATIVAS_PAGINA_ESCANEADA):
            palavras, nativo = _palavras_da_evidencia(ev, ocr=True)
            ev["usou_ocr"] = True
            rects = _rects_de_palavras(palavras, termos)
        if not rects:
            return ev
        if linha_inteira:
            rects = [_linha_inteira(palavras, r) for r in rects]
        if ev["tipo"] == "pdf" and nativo and len(palavras) > _PALAVRAS_PAGINA_DENSA:
            recortada = _recortar_em_torno(ev, palavras, rects[0])
            if recortada:
                recortada["destaque"] = rects[:1]
                return recortada
        ev["destaque"] = rects
        return ev
    except Exception:
        return ev
