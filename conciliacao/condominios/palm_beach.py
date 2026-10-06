"""
Conciliador específico — Palm Beach (administradora HABITAT/GROUP condomínios).

Cadastrado como empresa_gestora="lirba_pdf" em condominios.json, mas o PDF
real não é ContasData — é um relatório GROUP condomínios com a maior parte
do conteúdo renderizada como IMAGEM (confirmado em dados reais, jul/2026,
162 páginas). O conciliador genérico Lirba/ContasData dava 0 registros
porque depende de regex em texto real pra achar tanto a listagem de
despesas quanto as páginas de comprovante — nenhum dos dois existe nesse
formato do jeito que o Lirba espera.

Duas seções relevantes, tratadas de formas bem diferentes:

  1. "Despesas > Anexos" (confirmado jul/2026: páginas 22-81, sem entrada
     própria no sumário) — UMA página-capa por despesa (às vezes com mais
     páginas de continuação, mesmo rótulo repetido), com um cabeçalho em
     TEXTO REAL pesquisável: "Anexos - N° Doc: <número> - <fornecedor>"
     (às vezes sem o "N° Doc:", só "Anexos - <fornecedor>"). A imagem da
     página-capa mostra, também em formato limpo: "Número Fornecedor
     Classe de conta Valor (R$)" — ou seja, CADA anexo já reproduz a
     própria linha da despesa (fornecedor, categoria, valor), então não
     precisa ler a tabela de despesas em si (essa sim inteiramente imagem,
     inviável de OCR com confiança em ~70 páginas de tabela densa) — só a
     capa de cada anexo, uma vez por grupo de páginas consecutivas com o
     mesmo cabeçalho.

  2. "Outros documentos" (últimas páginas, também sem entrada no sumário —
     confirmado jul/2026: páginas 106-162, 57 páginas) — pasta heterogênea
     de documentos de apoio do mês INTEIRO, sem vínculo com uma despesa
     específica: extrato bancário (várias linhas, não um valor único),
     guias de tributos (DARF/FGTS/INSS/ISS — cada uma com layout próprio),
     certidões, comprovantes de transferência, PIX QR Code, recibo de
     entrega DCTFWeb, folha de pagamento de terceirizados (documento de
     apoio pro comprovante de transferência correspondente, não um
     lançamento próprio). Classificada por tipo — só confirma presença dos
     que não têm valor individual por natureza, e confirma o valor (com
     checagem de plausibilidade) dos que têm.

Ambas as seções e as páginas de "Despesas"/"Receitas"/"Movimento de conta"
compartilham o MESMO cabeçalho de página "CONDOMINIO EDIFICIO PALM BEACH" —
a distinção entre elas é feita pelo texto que vem logo depois: "Despesas\\n
Anexos - ..." pras capas de anexo, "Outros documentos" pro segundo grupo, e
qualquer outra coisa (inclusive o mesmo cabeçalho em ORDEM REVERSA de
caracteres nas páginas de tabela, ex.: "OINIMODNOC" em vez de
"CONDOMINIO" — artefato de renderização dessas páginas) é ignorada.

Algumas imagens vêm rotacionadas 90°/180°/270° DENTRO da página
(page.rotation do PyMuPDF continua 0 — é só a imagem embutida que está
girada), o que embaralhava o OCR completamente até a correção de
orientação automática em conciliacao/ocr.py::_angulo_correcao().
"""
import re
from pathlib import Path

from conciliacao import ocr
from conciliacao.base import ConciliadorBase, RegistroComprovante

_RE_ANEXO_DESPESA = re.compile(r"Despesas\s*\n\s*Anexos\s*-\s*(?:N.\s*Doc:?\s*(\d+)\s*-\s*)?(.+)")
_RE_OUTROS_DOCUMENTOS = re.compile(r"Outros documentos", re.IGNORECASE)

# Rótulos confirmados na página-capa de cada anexo (jul/2026): "Classe de
# conta" seguido do código+nome da categoria, "Valor (R$)" seguido do valor
# — às vezes colados, às vezes com a linha inteira ("Número Fornecedor
# Classe de conta Valor (R$)" seguido de "1052 Habitat ADM 2.10.1 -
# Honorários de Administração R$1.367,99") entre o rótulo e o valor de
# verdade — mesma leitura fora de ordem já vista em outros formatos, daí
# pegar o primeiro "R$ valor" DEPOIS da âncora, não colado a ela.
_RE_CLASSE_CONTA = re.compile(r"Classe de conta\s*\n*\s*(\d+(?:\.\d+)*\s*-\s*[^\n]+)", re.IGNORECASE)
_RE_ANCORA_VALOR_PARENTESES = re.compile(r"Valor\s*\(R\$\)", re.IGNORECASE)
_RE_VALOR_BRUTO = re.compile(r"([\d.]+,\d{2})")


