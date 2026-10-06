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
import tempfile
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
_RE_EXTRATO = re.compile(r"e[xs]trato\s*:?\s*mens[ao]l", re.IGNORECASE)
# Folha/resumo de folha da prestadora de serviço terceirizada (SOUZA LIMA): "RESUMO TERCERIZAÇÃO GERAL",
# "Demonstrativo de Pagamento" (holerite), "Cálculo Mensal" — documentos de apoio ao pagamento da NF.
_RE_FOPAG = re.compile(
    r"FOPAG|Folha de Pagamento|RESUMO\s+TERCERIZA|Demonstrativo de Pagamento|C[aá]lculo Mensal", re.IGNORECASE)
_RE_CERTIDAO = re.compile(r"CERTID.O|Certificado de Regularidade", re.IGNORECASE)
_RE_RECIBO_ENTREGA = re.compile(r"Recibo de Entrega", re.IGNORECASE)
# Relatórios DCTFWeb e guias de recolhimento (FGTS Digital / DARF) EMITIDOS EM NOME DA PRESTADORA: provam
# o recolhimento de encargos da terceirizada; não são lançamento de despesa do condomínio.
_RE_DCTFWEB = re.compile(
    r"DCTFWeb|D[ée]bito Apurado e Cr[ée]dito Vinculado|Relat[óo]rio por Cr[ée]dito|Descri[cç][aã]o do D[ée]bito|"
    r"Grupo:\s*(?:IRRF|CSRF)|Outros\s+Cr[ée]ditos\s+Dedu", re.IGNORECASE)
_RE_GUIA = re.compile(
    r"Guia do FGTS|Detalhe da Guia Emitida|Documento de Arrecada[cç][aã]o|Composi[cç][aã]o do Documento de Arrecada",
    re.IGNORECASE)
# CNPJ do condomínio como CONTRIBUINTE da guia ("CNPJ  Razão Social  55.402.879/0001-90  CONDOMINIO ..."); a guia
# da prestadora também cita o CNPJ do condomínio, mas só como "Tomador:", nunca logo após "Razão Social".
_RE_CNPJ_CONDOMINIO = re.compile(r"Raz[ãa]o\s+Social\W{0,6}55\D{0,2}402\D{0,2}879", re.IGNORECASE)
_RE_COMPROVANTE_BANCARIO = re.compile(r"Comprovante de (?:pagamento|transfer[eê]ncia)", re.IGNORECASE)
# Quem pagou (bloco "Dados da conta debitada"): se não for o condomínio, é pagamento da prestadora.
_RE_BLOCO_PAGADOR = re.compile(r"dados da conta debitada:?(.{0,260})", re.IGNORECASE | re.DOTALL)
_RE_NOME_PAGADOR = re.compile(r"nome(?:\s+d[ao]\s+\w+)?\s*:?\s*([^\n]+)", re.IGNORECASE)
_RE_CABECALHO_RODAPE = re.compile(
    r"CONDOMINIO EDIFICIO PALM BEACH|Outros documentos|GROUP\s+condom[ií]nios|"
    r"HABITAT\s+ADMINISTRADORA\s+DE\s+CONDOM[ÍI]NIO|Emitido em[^\n]*|P[aá]g\.?\s*\d+\s*/\s*\d+", re.IGNORECASE)


def _pagador_nao_e_o_condominio(texto: str) -> str | None:
    """Nome do pagador quando o comprovante bancário foi pago por OUTRA empresa (ex.: SOUZA LIMA)."""
    m_bloco = _RE_BLOCO_PAGADOR.search(texto)
    if not m_bloco:
        return None
    m_nome = _RE_NOME_PAGADOR.search(m_bloco.group(1))
    if not m_nome:
        return None
    nome = m_nome.group(1).strip()
    if len(nome) < 4 or re.search(r"CONDOM[IÍ]NIO|PALM\s*BEACH", nome, re.IGNORECASE):
        return None
    return nome

