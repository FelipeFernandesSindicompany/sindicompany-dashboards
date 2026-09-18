"""
Conciliador "Balancete Mensal" — Giardino D'Itália, Vita Parque (iello_pdf) e
Jaú 1894 (lello_pdf).

Diferente de TODOS os outros conciliadores: o "Balancete Mensal" desses
administradoras é só 2-3 páginas de TOTAIS AGREGADOS por categoria — não
existe nenhum lançamento individual (sem data, sem fornecedor, sem NF) nem
comprovante escaneado em lugar nenhum do arquivo. Não há como fazer
conciliação comprovante-a-comprovante nem verificar duplicidade de
lançamento, porque simplesmente não existe o lançamento no arquivo.

O que É verificável de forma 100% determinística (sem inventar dado
nenhum) é a CONSISTÊNCIA ARITMÉTICA INTERNA do próprio balancete — duas
checagens:
  1. Cada seção "COMPOSIÇÃO/RECEBIMENTO/DESPESAS DE..." lista itens que
     devem somar exatamente a linha "TOTAL" que fecha a seção.
  2. Cada conta em "RESUMO FINANCEIRO" (Saldo Anterior, Créditos, Débitos,
     Saldo Final) deve fechar: saldo_anterior + créditos + débitos ==
     saldo_final (débitos já vêm negativos no próprio arquivo).

Isso não é evidência de comprovante, mas é uma auditoria real: se o
gerador do balancete arredondar errado ou uma categoria for lançada na
conta errada, a soma não fecha e o achado aparece. Reaproveita
gerar_achados_balancete_mensal() (ver conciliacao/matching.py) — tipos de
registro sintéticos "secao_soma_calculada"/"secao_total_declarado" e
"conta_saldo_calculado"/"conta_saldo_declarado", nunca "despesa_listada"
(não existe lançamento pra listar).
"""
from pathlib import Path
import re
import unicodedata

from conciliacao.base import ConciliadorBase, RegistroComprovante

# Seções cujos itens simplesmente somam pra uma linha "TOTAL <valor>" —
# confirmado em dados reais (Giardino D'Itália, Vita Parque, Jaú 1894).
# "RESUMO DE ACORDOS" e "RESUMO DE INADIMPLÊNCIA" ficam de fora: não fecham
# com um "TOTAL" simples (ex.: "TOTAL GERAL DE DEVEDORES").
_SECOES_SOMA = {
    "COMPOSICAO DE ARRECADACAO",
    "COMPOSICAO RECEITAS ORDINARIAS",
    "COMPOSICAO DESPESAS ORDINARIA",
    "RECEBIMENTO DE CONTAS EXTRAORDINARIAS",
    "DESPESAS DE CONTAS EXTRAORDINARIAS",
}

_RE_ITEM = re.compile(r'^(.+?)\s+(-?[\d.]+,\d{2})\s*$')
_RE_TOTAL_SECAO = re.compile(r'^TOTAL\s+(-?[\d.]+,\d{2})\s*$', re.IGNORECASE)
_RE_RESUMO_FINANCEIRO_HDR = re.compile(r'^DESCRI[CÇ][AÃ]O\s+SALDO\s+ANT', re.IGNORECASE)
_RE_LINHA_CONTA = re.compile(
    r'^(.+?)\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})\s*$'
)


def _normalize(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.strip().upper())


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = str(s).strip()
    negativo = s.startswith("-")
    s = re.sub(r"[^\d,.]", "", s)
    s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except Exception:
        return 0.0
    return -v if negativo else v


