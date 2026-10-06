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
    como em Addomus/Lirba/Habitacional. Layout da página (TEXTO NATIVO):
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

  - **MUDANÇA CONFIRMADA EM DADOS REAIS (ago/2026):** a administradora
    passou a anexar o recibo como IMAGEM ESCANEADA (print do extrato
    bancário Itaú), não mais como texto nativo — `page.get_text()` só
    devolve o cabeçalho/rodapé ("Comprovantes de despesas", "Parcela NNNN",
    "N de 1041"), o corpo inteiro (valor, fornecedor, datas) é um bloco de
    imagem (`page.get_text("dict")["blocks"]` tipo 1). Confirmado: TODAS as
    166 parcelas de ago/2026 vieram assim, nenhuma com texto nativo — não é
    uma exceção pontual, é o formato novo. Por isso agora SEMPRE tenta texto
    nativo primeiro (zero custo) e cai pra OCR só quando ele não acha os
    marcadores esperados — nunca assume qual dos dois formatos vai aparecer
    num mês futuro.

    Confirmados 9 modelos de recibo diferentes nessa nova imagem (o próprio
    banco Itaú gera modelos diferentes por tipo de pagamento):

    a) "comprovante de pagamento de débito automático" — rótulo único
       "valor R$ X,XX", fornecedor em "Identificação no extrato DA
       <FORNECEDOR> <código>", data em "pagamento realizado em DD/MM/AAAA"
       (sem vencimento separado — é débito no mesmo dia).

    b) "comprovante de pagamento de boleto"[ Itaú] — layout em DUAS colunas
       que o OCR lê em ORDEM EMBARALHADA (mesmo problema já visto em outros
       formatos deste projeto: todos os RÓTULOS primeiro, todos os VALORES
       depois). O fornecedor é sempre "nome do beneficiário" + CNPJ +
       "razão social" repetindo o MESMO nome em sequência (confirmado em
       todos os exemplos reais) — âncora confiável mesmo com campos
       intermediários variáveis (às vezes "dados do pagador" vem vazio,
       às vezes tem um nome diferente do próprio condomínio). O valor é
       sempre o ÚLTIMO "R$ X,XX" do bloco de 5 valores em sequência (valor
       do documento/desconto/mora/multa/valor do pagamento) — nunca o
       primeiro (esse é o valor do DOCUMENTO, antes de desconto/multa).
       As duas primeiras datas DD/MM/AAAA depois do nome do fornecedor são
       vencimento e data de pagamento (nessa ordem).

    c) "comprovante de pagamento - DARF" — layout direto, sem embaralhar:
       "valor do pagamento R$ X,XX" e "data do pagamento DD/MM/AAAA" cada
       um na própria linha. Pagador é o próprio condomínio (é um tributo,
       não um fornecedor terceiro) — sem Nota Fiscal associada.

    d) "comprovante de transferência para conta corrente" e
       "comprovante de pagamento TED - outra titularidade" — layout direto
       (rótulo e valor na mesma linha, sem embaralhar): "nome" aparece 2x
       (pagador, depois beneficiário) — usa a ÚLTIMA ocorrência; "valor do
       pagamento R$ X,XX" e "data do pagamento DD/MM/AAAA" cada um na
       própria linha, igual ao modelo DARF.

    e) "comprovante de pagamento Tributos municipais" — mesmo layout direto
       do item d), mas o beneficiário não é uma "nome" (é um tributo): usa
       o rótulo "município" como fornecedor (não tem Nota Fiscal associada,
       igual DARF).

    f) "comprovante de pagamento de concessionárias" — mesmo layout direto,
       mas o valor vem no rótulo "valor do documento R$ X,XX" (não "valor
       do pagamento") e o fornecedor é o "nome" dentro de "dados da
       concessionária" (última ocorrência de "nome", igual item d).

    g) "comprovante de transferência" (PIX, sem sufixo "para conta
       corrente") e h) "comprovante de pagamento QR Code" — mesmo problema
       de ORDEM EMBARALHADA do boleto (item b): todos os RÓTULOS vêm sem
       valor na própria linha ("nome", "nome do recebedor" aparecem
       sozinhos), os VALORES ficam num bloco à parte mais abaixo. Confirmado
       em dados reais que esse bloco de valores é "R$ X,XX" ÚNICO (item g)
       ou uma sequência onde o 1º "R$ X,XX" já é o valor correto por não
       haver desconto/multa nesses casos reais (item h) — por isso usa o
       1º valor "R$ X,XX" da página inteira. Fornecedor tentado via
       heurística (1ª linha em CAIXA-ALTA que não é o nome do próprio
       condomínio, não é código de agência/conta, nem rótulo genérico de
       instituição/tipo de conta/tipo de pagamento) — fica None quando não
       encontra candidato confiável (ex.: QR Code nos dados reais é o
       condomínio pagando pra si mesmo, não há fornecedor terceiro). Data
       via "transação efetuada em DD/MM/AAAA" / "pagamento efetuado em
       DD/MM/AAAA" (único timestamp confiável fora do bloco embaralhado).

    Nenhum dos modelos novos mostra a seção "Destina-se a" (categoria) —
    diferente do formato antigo que tinha isso na própria capa. `categoria_
    demonstrativo` fica None pras páginas lidas via OCR (honesto: não
    inventa uma categoria que não foi vista no documento).

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

from conciliacao import ocr
from conciliacao.base import ConciliadorBase, RegistroComprovante

_RE_VALOR_DECLARADO = re.compile(r'^Valor:\s*([\d.]+,\d{2})', re.MULTILINE)
_RE_PARCELA = re.compile(r'Parcela\s+(\d+)')
_RE_LINHA_FORNECEDOR = re.compile(
    r'^(.*?)\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(?:(\S+)\s+)?([\d.]+,\d{2})\s*$'
)
_RE_CATEGORIA = re.compile(r'^(\d+(?:\.\d+)+)\s+(.+?)\s+[\d.]+,\d{2}\s*$')
_RE_TOTAL_LEDGER = re.compile(r'(\d+)\s+itens?\s+([\d.]+,\d{2})')

# ── Formato novo (recibo em imagem, ago/2026+) — ver docstring do módulo ──
_RE_DEBITO_AUTOMATICO = re.compile(r"d[eé]bito\s+autom[aá]tico", re.IGNORECASE)
_RE_DARF = re.compile(r"\bDARF\b", re.IGNORECASE)
_RE_BOLETO = re.compile(r"pagamento\s+de\s+boleto", re.IGNORECASE)

_RE_VALOR_DEBITO = re.compile(r"\bvalor\s+R\$\s*([\d.]+,\d{2})", re.IGNORECASE)
_RE_FORNECEDOR_DEBITO = re.compile(r"Identifica[cç][aã]o no extrato\s+DA\s+(.+)", re.IGNORECASE)
_RE_DATA_DEBITO = re.compile(r"pagamento realizado em\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

_RE_VALOR_DARF = re.compile(r"valor do pagamento\s+R\$\s*([\d.]+,\d{2})", re.IGNORECASE)
_RE_DATA_PAGAMENTO_DARF = re.compile(r"data do pagamento\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

# Âncora pro fornecedor do boleto: "nome\nCNPJ\nnome" (mesmo nome repetido —
# é sempre "dados do beneficiário: nome" + "CPF/CNPJ" + "razão social",
# confirmado em dados reais que a razão social é idêntica ao nome em todos
# os casos). Robusto a campos intermediários variáveis (às vezes "dados do
# pagador" vem vazio, às vezes tem um nome diferente do condomínio).
_RE_CNPJ_REPETIDO = re.compile(r"^(.{3,80}?)\n(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\n\1\s*$", re.MULTILINE)
_RE_TODOS_VALORES_RS = re.compile(r"R\$\s*([\d.]+,\d{2})")
_RE_TODAS_DATAS = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")

# ── Modelos d)-h): transferência/TED/tributos/concessionárias/QR Code ──
# Título da própria página ("comprovante de X") identifica o modelo de
# forma mais confiável do que procurar palavras soltas no corpo — nenhum
# outro modelo contém essas substrings por acaso (conferido nos 6 exemplos
# reais: "transferência", "transferência para conta corrente", "pagamento
# TED - outra titularidade", "pagamento Tributos municipais", "pagamento de
# concessionárias", "pagamento QR Code").
_RE_TITULO = re.compile(r"comprovante de ([^\n]+)", re.IGNORECASE)
# "nome" com valor na mesma linha (modelos NÃO embaralhados) — quando
# aparece 2x (pagador, depois beneficiário/concessionária), a última
# ocorrência é o beneficiário real; quando aparece só 1x é o pagador, não
# usar nesse caso (ver _RE_TRIBUTO_MUNICIPIO, que trata isso à parte).
_RE_NOME_LINHA = re.compile(r"^nome\s+(.+)$", re.MULTILINE)
_RE_MUNICIPIO_LINHA = re.compile(r"^munic.pio\s+(.+)$", re.IGNORECASE | re.MULTILINE)
_RE_VALOR_DOCUMENTO = re.compile(r"valor do documento\s+R\$\s*([\d.]+,\d{2})", re.IGNORECASE)
# Timestamp de rodapé presente em TODOS os modelos ("transação efetuada em"
# / "pagamento efetuado em") — usado como última alternativa de data quando
# o rótulo "data do pagamento" não tem valor na mesma linha (bloco
# embaralhado, modelos g/h).
_RE_DATA_EFETUADA = re.compile(r"efetuad[ao]\s+em\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
# Heurística de fornecedor pros modelos embaralhados (g): 1ª linha em
# CAIXA-ALTA que não é o próprio condomínio, nem código de agência/conta,
# nem CNPJ/dígitos soltos, nem rótulo genérico de instituição/tipo de
# conta/pagamento (que também aparecem em CAIXA-ALTA no bloco de valores).
_RE_LINHA_MAIUSCULA_CANDIDATA = re.compile(r"^([A-ZÀ-ÚÇ][A-ZÀ-ÚÇ0-9 .\-&/']{4,80})$", re.MULTILINE)
_RE_CONDOMINIO_PROPRIO = re.compile(r"CONDOMINIO|CLUB PARK", re.IGNORECASE)
_RE_PALAVRA_GENERICA = re.compile(
    r"^(CONTA CORRENTE|CONTA POUPAN.A|PIX\b.*|BCO\b.*|BANCO\b.*|TED\b.*|DOC\b.*)$", re.IGNORECASE
)


def _candidata_fornecedor_maiuscula(texto: str) -> str | None:
    for linha in _RE_LINHA_MAIUSCULA_CANDIDATA.findall(texto):
        linha = linha.strip()
        if _RE_CONDOMINIO_PROPRIO.search(linha) or _RE_PALAVRA_GENERICA.match(linha):
            continue
        if re.fullmatch(r"[\d./\-]+", linha):
            continue
        # Descarta hash/autenticação (ex.: "ASS6CCA5S491C4590F2EA...") que
        # passa pelo filtro acima por ter alguma letra misturada — nome real
        # tem mais letras que dígitos.
        if sum(c.isdigit() for c in linha) >= sum(c.isalpha() for c in linha):
            continue
        return linha
    return None

_TAMANHO_MINIMO_TEXTO_NATIVO = 150


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


def _extrair_dados_ocr(texto: str) -> dict:
    """Despacha pro parser certo conforme o modelo de recibo Itaú (ver
    docstring do módulo) — nunca lança, campos ficam None/0.0 quando o
    modelo não é reconhecido (honesto: não inventa dado)."""
    if _RE_DEBITO_AUTOMATICO.search(texto):
        m_valor = _RE_VALOR_DEBITO.search(texto)
        m_forn = _RE_FORNECEDOR_DEBITO.search(texto)
        m_data = _RE_DATA_DEBITO.search(texto)
        data = m_data.group(1) if m_data else None
        return {
            "valor": _num(m_valor.group(1)) if m_valor else 0.0,
            "fornecedor": m_forn.group(1).strip()[:200] if m_forn else None,
            "vencimento": data,
            "pagamento": data,
            "autenticacao": None,
        }
    if _RE_DARF.search(texto):
        m_valor = _RE_VALOR_DARF.search(texto)
        m_data = _RE_DATA_PAGAMENTO_DARF.search(texto)
        data = m_data.group(1) if m_data else None
        return {
            "valor": _num(m_valor.group(1)) if m_valor else 0.0,
            "fornecedor": "DARF - Receita Federal",
            "vencimento": data,
            "pagamento": data,
            "autenticacao": None,
        }
    if _RE_BOLETO.search(texto):
        m_forn = _RE_CNPJ_REPETIDO.search(texto)
        valores = _RE_TODOS_VALORES_RS.findall(texto)
        # Sempre o ÚLTIMO valor do bloco (valor do pagamento, depois de
        # desconto/mora/multa) — nunca o primeiro (valor do documento, sem
        # os ajustes) nem um valor solto de outra parte da página.
        valor = _num(valores[-1]) if valores else 0.0
        pos_forn = m_forn.end() if m_forn else 0
        datas = _RE_TODAS_DATAS.findall(texto[pos_forn:])
        vencimento = datas[0] if len(datas) >= 1 else None
        pagamento = datas[1] if len(datas) >= 2 else vencimento
        return {
            "valor": valor,
            "fornecedor": m_forn.group(1).strip()[:200] if m_forn else None,
            "vencimento": vencimento,
            "pagamento": pagamento,
            "autenticacao": m_forn.group(2) if m_forn else None,
        }

    m_titulo = _RE_TITULO.search(texto)
    titulo = (m_titulo.group(1) if m_titulo else "").lower()

    def _data_pagamento_ou_fallback() -> str | None:
        m = _RE_DATA_PAGAMENTO_DARF.search(texto) or _RE_DATA_EFETUADA.search(texto)
        return m.group(1) if m else None

    if "concession" in titulo:
        m_valor = _RE_VALOR_DOCUMENTO.search(texto)
        nomes = _RE_NOME_LINHA.findall(texto)
        return {
            "valor": _num(m_valor.group(1)) if m_valor else 0.0,
            "fornecedor": nomes[-1].strip()[:200] if nomes else None,
            "vencimento": _data_pagamento_ou_fallback(),
            "pagamento": _data_pagamento_ou_fallback(),
            "autenticacao": None,
        }
    if "conta corrente" in titulo or "ted" in titulo:
        m_valor = _RE_VALOR_DARF.search(texto)
        nomes = _RE_NOME_LINHA.findall(texto)
        return {
            "valor": _num(m_valor.group(1)) if m_valor else 0.0,
            "fornecedor": nomes[-1].strip()[:200] if nomes else None,
            "vencimento": _data_pagamento_ou_fallback(),
            "pagamento": _data_pagamento_ou_fallback(),
            "autenticacao": None,
        }
    if "tribut" in titulo or "municipais" in titulo:
        m_valor = _RE_VALOR_DARF.search(texto)
        m_forn = _RE_MUNICIPIO_LINHA.search(texto)
        return {
            "valor": _num(m_valor.group(1)) if m_valor else 0.0,
            "fornecedor": m_forn.group(1).strip()[:200] if m_forn else None,
            "vencimento": _data_pagamento_ou_fallback(),
            "pagamento": _data_pagamento_ou_fallback(),
            "autenticacao": None,
        }
    if "qr code" in titulo:
        valores = _RE_TODOS_VALORES_RS.findall(texto)
        data = _RE_DATA_EFETUADA.search(texto)
        data = data.group(1) if data else None
        return {
            "valor": _num(valores[0]) if valores else 0.0,
            "fornecedor": None,
            "vencimento": data,
            "pagamento": data,
            "autenticacao": None,
        }
    if "transfer" in titulo:
        valores = _RE_TODOS_VALORES_RS.findall(texto)
        data = _RE_DATA_EFETUADA.search(texto)
        data = data.group(1) if data else None
        fornecedor = _candidata_fornecedor_maiuscula(texto)
        return {
            "valor": _num(valores[0]) if valores else 0.0,
            "fornecedor": fornecedor[:200] if fornecedor else None,
            "vencimento": data,
            "pagamento": data,
            "autenticacao": None,
        }
    return {"valor": 0.0, "fornecedor": None, "vencimento": None, "pagamento": None, "autenticacao": None}


class Conciliador(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import fitz
        import pdfplumber

        registros: list[RegistroComprovante] = []
        # Só a 1ª página de cada "Parcela" tem dado útil (capa) — as
        # seguintes são imagem/anexo do que foi pago (fatura, nota fiscal
        # digitalizada), sem texto nem marcador "Parcela" confiável. Guarda
        # a PRIMEIRA ocorrência de cada código pra nunca reprocessar/pegar
        # uma página de continuação por engano.
        primeira_pagina_parcela: dict[str, int] = {}

        # Reaproveita UM fitz.Document aberto pra todas as chamadas de OCR
        # (ver conciliacao/ocr.py::ocr_pagina_pdf, parâmetro `doc_aberto`) —
        # confirmado em dados reais que reabrir um arquivo de 333MB/1042
        # páginas a cada uma das ~166 páginas de comprovante era o gargalo
        # real, não o OCR em si.
        doc_fitz = fitz.open(str(caminho))
        with pdfplumber.open(str(caminho)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""
                page.flush_cache()

                m_total = _RE_TOTAL_LEDGER.search(texto)
                if m_total and "Pago a:" not in texto and "Comprovantes de despesas" not in texto:
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

                if "Comprovantes de despesas" not in texto:
                    continue  # não é página de comprovante nem do Livro Caixa

                m_parcela = _RE_PARCELA.search(texto)
                if not m_parcela:
                    continue
                codigo = m_parcela.group(1)
                if codigo in primeira_pagina_parcela:
                    continue  # já processamos a capa desse código — isto é continuação
                primeira_pagina_parcela[codigo] = i

                # ── Formato antigo: texto nativo já tem tudo (ver docstring) ──
                if "Pago a:" in texto and len(texto) >= _TAMANHO_MINIMO_TEXTO_NATIVO:
                    fornecedor = venc = liquidacao = documento = None
                    for linha in texto.split("\n"):
                        m = _RE_LINHA_FORNECEDOR.match(linha.strip())
                        if m:
                            fornecedor, venc, liquidacao, documento, _valor2 = m.groups()
                            fornecedor = fornecedor.strip()
                            break
                    categoria = None
                    for linha in texto.split("\n"):
                        m = _RE_CATEGORIA.match(linha.strip())
                        if m:
                            categoria = f"{m.group(1)} {m.group(2).strip()}"
                            break
                    m_valor = _RE_VALOR_DECLARADO.search(texto)
                    registros.append(RegistroComprovante(
                        pagina=i,
                        tipo_documento="despesa_com_comprovante",
                        codigo=codigo,
                        fornecedor=fornecedor,
                        vencimento=venc,
                        pagamento=liquidacao,
                        valor=_num(m_valor.group(1)) if m_valor else 0.0,
                        categoria_demonstrativo=categoria,
                        autenticacao=documento,
                        texto_bruto=texto,
                    ))
                    continue

                # ── Formato novo: recibo em imagem — OCR (ver docstring) ──
                texto_ocr = ocr.ocr_pagina_pdf(caminho, i - 1, doc_aberto=doc_fitz)
                dados = _extrair_dados_ocr(texto_ocr)
                registros.append(RegistroComprovante(
                    pagina=i,
                    tipo_documento="despesa_com_comprovante",
                    codigo=codigo,
                    fornecedor=dados["fornecedor"],
                    vencimento=dados["vencimento"],
                    pagamento=dados["pagamento"],
                    valor=dados["valor"],
                    categoria_demonstrativo=None,
                    autenticacao=dados["autenticacao"],
                    texto_bruto=texto_ocr,
                ))

        doc_fitz.close()
        return registros
