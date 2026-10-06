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