def _valor_apos_valor_parenteses(texto: str):
    """
    Âncora "Valor (R$)" seguida do ÚLTIMO valor na primeira linha de dados
    não vazia depois dela — não o primeiro valor no resto do texto inteiro
    (bug já visto: em algumas páginas, um "R$" mais adiante no texto, ex.
    um subtotal de outra seção, batia antes do valor de verdade), nem
    necessariamente o primeiro valor da própria linha (confirmado em dados
    reais: uma guia DAMSP tem "CPF/CNPJ ... Valor (R$)" e a linha de dados é
    "55.402,879/0001-90 ... 847,18" — o CNPJ em si já bate um "X,XX" falso
    antes do valor de verdade, que é sempre o ÚLTIMO campo da linha).
    """
    m_ancora = _RE_ANCORA_VALOR_PARENTESES.search(texto)
    if not m_ancora:
        return None
    # Só considera as primeiras linhas não vazias depois da âncora (a
    # "capa" do anexo tem só algumas linhas de resumo antes da imagem do
    # documento anexado em si) — nunca deixa a busca vagar página adentro.
    # Confirmado em dados reais que isso é necessário: numa página onde a
    # capa não trouxe o valor, deixar a busca continuar indefinidamente
    # acabou pegando um valor de ITEM DE LINHA dentro do corpo da nota
    # fiscal anexada (ex.: R$ 102,96 de um dos 4 itens de uma nota de
    # R$ 648,65 no total) — um valor plausível, mas ERRADO. Melhor marcar
    # como não identificado do que confiar num valor sem essa garantia.
    linhas_nao_vazias = 0
    for linha in texto[m_ancora.end():].split("\n"):
        if not linha.strip():
            continue
        matches = list(_RE_VALOR_BRUTO.finditer(linha))
        if matches:
            return matches[-1]
        linhas_nao_vazias += 1
        if linhas_nao_vazias >= 3:
            break
    return None

# Tipos de documento (seção "Outros documentos") SEM valor de transação
# individual comparável — só confirma que existem (documento de apoio),
# nunca tenta extrair "o" valor deles (um extrato tem várias linhas de
# valor, uma certidão não tem valor nenhum, uma folha de pagamento é o
# detalhamento de UM pagamento que já tem seu próprio comprovante).
_RE_EXTRATO = re.compile(r"e[xs]trato\s+mens[ao]l", re.IGNORECASE)
_RE_FOPAG = re.compile(r"FOPAG|Folha de Pagamento", re.IGNORECASE)
_RE_CERTIDAO = re.compile(r"CERTID.O", re.IGNORECASE)
_RE_RECIBO_ENTREGA = re.compile(r"Recibo de Entrega", re.IGNORECASE)

