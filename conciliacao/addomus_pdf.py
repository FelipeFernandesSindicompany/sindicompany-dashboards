"""
Conciliador Addomus PDF — extrai RegistroComprovante[] da mesma "Pasta de
Prestação de Contas" que adapters/addomus_pdf.py já lê para o demonstrativo
consolidado (é o MESMO arquivo PDF — só uma leitura mais granular, página a
página, em vez de somar tudo em DadosFinanceiros).

⚠️ ATENÇÃO — regexes derivados apenas das 22 páginas do PDF-modelo (Spazio
Jardins da Orla, Ago/2026) fornecido pelo usuário, sem acesso à pasta
completa de 365 páginas. Isso É uma primeira versão para validação, não uma
implementação testada contra dados reais. Antes de usar em produção, rodar
`extrair_comprovantes()` contra o PDF real e comparar contagem de páginas
classificadas / campos extraídos, ajustando os padrões abaixo (ver risco #1
e #2 do plano em C:\\Users\\MF PRINTER\\.claude\\plans\\humming-swimming-hellman.md).

Layouts observados no PDF-modelo, um por página (ou par de páginas
consecutivas — 1 "capa" de despesa + 1 comprovante de pagamento):

  1. Cabeçalho recorrente "Comprovantes de Despesas" / "Despesa" com os
     campos Código / Descrição / Fornecedor / Conta / Competência / Parcela /
     Pagamento / Forma / Doc.NF / Valor / Pago — presente na maioria das
     páginas de comprovante bancário, é a fonte primária e mais confiável de
     código/fornecedor/valor para o matching, independente do tipo de prova
     que vem depois.
  2. Tela interna "Despesa" (Código/Conta/Razão Social/Nome Fantasia/
     Descrição/Parcela/Forma Pgto/Emissão/Vencimento/Competência/Doc.NF +
     tabela "Composição da Despesa" + tabela "Liquidação") — mesmo layout que
     adapters/addomus_pdf.py já usa para somar categorias.
  3. Comprovante bancário Itaú: transferência PIX, DARF, boleto, débito
     automático — corpo variável, mas o cabeçalho do item 1 já basta para
     o matching; o tipo é só para classificação/exibição no relatório.
  4. Listagem de despesas (uma página, várias linhas — usada para achados
     tipo "achado positivo"/consolidação, ex.: DARF que soma N guias).
  5. E-mail (print de thread Outlook) — evidência de autorização/pedido.
  6. Relatório fiscal (ex.: EFD-Reinf da Receita Federal) — evidência de
     fechamento de retenções.

Páginas que não casam nenhum padrão viram tipo_documento="outro", mas o
texto_bruto é sempre preservado — nada é descartado silenciosamente.
"""
import re
from pathlib import Path

from conciliacao.base import ConciliadorBase, RegistroComprovante

# Reaproveita a mesma regra de categorização (código 2.X -> nome canônico) já
# validada em adapters/addomus_pdf.py — não duplica o mapa de categorias.
from adapters.addomus_pdf import _CATEGORIAS_NIVEL2, _RE_COMPOSICAO


def _num(s) -> float:
    """Converte string numérica brasileira (1.234,56) para float. Mesma lógica de adapters/addomus_pdf.py."""
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


_RE_PAGINA_ORIGINAL = re.compile(r"P[áa]g\.?\s*(\d+)\s*de\s*(\d+)", re.IGNORECASE)

