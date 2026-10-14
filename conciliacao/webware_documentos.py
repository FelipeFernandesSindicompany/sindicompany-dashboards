"""
Cliente HTTP do sistema Webware (gominio.webware.com.br) — usado pela planilha Habitacional do Fatto Morumbi (ago/2026 em diante), cujo
"Anexo" é um hyperlink  https://gominio.webware.com.br/Relatorio/Arquivos?request=<token>  (aberto sem login).

A página devolvida é um visualizador HTML com UM item por documento anexado, em um de dois formatos (confirmados em dados reais):
  a) <img id='N' src='.../api/MovimentoDiario/GetDocTos?cript=...'>            — JPEG (ex.: "Comprovante de Pagamento Eletrônico")
  b) <iframe id='N_pdf' src='.../api/MovimentoDiario/GetDocTos?cript=...'>     — PDF (ex.: guia de tributo, fatura de consumo, NF)
Este módulo baixa todos os itens, na ordem, e identifica o tipo pelo conteúdo. Nunca lança: qualquer falha de rede/parsing vira
lista vazia, e quem chama trata como "conteúdo não confirmável" (nunca confirma um valor às cegas).
"""
import re
import urllib.error
import urllib.request

_RE_ITEM = re.compile(r"""<(?:img|iframe)[^>]*\bid=['"](\d+)(?:_pdf)?['"][^>]*\bsrc=['"]([^'"]+)['"]""", re.IGNORECASE)
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def eh_link_webware(uri: str | None) -> bool:
    return bool(uri) and "webware.com.br" in uri.lower()


def _tipo(dados: bytes) -> str:
    return "pdf" if dados[:5] == b"%PDF-" else "jpeg"


def baixar_documentos(uri: str, timeout: int = 40) -> list[tuple[bytes, str]]:
    """[(dados, 'jpeg'|'pdf'), ...] dos documentos atrás do link `uri`, na ordem (lista vazia em qualquer falha)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(uri, headers=_HEADERS), timeout=timeout) as r:
            html = r.read().decode("utf-8", errors="replace")
        docs: list[tuple[bytes, str]] = []
        for _id, src in sorted(((int(i), s) for i, s in _RE_ITEM.findall(html)), key=lambda x: x[0]):
            src = src.replace("&amp;", "&")
            try:
                with urllib.request.urlopen(urllib.request.Request(src, headers=_HEADERS), timeout=timeout) as r2:
                    dados = r2.read()
                if dados:
                    docs.append((dados, _tipo(dados)))
            except (urllib.error.URLError, TimeoutError, OSError):
                continue
        return docs
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
