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
     código. O cabeçalho/rodapé do sistema é texto real, mas o comprovante
     em si é uma IMAGEM digitalizada embutida na página — sem OCR não dá
     pra extrair código/fornecedor/valor dela como no Addomus. Um spike
     manual (Baturité, jul+ago/2026) confirmou que essas imagens costumam
     ser um recibo digital limpo (não scan de papel) e que o Tesseract lê
     bem — mas o LAYOUT do recibo varia por tipo de pagamento (confirmados
     pelo menos 4: "Comprovante de Pagamento Eletrônico"/DCTFWeb com "Valor
     do lancto", "Comprovante de Operação Débito Automático" de
     concessionária com "Valor:" solto, "Comprovante de Transferência"
     PIX/TED com "valor:" minúsculo, "Comprovante de pagamento" de guia
     tributária tipo DARE com "Valor do pagamento" sem "lancto") — por isso
     `_preencher_via_ocr()` tenta várias regras em ordem, não uma só. O MESMO
     spike também confirmou que a página às vezes é genuinamente uma capa
     SEM nenhum anexo (comprovante 0001 do Baturité, página em branco) —
     por isso o OCR aqui nunca é tratado como "confirmação" quando não
     encontra um valor: vira um registro com `valor == 0.0`, e
     conciliacao/matching.py::gerar_achados_lirba decide entre
     "conteudo_nao_verificavel" (comprovante existe, sem confirmação) e
     segue usando "sem_comprovante" para quando a página nem existe.

