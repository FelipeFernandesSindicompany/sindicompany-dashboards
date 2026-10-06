"""
PDF aberto uma vez por processo. Abrir um PDF grande com pdfplumber e listar as
páginas (`pdf.pages`) leva minutos (Fatto Morumbi: 89 MB) — e vários módulos
(demonstrativo, categorias novas, evidências, destaques) leem o MESMO arquivo.
Todos passam por aqui: o primeiro paga o custo, os demais reaproveitam.
"""
import contextlib

_PDFS_PLUMBER: dict = {}
_TOTAL_PAGINAS: dict = {}


def pdf_plumber_aberto(caminho):
    """Context manager que devolve o pdfplumber.PDF do arquivo. Não fecha ao
    sair do `with` (processo curto; o arquivo só é lido, nunca alterado)."""
    import pdfplumber

    chave = str(caminho)
    if chave not in _PDFS_PLUMBER:
        _PDFS_PLUMBER[chave] = pdfplumber.open(chave)
    return contextlib.nullcontext(_PDFS_PLUMBER[chave])


def total_paginas(caminho) -> int:
    """Nº de páginas via fitz (instantâneo), sem listar pelo pdfplumber."""
    chave = str(caminho)
    if chave not in _TOTAL_PAGINAS:
        import fitz

        doc = fitz.open(chave)
        try:
            _TOTAL_PAGINAS[chave] = len(doc)
        finally:
            doc.close()
    return _TOTAL_PAGINAS[chave]


# ── Cache EM DISCO do texto das páginas (pdfplumber) ────────────────────────────────────────────
# Extrair o texto de um PDF de 200+ páginas com pdfplumber leva minutos, e a Validação lê o MESMO arquivo
# várias vezes (leitor financeiro, marcadores, conciliador, regras gerais) e também os do mês anterior —
# que já foram lidos quando aquele mês foi validado. O texto devolvido é exatamente o mesmo; só deixa de
# ser recalculado. Chave: caminho + tamanho + data de modificação do arquivo (mudou o arquivo, recalcula).
#
# Três camadas, todas transparentes para quem usa `pdfplumber.open(...)` / `page.extract_text()`:
#   1. `Page.extract_text()` (chamada padrão, página inteira) é gravado/lido do cache em disco;
#   2. um PDF já lido por inteiro (todas as páginas no cache) é "aberto" sem pdfplumber: devolve um objeto
#      leve cujas páginas respondem `extract_text()` do cache e, se alguém pedir qualquer outra coisa
#      (palavras, imagem, recorte, argumentos), abre o PDF de verdade só nesse momento;
#   3. na mesma execução, o PDF aberto de verdade é reaproveitado (não refaz a árvore de páginas).
# Desligar tudo: variável de ambiente SINDICOMPANY_SEM_CACHE_TEXTO=1.
import atexit
import hashlib
import json
import os
import threading
from pathlib import Path

_DIR_CACHE = Path(__file__).parent.parent / "data" / "cache_texto_pdf"
_TEXTOS: dict = {}          # chave do arquivo -> {"n": nº de páginas | None, "p": {"1": texto, ...}}
_NOVAS: dict = {}           # chave -> {página: texto} novas desde o último flush
_REAIS: dict = {}           # caminho -> PDF aberto de verdade nesta execução (reaproveitado)
_TRAVA = threading.RLock()
_ATIVADO = False
_FLUSH_A_CADA = 25
_MAX_REAIS = 3


def _chave_arquivo(caminho: str) -> str | None:
    try:
        st = os.stat(caminho)
    except OSError:
        return None
    return hashlib.sha1(f"{os.path.abspath(caminho)}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8")).hexdigest()


def _ler_disco(chave: str) -> dict:
    arq = _DIR_CACHE / f"{chave}.json"
    try:
        dados = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    except (OSError, ValueError):
        dados = {}
    if "p" not in dados:      # formato antigo / vazio
        dados = {"n": dados.get("n"), "p": {}}
    return dados


def _carregar(chave: str) -> dict:
    if chave not in _TEXTOS:
        _TEXTOS[chave] = _ler_disco(chave)
    return _TEXTOS[chave]


def _descarregar(chave: str) -> None:
    """Grava no disco as páginas novas (mescla com o que outro processo possa ter gravado)."""
    novas = _NOVAS.pop(chave, None)
    if not novas:
        return
    try:
        _DIR_CACHE.mkdir(parents=True, exist_ok=True)
        atual = _ler_disco(chave)
        atual["p"].update(novas)
        em_memoria = _TEXTOS.get(chave, {})
        if em_memoria.get("n"):
            atual["n"] = em_memoria["n"]
        arq = _DIR_CACHE / f"{chave}.json"
        tmp = arq.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(atual, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, arq)
    except OSError:
        pass  # cache é só otimização: falha de disco nunca derruba a Validação


