"""
Conciliador webware (sub-formato Lirba/ContasData) — NYC Berrini.

Mais simples que os outros sub-formatos ContasData: aqui a página
"Comprovante de Despesa NNNN" já traz a própria linha "Data Histórico
Valor" (não existe uma "Demonstrativo de Despesas" com listagem separada
pra cruzar) — o despesa e o comprovante são a MESMA página. Quando o
comprovante tem mais de 1 página (rodapé "01/02", "02/02" etc.), os dados
se repetem — extrai só 1 despesa por código (usa a 1ª página do grupo).

Como despesa e comprovante são sempre a mesma coisa aqui, não existe "sem
comprovante" nesse formato. Não foi encontrado nenhum total geral de
despesas confiável no restante do arquivo (a "Posição Financeira" é por
conta e mistura receita/despesa) — checagem por ora é só duplicidade
(mesmo código repetido, mesmo valor), reaproveitando o mesmo princípio de
gerar_achados_lirba() mas sem a regra de comprovante ausente.
"""
from pathlib import Path
import re

from conciliacao.base import ConciliadorBase, RegistroComprovante

_RE_COMPROVANTE = re.compile(r'Comprovante\s+de\s+Despesa\s+(\d+)')
_RE_LINHA = re.compile(r'^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d.]+,\d{2})\s*$')


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


class ConciliadorWebwarePDF(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import pdfplumber

        registros: list[RegistroComprovante] = []
        vistos: set[str] = set()

        with pdfplumber.open(str(caminho)) as pdf:
            for pagina_num, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""
                page.flush_cache()

                m_comp = _RE_COMPROVANTE.search(texto)
                if not m_comp:
                    continue
                codigo = m_comp.group(1).zfill(4)
                if codigo in vistos:
                    continue  # já extraído a partir da 1ª página desse comprovante

                m_linha = None
                for linha in texto.split("\n"):
                    m_linha = _RE_LINHA.match(linha.strip())
                    if m_linha:
                        break
                if not m_linha:
                    continue

                vistos.add(codigo)
                data, historico, valor_str = m_linha.groups()
                registros.append(RegistroComprovante(
                    pagina=pagina_num,
                    codigo=codigo,
                    tipo_documento="despesa_listada",
                    descricao=historico.strip()[:200],
                    vencimento=data,
                    valor=_num(valor_str),
                    conta="TOTAL",
                    texto_bruto=texto,
                ))

        return registros
