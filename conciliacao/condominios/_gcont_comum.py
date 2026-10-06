"""
Camada comum dos conciliadores GCONT/HSA com comprovante em TEXTO NATIVO
(Parque Saint Afonso, I-Gloo Alphaville, ...) — reaproveita
conciliacao/condominios/club_park_butanta.py (que NAO e alterado) e corrige o
que aquele parser nao cobre:

  1. Fornecedor com nome em DUAS linhas na capa. Layout pdfplumber da capa:
         Pago a: Vencimento Liquidacao Documento Valor
         FORTPEL COMERCIO DE DESCARTAVEIS 01/07/2026 01/07/2026 423125 745,24
         LTDA (1 de 2)
     O parser do Club Park le so a 1a linha (perde "LTDA (1 de 2)", que e o
     marcador de parcela da NF) e, quando o "Documento" tem espacos
     ("7930 / 5566"), nao casa a linha e deixa fornecedor/datas vazios. Aqui a
     capa e relida: fornecedor = nome completo (todas as linhas ate "Destina-se
     a:"), vencimento, liquidacao e documento completos. So grava se o valor da
     linha conferir com o "Valor:" da capa.

  2. Duplicidade falsa de debito automatico (mesmo fornecedor/valor/dia,
     varias parcelas): a capa nao traz identificador, mas a pagina seguinte
     (imagem do recibo Itau) traz "Identificacao no extrato DA COMGAS
     <instalacao>" e a autenticacao. Para os GRUPOS candidatos a duplicidade
     (mesma chave usada em matching.gerar_achados_gcont), o OCR dessa pagina e
     anexado ao texto_bruto do registro sob o marcador
     "[RECIBO OCR pag. N]"; matching.gerar_achados_gcont usa a assinatura
     (autenticacao/instalacao) para separar pagamentos distintos de repeticoes
     reais. OCR so roda nesses grupos (poucas paginas).

Arquivo com prefixo "_" nao e carregado como conciliador de condominio
(ver conciliacao/__init__.py::_condo_conciliadores).
"""
import re
from collections import defaultdict

from conciliacao import ocr
from conciliacao.condominios.club_park_butanta import Conciliador as _ConciliadorClubPark
from conciliacao.condominios.club_park_butanta import _num

MARCADOR_RECIBO_OCR = "[RECIBO OCR pag. {pag}]"

_RE_LINHA1 = re.compile(
    r"^(?P<n>.+?)\s+(?P<v>\d{2}/\d{2}/\d{4})\s+(?P<l>\d{2}/\d{2}/\d{4})\s+"
    r"(?:(?P<d>.*?)\s+)?(?P<val>[\d.]+,\d{2})\s*$"
)


def _reler_capa(texto: str):
    """(fornecedor, vencimento, liquidacao, documento, valor) da capa em layout
    pdfplumber, ou None."""
    linhas = [l.strip() for l in (texto or "").split("\n")]
    for i, l in enumerate(linhas):
        if l.startswith("Pago a:") and i + 1 < len(linhas):
            m = _RE_LINHA1.match(linhas[i + 1])
            if not m:
                return None
            continuacao = []
            for l2 in linhas[i + 2:]:
                if not l2 or l2.startswith("Destina-se a"):
                    break
                continuacao.append(l2)
            forn = re.sub(r"\s+", " ", " ".join([m.group("n")] + continuacao)).strip()
            return forn, m.group("v"), m.group("l"), (m.group("d") or "").strip() or None, _num(m.group("val"))
    return None


def reparar_capas(registros: list) -> int:
    """Reescreve fornecedor/vencimento/pagamento/documento a partir da capa
    completa. Devolve quantos registros mudaram."""
    n = 0
    for r in registros:
        if r.tipo_documento != "despesa_com_comprovante":
            continue
        lido = _reler_capa(r.texto_bruto)
        if not lido:
            continue
        forn, venc, liq, doc, valor = lido
        if r.valor and abs(valor - r.valor) > 0.01:
            continue
        if not forn or len(forn) > 200:
            continue
        mudou = (r.fornecedor, r.vencimento, r.pagamento) != (forn, venc, liq)
        r.fornecedor, r.vencimento, r.pagamento = forn, venc, liq
        if doc:
            r.autenticacao = doc
        n += int(mudou)
    return n


def _chave_duplicidade(r):
    # espelha matching.gerar_achados_gcont
    return ((r.fornecedor or "").strip().upper(), r.autenticacao or r.vencimento, round(r.valor, 2))


def anexar_recibos_ocr_em_grupos_duplicados(registros: list, caminho) -> int:
    """OCR da pagina seguinte a capa (recibo em imagem) so para os membros de
    grupos candidatos a duplicidade. Devolve quantos recibos foram lidos."""
    grupos = defaultdict(list)
    for r in registros:
        if r.tipo_documento == "despesa_com_comprovante":
            grupos[_chave_duplicidade(r)].append(r)
    lidos = 0
    candidatos = [r for g in grupos.values() if len(g) >= 2 for r in g]
    if not candidatos:
        return 0
    import fitz

    with fitz.open(str(caminho)) as doc:
        for r in candidatos:
            idx = r.pagina  # 0-based da pagina seguinte a capa
            if idx >= len(doc):
                continue
            t_prox = doc[idx].get_text()
            if "Comprovantes de despesas" not in t_prox or f"Parcela {r.codigo}" not in t_prox:
                continue  # a pagina seguinte nao e continuacao desta parcela
            if len(t_prox.strip()) > 200:
                texto = t_prox  # recibo ja em texto nativo
            else:
                texto = ocr.ocr_pagina_pdf(caminho, idx, doc_aberto=doc)
            if texto and texto.strip():
                r.texto_bruto = (r.texto_bruto or "") + "\n" + MARCADOR_RECIBO_OCR.format(pag=idx + 1) + "\n" + texto
                lidos += 1
    return lidos


class ConciliadorGcontNativo(_ConciliadorClubPark):
    def extrair_comprovantes(self, caminho) -> list:
        registros = super().extrair_comprovantes(caminho)
        reparar_capas(registros)
        try:
            anexar_recibos_ocr_em_grupos_duplicados(registros, caminho)
        except Exception as exc:  # nunca derruba a extracao por causa do OCR
            print(f"[AVISO] OCR dos recibos de grupos repetidos falhou: {exc}")
        return registros
