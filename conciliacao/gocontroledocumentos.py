"""
Cliente HTTP compartilhado para o sistema "GoControleDocumentos" (Telerik +
ASP.NET) — confirmado em dados reais em pelo menos 3 white-labels diferentes
que rodam o MESMO protocolo, só o domínio/caminho base muda:

  - Robotton (Hausy/Central das Artes): sistemas.imoveis.robotton.com.br/
    gocontroledocumentos_condo/AbrirDoctos.aspx?LANCTO=...&TIPO=...
  - GK ADM (Ciudad Real): sistemas.gk.com.br/gocontroledocumentos/
    AbrirDoctos.aspx?LANCTO=...&TIPO=...
  - Loan Imóveis (Upper Itaim): loanimoveis.dyndns.org:8080/
    gocontroledocumentos/AbrirDoctos.aspx?LANCTO=...&TIPO=...

Protocolo:
  1. GET no link "AbrirDoctos.aspx?LANCTO=...&TIPO=..." (extraído do próprio
     PDF do demonstrativo, anotação kind=2/URI) estabelece uma sessão
     ASP.NET (cookies).

  2. Um LANÇAMENTO PODE TER MAIS DE UM DOCUMENTO ANEXADO — confirmado em
     dados reais (Upper Itaim, código 0004: o comprovante bancário E a Nota
     Fiscal, dois arquivos distintos pro MESMO lançamento). A página HTML
     lista os documentos numa tabela `dlDocumentos` (`dlDocumentos_ctl00_
     imgDocto`, `dlDocumentos_ctl01_imgDocto`, ...) — o PRIMEIRO já vem
     pronto no HTML inicial (padrão a/b abaixo), mas os DEMAIS só aparecem
     depois de simular o clique (postback ASP.NET no botão de imagem — os
     mesmos campos ocultos `__VIEWSTATE`/`__VIEWSTATEGENERATOR`/
     `__EVENTVALIDATION` da página, mais `dlDocumentos$ctlNN$imgDocto.x`/`.y`
     reenviados por POST na MESMA URL) — sem isso, o índice 0 é o único
     baixado, e qualquer NF anexada como segundo documento nunca é vista
     (confirmado: gerava falso-positivo de "Nota Fiscal ausente" quando a NF
     na verdade estava lá, só não no primeiro item da lista).

     Cada documento (primeiro ou via postback) devolve HTML com UM de dois
     padrões, dependendo do tipo:
       a) <img ... src="/.../Show.aspx?ca=X&or=Y&Session=Z" ...> — imagem
          JPEG do comprovante (comprovantes bancários digitalizados).
       b) ".../pdf.js/web/viewer.html?file=<caminho URL-encoded>" — um PDF
          de verdade (documento que já era PDF nativo, ex.: a Nota Fiscal).
     Um segundo GET (mesmos cookies da sessão) na URL encontrada devolve o
     binário.

Generaliza a base (scheme://netloc) via urlsplit em vez de fixar um
segmento de caminho como "/gocontroledocumentos_condo/" — necessário porque
o segmento varia por white-label (com ou sem "_condo").

Nunca lança — qualquer falha de rede/parsing vira lista vazia/None, e quem
chama trata como "conteúdo não confirmável" (não confirma um valor às
cegas).
"""
import re
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

