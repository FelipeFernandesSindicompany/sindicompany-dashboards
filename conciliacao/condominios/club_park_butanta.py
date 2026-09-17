"""
Conciliador específico — Club Park Butantã (administradora GCONT, PDF
"Comprovantes de despesas").

Formato totalmente diferente do resto da família ContasData/Lirba (mesmo
sendo cadastrado como empresa_gestora="lirba_pdf" em condominios.json, por
não ter parser_config.extract_cats definido). Confirmado em dados reais
(jul/2026, 1184 páginas):

  - Cada pagamento do mês já vem com sua PRÓPRIA página de "Comprovantes de
    despesas" (marcada "Parcela <código>"), com todos os dados relevantes
    em texto extraível — não é preciso cruzar com uma listagem separada
    como em Addomus/Lirba/Habitacional. Layout da página:
        Credt. em Jul/2026;Parcela <código>
        Valor: <valor> ( <valor por extenso> )
        Conta: <banco>
        Pago a: Vencimento Liquidação Documento Valor
        <FORNECEDOR> <venc> <liquidação> [<documento>] <valor>
        Destina-se a: Complemento
        <código_categoria> <NOME CATEGORIA> [<complemento>] <valor>
        Valor Emitido: <valor>
    Quando o comprovante tem mais de 1 página (ex.: "(1 de 2)" no nome do
    fornecedor), só a 1ª é a "capa" com texto — as demais são a imagem
    escaneada em si, sem texto útil (mesma limitação do Lirba).

  - Antes dos comprovantes, um "Livro Caixa"/ledger lista TODOS os
    pagamentos do mês (data, fornecedor, valor) e fecha com uma linha
    "N itens VALOR_TOTAL" — confirmado que N e VALOR_TOTAL batem
    exatamente com a soma das N páginas de comprovante (160 itens /
    R$ 913.628,65 no piloto). Essa linha vira um registro
    "total_declarado" pra checagem de consistência (ver
    conciliacao/matching.py::gerar_achados_gcont).

Como cada comprovante já é auto-suficiente (não existe despesa "sem
comprovante" nesse formato — o sistema só gera a página quando o pagamento
é efetivado), a checagem aqui não é presença/ausência de evidência, e sim:
  1. Duplicidade: mesmo fornecedor + documento + valor repetidos (ou
     fornecedor + vencimento + valor, quando não há nº de documento).
  2. Soma dos comprovantes extraídos x total declarado no Livro Caixa.
"""
import re
from pathlib import Path

from conciliacao.base import ConciliadorBase, RegistroComprovante

_RE_VALOR_DECLARADO = re.compile(r'^Valor:\s*([\d.]+,\d{2})', re.MULTILINE)
_RE_PARCELA = re.compile(r'Parcela\s+(\d+)')
_RE_LINHA_FORNECEDOR = re.compile(
    r'^(.*?)\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(?:(\S+)\s+)?([\d.]+,\d{2})\s*$'
)
_RE_CATEGORIA = re.compile(r'^(\d+(?:\.\d+)+)\s+(.+?)\s+[\d.]+,\d{2}\s*$')
_RE_TOTAL_LEDGER = re.compile(r'(\d+)\s+itens?\s+([\d.]+,\d{2})')


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


class Conciliador(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import pdfplumber

        registros: list[RegistroComprovante] = []

        with pdfplumber.open(str(caminho)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""
                page.flush_cache()

                m_total = _RE_TOTAL_LEDGER.search(texto)
                if m_total and "Pago a:" not in texto:
                    # Linha de fechamento do Livro Caixa ("N itens VALOR") —
                    # só considera se não for coincidência dentro de uma
                    # página de comprovante (que também tem "Valor:").
                    registros.append(RegistroComprovante(
                        pagina=i,
                        tipo_documento="total_declarado",
                        valor=_num(m_total.group(2)),
                        descricao=f"{m_total.group(1)} itens (Livro Caixa)",
                        texto_bruto=texto,
                    ))
                    continue

                if "Pago a:" not in texto or "Parcela" not in texto:
                    continue  # página de continuação (imagem) ou outra seção

                m_parcela = _RE_PARCELA.search(texto)
                m_valor = _RE_VALOR_DECLARADO.search(texto)
                if not (m_parcela and m_valor):
                    continue

                fornecedor = venc = documento = None
                for linha in texto.split("\n"):
                    m = _RE_LINHA_FORNECEDOR.match(linha.strip())
                    if m:
                        fornecedor, venc, _liq, documento, _valor2 = m.groups()
                        fornecedor = fornecedor.strip()
                        break

                categoria = None
                for linha in texto.split("\n"):
                    m = _RE_CATEGORIA.match(linha.strip())
                    if m:
                        categoria = f"{m.group(1)} {m.group(2).strip()}"
                        break

                registros.append(RegistroComprovante(
                    pagina=i,
                    tipo_documento="despesa_com_comprovante",
                    codigo=m_parcela.group(1),
                    fornecedor=fornecedor,
                    vencimento=venc,
                    valor=_num(m_valor.group(1)),
                    categoria_demonstrativo=categoria,
                    # Reaproveita "autenticacao" (nº de referência impresso no
                    # comprovante) pra guardar o nº de Documento/NF — usado na
                    # chave de duplicidade em gerar_achados_gcont().
                    autenticacao=documento,
                    texto_bruto=texto,
                ))

        return registros