def _descarregar_tudo() -> None:
    with _TRAVA:
        for chave in list(_NOVAS):
            _descarregar(chave)


def _completo(chave: str) -> bool:
    dados = _carregar(chave)
    n = dados.get("n")
    return bool(n) and len(dados["p"]) >= n and all(str(i) in dados["p"] for i in range(1, n + 1))


def ativar_cache_texto() -> None:
    """Instala o cache no pdfplumber (idempotente)."""
    global _ATIVADO
    if _ATIVADO or os.environ.get("SINDICOMPANY_SEM_CACHE_TEXTO") == "1":
        return
    try:
        import pdfplumber
        from pdfplumber import page as _pagina
        from pdfplumber import pdf as _pdf_mod
    except ImportError:
        return
    extrair_original = _pagina.Page.extract_text
    abrir_original = pdfplumber.open

    # ── camada 1: texto da página ──
    def extract_text_com_cache(self, **kwargs):
        if kwargs or type(self) is not _pagina.Page:
            return extrair_original(self, **kwargs)
        caminho = getattr(self.pdf, "path", None) or getattr(getattr(self.pdf, "stream", None), "name", None)
        chave = _chave_arquivo(str(caminho)) if caminho else None
        if chave is None:
            return extrair_original(self)
        numero = str(self.page_number)
        with _TRAVA:
            texto = _carregar(chave)["p"].get(numero)
        if texto is not None:
            return texto
        texto = extrair_original(self)
        with _TRAVA:
            dados = _carregar(chave)
            dados["p"][numero] = texto
            try:
                dados["n"] = len(self.pdf.pages)
            except Exception:
                pass
            novas = _NOVAS.setdefault(chave, {})
            novas[numero] = texto
            if len(novas) >= _FLUSH_A_CADA:
                _descarregar(chave)
        return texto

    _pagina.Page.extract_text = extract_text_com_cache

    # ── camadas 2 e 3: abertura do PDF ──
    class _PaginaLeve:
        """Página de um PDF 'aberto' pelo cache: texto do cache; o resto vem do PDF de verdade, sob demanda."""

        def __init__(self, pdf, numero):
            self._pdf, self.page_number = pdf, numero

        def extract_text(self, **kwargs):
            if kwargs:
                return self._real().extract_text(**kwargs)
            return _carregar(self._pdf._chave)["p"][str(self.page_number)]

        def _real(self):
            return self._pdf._real().pages[self.page_number - 1]

        def __getattr__(self, nome):
            return getattr(self._real(), nome)

    class _PdfLeve:
        def __init__(self, caminho, chave):
            self.path, self._chave, self._pdf_real = caminho, chave, None
            self.pages = [_PaginaLeve(self, i + 1) for i in range(_carregar(chave)["n"])]

        def _real(self):
            if self._pdf_real is None:
                self._pdf_real = _abrir_reaproveitando(self.path)
            return self._pdf_real

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def close(self):
            return None

        def __getattr__(self, nome):
            return getattr(self._real(), nome)

    def _abrir_reaproveitando(caminho):
        with _TRAVA:
            pdf = _REAIS.get(caminho)
            if pdf is not None:
                return pdf
        pdf = abrir_original(caminho)
        pdf.close = lambda *a, **k: None          # `with pdfplumber.open(...)` não fecha o que é reaproveitado
        with _TRAVA:
            if len(_REAIS) >= _MAX_REAIS:
                _REAIS.pop(next(iter(_REAIS)))
            _REAIS[caminho] = pdf
        return pdf

    def abrir_com_cache(caminho, *args, **kwargs):
        if args or kwargs or not isinstance(caminho, (str, os.PathLike)):
            return abrir_original(caminho, *args, **kwargs)
        caminho = str(caminho)
        chave = _chave_arquivo(caminho)
        if chave is None:
            return abrir_original(caminho)
        with _TRAVA:
            if _completo(chave):
                return _PdfLeve(caminho, chave)
        return _abrir_reaproveitando(caminho)

    pdfplumber.open = abrir_com_cache
    atexit.register(_descarregar_tudo)
    _limpar_cache_antigo()
    _ATIVADO = True


def _limpar_cache_antigo(dias: int = 400) -> None:
    """Apaga do cache arquivos gravados há mais de `dias` (PDF de mês muito antigo não volta a ser lido)."""
    import time

    try:
        limite = time.time() - dias * 86400
        for arq in _DIR_CACHE.glob("*.json"):
            if arq.stat().st_mtime < limite:
                arq.unlink(missing_ok=True)
    except OSError:
        pass