_RE_SHOW_SRC = re.compile(r'src="([^"]*Show\.aspx[^"]*)"')
_RE_VIEWER_FILE = re.compile(r"viewer\.html\?file=([^\"'&\s]+)")
_RE_INDICE_DOCUMENTO = re.compile(r"dlDocumentos_ctl(\d+)_imgDocto")
_RE_CAMPO_OCULTO = re.compile(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"')
# "ControlaPaineis(sAux, sAux2, sId, sPdfString, ori)" — sAux=1 significa
# "mostra o painel de IMAGEM" (Show.aspx), sAux=2 significa "mostra o
# painel de PDF" e sAux2 já É o caminho do viewer.html (URL-encoded), sem
# precisar buscar separado. Confirmado em dados reais (Upper Itaim) que é a
# ÚNICA forma confiável de saber qual dos dois modos vale pra um documento
# específico depois de um postback — o HTML de resposta continua incluindo
# a MINIATURA Show.aspx do primeiro documento na tira lateral mesmo quando o
# painel principal mudou pra PDF, então buscar "Show.aspx" solto no HTML
# (sem checar o modo primeiro) pega sempre a miniatura errada.
_RE_CONTROLA_PAINEIS = re.compile(r"ControlaPaineis\((\d+),\s*'([^']*)'")

_EXTENSAO_POR_TIPO = {"jpeg": "jpg", "pdf": "pdf"}


def _extrair_documento_do_html(html: str, base: str, headers: dict, opener) -> tuple[bytes, str] | None:
    """Acha o padrão a) Show.aspx (imagem) ou b) viewer.html?file=... (PDF) no
    HTML de UM documento (either a página inicial, either a resposta de um
    postback) e baixa o binário. None se nenhum padrão bater."""
    m_cp = _RE_CONTROLA_PAINEIS.search(html)
    if m_cp and m_cp.group(1) == "2" and m_cp.group(2):
        # sAux2 é a URL do VISUALIZADOR pdf.js ("pdf.js/web/viewer.html?
        # file=<caminho-do-pdf-real>"), não o PDF em si — precisa extrair o
        # parâmetro "file=" de dentro dela (mesmo padrão de _RE_VIEWER_FILE),
        # senão o GET baixa a página HTML do visualizador, não o binário.
        m_arquivo = _RE_VIEWER_FILE.search(m_cp.group(2))
        if m_arquivo:
            caminho = urllib.parse.unquote(m_arquivo.group(1))
            pdf_url = caminho if caminho.startswith("http") else base + caminho
            req = urllib.request.Request(pdf_url, headers=headers)
            with opener.open(req, timeout=20) as resp:
                return resp.read(), "pdf"

    m = _RE_SHOW_SRC.search(html)
    if m:
        caminho = m.group(1).replace("&amp;", "&")
        show_url = caminho if caminho.startswith("http") else base + caminho
        req = urllib.request.Request(show_url, headers=headers)
        with opener.open(req, timeout=20) as resp:
            return resp.read(), "jpeg"

    m2 = _RE_VIEWER_FILE.search(html)
    if m2:
        caminho = urllib.parse.unquote(m2.group(1))
        pdf_url = caminho if caminho.startswith("http") else base + caminho
        req = urllib.request.Request(pdf_url, headers=headers)
        with opener.open(req, timeout=20) as resp:
            return resp.read(), "pdf"

    return None


def _campos_ocultos(html: str) -> dict[str, str]:
    return {nome: valor for nome, valor in _RE_CAMPO_OCULTO.findall(html)}


def baixar_todos_comprovantes(uri: str) -> list[tuple[bytes, str]]:
    """
    Baixa TODOS os documentos anexados a um lançamento (ver docstring do
    módulo — pode ser mais de um: comprovante bancário + Nota Fiscal, por
    exemplo). Devolve lista de (dados, "jpeg"|"pdf"), na ordem em que
    aparecem no sistema de origem — lista vazia se nada foi encontrado ou
    em qualquer falha de rede (nunca lança).
    """
    try:
        jar = CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        headers = {"User-Agent": "Mozilla/5.0"}

        req1 = urllib.request.Request(uri, headers=headers)
        with opener.open(req1, timeout=20) as resp1:
            html = resp1.read().decode("utf-8", errors="replace")

        partes = urllib.parse.urlsplit(uri)
        base = f"{partes.scheme}://{partes.netloc}"

        resultados: list[tuple[bytes, str]] = []
        primeiro = _extrair_documento_do_html(html, base, headers, opener)
        if primeiro:
            resultados.append(primeiro)

        indices = sorted({int(i) for i in _RE_INDICE_DOCUMENTO.findall(html)})
        if len(indices) <= 1:
            return resultados

        campos_base = _campos_ocultos(html)
        for idx in indices[1:]:
            try:
                campos = dict(campos_base)
                campos[f"dlDocumentos$ctl{idx:02d}$imgDocto.x"] = "5"
                campos[f"dlDocumentos$ctl{idx:02d}$imgDocto.y"] = "5"
                dados_post = urllib.parse.urlencode(campos).encode("utf-8")
                req2 = urllib.request.Request(
                    uri, data=dados_post,
                    headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
                )
                with opener.open(req2, timeout=20) as resp2:
                    html2 = resp2.read().decode("utf-8", errors="replace")
                documento = _extrair_documento_do_html(html2, base, headers, opener)
                if documento:
                    resultados.append(documento)
            except (urllib.error.URLError, TimeoutError, OSError):
                continue  # um documento falhando não deve derrubar os demais

        return resultados
    except (urllib.error.URLError, TimeoutError, OSError):
        return []


def baixar_comprovante(uri: str) -> tuple[bytes, str] | None:
    """Compatibilidade com chamadores que só querem UM documento (o
    primeiro) — ver baixar_todos_comprovantes para o caso de múltiplos
    documentos por lançamento."""
    resultados = baixar_todos_comprovantes(uri)
    return resultados[0] if resultados else None


def texto_de_pdf_baixado(dados_bin: bytes) -> tuple[str, bool]:
    """Extrai o texto nativo da 1ª página de um PDF baixado (tipo_arquivo
    "pdf" de baixar_comprovante) — devolve (texto, pagina_disponivel_para_ocr).
    `pagina_disponivel_para_ocr` é False quando o PDF não abriu/não tem
    página nenhuma (não há nada pra renderizar depois via `ocr_primeira_pagina`,
    mesmo que o texto nativo tenha falhado)."""
    try:
        import fitz
        with fitz.open(stream=dados_bin, filetype="pdf") as doc_comp:
            if len(doc_comp) == 0:
                return "", False
            return doc_comp[0].get_text() or "", True
    except Exception:
        return "", False


def ocr_primeira_pagina(dados_bin: bytes) -> str:
    """Renderiza a 1ª página de um PDF baixado e roda OCR — usado quando o
    texto nativo falhou ou saiu curto/ilegível demais pra confiar (ver
    conciliacao/ocr.py). Nunca lança."""
    from conciliacao import ocr
    try:
        import fitz
        with fitz.open(stream=dados_bin, filetype="pdf") as doc_comp:
            pix = doc_comp[0].get_pixmap(dpi=300)
            return ocr.ocr_imagem_bytes(pix.tobytes("png"))
    except Exception:
        return ""


def salvar_evidencia_externa(caminho_pdf: Path, codigo: str, dados_bin: bytes, tipo_arquivo: str) -> str | None:
    """Salva uma cópia local do comprovante baixado — sem isso o relatório
    final não tem página nenhuma do PDF original pra recortar (ver
    render.py::preparar_evidencia_vetorial). Fica em
    version_dir/evidencias_externas/<código>.<ext>. Nunca lança."""
    try:
        version_dir = caminho_pdf.parent.parent
        pasta = version_dir / "evidencias_externas"
        pasta.mkdir(parents=True, exist_ok=True)
        extensao = _EXTENSAO_POR_TIPO.get(tipo_arquivo, "bin")
        destino = pasta / f"{codigo}.{extensao}"
        destino.write_bytes(dados_bin)
        return str(destino)
    except OSError:
        return None