class ConciliadorBalanceteMensal(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import pdfplumber

        registros: list[RegistroComprovante] = []
        indice = 0

        secao_atual: str | None = None
        secao_pagina: int = 1
        itens_secao: list[float] = []
        total_declarado_pendente: float | None = None
        dentro_resumo_financeiro = False

        def _fechar_secao_pendente():
            nonlocal secao_atual, itens_secao, total_declarado_pendente, indice
            if secao_atual is None or total_declarado_pendente is None:
                secao_atual = None
                itens_secao = []
                total_declarado_pendente = None
                return
            indice += 1
            chave_secao = f"secao-{indice}"
            registros.append(RegistroComprovante(
                pagina=secao_pagina, codigo=chave_secao,
                tipo_documento="secao_soma_calculada",
                descricao=secao_atual, valor=sum(itens_secao),
                texto_bruto=f"{secao_atual}: soma de {len(itens_secao)} itens",
            ))
            registros.append(RegistroComprovante(
                pagina=secao_pagina, codigo=chave_secao + "-total",
                tipo_documento="secao_total_declarado",
                descricao=secao_atual, valor=total_declarado_pendente,
                texto_bruto=f"TOTAL {total_declarado_pendente}",
            ))
            secao_atual = None
            itens_secao = []
            total_declarado_pendente = None

        with pdfplumber.open(str(caminho)) as pdf:
            for pagina_num, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""
                page.flush_cache()

                for linha in texto.split("\n"):
                    l = linha.strip()
                    if not l:
                        continue
                    l_norm = _normalize(l)

                    if l_norm in _SECOES_SOMA:
                        # O cabeçalho da seção se repete no topo da página de
                        # continuação (mesma convenção do "RESUMO FINANCEIRO")
                        # MESMO depois do "TOTAL" já ter aparecido (quando ainda
                        # há itens da mesma seção espalhados por coluna fora de
                        # ordem) — só reinicia a soma se for uma seção
                        # REALMENTE diferente da que está pendente.
                        if secao_atual is None or _normalize(secao_atual) != l_norm:
                            _fechar_secao_pendente()
                            secao_atual = l
                            secao_pagina = pagina_num
                            itens_secao = []
                        dentro_resumo_financeiro = False
                        continue

                    if l_norm.startswith("RESUMO"):
                        # "RESUMO DE ACORDOS"/"RESUMO DE INADIMPLÊNCIA"/"RESUMO
                        # FINANCEIRO" sempre fecham qualquer seção-soma pendente
                        # (mesmo com itens "atrasados" de coluna fora de ordem
                        # ainda por vir depois do "TOTAL" — ver _RE_TOTAL_SECAO).
                        _fechar_secao_pendente()
                        dentro_resumo_financeiro = l_norm.startswith("RESUMO FINANCEIRO")
                        continue

                    if secao_atual:
                        m_total = _RE_TOTAL_SECAO.match(l)
                        if m_total and total_declarado_pendente is None:
                            # Não fecha ainda — o PDF às vezes intercala mais
                            # itens da MESMA seção depois do "TOTAL" (coluna
                            # fora de ordem na extração); só fecha de fato no
                            # próximo cabeçalho reconhecido (_SECOES_SOMA ou
                            # "RESUMO...").
                            total_declarado_pendente = _num(m_total.group(1))
                            continue
                        m_item = _RE_ITEM.match(l)
                        if m_item:
                            itens_secao.append(_num(m_item.group(2)))
                        continue

                    if dentro_resumo_financeiro:
                        if _RE_RESUMO_FINANCEIRO_HDR.match(l):
                            continue  # cabeçalho da tabela (repete a cada página)
                        m_conta = _RE_LINHA_CONTA.match(l)
                        if m_conta:
                            nome, saldo_ant, creditos, debitos, saldo_final = m_conta.groups()
                            indice += 1
                            chave_conta = f"conta-{indice}"
                            calculado = _num(saldo_ant) + _num(creditos) + _num(debitos)
                            registros.append(RegistroComprovante(
                                pagina=pagina_num, codigo=chave_conta,
                                tipo_documento="conta_saldo_calculado",
                                descricao=nome.strip(), valor=calculado,
                                texto_bruto=l,
                            ))
                            registros.append(RegistroComprovante(
                                pagina=pagina_num, codigo=chave_conta + "-total",
                                tipo_documento="conta_saldo_declarado",
                                descricao=nome.strip(), valor=_num(saldo_final),
                                texto_bruto=l,
                            ))

        _fechar_secao_pendente()
        return registros
