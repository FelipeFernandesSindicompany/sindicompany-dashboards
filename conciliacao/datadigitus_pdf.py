"""
Conciliador DataDigitus PDF — Cap D'Antibes (e demais condomínios DataDigitus).

Diferente de Addomus/Lirba/Habitacional: o "Prestação de Contas" da
DataDigitus é só o balancete consolidado + demonstrativo de despesas listado
por conta/categoria — NÃO existe comprovante escaneado nem link anexado em
lugar nenhum do arquivo (confirmado em Cap D'Antibes, jul/2026: 8 páginas,
nenhuma delas é imagem de recibo ou tem hyperlink). Por isso este
conciliador não faz checagem de "comprovante presente/ausente" — não há
evidência externa pra cruzar. Só duas checagens de consistência aritmética
do próprio documento (ver conciliacao/matching.py::gerar_achados_datadigitus):
  1. Duplicidade: mesma data + valor + categoria repetidos.
  2. Divergência entre a soma dos lançamentos de uma conta e o "TOTAL DA
     CONTA X" declarado no mesmo documento.

Estrutura confirmada (ver docstring de adapters/datadigitus_pdf.py para mais
detalhes — este conciliador reaproveita _e_categoria()/_num() de lá):
  "Demonstrativo de Despesas" (marcador) até "TOTAL GERAL DAS DESPESAS":
    "NNN - CONTA NOME" abre uma conta (NNN = código de 3 dígitos)
    "CATEGORIA EM MAIÚSCULAS" abre uma categoria dentro da conta
    "DD/MM/AAAA histórico valor" = um lançamento
    "valor" isolado = subtotal da categoria (fecha a categoria)
    "TOTAL DA CONTA NOME  valor" fecha a conta
"""
from pathlib import Path
import re

from conciliacao.base import ConciliadorBase, RegistroComprovante
from adapters.datadigitus_pdf import _e_categoria, _num

# Nem toda conta começa com a palavra "CONTA" (ex.: "006 - PROV.13O
# SAL/FERIAS" em Maison Du Rhone) — exige só o prefixo "NNN - ", não a
# palavra específica depois.
_RE_CONTA_HDR = re.compile(r'^\d{3}\s*-\s*(.+)$')
_RE_TOTAL_CONTA = re.compile(r'^TOTAL DA CONTA\b(.*?)\s+([\d.]+,\d{2})(?:\s+[\d,]+%)?\s*$', re.IGNORECASE)
_RE_TOTAL_GERAL = re.compile(r'^TOTAL GERAL DAS DESPESAS\b', re.IGNORECASE)
_RE_LANCAMENTO = re.compile(r'^(\d{2}/\d{2}/\d{4})\s+(.*?)\s*([\d.]+,\d{2})$')
_RE_SUBTOTAL = re.compile(r'^[\d.]+,\d{2}$')


def _categoria_generica(linha: str) -> str | None:
    """
    Fallback quando a linha não bate com o _CAT_MAP do adapter — esse mapa
    só cobre as categorias confirmadas em Cap D'Antibes; outros condomínios
    DataDigitus (ex.: Maison Du Rhone: "FERIAS", "SERVICOS PRESTADOS") têm
    categorias próprias. Não altera adapters/datadigitus_pdf.py (usado pelo
    dashboard) — qualquer cabeçalho em CAIXA ALTA que não seja um marcador
    estrutural conhecido (conta/total/subtotal) também é aceito como
    categoria aqui, usando o próprio texto como nome (sem mapeamento
    canônico — só precisa ser consistente pra duplicidade, não "bonito").
    """
    if not linha or linha[0].isdigit():
        return None
    if _RE_CONTA_HDR.match(linha) or _RE_TOTAL_CONTA.match(linha) or _RE_TOTAL_GERAL.match(linha):
        return None
    letras = [c for c in linha if c.isalpha()]
    if not letras or any(c.islower() for c in letras):
        return None
    return linha


class ConciliadorDatadigitusPDF(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import pdfplumber
        with pdfplumber.open(str(caminho)) as pdf:
            textos = [p.extract_text() or "" for p in pdf.pages]

        registros: list[RegistroComprovante] = []
        dentro_demonstrativo = False
        nome_conta_atual: str | None = None
        cat_atual: str | None = None

        for pagina_num, texto_pagina in enumerate(textos, start=1):
            indice_pagina = 0
            for linha in texto_pagina.split("\n"):
                l = linha.strip()
                if not l:
                    continue

                if not dentro_demonstrativo:
                    if "Demonstrativo de Despesas" in l:
                        dentro_demonstrativo = True
                    continue

                if _RE_TOTAL_GERAL.match(l):
                    dentro_demonstrativo = False
                    break

                m_conta = _RE_CONTA_HDR.match(l)
                if m_conta:
                    nome_conta_atual = m_conta.group(1).strip()
                    cat_atual = None
                    continue

                m_total_conta = _RE_TOTAL_CONTA.match(l)
                if m_total_conta:
                    indice_pagina += 1
                    registros.append(RegistroComprovante(
                        pagina=pagina_num,
                        codigo=str(indice_pagina),
                        tipo_documento="total_conta_declarado",
                        descricao=nome_conta_atual,
                        valor=_num(m_total_conta.group(2)),
                        texto_bruto=l,
                    ))
                    cat_atual = None
                    continue

                nome_cat = _e_categoria(l) or _categoria_generica(l)
                if nome_cat:
                    cat_atual = nome_cat
                    continue

                m_lanc = _RE_LANCAMENTO.match(l)
                if m_lanc and cat_atual:
                    data, historico, valor_str = m_lanc.groups()
                    indice_pagina += 1
                    registros.append(RegistroComprovante(
                        pagina=pagina_num,
                        codigo=str(indice_pagina),
                        tipo_documento="despesa_listada",
                        descricao=historico.strip()[:200] or None,
                        vencimento=data,
                        valor=_num(valor_str),
                        categoria_demonstrativo=cat_atual,
                        conta=nome_conta_atual,
                        texto_bruto=l,
                    ))
                    continue

                if _RE_SUBTOTAL.match(l) and cat_atual:
                    # Subtotal da categoria — fecha a categoria corrente, não é lançamento.
                    cat_atual = None
                    continue

            if not dentro_demonstrativo and registros:
                break

        return registros