# Cabeçalho recorrente "Comprovantes de Despesas" — campos soltos, buscados
# independentemente (não assume ordem fixa, pdfplumber pode reordenar colunas).
_RE_CAMPO = {
    "codigo": re.compile(r"C[óo]digo\s*:?\s*(\d+)", re.IGNORECASE),
    "descricao": re.compile(r"Descri[çc][ãa]o\s*:?\s*(.+?)(?:\n|Fornecedor|Conta\s*:|Parcela|$)", re.IGNORECASE),
    "fornecedor": re.compile(r"Fornecedor(?:/Favorecido)?\s*:?\s*(.+?)(?:\n|Conta\s*:|Compet[êe]ncia|Parcela|$)", re.IGNORECASE),
    "conta": re.compile(r"\bConta\s*:\s*(.+?)(?:\n|Compet[êe]ncia|Parcela|$)", re.IGNORECASE),
    "competencia": re.compile(r"Compet[êe]ncia\s*:?\s*(\d{2}/\d{4})", re.IGNORECASE),
    "vencimento": re.compile(r"Vencimento\s*:?\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE),
    "pagamento": re.compile(r"Pagamento\s*:?\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE),
    # "Doc/NF", "Doc.NF" ou "DocNF" — a pasta real usa barra, não ponto, entre "Doc" e "NF".
    "forma": re.compile(r"Forma(?:\s*Pgto)?\s*:?\s*([A-Za-zÀ-ÿ\-\s]+?)(?:\n|Doc\.?/?\s*NF|$)", re.IGNORECASE),
    "docnf": re.compile(r"Doc\.?/?\s*NF\s*:?\s*(\S*)", re.IGNORECASE),
    "valor": re.compile(r"\bValor\s*:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
    "pago": re.compile(r"\bPago\s*:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
    # Só existe na tela interna "Despesa" (tabela "Composição da Despesa"), onde
    # "Valor" é cabeçalho de coluna (não campo rotulado) — TOTAL: é a fonte confiável.
    "total_composicao": re.compile(r"\bTOTAL\s*:?\s*([\d.]+,\d{2})", re.IGNORECASE),
    "razao_social": re.compile(r"Raz[ãa]o\s*Social\s*:?\s*(.+?)(?:\n|Nome\s*Fantasia|$)", re.IGNORECASE),
    "autenticacao": re.compile(r"Autentica[çc][ãa]o(?:\s*no\s*comprovante)?\s*:?\s*(\S+)", re.IGNORECASE),
    "cnpj_cpf": re.compile(r"CPF\s*(?:/|\s*ou\s*)?\s*CNPJ\s*:?\s*([\d./\-]+)", re.IGNORECASE),
}

_MARCADORES_TIPO = [
    # (tipo_documento, padrão de detecção — primeiro que casar vence)
    ("pix", re.compile(r"Comprovante\s+de\s+Transfer[êe]ncia|PIX\s*-\s*pagamento\s+instant[âa]neo", re.IGNORECASE)),
    ("darf", re.compile(r"Comprovante\s+de\s+pagamento\s*-?\s*DARF|c[óo]digo\s+de\s+barras", re.IGNORECASE)),
    ("boleto", re.compile(r"Comprovante\s+de\s+pagamento\s+de\s+boleto|Dados\s+da\s+conta\s+debitada\s*/\s*Pagador", re.IGNORECASE)),
    ("debito_automatico", re.compile(r"D[ée]bito\s+Autom[áa]tico", re.IGNORECASE)),
    ("relatorio_fiscal", re.compile(r"EFD-?Reinf|Relat[óo]rio\s+de\s+Fechamento", re.IGNORECASE)),
    ("email", re.compile(r"^\s*De\s*:.+Enviado\s*:.+Para\s*:", re.IGNORECASE | re.DOTALL | re.MULTILINE)),
    ("despesa_interna", re.compile(r"Composi[çc][ãa]o\s+da\s+Despesa", re.IGNORECASE)),
    ("listagem_despesas", re.compile(r"\bDespesas\b[\s\S]{0,80}Per[íi]odo\s*:", re.IGNORECASE)),
    # Página "capa" do comprovante (cabeçalho "Comprovantes de Despesas" com
    # Código/Fornecedor/Valor/Pago já rotulados) que antecede a nota fiscal ou
    # o comprovante bancário propriamente dito — fallback de baixa prioridade,
    # só quando nenhum marcador mais específico casou.
    ("capa_comprovante", re.compile(r"Comprovantes\s+de\s+Despesas[\s\S]{0,300}C[óo]digo\s*:", re.IGNORECASE)),
]

_MIN_CHARS_TEXTO = 20  # abaixo disso, considera página sem texto extraível (provável imagem/scan)


def _classificar_tipo(texto: str) -> str:
    for tipo, padrao in _MARCADORES_TIPO:
        if padrao.search(texto):
            return tipo
    return "outro"


def _extrair_campo(texto: str, nome: str) -> str | None:
    m = _RE_CAMPO[nome].search(texto)
    return m.group(1).strip() if m else None


def _extrair_pagina_original(texto: str) -> str | None:
    m = _RE_PAGINA_ORIGINAL.search(texto)
    return f"{m.group(1)} de {m.group(2)}" if m else None


# Tabela "Retenções de Impostos" (só na tela interna "Despesa"):
#   Imposto Cód. Despesa Vencimento Valor
#   INSS    1221         20/07/2026 3.633,96
_RE_RETENCAO_LINHA = re.compile(
    r"^([A-Za-zÀ-ÿ/]+)\s+(\d+)\s+(\d{2}/\d{2}/\d{4})\s+(-?[\d.]+,\d{2})\s*$",
    re.MULTILINE,
)


def _extrair_retencoes_vinculadas(texto: str) -> list:
    inicio = re.search(r"Reten[çc][õo]es\s+de\s+Impostos", texto, re.IGNORECASE)
    if not inicio:
        return []
    bloco = texto[inicio.end():]
    return [
        {
            "imposto": m.group(1),
            "codigo_despesa": m.group(2),
            "vencimento": m.group(3),
            "valor": _num(m.group(4)),
        }
        for m in _RE_RETENCAO_LINHA.finditer(bloco)
    ]


# Quadro do EFD-Reinf: "Natureza do Rendimento | Código de Receita | Valor Retido | Valor Suspenso"
#   15043 595207 948,01 -
_RE_LINHA_DETALHAMENTO_FISCAL = re.compile(
    r"^\d{4,6}\s+\d{4,6}\s+(-?[\d.]+,\d{2})\s+", re.MULTILINE,
)


def _extrair_valores_detalhamento_fiscal(texto: str) -> list:
    return [_num(m.group(1)) for m in _RE_LINHA_DETALHAMENTO_FISCAL.finditer(texto)]


def _montar_registro(pagina: int, texto: str) -> RegistroComprovante:
    if not texto or len(texto.strip()) < _MIN_CHARS_TEXTO:
        return RegistroComprovante(
            pagina=pagina,
            tipo_documento="nao_extraivel_texto",
            texto_bruto=texto or "",
        )

    tipo = _classificar_tipo(texto)

    fornecedor = _extrair_campo(texto, "fornecedor") or _extrair_campo(texto, "razao_social")
    if tipo == "despesa_interna":
        # Na tela interna "Despesa", "Valor" é cabeçalho de coluna da tabela
        # "Composição da Despesa" (não campo rotulado) — TOTAL: é a fonte
        # confiável do valor total da despesa.
        valor = _num(_extrair_campo(texto, "total_composicao"))
    else:
        valor = _num(_extrair_campo(texto, "pago") or _extrair_campo(texto, "valor"))

    categoria = None
    if tipo == "despesa_interna":
        # Reaproveita _RE_COMPOSICAO de adapters/addomus_pdf.py: pega a primeira
        # linha "Composição da Despesa" da página (só Fundo Ordinário conta
        # para o demonstrativo, mesma regra do adapter existente).
        m_comp = _RE_COMPOSICAO.search(texto)
        if m_comp:
            cod_categoria, _cod_fundo, nome_fundo, _rat, _valor = m_comp.groups()
            if "Fundo Ordinário" in nome_fundo or _cod_fundo == "3.1":
                partes = cod_categoria.split(".")
                categoria = _CATEGORIAS_NIVEL2.get(f"{partes[0]}.{partes[1]}")

    return RegistroComprovante(
        pagina=pagina,
        tipo_documento=tipo,
        codigo=_extrair_campo(texto, "codigo"),
        descricao=_extrair_campo(texto, "descricao"),
        fornecedor=fornecedor,
        cnpj_cpf=_extrair_campo(texto, "cnpj_cpf"),
        conta=_extrair_campo(texto, "conta"),
        competencia=_extrair_campo(texto, "competencia"),
        vencimento=_extrair_campo(texto, "vencimento"),
        pagamento=_extrair_campo(texto, "pagamento"),
        valor=valor,
        forma_pagamento=_extrair_campo(texto, "forma"),
        autenticacao=_extrair_campo(texto, "autenticacao"),
        pagina_original_texto=_extrair_pagina_original(texto),
        categoria_demonstrativo=categoria,
        retencoes_vinculadas=_extrair_retencoes_vinculadas(texto) if tipo == "despesa_interna" else [],
        valores_detalhamento_fiscal=_extrair_valores_detalhamento_fiscal(texto) if tipo == "relatorio_fiscal" else [],
        texto_bruto=texto,
    )


class ConciliadorAddomusPDF(ConciliadorBase):
    """Extrai comprovantes individuais da Pasta de Prestação de Contas (Addomus)."""

    def extrair_comprovantes(self, caminho: Path) -> list:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        registros: list[RegistroComprovante] = []
        with pdfplumber.open(str(caminho)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""
                registros.append(_montar_registro(i, texto))
                # Libera cache de layout da página — evita acúmulo de memória em PDFs grandes.
                page.flush_cache()
        return registros
