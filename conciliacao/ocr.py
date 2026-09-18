"""
OCR compartilhado para páginas de comprovante sem texto extraível (imagem
raster embutida no PDF) — hoje usado só por conciliacao/lirba_pdf.py
(família ContasData), mas desenhado para ser reaproveitado por qualquer
outro parser que precise do mesmo tipo de comprovante digitalizado.

Nunca lança exceção: qualquer falha (tesseract não instalado, idioma
ausente, imagem ilegível) degrada para string vazia — quem chama decide
entre "sem_comprovante" (nenhum conteúdo confirmado) e
"conteudo_nao_verificavel" (comprovante existe, mas o OCR não confirmou o
valor/data com confiança), ver conciliacao/matching.py.

Resolve o bug de quoting descoberto num spike manual: passar
`--tessdata-dir "C:/pasta com espaço"` como config string pro pytesseract
faz as aspas irem literalmente para o caminho que o tesseract tenta abrir
(o subprocess não passa por um shell que as interpretaria). A variável de
ambiente TESSDATA_PREFIX não tem esse problema.
"""
import os
import shutil
import tempfile
from pathlib import Path

# Instalação via winget (UB-Mannheim.TesseractOCR) cai aqui por padrão no
# Windows; shutil.which("tesseract") cobre quem tiver o binário no PATH.
_TESSERACT_CANDIDATOS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe"]
# O pacote de idioma "por.traineddata" não vem por padrão nem no instalador
# oficial (só eng+osd) — precisa ser baixado à parte (tesseract-ocr/tessdata
# no GitHub) para uma pasta com permissão de escrita do usuário, já que
# escrever direto em Program Files exige elevação.
_TESSDATA_CANDIDATOS = [Path.home() / "tessdata", Path(r"C:\Program Files\Tesseract-OCR\tessdata")]

_disponivel: bool | None = None  # cache do feature-detection (só avisa/checa uma vez por processo)


def tesseract_disponivel() -> bool:
    """Feature-detection cacheada — nunca lança, só retorna True/False."""
    global _disponivel
    if _disponivel is not None:
        return _disponivel

    try:
        import pytesseract
    except ImportError:
        print("[AVISO] pytesseract não instalado (pip install -r requirements.txt) — "
              "comprovantes sem texto extraível ficarão como 'conteudo_nao_verificavel'.")
        _disponivel = False
        return False

    tesseract_cmd = shutil.which("tesseract") or next(
        (p for p in _TESSERACT_CANDIDATOS if Path(p).exists()), None
    )
    tessdata_dir = next(
        (str(p) for p in _TESSDATA_CANDIDATOS if (p / "por.traineddata").exists()), None
    )
    if not (tesseract_cmd and tessdata_dir):
        print("[AVISO] OCR indisponível (tesseract e/ou o idioma 'por' não encontrados nesta "
              "máquina) — comprovantes sem texto extraível ficarão como 'conteudo_nao_verificavel'.")
        _disponivel = False
        return False

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    os.environ["TESSDATA_PREFIX"] = tessdata_dir
    _disponivel = True
    return True


def ocr_pagina_pdf(caminho_pdf: Path, indice_pagina_0based: int, dpi: int = 300, lang: str = "por") -> str:
    """
    Renderiza 1 página do PDF (via pymupdf, já dependência do projeto) e roda
    OCR nela. Retorna "" em qualquer falha — inclusive OCR indisponível,
    página inexistente ou imagem ilegível — nunca lança exceção, para não
    derrubar a extração inteira por causa de 1 página problemática.
    """
    if not tesseract_disponivel():
        return ""
    try:
        import fitz
        import pytesseract

        doc = fitz.open(str(caminho_pdf))
        try:
            if not (0 <= indice_pagina_0based < len(doc)):
                return ""
            pix = doc[indice_pagina_0based].get_pixmap(dpi=dpi)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                pix.save(tmp_path)
                return pytesseract.image_to_string(tmp_path, lang=lang)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        finally:
            doc.close()
    except Exception as exc:
        print(f"[AVISO] OCR falhou na página {indice_pagina_0based + 1} de {caminho_pdf.name}: {exc}")
        return ""
