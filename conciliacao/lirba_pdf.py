"""
Conciliador Lirba PDF (formato "posicao_financeira"/ContasData) — extrai
RegistroComprovante[] da "Pasta de Prestação de Contas" gerada pelo sistema
Lirba (marca "ContasData" nos rodapés).

⚠️ Formato bem diferente do Addomus (ver conciliacao/addomus_pdf.py):

  1. "Demonstrativo de Despesas" — não é uma tela por lançamento, é uma
     LISTAGEM (várias linhas por página), uma linha por código, agrupada em
     categorias fechadas por uma linha "TOTAL DA CONTA <categoria> <valor>
     <pct>%". Cada linha termina em "<valor> <código de 4 dígitos>"
     (às vezes com um "<total> <pct>%" extra quando fecha um mini-grupo de
     mesma subcategoria — pegamos sempre o PRIMEIRO valor da linha, que é o
     valor individual do lançamento, nunca o total agregado).

  2. "Comprovante de Despesa <código>" — página(s) de EVIDÊNCIA para aquele
     código, mas SEM NENHUM TEXTO ÚTIL (só cabeçalho/rodapé do sistema) — o
     comprovante em si é uma IMAGEM digitalizada embutida na página. Por
     isso aqui não dá pra extrair código/fornecedor/valor da página de
     evidência como no Addomus — o valor e a categoria vêm só da listagem
     (item 1), e a página de comprovante só serve como referência de
     evidência (para o recorte vetorial do relatório).

Conclusão prática: o matching aqui é mais simples que o do Addomus — não há
"pareamento por valor" a fazer (não existe segundo texto pra comparar), só
"este código da listagem tem alguma página de Comprovante de Despesa
correspondente, ou não" (ver conciliacao/matching.py::gerar_achados_lirba).
"""
import re
from pathlib import Path

from conciliacao.base import ConciliadorBase, RegistroComprovante


def _num(s) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


_RE_HEADER_LISTAGEM = re.compile(r"Data\s+Hist[oó]rico\s+Valor\s+Total")
_RE_COMPROVANTE = re.compile(r"Comprovante\s+de\s+Despesa\s+(\d+)")
_RE_TOTAL_LINHA = re.compile(r"^TOTAL\s+DA\s+CONTA\s+(.+?)\s+[\d.]+,\d{2}(?:\s+[\d,]+%)?\s*$")
# Linha de item: valor individual (obrigatório) + opcionalmente total+pct do
# mini-grupo (quando a linha fecha uma subcategoria) + código de 4 dígitos no fim.
_RE_ITEM_LINHA = re.compile(
    r"([\d.]+,\d{2})\s+(?:[\d.]+,\d{2}\s+[\d,]+%\s+)?(\d{4})\s*$"
)
_RE_DATA_INICIO = re.compile(r"^(\d{2}/\d{2}/\d{4})")


class ConciliadorLirbaPDF(ConciliadorBase):
    """Extrai despesas listadas (Demonstrativo de Despesas) e páginas de
    evidência (Comprovante de Despesa) da pasta Lirba/ContasData."""

    def extrair_comprovantes(self, caminho: Path) -> list:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        cat_map = self.parser_config.get("cat_map", {})
        registros: list[RegistroComprovante] = []
        pendentes: list[RegistroComprovante] = []  # aguardando a linha "TOTAL DA CONTA X"
        primeira_pagina_comprovante: dict[str, int] = {}

        with pdfplumber.open(str(caminho)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""
                page.flush_cache()
                # "ContasData" é a marca-d'água do sistema (rodapé) e às vezes cola
                # na mesma linha de uma despesa (ex.: "... 0,40% 0034 ContasData"),
                # empurrando o código pra fora do fim de linha que o regex espera.
                texto = texto.replace("ContasData", " ")

                m_comp = _RE_COMPROVANTE.search(texto)
                if m_comp:
                    codigo = m_comp.group(1).zfill(4)
                    if codigo not in primeira_pagina_comprovante:
                        primeira_pagina_comprovante[codigo] = i
                    continue  # página de evidência não tem linhas de despesa

                if not _RE_HEADER_LISTAGEM.search(texto):
                    continue  # não é página de listagem nem de comprovante — ignora

                for linha in texto.split("\n"):
                    m_total = _RE_TOTAL_LINHA.match(linha.strip())
                    if m_total:
                        categoria_raw = m_total.group(1).strip()
                        categoria = cat_map.get(categoria_raw, categoria_raw)
                        for r in pendentes:
                            r.categoria_demonstrativo = categoria
                        registros.extend(pendentes)
                        pendentes = []
                        continue

                    m_item = _RE_ITEM_LINHA.search(linha)
                    if not m_item:
                        continue
                    valor_str, codigo = m_item.groups()
                    m_data = _RE_DATA_INICIO.match(linha.strip())
                    pendentes.append(RegistroComprovante(
                        pagina=i,
                        tipo_documento="despesa_listada",
                        codigo=codigo.zfill(4),
                        descricao=linha.strip()[:200],
                        vencimento=m_data.group(1) if m_data else None,
                        valor=_num(valor_str),
                        texto_bruto=linha,
                    ))

        # Sobras sem "TOTAL DA CONTA" explícito até o fim do documento
        # (não deveria acontecer no formato normal, mas não descarta dados).
        registros.extend(pendentes)

        for codigo, pagina in primeira_pagina_comprovante.items():
            registros.append(RegistroComprovante(
                pagina=pagina,
                tipo_documento="comprovante_anexado",
                codigo=codigo,
                texto_bruto=f"Comprovante de Despesa {codigo}",
            ))

        return registros