Conclusão prática: quando o OCR confirma o valor do comprovante, o matching
cruza esse valor contra o da listagem (item 1) igual a um pareamento por
código; quando não confirma (OCR indisponível na máquina, imagem ilegível,
ou capa sem anexo real), vira "conteúdo não verificável" em vez de uma
confirmação às cegas — ver conciliacao/matching.py::gerar_achados_lirba.
"""
import re
from pathlib import Path

from conciliacao import ocr
from conciliacao.base import ConciliadorBase, RegistroComprovante

# Abaixo desse tamanho de texto OCR, mesmo que algum trecho combine por
# acidente com um dos padrões abaixo, não há confiança suficiente pra tratar
# como comprovante confirmado — na prática só cabeçalho/rodapé do sistema
# ("Página: N", "Comprovante de Despesa NNNN", "Voltar ao Índice").
_OCR_TEXTO_MINIMO = 80
# Regras de extração de VALOR, tentadas em ordem — a primeira que casar
# vence. A ordem importa: quando o lançamento é um DARF/DCTFWeb
# "(CONSOLIDADO)" que quita várias retenções de uma vez, o "Valor do
# pagamento" é a SOMA de todas elas, não o valor do lançamento individual
# (confirmado em dados reais: várias páginas diferentes mostravam o mesmo
# "Valor do pagamento", uma por retenção consolidada) — "Valor do lancto" é
# o valor individual correto nesse caso, então é tentado PRIMEIRO. Templates
# sem o conceito de "lancto" (guia tributária tipo DARE, débito automático de
# concessionária, transferência PIX/TED) cada um só tem uma das variantes
# abaixo, então a ordem entre elas não muda o resultado.
# OCR troca "V" por "W" com frequência no rótulo "Valor do lancto"
# (confirmado em dados reais: às vezes sai "Walor"/"WValor") — [VW]+ absorve
# qualquer uma dessas variantes sem perder a leitura.
# NOTA: "(?:R\$)?" (o par inteiro opcional), nunca "R\$?" (que exige o "R"
# obrigatório e só o "$" opcional) — bug já cometido aqui uma vez: nenhuma
# das 3 regras batia contra o template de débito automático ("Valor: 53,85",
# sem "R$" nenhum) até essa correção.
_RE_OCR_VALORES_EM_ORDEM = [
    # "Valor do lancto"/"Valor lancto" (o "do" é opcional — confirmado em
    # dados reais: o DARF/tributos Bradesco de Dueto Morumbi omite o "do" na
    # seção "Lançamento consolidado", diferente do "Comprovante de Pagamento
    # Eletrônico" do Baturité, que sempre tem "do") — sempre o valor
    # INDIVIDUAL do lançamento, mesmo quando o pagamento em si é consolidado.
    re.compile(r"[VW]+alor\s*(?:do\s*)?lan\S*to:?\s*(?:R\$)?\s*([\d.]+,\d{2})", re.IGNORECASE),
    re.compile(r"Valor do pagamento:?\s*(?:R\$)?\s*([\d.]+,\d{2})", re.IGNORECASE),            # guia tributária (DARE etc.) sem conceito de "lancto"
    re.compile(r"^Valor:\s*(?:R\$)?\s*([\d.]+,\d{2})\s*$", re.IGNORECASE | re.MULTILINE),     # débito automático de concessionária
    re.compile(r"Valor\s*R\$:?\s*(?:R\$)?\s*([\d.]+,\d{2})", re.IGNORECASE),                  # boleto Bradesco "Pag-For" (Dueto Morumbi/manager_adm_pdf)
    # Tabela de TED/DOC do Pag-For Bradesco: colunas viram texto solto no OCR
    # ("... l l R$ 1.983,75"), mas o valor sempre aparece na linha logo ANTES
    # de "Banco destinatário" — âncora confiável mesmo com a tabela toda
    # desalinhada.
    re.compile(r"R\$\s*([\d.]+,\d{2})\s*\n\s*Banco destinat", re.IGNORECASE),
    # "Demonstrativo para Faturamento de Serviços Prestados" (ex.: Correios/
    # AGF) — fecha com "Total da Operação"/"Total do Departamento" (o mesmo
    # valor nos dois, um logo depois do outro).
    re.compile(r"Total d[ao] (?:Opera[cç][aã]o|Departamento):?\s*\d*\s*([\d.]+,\d{2})", re.IGNORECASE),
    # "alor Total" (sem exigir o "V"/"v" inicial) — confirmado em dados reais
    # que o OCR às vezes gruda um caractere solto antes ("vValor Total") —
    # guia de tributos Bradesco (DARF) quando rótulo e valor saem na mesma
    # linha; quando o layout da página faz o OCR ler todos os rótulos
    # primeiro e todos os valores depois (fora de ordem), essa regra não bate
    # e o comprovante fica "conteudo_nao_verificavel" — correto: mais vale
    # não confirmar do que confirmar errado. É o ÚLTIMO da lista porque no
    # DARF consolidado é o valor AGREGADO (soma de N retenções), não o valor
    # do lançamento individual — só serve de fallback quando a regra 1 (mais
    # específica) não encontrar a seção "Lançamento consolidado".
    re.compile(r"alor Total:?\s*(?:R\$)?\s*([\d.]+,\d{2})", re.IGNORECASE),
]
# OCR também troca "V" por "Y" com frequência (confirmado: "Vencimento" saindo
# "Yencimento" no boleto Bradesco) — além do "Data do "/"Data de " opcional
# que precede o rótulo (boleto Bradesco usa "do", fatura Eletropaulo usa "de").
_RE_OCR_VENCIMENTO = re.compile(r"(?:Data d[eo] )?[VY]encimento:?\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
# Data efetiva do pagamento — cada template usa um rótulo diferente; tentados
# em ordem, a primeira que casar vence. Nenhuma delas tem uma "Vencimento"
# correspondente nos templates de PIX/débito automático/DARE (a operação é
# instantânea/no mesmo dia), então isso nunca gera atraso_pagamento sozinho
# — achado_atraso_pagamento() exige os dois campos.
_RE_OCR_PAGAMENTOS_EM_ORDEM = [
    re.compile(r"Pago em:?\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE),                            # DCTFWeb/eletrônico
    re.compile(r"Data d[ao] (?:transfer[eê]ncia|pagamento):?\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE),  # PIX/TED, guia tributária
]
# Débito automático não usa "DD/MM/YYYY" e sim "Pagamento realizado em DD.MM.YYYY".
_RE_OCR_PAGAMENTO_REALIZADO = re.compile(r"Pagamento realizado em (\d{2})\.(\d{2})\.(\d{4})", re.IGNORECASE)
_RE_OCR_FORNECEDOR = re.compile(r"(?:Fornecedor|nome do recebedor):?\s*(.+)", re.IGNORECASE)
_RE_OCR_CPF_CNPJ = re.compile(r"(?:CNPJ|CPF)(?:\s*/\s*CNPJ)?(?:\s*d[oa]\s*\w+)?:?\s*([\d./\-]{11,18})", re.IGNORECASE)
# Âncoras cujo valor mora DEPOIS delas no texto, não necessariamente colado
# ao rótulo — confirmado em dados reais que várias páginas saem com "todos
# os rótulos primeiro, todos os valores depois" (o OCR lê a página por
# blocos/colunas, não linha a linha) — ver _valor_apos_ancora().
#   - "Lançamento consolidado" (guia de tributos Bradesco/DARF): sinal mais
#     forte de que existe um valor INDIVIDUAL ali dentro, distinto do "Valor
#     Total" da página (que é o agregado de N retenções).
#   - "VALOR DO DOCUMENTO" (segunda via de fatura de concessionária, ex.:
#     Eletropaulo/Enel, anexada como comprovante): o valor da fatura em si.
_RE_LANCAMENTO_CONSOLIDADO = re.compile(r"Lan\S*amento consolidado", re.IGNORECASE)
_RE_VALOR_DO_DOCUMENTO = re.compile(r"VALOR DO DOCUMENTO", re.IGNORECASE)
_RE_PRIMEIRO_VALOR_RS = re.compile(r"R\$\s*([\d.]+,\d{2})")

# NFS-e (Nota Fiscal Eletrônica de Serviços) mostra o valor BRUTO do serviço
# prestado — mas a listagem sempre traz o valor LÍQUIDO já descontadas as
# retenções de PIS/COFINS/CSLL (confirmado em dados reais: NFS-e de
# administração mostrando R$ 3.500,00 brutos, retenção de R$ 162,75, listagem
# com R$ 3.337,25 líquidos — os dois batem exatamente). Sem essa conta, toda
# NFS-e anexada como comprovante de uma despesa com retenção vira um falso
# "divergência de valor" (bruto ≠ líquido, quando na verdade os documentos
# conferem perfeitamente).
_RE_NFS_E_MARCADOR = re.compile(r"NOTA FISCAL ELETR\S*NICA DE SERVI\S*OS|NFS-e", re.IGNORECASE)
_RE_NFS_E_VALOR_BRUTO = re.compile(r"VALOR TOTAL DO SERVI\S*O\s*=?\s*R\$\s*([\d.]+,\d{2})", re.IGNORECASE)
_RE_NFS_E_RETENCAO = re.compile(r"Contribui\S*es Sociais\s*-?\s*Retidas[^\d]*?([\d.]+,\d{2})", re.IGNORECASE)


def _valor_apos_ancora(texto: str, ancora: re.Pattern) -> re.Match | None:
    """Acha `ancora` no texto e retorna o primeiro "R$ valor" que aparecer
    DEPOIS dela — funciona tanto quando rótulo e valor estão colados na
    mesma linha quanto quando o OCR lê rótulos e valores em blocos
    separados (ver comentário acima). None se a âncora não existir."""
    m_ancora = ancora.search(texto)
    return _RE_PRIMEIRO_VALOR_RS.search(texto, m_ancora.end()) if m_ancora else None


def _num(s) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


def _preencher_via_ocr(registro: RegistroComprovante, caminho_pdf: Path, pagina_1based: int) -> None:
    """
    Roda OCR na página de "Comprovante de Despesa" e, quando encontra um
    "Valor do pagamento" confiável, popula os campos do registro. Nunca
    lança exceção (ver conciliacao/ocr.py) — na pior hipótese o registro
    fica exatamente como estava (valor=0.0), sinalizando pra
    gerar_achados_lirba() que o conteúdo não pôde ser confirmado.
    """
    texto = ocr.ocr_pagina_pdf(caminho_pdf, pagina_1based - 1)
    if len(texto.strip()) < _OCR_TEXTO_MINIMO:
        return

    valor: float | None = None
    if _RE_NFS_E_MARCADOR.search(texto):
        m_bruto = _RE_NFS_E_VALOR_BRUTO.search(texto)
        if m_bruto:
            m_retencao = _RE_NFS_E_RETENCAO.search(texto)
            retencao = _num(m_retencao.group(1)) if m_retencao else 0.0
            valor = _num(m_bruto.group(1)) - retencao
    if valor is None:
        m_valor = (
            _valor_apos_ancora(texto, _RE_LANCAMENTO_CONSOLIDADO)
            or _valor_apos_ancora(texto, _RE_VALOR_DO_DOCUMENTO)
            or next((m for m in (regex.search(texto) for regex in _RE_OCR_VALORES_EM_ORDEM) if m), None)
        )
        if not m_valor:
            return  # texto substancial, mas nenhum valor reconhecível — não confirma nada
        valor = _num(m_valor.group(1))
    registro.texto_bruto = texto
    registro.valor = valor
    m = _RE_OCR_VENCIMENTO.search(texto)
    if m:
        registro.vencimento = m.group(1)
    m_pagamento = next((m for m in (regex.search(texto) for regex in _RE_OCR_PAGAMENTOS_EM_ORDEM) if m), None)
    if m_pagamento:
        registro.pagamento = m_pagamento.group(1)
    else:
        # Débito automático não usa "DD/MM/YYYY" — só "Pagamento realizado em
        # DD.MM.YYYY" (sem "Vencimento" correspondente, então isso nunca vira
        # atraso_pagamento sozinho — achado_atraso_pagamento exige os dois).
        m = _RE_OCR_PAGAMENTO_REALIZADO.search(texto)
        if m:
            registro.pagamento = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    m = _RE_OCR_FORNECEDOR.search(texto)
    if m:
        registro.fornecedor = m.group(1).strip()[:200]
    m = _RE_OCR_CPF_CNPJ.search(texto)
    if m:
        registro.cnpj_cpf = m.group(1)


# A coluna "Data" às vezes não existe (ex.: Baturité a partir de jul/2026
# passou a exportar sem data por lançamento) — prefixo opcional.
_RE_HEADER_LISTAGEM = re.compile(r"(?:Data\s+)?Hist[oó]rico\s+Valor\s+Total")
_RE_COMPROVANTE = re.compile(r"Comprovante\s+de\s+Despesa\s+(\d+)")
_RE_TOTAL_LINHA = re.compile(r"^TOTAL\s+DA\s+CONTA\s+(.+?)\s+[\d.]+,\d{2}(?:\s+[\d,]+%)?\s*$")
# Linha de item: valor individual (obrigatório, sempre o primeiro/mais à
# esquerda) + opcionalmente total do mini-grupo (quando a linha fecha uma
# subcategoria) + opcionalmente um percentual + código de 4 dígitos no fim.
# O total do mini-grupo às vezes vem SEM percentual (ex.: Baturité a partir
# de jul/2026: "1.204,14 4.281,01 0007", sem "%") — os dois sufixos são
# independentes um do outro, e o "search" com âncora em "$" sempre casa a
# partir do primeiro valor decimal válido (o individual), nunca o total.
_RE_ITEM_LINHA = re.compile(
    r"([\d.]+,\d{2})(?:\s+[\d.]+,\d{2})?(?:\s+[\d,]+%)?\s+(\d{4})\s*$"
)
# Algumas variantes do ContasData (ex.: Dueto Morumbi/manager_adm_pdf) têm uma
# coluna extra "Nº lancto." (número de 8 dígitos) antes da data — o prefixo
# numérico é opcional pra continuar funcionando nas variantes sem essa coluna.
_RE_DATA_INICIO = re.compile(r"^(?:\d+\s+)?(\d{2}/\d{2}/\d{4})")


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
            registro = RegistroComprovante(
                pagina=pagina,
                tipo_documento="comprovante_anexado",
                codigo=codigo,
                texto_bruto=f"Comprovante de Despesa {codigo}",
            )
            _preencher_via_ocr(registro, caminho, pagina)
            registros.append(registro)

        return registros
