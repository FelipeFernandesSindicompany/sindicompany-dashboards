"""Segunda tentativa de leitura de um anexo escaneado cujo valor não apareceu no OCR normal.

Faturas escaneadas (Sabesp, Enel...) têm o TOTAL em quadro cinza, que o OCR padrão perde (caso real: Sabesp R$ 24.698,24 no Elo, jul/2026,
confirmado na imagem). Aqui cada página é renderizada e lida de novo, binarizada em dois limiares e ampliada; só devolve texto — quem chama
decide se o valor da listagem aparece. Nunca lança."""
import io
import tempfile
from pathlib import Path


def textos_binarizados(docs: list, max_paginas: int = 3) -> list:
    """docs: [(bytes, 'pdf'|'jpeg')] -> lista de textos extra (um por página x limiar)."""
    saida: list = []
    try:
        import fitz
        import pytesseract
        from PIL import Image

        from conciliacao import ocr
        if not ocr.tesseract_disponivel():
            return saida
        for dados, tipo in docs:
            imagens = []
            if tipo == "pdf":
                with fitz.open(stream=dados, filetype="pdf") as doc:
                    for i in range(min(len(doc), max_paginas)):
                        imagens.append(Image.open(io.BytesIO(doc[i].get_pixmap(dpi=200).tobytes("png"))).convert("L"))
            else:
                imagens.append(Image.open(io.BytesIO(dados)).convert("L"))
            for img in imagens:
                if img.width < 1800:
                    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
                for limiar in (150, 190):
                    bw = img.point(lambda p, l=limiar: 255 if p > l else 0)
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        caminho = tmp.name
                    try:
                        bw.save(caminho)
                        saida.append(pytesseract.image_to_string(caminho, lang="por"))
                    finally:
                        Path(caminho).unlink(missing_ok=True)
    except Exception:
        return saida
    return saida
