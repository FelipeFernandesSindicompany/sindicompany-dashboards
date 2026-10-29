"""
Anexos de cada despesa no portal da GCONT (Superlogica) — usados quando a prestação de contas vem RESUMIDA (sem as páginas de comprovante) mas o
livro caixa traz, em cada linha de despesa, um link público ("...areadocondomino/publico/arquivos?accesskey=...&idParcela=...") para a página com os
documentos do pagamento (nota fiscal, boleto, comprovante bancário).

A página lista os arquivos ("downloadarquivo?id=...&hash=...") ou, quando só há um, devolve o próprio PDF. Cada despesa é baixada uma vez e guardada em
`<temp>/anexos_portal_gcont/<idParcela>/` (nas próximas validações do mesmo mês não baixa de novo). Nunca lança: falha de rede = lista vazia.
"""
import html
import re
import tempfile
import time
import urllib.parse as up
import urllib.request
from pathlib import Path
from typing import Optional

CACHE = Path(tempfile.gettempdir()) / "anexos_portal_gcont"
_UA = {"User-Agent": "Mozilla/5.0"}


def _get(url: str):
    erro = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=60) as r:
                return r.read(), r.headers
        except Exception as exc:                       # noqa: BLE001
            erro = exc
            time.sleep(1)
    return None, str(erro)


def id_parcela(uri: str) -> Optional[str]:
    return (up.parse_qs(up.urlparse(uri).query).get("idParcela") or [None])[0]


def anexos_da_parcela(uri: str) -> list:
    """[(caminho local, nome do arquivo)] dos documentos anexados à despesa deste link."""
    parc = id_parcela(uri)
    if not parc:
        return []
    pasta = CACHE / parc
    if pasta.is_dir() and any(pasta.iterdir()):
        return sorted(((f, f.name.split("_", 1)[-1]) for f in pasta.iterdir() if f.is_file()), key=lambda x: x[0].name)
    corpo, cab = _get(uri)
    if corpo is None:
        return []
    pasta.mkdir(parents=True, exist_ok=True)
    if corpo[:4] == b"%PDF":                     # a página É o documento (anexo único)
        m = re.search(r'filename="?([^";]+)', cab.get("Content-Disposition", "") if not isinstance(cab, str) else "")
        (pasta / f"0_{re.sub(r'[^A-Za-z0-9._-]', '_', up.unquote(m.group(1)) if m else 'documento.pdf')[:60]}").write_bytes(corpo)
    else:
        links = re.findall(r'href="(https://[^"]*downloadarquivo\?[^"]+)"', corpo.decode("latin-1"))
        for k, l in enumerate(dict.fromkeys(links)):
            dados, hh = _get(html.unescape(l))
            if dados is None:
                continue
            m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', hh.get("Content-Disposition", ""))
            nome = up.unquote(m.group(1)) if m else f"arq{k}.pdf"
            (pasta / f"{k}_{re.sub(r'[^A-Za-z0-9._-]', '_', nome)[:60]}").write_bytes(dados)
    return sorted(((f, f.name.split("_", 1)[-1]) for f in pasta.iterdir() if f.is_file()), key=lambda x: x[0].name)


def texto_do_arquivo(caminho: Path) -> str:
    """Texto de todas as páginas (nativo; OCR nas digitalizadas/imagens)."""
    from conciliacao import gocontroledocumentos as g, ocr

    dados = caminho.read_bytes()
    if caminho.suffix.lower() in (".jpg", ".jpeg", ".png"):
        return ocr.ocr_imagem_bytes(dados)
    texto, ok = g.texto_de_pdf_baixado(dados)
    if len(texto.strip()) < 30 and ok:
        texto = g.ocr_primeira_pagina(dados)
    resto = g.textos_das_demais_paginas(dados)
    return texto + ("\n" + resto if resto else "")


def textos_por_pagina(caminho: Path) -> list:
    """Texto de cada página do arquivo (nativo; OCR na página digitalizada) — comprovante de várias páginas = um pagamento por página."""
    from conciliacao import gocontroledocumentos as g, ocr

    if caminho.suffix.lower() in (".jpg", ".jpeg", ".png"):
        return [ocr.ocr_imagem_bytes(caminho.read_bytes())]
    import fitz

    out = []
    with fitz.open(str(caminho)) as doc:
        for pg in doc:
            t = pg.get_text() or ""
            if len(t.strip()) < 30:
                try:
                    t = ocr.ocr_imagem_bytes(pg.get_pixmap(dpi=300).tobytes("png"))
                except Exception:
                    t = ""
            out.append(t)
    return out