# Valor da transação (seção "Outros documentos") — rótulos confirmados em
# dados reais (PIX QR Code, guias de tributos, transferências), tentados em
# ordem, o mais específico primeiro.
_RE_VALORES_OUTROS_DOCUMENTOS = [
    re.compile(r"valor do documento:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
    re.compile(r"valor da transa[cç][aã]o:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
    re.compile(r"valor final:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
    re.compile(r"valor total:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
    re.compile(r"^valor:?\s*R?\$?\s*([\d.]+,\d{2})\s*$", re.IGNORECASE | re.MULTILINE),
]
# Acima disso, é mais provável ser erro de leitura do OCR (dígito extra ou
# separador decimal trocado) do que uma despesa individual real de
# condomínio — confirmado em dados reais: um PIX leu "valor da transação:
# 4.843.850,73" (R$ 4,8 milhões), implausível pra uma folha de pagamento de
# terceirizados de um condomínio.
_VALOR_MAXIMO_PLAUSIVEL = 100_000.0


def _num(s) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


def _extrair_anexo_despesa(pagina: int, texto_real: str, caminho: Path) -> RegistroComprovante:
    """Página-capa de "Despesas > Anexos" — fornecedor/nº doc já vêm de
    texto real (grátis, sem OCR); valor e classe de conta pedem OCR da
    própria imagem da capa."""
    m = _RE_ANEXO_DESPESA.search(texto_real)
    doc_numero, fornecedor_cabecalho = m.groups()
    texto_ocr = ocr.ocr_pagina_pdf(caminho, pagina - 1)
    texto_base = texto_ocr or texto_real

    m_valor = _valor_apos_valor_parenteses(texto_base)
    valor = _num(m_valor.group(1)) if m_valor else 0.0
    m_classe = _RE_CLASSE_CONTA.search(texto_base)
    categoria = m_classe.group(1).strip() if m_classe else None

    return RegistroComprovante(
        pagina=pagina,
        tipo_documento="anexo_despesa_com_valor" if m_valor else "anexo_despesa_sem_valor_identificado",
        codigo=doc_numero,
        fornecedor=fornecedor_cabecalho.strip(),
        categoria_demonstrativo=categoria,
        valor=valor,
        texto_bruto=texto_base,
    )


def _classificar_outro_documento(pagina: int, texto: str) -> RegistroComprovante:
    if _RE_EXTRATO.search(texto):
        return RegistroComprovante(
            pagina=pagina, tipo_documento="documento_apoio_sem_valor",
            descricao="Extrato bancário", texto_bruto=texto,
        )
    if _RE_FOPAG.search(texto):
        return RegistroComprovante(
            pagina=pagina, tipo_documento="documento_apoio_sem_valor",
            descricao="Folha de pagamento (terceirizados)", texto_bruto=texto,
        )
    if _RE_CERTIDAO.search(texto):
        return RegistroComprovante(
            pagina=pagina, tipo_documento="documento_apoio_sem_valor",
            descricao="Certidão", texto_bruto=texto,
        )
    if _RE_RECIBO_ENTREGA.search(texto):
        return RegistroComprovante(
            pagina=pagina, tipo_documento="documento_apoio_sem_valor",
            descricao="Recibo de entrega (protocolo)", texto_bruto=texto,
        )

    # Guia de tributo tipo DAMSP (Prefeitura de São Paulo) — mesma coluna
    # "Valor (R$)" da capa de anexo de despesa, ver _valor_apos_valor_parenteses.
    m_valor_parenteses = _valor_apos_valor_parenteses(texto)
    if m_valor_parenteses:
        valor = _num(m_valor_parenteses.group(1))
        if valor > _VALOR_MAXIMO_PLAUSIVEL:
            return RegistroComprovante(
                pagina=pagina, tipo_documento="comprovante_valor_suspeito",
                valor=valor, texto_bruto=texto,
            )
        return RegistroComprovante(
            pagina=pagina, tipo_documento="comprovante_com_valor",
            valor=valor, texto_bruto=texto,
        )

    for regex in _RE_VALORES_OUTROS_DOCUMENTOS:
        m = regex.search(texto)
        if m:
            valor = _num(m.group(1))
            if valor > _VALOR_MAXIMO_PLAUSIVEL:
                return RegistroComprovante(
                    pagina=pagina, tipo_documento="comprovante_valor_suspeito",
                    valor=valor, texto_bruto=texto,
                )
            return RegistroComprovante(
                pagina=pagina, tipo_documento="comprovante_com_valor",
                valor=valor, texto_bruto=texto,
            )

    return RegistroComprovante(pagina=pagina, tipo_documento="comprovante_sem_valor_identificado", texto_bruto=texto)


class Conciliador(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import pdfplumber

        registros: list[RegistroComprovante] = []
        grupo_anexo_atual: tuple | None = None  # (doc_numero, fornecedor_cabecalho) do grupo em andamento

        with pdfplumber.open(str(caminho)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""

                m_anexo = _RE_ANEXO_DESPESA.search(texto)
                if m_anexo:
                    chave_grupo = m_anexo.groups()
                    if chave_grupo == grupo_anexo_atual:
                        continue  # página de continuação do mesmo anexo — já processada na primeira página do grupo
                    grupo_anexo_atual = chave_grupo
                    registros.append(_extrair_anexo_despesa(i, texto, caminho))
                    continue

                grupo_anexo_atual = None
                if _RE_OUTROS_DOCUMENTOS.search(texto):
                    texto_ocr = ocr.ocr_pagina_pdf(caminho, i - 1)
                    registros.append(_classificar_outro_documento(i, texto_ocr or texto))

        return registros
