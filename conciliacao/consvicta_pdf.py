"""
Conciliador Consvicta PDF — Gardens Living Club I.

Mesmo sistema GCONT do Club Park Butantã (ver conciliacao/condominios/
club_park_butanta.py — "Comprovantes de despesas / Parcela X"), mas nesse
condomínio as páginas de comprovante NÃO têm nenhuma capa com texto (só
cabeçalho/rodapé, confirmado em 100% das páginas de jul/2026) — é imagem
escaneada pura, como no Lirba. Pior: o código "Parcela" dessas páginas não
aparece em nenhum outro lugar do PDF (nem no "Demonstrativo de Despesas
Analítico" nem no "Caixa"), então não existe vínculo textual possível entre
uma despesa listada e sua página de comprovante.

Por isso este conciliador não faz checagem de "comprovante presente/
ausente" (não há como parear) — extrai só o "Demonstrativo de Receitas e
Despesas Analítico" (seção "Despesas", cabeçalho "Despesas Liquidação
Documento Valor") e reaproveita as MESMAS regras do DataDigitus
(gerar_achados_datadigitus: duplicidade por data+valor+categoria+histórico
e soma extraída x "Total de Despesas" declarado), tratando o condomínio
inteiro como uma "conta" única (não há múltiplas contas bancárias como no
DataDigitus).

Estrutura da seção (por categoria/sub-categoria, aninhamento livre):
  "<CATEGORIA> (X,XX%)"          → abre categoria (só isso fecha com % entre parênteses)
  "<Subcategoria>"               → rótulo livre (sem números), ignorado
  "<Fornecedor> - <competência MM/YYYY> <liquidação DD/MM/YYYY> [<documento>] <pct>% <valor>"
                                  → um lançamento (documento tipo NF-/Fatura-/Recibo- é opcional)
  "Total de <nome> <pct>% <valor>" → fecha subcategoria/categoria (não é lançamento)
  "Total de Despesas 100,00% <valor>" → fecha a seção inteira (total geral)
"""
from pathlib import Path
import re

from conciliacao.base import ConciliadorBase, RegistroComprovante

_RE_CATEGORIA = re.compile(r'^(.+?)\s+\(-?[\d.]+,\d{2}%\)\s*$')
_RE_TOTAL_DESPESAS = re.compile(r'^Total de Despesas\s+[\d.]+,\d{2}%\s+\(?-?([\d.]+,\d{2})\)?\s*$', re.IGNORECASE)
_RE_TOTAL_SUBGRUPO = re.compile(r'^Total de\s+.+?\s+\(?-?[\d.]+,\d{2}%\)?\s+\(?-?[\d.]+,\d{2}\)?\s*$', re.IGNORECASE)
_RE_LANCAMENTO = re.compile(
    r'^(.*?)\s+(\d{2}/\d{2}/\d{4})\s+(?:(\S+-\S+|\d+)\s+)?'
    r'\(?-?[\d.]+,\d{2}%\)?\s+\(?-?([\d.]+,\d{2})\)?\s*$'
)


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


class ConciliadorConsvictaPDF(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import pdfplumber

        registros: list[RegistroComprovante] = []
        dentro_despesas = False
        categoria_atual: str | None = None

        with pdfplumber.open(str(caminho)) as pdf:
            for pagina_num, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""
                page.flush_cache()
                indice_pagina = 0

                for linha in texto.split("\n"):
                    l = linha.strip()
                    if not l:
                        continue

                    if not dentro_despesas:
                        if re.match(r'^Despesas\s+Liquida', l, re.IGNORECASE):
                            dentro_despesas = True
                        continue

                    m_total_geral = _RE_TOTAL_DESPESAS.match(l)
                    if m_total_geral:
                        indice_pagina += 1
                        registros.append(RegistroComprovante(
                            pagina=pagina_num,
                            codigo=str(indice_pagina),
                            tipo_documento="total_conta_declarado",
                            conta="TOTAL",
                            descricao="TOTAL",
                            valor=_num(m_total_geral.group(1)),
                            texto_bruto=l,
                        ))
                        dentro_despesas = False
                        continue

                    if _RE_TOTAL_SUBGRUPO.match(l):
                        continue  # fecha subcategoria — não é lançamento

                    m_cat = _RE_CATEGORIA.match(l)
                    if m_cat:
                        categoria_atual = m_cat.group(1).strip()
                        continue

                    m_lanc = _RE_LANCAMENTO.match(l)
                    if m_lanc and categoria_atual:
                        fornecedor, liquidacao, documento, valor_str = m_lanc.groups()
                        indice_pagina += 1
                        registros.append(RegistroComprovante(
                            pagina=pagina_num,
                            # Índice sequencial na página — só pra manter
                            # chave_registro() única quando várias despesas
                            # caem na mesma página física (ver conciliacao/base.py).
                            codigo=str(indice_pagina),
                            tipo_documento="despesa_listada",
                            descricao=fornecedor.strip()[:200] or None,
                            vencimento=liquidacao,
                            valor=_num(valor_str),
                            categoria_demonstrativo=categoria_atual,
                            conta="TOTAL",
                            # Reaproveita "autenticacao" pra guardar o nº de
                            # documento/NF (não confundir com o "Parcela" das
                            # páginas de comprovante — não há vínculo entre os dois).
                            autenticacao=documento,
                            texto_bruto=l,
                        ))
                        continue
                    # Linhas sem match (rótulo de subcategoria sem número,
                    # continuação de fornecedor/competência quebrada em 2
                    # linhas) são ignoradas — o lançamento correspondente
                    # ainda é capturado pela linha com data+valor.

        return registros