# Valor da transação (seção "Outros documentos") — rótulos confirmados em
# dados reais (PIX QR Code, guias de tributos, transferências), tentados em
# ordem, o mais específico primeiro.
_RE_VALORES_OUTROS_DOCUMENTOS = [
    re.compile(r"valor do documento:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
    # Comprovante de Tributos Municipais (Itaú): "Valor do pagamento R$ 920,94"
    re.compile(r"valor do pagamento:?\s*R?\$?\s*([\d.]+,\d{2})", re.IGNORECASE),
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


# ── OCR com cache em disco + leituras de reforço (ver docstring dos blocos abaixo) ──
def _cache_ocr(caminho: Path):
    """(impressão do arquivo, cache) — reaproveita o cache em disco de conciliacao/ocr.py; sem ele (ou se
    a API interna mudar) devolve (None, {}) e tudo roda sem cache."""
    try:
        imp = ocr._impressao_arquivo(Path(caminho))
        return imp, ocr._cache_do_arquivo(imp)
    except Exception:
        return None, {}


def _ocr_com_cache(caminho: Path, chave: str, funcao) -> str:
    imp, cache = _cache_ocr(caminho)
    if chave in cache:
        return cache[chave]
    texto = funcao() or ""
    if imp and texto:
        try:
            ocr._cache_gravar(imp, chave, texto)
        except Exception:
            pass
    return texto


def _ocr_pagina(caminho: Path, indice: int) -> str:
    """OCR da página inteira (300 dpi + correção de orientação), com cache em disco."""
    return _ocr_com_cache(caminho, f"pb|{indice}|pagina300", lambda: ocr.ocr_pagina_pdf(caminho, indice))


# Vocabulário de documentos fiscais/trabalhistas em português: página cujo OCR tem poucas dessas palavras
# provavelmente foi lida de cabeça para baixo / de lado (ex.: tabelas em paisagem dentro de página retrato).
_RE_VOCABULARIO = re.compile(
    r"\b(?:de|da|do|dos|das|valor|total|nome|data|empregador|guia|fgts|documento|per[ií]odo|empresa|"
    r"contribuinte|c[oó]digo|saldo|emitid[ao]|pagamento|resumo|d[eé]bito|cr[eé]dito|trabalhadores?|colaborador|"
    r"estabelecimento|remunera[cç][aã]o|categoria)\b", re.IGNORECASE)
_PONTUACAO_MINIMA = 6   # abaixo disso o OCR da página é considerado suspeito e as rotações são tentadas
_PONTUACAO_ACEITE = 3   # leitura girada só é aceita com pelo menos isto; quem valida é o classificador por tipo


def _pontuacao(texto: str) -> int:
    return len(_RE_VOCABULARIO.findall(texto or ""))


def _ocr_com_rotacoes(caminho: Path, indice: int) -> str:
    """Releitura de página de OCR ilegível: gira 90/180/270 graus e fica com a leitura que mais casa com o
    vocabulário. Devolve "" se nenhuma passar do mínimo (nunca inventa leitura)."""
    def _ler():
        import fitz
        from PIL import Image
        if not ocr.tesseract_disponivel():
            return ""
        import pytesseract
        melhor, melhor_pts = "", 0
        with fitz.open(str(caminho)) as doc:
            pix = doc[indice].get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        for ang in (90, 270, 180):
            txt = pytesseract.image_to_string(img.rotate(ang, expand=True), lang="por", config="--oem 1")
            pts = _pontuacao(txt)
            if pts > melhor_pts:
                melhor, melhor_pts = txt, pts
        return melhor if melhor_pts >= _PONTUACAO_ACEITE else ""
    return _ocr_com_cache(caminho, f"pb|{indice}|rotacoes200", _ler)


# Capa de anexo de despesa: a tabela "Data | Número | Fornecedor | Classe de conta | Valor (R$)" é uma
# faixa ESCURA com texto branco, que o OCR da página inteira costuma perder (8 de 22 capas em ago/2026,
# todas com o valor bem visível na imagem). Lê só a faixa, invertida.
_RE_VALOR_FAIXA = re.compile(r"R\$\s*(\d[\d.]*)[,. ](\d{2})(?!\d)")
_RE_CLASSE_FAIXA = re.compile(r"(\d+(?:\.\d+)+\s*-\s*.+?)\s+R\$")


def _ler_faixa_capa(caminho: Path, indice: int) -> str:
    def _ler():
        import fitz
        import numpy as np
        from PIL import Image, ImageOps
        if not ocr.tesseract_disponivel():
            return ""
        import pytesseract
        with fitz.open(str(caminho)) as doc:
            pix = doc[indice].get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        g = np.asarray(img.convert("L"))
        h, w = g.shape
        escura = (g[:, int(w * 0.10):int(w * 0.90)] < 90).mean(axis=1) > 0.55
        limite = int(h * 0.45)
        a = b = None
        for y in range(limite):
            if escura[y] and a is None:
                a = y
            elif not escura[y] and a is not None:
                if y - a >= 30:  # primeira faixa escura com altura de tabela (ignora logos coloridos)
                    b = y
                    break
                a = None
        if a is None or b is None:
            return ""
        faixa = ImageOps.invert(img.crop((0, max(0, a - 4), w, b + 4)).convert("L"))
        return pytesseract.image_to_string(faixa, lang="por", config="--oem 1 --psm 6")
    return _ocr_com_cache(caminho, f"pb|{indice}|faixa200", _ler)


def _valor_da_faixa(texto: str):
    """Último "R$ valor" da faixa; aceita o separador decimal lido como espaço ou ponto (R$542 80, R$1.088.94)."""
    achados = _RE_VALOR_FAIXA.findall(texto or "")
    if not achados:
        return None
    inteiro, centavos = achados[-1]
    return float(inteiro.replace(".", "") + "." + centavos)


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
    texto_ocr = _ocr_pagina(caminho, pagina - 1)
    texto_base = texto_ocr or texto_real

    m_valor = _valor_apos_valor_parenteses(texto_base)
    valor = _num(m_valor.group(1)) if m_valor else 0.0
    m_classe = _RE_CLASSE_CONTA.search(texto_base)
    categoria = m_classe.group(1).strip() if m_classe else None

    if not m_valor:
        # Reforço: o OCR da página inteira perdeu a faixa escura da capa — lê só a faixa (o valor lido
        # é o impresso na capa, nunca um valor de item da nota fiscal anexada).
        faixa = _ler_faixa_capa(caminho, pagina - 1)
        valor_faixa = _valor_da_faixa(faixa)
        if valor_faixa:
            valor = valor_faixa
            m_valor = True
            m_cl = _RE_CLASSE_FAIXA.search(re.sub(r"\s+", " ", faixa))
            if m_cl and not categoria:
                categoria = m_cl.group(1).strip()
            texto_base = texto_base + "\n[FAIXA DA CAPA]\n" + faixa

    return RegistroComprovante(
        pagina=pagina,
        tipo_documento="anexo_despesa_com_valor" if m_valor else "anexo_despesa_sem_valor_identificado",
        codigo=doc_numero,
        fornecedor=fornecedor_cabecalho.strip(),
        categoria_demonstrativo=categoria,
        valor=valor,
        texto_bruto=texto_base,
    )


def _apoio(pagina: int, texto: str, descricao: str) -> RegistroComprovante:
    return RegistroComprovante(
        pagina=pagina, tipo_documento="documento_apoio_sem_valor", descricao=descricao, texto_bruto=texto)


def _classificar_outro_documento(pagina: int, texto: str) -> RegistroComprovante:
    if _RE_EXTRATO.search(texto):
        return _apoio(pagina, texto, "Extrato bancário")
    if _RE_CERTIDAO.search(texto):
        return _apoio(pagina, texto, "Certidão")
    if _RE_RECIBO_ENTREGA.search(texto):
        return _apoio(pagina, texto, "Recibo de entrega (protocolo)")

    # Comprovante bancário: se quem pagou NÃO é o condomínio (ex.: a prestadora SOUZA LIMA recolhendo o
    # próprio FGTS/DARF, valores de milhões), não é pagamento do condomínio e o valor não é comparável a
    # nenhuma despesa dele — documento de apoio fiscal, não "valor implausível por erro de OCR".
    if _RE_COMPROVANTE_BANCARIO.search(texto):
        pagador = _pagador_nao_e_o_condominio(texto)
        if pagador:
            return _apoio(pagina, texto, f"Comprovante de recolhimento pago pela prestadora ({pagador[:60]})")

    if _RE_FOPAG.search(texto):
        return _apoio(pagina, texto, "Folha de pagamento (terceirizados)")
    if _RE_DCTFWEB.search(texto):
        return _apoio(pagina, texto, "Relatório DCTFWeb (tributos da prestadora)")
    # Guia emitida em nome do CONDOMÍNIO (CNPJ 55.402.879/0001-90, ex.: DARF de retenções, pág. 124 de ago/2026,
    # R$ 5.895,94) é tributo dele e segue o caminho do valor; só a guia da prestadora (CNPJ dela) é apoio.
    if _RE_GUIA.search(texto) and not _RE_COMPROVANTE_BANCARIO.search(texto) and not _RE_CNPJ_CONDOMINIO.search(texto):
        return _apoio(pagina, texto, "Guia de recolhimento (FGTS/DARF) da prestadora")
    if len(re.sub(r"[\W_]+", "", _RE_CABECALHO_RODAPE.sub(" ", texto))) < 30:
        return _apoio(pagina, texto, "Separador de seção da pasta")

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
                    texto_ocr = _ocr_pagina(caminho, i - 1)
                    reg = _classificar_outro_documento(i, texto_ocr or texto)
                    if reg.tipo_documento == "comprovante_sem_valor_identificado" and _pontuacao(texto_ocr) < _PONTUACAO_MINIMA:
                        # OCR ilegível (página girada de lado/de cabeça para baixo): relê com rotações e
                        # só aceita a leitura que passar do mínimo de vocabulário.
                        texto_rot = _ocr_com_rotacoes(caminho, i - 1)
                        if texto_rot:
                            reg = _classificar_outro_documento(i, texto_rot)
                    registros.append(reg)

        return registros
