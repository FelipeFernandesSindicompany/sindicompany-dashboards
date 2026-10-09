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
    # Comprovante Loggi (motoboy/entrega) — "Valor do pedido" aparece 2x
    # (rótulo com o valor, e o valor sozinho de novo logo abaixo) — inline,
    # sem o problema de coluna desalinhada dos outros formatos.
    re.compile(r"Valor do pedido:?\s*R\$\s*([\d.]+,\d{2})", re.IGNORECASE),
    # "Demonstrativo de Pagamento" (holerite/contracheque Verti — folha de
    # pagamento de funcionários, ex.: Port Saint Tropez) — fecha com
    # "Valor liquido <valor>", sem "R$" e sem dois-pontos. NFS-e de prestador
    # autônomo (ex.: Prefeitura de Barueri) usa a variante "Valor liquido a
    # ser pago R$ <valor>" — o texto entre "líquido" e o valor é opcional.
    re.compile(r"Valor\s*l[ií]quido(?:\s+a\s+ser\s+pago)?:?\s*(?:R\$)?\s*([\d.]+,\d{2})", re.IGNORECASE),
    # Relação de Empregados p/ FGTS (VERTI) — fecha com "Total a recolher FGTS".
    re.compile(r"Total a recolher FGTS:?\s*([\d.]+,\d{2})", re.IGNORECASE),
    # Relatório Analítico DARF-PIS / Demonstrativo do Cálculo do I.R.R.F.
    # (VERTI) — ambos fecham com "Total da Empresa: X,XX" e, no caso do PIS,
    # um segundo valor (a base de cálculo) logo depois na mesma linha — o
    # capture group pega sempre o PRIMEIRO valor após o rótulo, que é a
    # retenção em si, nunca a base.
    re.compile(r"Total d[ae] Empresa:?\s*([\d.]+,\d{2})", re.IGNORECASE),
    # Guia do FGTS Digital — fecha com "Total da Guia: X,XX" (valor já somado
    # de todos os recolhimentos/consignados da guia, não precisa de âncora
    # com busca em bloco — vem sempre colado na mesma linha).
    re.compile(r"Total da Guia:?\s*([\d.]+,\d{2})", re.IGNORECASE),
    # "Solicitação de Pagamentos" (formulário interno da administradora,
    # preenchido pra autorizar um pagamento sem boleto/comprovante bancário
    # próprio, ex.: mão de obra/serviço avulso) — sempre "VALOR A PAGAR: R$ X,XX".
    re.compile(r"VALOR A PAGAR:?\s*R\$\s*([\d.]+,\d{2})", re.IGNORECASE),
    # Boleto simples de fornecedor (ex.: "Aqui está seu boleto", layout tipo
    # Asaas) — cabeçalho "Vencimento Valor" seguido da linha de dados com
    # data + "R$ X,XX", tudo antes da linha digitável.
    re.compile(r"Vencimento\s*Valor\s*\n\s*\d{2}/\d{2}/\d{4}\s*R\$\s*([\d.]+,\d{2})", re.IGNORECASE),
]
# "Nota de Reembolso de Despesas" (VERTI, ex.: taxas de xerox/correio/gestão
# repassadas ao condomínio) fecha com "Total Geral da Nota de Reembolso de
# Desp[esas]" — mas o OCR corrompe "Reembolso" de formas diferentes conforme
# a página ("R bolso", "Rebolso") e às vezes o valor sai colado na mesma
# linha do rótulo, às vezes só reaparece depois de um bloco de outros
# metadados (Número/Data de Emissão/Competência) — mesma leitura fora de
# ordem já vista em outros formatos, daí usar o último valor bruto depois da
# âncora (ver _ultimo_valor_apos_ancora), não um regex de captura direta.
_RE_NOTA_REEMBOLSO_TOTAL = re.compile(r"Total Geral.{0,25}bolso de Desp\S*", re.IGNORECASE)
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
#   - "VALOR DO DOCUMENTO"/"(=) Valor do Documento" (segunda via de fatura de
#     concessionária, ex.: Eletropaulo/Enel; ou boleto bancário genérico
#     Bradesco/Santander/Itaú com "(=) Valor do Documento"): o valor do
#     documento/título em si — tolerante a "Valor" saindo corrompido no OCR
#     ("Valar", "Vaìor" etc., confirmado em dados reais), sempre mantendo
#     "do Documento" reconhecível.
#   - "Valor Total" (guia de tributos Bradesco/DARF SEM "Lançamento
#     consolidado" — ou seja, uma retenção só, não N somadas): aqui o valor
#     agregado da página É o valor individual, não tem ambiguidade — só
#     testada DEPOIS de "Lançamento consolidado" na ordem de chamadas em
#     _preencher_via_ocr, pra nunca virar o valor errado num DARF consolidado.
# "(CONSOLIDADO)" (formato GK ADM/Ciudad Real, confirmado em dados reais) é
# outra grafia do MESMO sinal — o rótulo completo "Lançamento consolidado"
# não aparece nesse formato, só a marca entre parênteses colada no número do
# lançamento (ex.: "33504500 (CONSOLIDADO)").
_RE_LANCAMENTO_CONSOLIDADO = re.compile(r"Lan\S*amento consolidado|\(CONSOLIDADO\)", re.IGNORECASE)
# O "do " entre "Va..." e "[Dd]ocumento" é opcional — confirmado em dados
# reais (Ciudad Real) um boleto cujo rótulo é só "Valor documento" (2
# palavras, sem o "do" solto no meio) em vez de "Valor do Documento" (3
# palavras) — mesmo rótulo, grafia mais curta. Superset do padrão anterior,
# nunca estreita o que já casava.
_RE_VALOR_DO_DOCUMENTO = re.compile(r"Va.{1,4}\s*(?:do\s+)?[Dd]ocumento", re.IGNORECASE)
_RE_ANCORA_VALOR_TOTAL = re.compile(r"alor Total", re.IGNORECASE)  # sem exigir "V"/"v" — OCR às vezes gruda um caractere solto antes ("vValor Total")
_RE_PRIMEIRO_VALOR_RS = re.compile(r"R\$\s*([\d.]+,\d{2})")
# Boleto tipo PJBank/DDA (ex.: prestador de serviço cobrando via duplicata)
# tem seu próprio rótulo direto "Valor total da cobrança R$ X,XX", perto do
# topo da página — mais confiável que a âncora genérica "Valor do Documento"
# abaixo, que nesses boletos específicos vem seguida por uma linha de aviso
# de "Multa/Juros" (ex.: "Após vencimento: Multa 2,00%= R$7,98 Juros 0,33%
# a.d.= R$1,31/dia") ANTES do valor de verdade — confirmado em dados reais
# que isso fazia a busca por âncora (bounded ou não) confundir a TAXA de
# multa/juros com o valor total da cobrança. Testada ANTES da âncora
# "Valor do Documento" na cadeia principal por causa disso.
_RE_VALOR_TOTAL_COBRANCA = re.compile(r"Valor total da cobran\S*a:?\s*R\$\s*([\d.]+,\d{2})", re.IGNORECASE)

# "Demonstrativo para Faturamento de Serviços Prestados" (ex.: Correios/AGF)
# fecha com "Total da Operação"/"Total do Departamento", mas os VALORES da
# tabela não têm "R$" (célula bruta tipo "161,70") — e confirmado em dados
# reais que essa tabela às vezes intercala uma coluna de PREÇO UNITÁRIO
# menor ("P.Cúbico", ex.: "3,85") antes do valor total de verdade, na mesma
# leitura fora de ordem que afeta outros formatos. Por isso pega o ÚLTIMO
# valor "X,XX" depois da âncora "Total do Departamento" (que fecha a
# página), não o primeiro — o total de verdade é sempre o último número
# antes de "Voltar ao Índice".
_RE_TOTAL_DEPARTAMENTO = re.compile(r"Total d[ao] Departamento", re.IGNORECASE)
_RE_VALOR_BRUTO = re.compile(r"([\d.]+,\d{2})")

# "Documento de Arrecadação de Receitas Federais" (DARF/GPS consolidado,
# gerado pelo sistema SENDA) — confirmado em dados reais (Port Saint Tropez,
# 11 comprovantes de despesa distintos, mesmo recibo e mesmo total) que este
# documento fecha com "[Vv]ator/[Vv]alor Total do Documento" seguido do valor
# AGREGADO de várias retenções (INSS, IRRF, contribuições de terceiros etc.)
# pagas de uma vez só — nunca o valor de UMA retenção específica. O "N°
# Recibo Declaração" é o identificador estável que amarra os N comprovantes
# que na verdade compartilham essa MESMA guia (ver uso em
# conciliacao/matching.py::gerar_achados_lirba, que agrupa por
# (autenticacao, valor) e emite um único achado de consolidação por grupo,
# em vez de comparar cada despesa sozinha contra o total errado).
_RE_TOTAL_DO_DOCUMENTO = re.compile(r"[Tt]otal do Documento\s*\n*\s*([\d.]+,\d{2})")
_RE_RECIBO_DECLARACAO = re.compile(r"Recibo\s*Declara.{0,4}:?\s*(\d{5,})", re.IGNORECASE)

# DAMSP (guia de tributo da Prefeitura de São Paulo, ex.: "Documento de
# Arrecadação do Município de São Paulo" para ISS retido) — porta pro
# formato compartilhado o mesmo padrão já validado em
# conciliacao/condominios/palm_beach.py::_valor_apos_valor_parenteses:
# a linha de dados logo após a âncora "Valor (R$)" traz o CNPJ/CCM/competência
# ANTES do valor de verdade (confirmado em dados reais: CNPJ com vírgula na
# formatação BR já bate um "X,XX" falso, ex. "53,999.447/0001-82" → "53,99"),
# então pega sempre o ÚLTIMO valor "X,XX" da linha, não o primeiro. O "l" de
# "Valor" às vezes sai como caractere ilegível no OCR (".?" tolera isso).
# A âncora "Valor (R$)" sozinha É GENÉRICA DEMAIS pra rodar em toda página —
# confirmado em dados reais que ela também aparece como cabeçalho de coluna
# em tabelas de OUTROS documentos (ex.: fatura Sabesp, "Base de Cálculo(R$)
# Valor(R$)" da tabela de tributos PIS/COFINS), onde bateria um valor errado
# (a base de cálculo do imposto, não o total da fatura). Por isso só roda
# quando a página já foi confirmada como guia DAMSP pelo marcador abaixo —
# nunca como fallback genérico solto na cadeia principal.
_RE_DAMSP_MARCADOR = re.compile(r"DAMSP|Arrecada\S*o do Munic\S*pio", re.IGNORECASE)
# Só exige o miolo "alor" (sem o "V"/"Va" inicial) — confirmado em dados
# reais (Ciudad Real/GK ADM) que a fonte embutida nesse PDF específico
# derruba o "V" inteiro na extração de texto nativa (não é OCR: "Valor"
# vira "alor"), diferente da corrupção "V"→caractere ilegível do OCR que a
# versão anterior deste regex cobria. "alor" sozinho é substring de TODOS
# os casos já validados ("Valor", "Vator" etc.), então isso só amplia quem
# casa, nunca estreita.
_RE_ANCORA_VALOR_PARENTESES = re.compile(r"alor\s*\(R\$\)", re.IGNORECASE)
# Confirmado em dados reais (Port Saint Tropez, códigos de despesa 0041 e
# 0067): uma guia DAMSP também pode ser CONSOLIDADA — o campo "Recolhimentos
# por Código de Serviço" lista N valores menores (ex.: "R$ 8,15 (09679); R$
# 266,66 (09954)") que somam o "Valor (R$)" único da guia, mas essa mesma
# página/guia é anexada IDENTICAMENTE como comprovante de CADA código de
# despesa — comparar cada um contra o valor agregado da guia gera divergência
# falsa (8,15 ou 266,66 esperados vs 274,81 encontrado). Mesmo problema do
# DARF/GPS consolidado da Receita Federal (ver _RE_TOTAL_DO_DOCUMENTO acima),
# resolvido do mesmo jeito: guarda o valor da guia + um identificador estável
# do documento (aqui, o "Documento No" impresso na linha digitável — mesmo
# número em ambas as vias/cópias da guia, confirmado em dados reais) e deixa
# conciliacao/matching.py::gerar_achados_lirba decidir se 2+ códigos
# compartilham a mesma guia (vira consolidação) ou se é só 1 código sozinho
# (segue o fluxo normal de comparação individual, sem alteração de comportamento).
# Tolera espaço embutido no meio da sequência de dígitos (confirmado em
# dados reais, Ciudad Real: "Documento No. 023 0055104975", onde o "\d{2}"
# original não bate por causa do espaço logo depois) — o valor final tem os
# espaços removidos antes de virar `autenticacao`, então o identificador
# fica estável mesmo com a extração de texto quebrando o número em pedaços.
_RE_DAMSP_DOCUMENTO_NO = re.compile(r"Documento No\.?\s*([\d\s]{8,20}\d)", re.IGNORECASE)


def _ultimo_valor_apos_ancora(texto: str, ancora: re.Pattern) -> re.Match | None:
    """Como _valor_apos_ancora, mas pega o ÚLTIMO valor (sem exigir "R$"),
    não o primeiro — ver comentário acima."""
    m_ancora = ancora.search(texto)
    if not m_ancora:
        return None
    matches = list(_RE_VALOR_BRUTO.finditer(texto, m_ancora.end()))
    return matches[-1] if matches else None


def _ultimo_valor_na_proxima_linha(texto: str, ancora: re.Pattern, max_linhas: int = 3) -> re.Match | None:
    """Como _ultimo_valor_apos_ancora, mas bounded às primeiras `max_linhas`
    não vazias depois da âncora — nunca deixa a busca vagar página adentro e
    pegar um valor de item de linha de um documento anexado mais abaixo (ver
    docstring de palm_beach.py::_valor_apos_valor_parenteses, mesmo bug já
    resolvido lá)."""
    m_ancora = ancora.search(texto)
    if not m_ancora:
        return None
    linhas_nao_vazias = 0
    for linha in texto[m_ancora.end():].split("\n"):
        if not linha.strip():
            continue
        matches = list(_RE_VALOR_BRUTO.finditer(linha))
        if matches:
            return matches[-1]
        linhas_nao_vazias += 1
        if linhas_nao_vazias >= max_linhas:
            break
    return None

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
# Variante NFS-e da Prefeitura de São Paulo (portal "Nota Gateway", ex.:
# VERTI como prestadora) não usa o rótulo "Contribuições Sociais Retidas" —
# em vez disso lista as retenções em colunas soltas ("INSS (R$) IRRF (R$)
# CSLL (R$) COFINS (R$) PIS/PASEP (R$) IPI(R$)") seguidas de uma linha de
# valores na mesma ordem (confirmado em dados reais: "0,00 0,00 28,76 86,28
# 18,69 0,00" somando R$ 133,73, que batia exatamente com bruto R$ 2.876,00
# menos líquido esperado R$ 2.742,27). Quando não há retenção nenhuma (ex.:
# prestador autônomo), essa linha de valores simplesmente não existe no OCR
# (pula direto pro "Código do Serviço" seguinte) — soma zero, sem efeito.
_RE_NFS_E_RETENCOES_COLUNAS_ANCORA = re.compile(r"PIS/PASEP\s*\(R\$\)", re.IGNORECASE)


def _retencao_nfs_e_colunas(texto: str) -> float:
    m_ancora = _RE_NFS_E_RETENCOES_COLUNAS_ANCORA.search(texto)
    if not m_ancora:
        return 0.0
    linhas_vistas = 0
    for linha in texto[m_ancora.end():].split("\n"):
        if not linha.strip():
            continue
        numeros = re.findall(r"[\d.]+,\d{2}", linha)
        if len(numeros) >= 4:  # INSS, IRRF, CSLL, COFINS, PIS/PASEP[, IPI]
            return sum(_num(n) for n in numeros)
        linhas_vistas += 1
        if linhas_vistas >= 2:
            break
    return 0.0


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
    preencher_de_texto(registro, texto)


def preencher_de_texto(registro: RegistroComprovante, texto: str) -> None:
    """
    Mesma cadeia de regras de `_preencher_via_ocr`, mas a partir de um texto
    já em mãos — reutilizável por conciliadores específicos que obtêm o
    texto do comprovante de outra forma (ex.: texto nativo de um PDF
    baixado externamente, não OCR de uma página do PDF de origem — ver
    conciliacao/condominios/ciudad_real.py). Nunca lança.
    """
    if len(texto.strip()) < _OCR_TEXTO_MINIMO:
        return
    # Sempre grava o texto, mesmo se nenhum valor for reconhecido a
    # seguir — a camada de interpretação (conciliacao/interpretacao.py) usa
    # o tamanho de texto_bruto pra distinguir "página genuinamente em
    # branco" de "tem conteúdo, só não reconhecido ainda" na narrativa
    # automática; sem isso, os dois casos ficavam indistinguíveis (bug já
    # visto: uma página de DARF real com bastante texto virou "está em
    # branco" na narrativa, só porque nenhuma regra de valor bateu).
    registro.texto_bruto = texto

    valor: float | None = None
    if _RE_NFS_E_MARCADOR.search(texto):
        m_bruto = _RE_NFS_E_VALOR_BRUTO.search(texto)
        if m_bruto:
            m_retencao = _RE_NFS_E_RETENCAO.search(texto)
            retencao = _num(m_retencao.group(1)) if m_retencao else _retencao_nfs_e_colunas(texto)
            valor = _num(m_bruto.group(1)) - retencao
    # Não é "elif" — uma guia DAMSP real cita "NFS-e" de passagem (na
    # descrição do próprio ISS retido), então o marcador de NFS-e pode bater
    # sem que a página seja de fato uma nota fiscal (sem "VALOR TOTAL DO
    # SERVIÇO"); quando isso acontece, `valor` continua None e cai aqui.
    if valor is None and _RE_DAMSP_MARCADOR.search(texto):
        m_damsp = _ultimo_valor_na_proxima_linha(texto, _RE_ANCORA_VALOR_PARENTESES)
        if m_damsp:
            # Não vira `valor` local pra comparação individual direta — uma
            # guia DAMSP pode ser consolidada (ver comentário acima de
            # _RE_DAMSP_DOCUMENTO_NO), então segue o mesmo caminho do DARF da
            # Receita Federal: guarda valor + identificador do documento e
            # deixa gerar_achados_lirba() decidir (agrupa se 2+ códigos
            # compartilharem o mesmo documento, senão segue normal).
            registro.valor = _num(m_damsp.group(1))
            m_doc_no = _RE_DAMSP_DOCUMENTO_NO.search(texto)
            if m_doc_no:
                registro.autenticacao = re.sub(r"\s+", "", m_doc_no.group(1))
            return
    if valor is None:
        m_valor = (
            _valor_apos_ancora(texto, _RE_LANCAMENTO_CONSOLIDADO)
            or _RE_VALOR_TOTAL_COBRANCA.search(texto)
            or _valor_apos_ancora(texto, _RE_VALOR_DO_DOCUMENTO)
            or _ultimo_valor_na_proxima_linha(texto, _RE_VALOR_DO_DOCUMENTO)
            or _valor_apos_ancora(texto, _RE_ANCORA_VALOR_TOTAL)
            or _ultimo_valor_apos_ancora(texto, _RE_TOTAL_DEPARTAMENTO)
            or _ultimo_valor_apos_ancora(texto, _RE_NOTA_REEMBOLSO_TOTAL)
            or next((m for m in (regex.search(texto) for regex in _RE_OCR_VALORES_EM_ORDEM) if m), None)
        )
        if not m_valor:
            # "Documento de Arrecadação de Receitas Federais" (DARF/GPS
            # consolidado) fecha com "Total do Documento" — mas esse valor é
            # o AGREGADO de várias retenções pagas de uma vez, nunca o valor
            # individual de UM código específico (confirmado em dados reais:
            # 11 códigos de despesa diferentes compartilhavam o mesmo "N°
            # Recibo Declaração" e o mesmo total). Por isso NÃO vira
            # `registro.valor` direto pra comparação 1:1 — fica guardado
            # (valor = total, autenticacao = identificador do recibo) pra
            # conciliacao/matching.py::gerar_achados_lirba detectar o grupo
            # de códigos que compartilham o mesmo recibo+total e tratar como
            # consolidação (mesma lógica de "soma bate com o total pago de
            # uma vez" já usada em gerar_achados() pro Addomus), em vez de
            # comparar cada um sozinho contra o valor agregado errado.
            m_total_doc = _RE_TOTAL_DO_DOCUMENTO.search(texto)
            if m_total_doc:
                registro.valor = _num(m_total_doc.group(1))
                m_recibo = _RE_RECIBO_DECLARACAO.search(texto)
                if m_recibo:
                    registro.autenticacao = m_recibo.group(1)
            return
        valor = _num(m_valor.group(1))
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
    # Confirmado em dados reais (Upper Itaim) que, quando o rótulo
    # "Fornecedor:" não tem valor colado na mesma linha (texto em ordem de
    # leitura embaralhada), o "\s*(.+)" acaba pulando linhas em branco e
    # capturando o PRÓXIMO rótulo do formulário (ex.: "Conta contábil:") como
    # se fosse o valor do fornecedor — sempre reconhecível por terminar em
    # ":". Descarta nesse caso em vez de exibir um rótulo como se fosse dado.
    if m and not m.group(1).strip().endswith(":"):
        registro.fornecedor = m.group(1).strip()[:200]
    m = _RE_OCR_CPF_CNPJ.search(texto)
    if m:
        registro.cnpj_cpf = m.group(1)


# ─────────────────────────────────────────────────────────────────────────────
# Leitura do anexo COMPLETO de uma despesa (todas as páginas "Comprovante de
# Despesa <código>"). No ContasData o anexo de uma despesa tem 1 a dezenas de
# páginas (guia/boleto, Nota Fiscal, comprovante bancário, contrato...), na
# ordem em que o síndico anexou — o comprovante bancário quase nunca é a
# primeira. A regra de ouro aqui: o valor que a LISTAGEM declara tem de ser
# PROCURADO no texto das páginas do anexo (formatos "1.234,56" e variações de
# OCR); só quando ele não aparece em nenhuma página (nem na leitura a 300 dpi)
# é que se lê o valor "de verdade" do comprovante e se compara — aí a diferença
# é divergência real, não artefato de ler a página errada.
# ─────────────────────────────────────────────────────────────────────────────
_MAX_PAGINAS_REOCR = 12
# Páginas de comprovante bancário / pagamento (onde o valor efetivamente pago e as datas estão).
_RE_PAGINA_PAGAMENTO = re.compile(
    r"Comprovante\s+de\s+(?:Pagamento|Transfer|Opera[cç]|Dep[oó]sito|Agendamento|Liquida)|"
    r"Dados\s+do\s+(?:Lan[cç]amento|Pagamento)|Autentica[cç][aã]o(?!\s+mec[aâ]nica)|Comprovante\s+PIX|Pagamento\s+realizado|"
    r"Valor\s+(?:do\s+)?lan\S*to|Conta\s+de\s+d[eé]bito|Data\s+d[ao]\s+(?:pagamento|transfer)",
    re.IGNORECASE,
)


def _regex_valor(valor: float) -> re.Pattern:
    inteiro, cent = divmod(int(round(valor * 100)), 100)
    s = str(inteiro)
    grupos = [s[max(0, i - 3):i] for i in range(len(s), 0, -3)][::-1]
    corpo = r"[.,\s]?".join(grupos)
    # (?<!\d[.,]) impede casar o miolo de um valor maior ("1.573,55" para 573,55)
    # o OCR às vezes perde o zero final dos centavos ("R$ 368,1" para 368,10): aceita a forma curta quando os
    # centavos terminam em 0 (e só se o dígito seguinte não for mais um dígito)
    centavos = f"(?:{cent:02d}|{cent // 10})" if cent % 10 == 0 and cent else f"{cent:02d}"
    return re.compile(rf"(?<!\d)(?<!\d[.,]){corpo}\s?[,.]\s?{centavos}(?!\d)")


def valor_aparece_no_texto(texto: str | None, valor: float | None) -> bool:
    """True se `valor` (ex.: 1234.5) aparece formatado como moeda no texto ("1.234,50" e variações de OCR)."""
    if not texto or not valor or valor <= 0:
        return False
    return bool(_regex_valor(valor).search(texto))


def eh_pagina_pagamento(texto: str) -> bool:
    return bool(_RE_PAGINA_PAGAMENTO.search(texto or ""))


# Nº de Nota Fiscal citado na descrição da listagem ("... - NF. 24282 - FORT SERV", "NF.: 14537", "NFS-e 88").
# O número não pode ser o começo de um VALOR ("NF 200,00" é a palavra "NF" solta seguida do valor da linha).
RE_NF_NA_DESCRICAO = re.compile(r"\bN\.?F\.?S?\.?-?E?\.?:?\s*(\d{2,})(?![\d.]*,\d{2}\b)", re.IGNORECASE)
# Marcadores de que o texto de uma página é (ou contém) uma Nota Fiscal / documento fiscal equivalente. Inclui as
# leituras truncadas que o OCR produz de "DANFE"/"DANFSe".
RE_MARCADOR_NF = re.compile(
    r"NOTA\s+FISCAL|NOTA\s+FATURA|NFS-?E|DANF[A-Z]?|NF-?E\b|CHAVE\s+DE\s+ACESSO|Identifica\S*\s+do\s+Emitente|"
    r"Documento\s+Auxiliar|NOTA\s+DE\s+REEMBOLSO|C[oó]digo\s+de\s+Verifica\S*o|"
    r"C[aá]lculo\s+do\s+ISS|VALOR\s+TOTAL\s+DOS\s+SERVI|TOMADOR\s+D[EO]\s+SERVI|PRESTADOR\s+D[EO]\s+SERVI",
    re.IGNORECASE,
)
_RE_PAGINA_BOLETO = re.compile(r"Benefici[aá]rio|Linha\s+Digit|Recibo\s+do\s+Pagador|Sacador|Ficha\s+de\s+Compensa", re.IGNORECASE)
_RE_SPLIT_PAGINAS = re.compile(r"\[P[aá]gina (\d+)\]\n")


def tem_marcador_nf(texto: str | None) -> bool:
    return bool(RE_MARCADOR_NF.search(texto or ""))


def paginas_do_texto_bruto(texto_bruto: str | None) -> list[tuple[int, str]]:
    """Separa o `texto_bruto` de um comprovante multi-página ("[Página N]\\n...") em [(pagina, texto)]."""
    partes = _RE_SPLIT_PAGINAS.split(texto_bruto or "")
    return [(int(partes[i]), partes[i + 1]) for i in range(1, len(partes) - 1, 2)]


def numero_nf_em_documento(texto_bruto: str | None, numero: str) -> bool:
    """O nº de NF citado na listagem aparece numa página que NÃO é comprovante bancário nem boleto (esses só
    repetem o histórico/número do documento, não provam que a NF foi anexada)?"""
    n = numero.lstrip("0") or numero
    if len(n) >= 4:
        corpo = r"[.\s]?".join([n[:-3], n[-3:]])  # "1378" também como "1.378"
    else:
        corpo = re.escape(n)
    padrao = re.compile(rf"(?<!\d)0*{corpo}(?!\d)")
    for _p, t in paginas_do_texto_bruto(texto_bruto):
        if eh_pagina_pagamento(t) or _RE_PAGINA_BOLETO.search(t):
            continue
        # a própria capa "Comprovante de Despesa" repete a descrição da listagem (com o nº da NF) — não conta
        t_sem_capa = "\n".join(l for l in t.split("\n") if not RE_NF_NA_DESCRICAO.search(l))
        if padrao.search(t_sem_capa):
            return True
    return False


# Identificador estável de uma GUIA de tributo (DARF/GPS da Receita Federal, DAMSP): o mesmo documento é anexado
# a vários códigos de despesa (uma retenção por código, guia única consolidada). Serve para o matching agrupar
# esses códigos em vez de comparar cada retenção com o total da guia.
_RE_IDENT_GUIA = [
    re.compile(r"Recibo\s*Declara.{0,4}:?\s*(\d{5,})", re.IGNORECASE),
    re.compile(r"N[uú\S]mero\s+do\s+Documento:?\s*(\d{2}[\d.\-\s]{10,24}\d)", re.IGNORECASE),
    re.compile(r"Documento No\.?\s*([\d\s]{8,20}\d)", re.IGNORECASE),
]


def identificador_guia(texto: str | None) -> str | None:
    for rx in _RE_IDENT_GUIA:
        m = rx.search(texto or "")
        if m:
            return re.sub(r"\s+", "", m.group(1))
    return None


def resolver_comprovante(registro: RegistroComprovante, paginas: list, esperados: list[float],
                         definitivo: bool = False) -> str:
    """
    Preenche `registro` (comprovante de UM código) a partir de todas as suas páginas.

    paginas: [(pagina_1based, [variantes de texto da página])] — variantes = leituras OCR da mesma página
    (ex.: 300 dpi e 150 dpi), tentadas nessa ordem.
    esperados: valor(es) da listagem para este código.

    Retorna "confirmado" (algum valor esperado aparece no anexo: registro.valor = esse valor, registro.pagina =
    a página que o mostra, de preferência o comprovante bancário), "lido" (nenhum valor esperado achado; o valor
    lido do melhor comprovante vai em registro.valor para o matching comparar) ou "vazio" (nada legível).
    "fraco": o valor listado só aparece em página que NÃO é comprovante bancário (NF, boleto...) enquanto uma página
    de pagamento traz outro valor — pode ser erro de OCR no comprovante (relido em 300 dpi pelo chamador) ou
    divergência real; com `definitivo=True` (última leitura) a dúvida vira "lido" (o matching compara).
    """
    textos = [(p, [t for t in vs if t and t.strip()]) for p, vs in paginas]
    # todas as leituras da página (ex.: 300 dpi e 150 dpi) ficam no texto: um marcador de NF ou um valor que só uma
    # delas leu continua visível para o matching
    todos = "\n".join(f"[Página {p}]\n" + "\n".join(dict.fromkeys(vs)) for p, vs in textos if vs)
    if len(todos.strip()) >= _OCR_TEXTO_MINIMO:
        registro.texto_bruto = todos
    else:
        return "vazio"

    def _dados_da_pagina(pagina: int, vs: list[str]) -> RegistroComprovante | None:
        for t in vs:
            tmp = RegistroComprovante(pagina=pagina, tipo_documento="comprovante_anexado", codigo=registro.codigo)
            preencher_de_texto(tmp, t)
            if tmp.valor > 0 or tmp.pagamento or tmp.vencimento:
                return tmp
        return None

    def _copiar_datas(tmp: RegistroComprovante | None) -> None:
        if tmp is None:
            return
        registro.vencimento = tmp.vencimento or registro.vencimento
        registro.pagamento = tmp.pagamento or registro.pagamento
        registro.fornecedor = tmp.fornecedor or registro.fornecedor
        registro.cnpj_cpf = tmp.cnpj_cpf or registro.cnpj_cpf

    # 1) o valor da listagem aparece em alguma página do anexo?
    for esperado in esperados:
        achados = [(p, vs) for p, vs in textos if any(valor_aparece_no_texto(t, esperado) for t in vs)]
        if not achados:
            continue
        bancarias = [(p, vs) for p, vs in achados if any(eh_pagina_pagamento(t) for t in vs)]
        fraco = False
        if not bancarias:
            for p, vs in textos:
                if not any(eh_pagina_pagamento(t) for t in vs):
                    continue
                if any(_RE_LANCAMENTO_CONSOLIDADO.search(t) for t in vs):
                    # recibo consolidado: o "valor pagto" é o total de vários lançamentos e não conflita; só o
                    # "Valor do lancto" (individual), quando legível, pode contradizer a listagem
                    for t in vs:
                        m_l = _RE_OCR_VALORES_EM_ORDEM[0].search(t)
                        if m_l and abs(_num(m_l.group(1)) - esperado) > 0.011:
                            fraco = True
                    if fraco:
                        break
                    continue
                tmp = _dados_da_pagina(p, vs)
                if tmp is not None and tmp.valor > 0 and abs(tmp.valor - esperado) > 0.011:
                    fraco = True
                    break
        if fraco and definitivo:
            continue  # cai para a leitura do comprovante bancário (passo 2): o matching compara e aponta divergência
        p_ev, vs_ev = (bancarias or achados)[0]
        registro.pagina = p_ev
        registro.valor = esperado
        # datas/fornecedor vêm da página de pagamento (a que mostra o valor, ou qualquer outra de pagamento)
        pg_pag = bancarias[0] if bancarias else next(((p, vs) for p, vs in textos if any(eh_pagina_pagamento(t) for t in vs)), None)
        if pg_pag:
            _copiar_datas(_dados_da_pagina(*pg_pag))
        return "fraco" if fraco else "confirmado"

    # 1b) lançamento que soma vários documentos (ex.: salário + reembolsos pagos em comprovantes separados; vários
    #     recibos de motoboy num reembolso): o valor da listagem é a soma dos valores principais dos documentos do
    #     anexo — primeiro só os comprovantes bancários, depois todas as páginas (um valor por página)
    from itertools import combinations
    grupos_soma: list[list[tuple[int, float]]] = []
    so_pagamento: list[tuple[int, float]] = []
    todas_paginas: list[tuple[int, float]] = []
    for p, vs in textos:
        tmp = _dados_da_pagina(p, vs)
        if tmp is not None and tmp.valor > 0:
            todas_paginas.append((p, tmp.valor))
            if any(eh_pagina_pagamento(t) for t in vs):
                so_pagamento.append((p, tmp.valor))
    # entre páginas de documentos a mesma quantia repetida costuma ser a cópia/segunda via do mesmo documento
    unicos: dict[float, tuple[int, float]] = {}
    for p_, v_ in todas_paginas:
        unicos.setdefault(round(v_, 2), (p_, v_))
    grupos_soma = [so_pagamento, list(unicos.values())]
    for grupo in grupos_soma:
        if not 2 <= len(grupo) <= 8:
            continue
        for esperado in esperados:
            for n in range(2, len(grupo) + 1):
                for comb in combinations(grupo, n):
                    if abs(sum(v for _p, v in comb) - esperado) <= 0.011:
                        registro.pagina = comb[0][0]
                        registro.valor = esperado
                        pg_pag = next(((p, vs) for p, vs in textos if p == comb[0][0]), None)
                        if pg_pag:
                            _copiar_datas(_dados_da_pagina(*pg_pag))
                        return "confirmado"

    # 1c) valor DERIVADO pela cadeia de regras (ex.: NFS-e = valor bruto menos as retenções, que nunca aparece impresso)
    #     igual ao da listagem em alguma das leituras da página
    for p, vs in textos:
        for t in vs:
            tmp = RegistroComprovante(pagina=p, tipo_documento="comprovante_anexado", codigo=registro.codigo)
            preencher_de_texto(tmp, t)
            if tmp.valor > 0 and any(abs(tmp.valor - e) <= 0.011 for e in esperados):
                registro.pagina = p
                registro.valor = tmp.valor
                _copiar_datas(tmp)
                return "confirmado"

    # 2) nenhum valor esperado em lugar nenhum: lê o valor do melhor comprovante (bancário primeiro)
    ordem = sorted(textos, key=lambda x: 0 if any(eh_pagina_pagamento(t) for t in x[1]) else 1)
    for p, vs in ordem:
        tmp = _dados_da_pagina(p, vs)
        if tmp is not None and tmp.valor > 0:
            registro.pagina = p
            registro.valor = tmp.valor
            registro.autenticacao = tmp.autenticacao or next(
                (i for _pp, vv in textos for t in vv if (i := identificador_guia(t))), None)
            if not registro.autenticacao and not any(eh_pagina_pagamento(t) for t in vs) and esperados:
                # Sem comprovante bancário legível e sem guia: o valor da cadeia pode ser qualquer número do
                # documento (ex.: "32,00" de um recibo de locação de R$ 1.600,00). Para o relatório mostrar o que o
                # documento realmente declara, usa o valor monetário do anexo mais próximo do listado.
                esp = esperados[0]
                cand = [v for _pp, vv in textos for t in vv for v in _valores_monetarios(t)
                        if 0.5 * esp <= v <= 1.5 * esp and abs(v - esp) > 0.011]
                if cand:
                    registro.valor = min(cand, key=lambda v: abs(v - esp))
            _copiar_datas(tmp)
            return "lido"
    return "vazio"


def _valores_monetarios(texto: str) -> list[float]:
    return [_num(x) for x in re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", texto or "")]


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


def _texto_em_linhas(pagina_fitz, tolerancia: float = 3.0) -> str:
    """Texto de uma página do fitz agrupado em linhas visuais (palavras com a mesma altura, da esquerda para
    a direita) — equivalente ao `extract_text()` do pdfplumber para as tabelas do ContasData."""
    palavras = pagina_fitz.get_text("words")
    palavras.sort(key=lambda w: (w[1], w[0]))
    linhas: list[list] = []
    for w in palavras:
        if linhas and abs(w[1] - linhas[-1][0]) <= tolerancia:
            linhas[-1][1].append(w)
        else:
            linhas.append([w[1], [w]])
    return "\n".join(" ".join(x[4] for x in sorted(l[1], key=lambda x: x[0])) for l in linhas)


MARCADOR_PAGINA_EM_BRANCO = "[PAGINA EM BRANCO]"
_LIMITE_NAO_BRANCO = 0.010      # fração de pixels não brancos abaixo da qual a página é só cabeçalho (medido: vazia 0,34%, comprovante 7%)


def paginas_em_branco(caminho: Path, paginas_1based: list) -> set:
    """Páginas "Comprovante de Despesa" que têm só o cabeçalho do sistema: nenhum documento anexado (a imagem é só o
    ícone "voltar ao índice"). Sem isso o OCR "não achava valor" e o relatório dizia "formato não reconhecido", quando
    na verdade o comprovante simplesmente não foi anexado. Nunca lança: na dúvida, a página NÃO é dada como branca."""
    brancas: set = set()
    try:
        import fitz
        doc = fitz.open(str(caminho))
        try:
            for p in paginas_1based:
                pg = doc[p - 1]
                if len(pg.get_text().strip()) > 200:
                    continue
                pm = pg.get_pixmap(dpi=60, colorspace=fitz.csGRAY)
                amostra = pm.samples
                if sum(1 for b in amostra if b < 235) / max(len(amostra), 1) < _LIMITE_NAO_BRANCO:
                    brancas.add(p)
        finally:
            doc.close()
    except Exception:
        return set()
    return brancas


class ConciliadorLirbaPDF(ConciliadorBase):
    """Extrai despesas listadas (Demonstrativo de Despesas) e páginas de
    evidência (Comprovante de Despesa) da pasta Lirba/ContasData."""

    def extrair_comprovantes(self, caminho: Path) -> list:
        """Despesas listadas + UM registro de comprovante por código, lido a partir de TODAS as páginas
        "Comprovante de Despesa <código>" (ver `resolver_comprovante`): o anexo de uma despesa costuma ter
        várias páginas (guia/boleto, Nota Fiscal, comprovante bancário) e o comprovante bancário raramente é
        a primeira — ler só a primeira (como era antes) produzia divergências e "NF ausente" falsas."""
        registros, primeira_pagina_comprovante = self._extrair_despesas_listadas(caminho)
        paginas_por_codigo = dict(getattr(self, "_paginas_por_codigo", None) or {})
        for codigo, pagina in primeira_pagina_comprovante.items():
            paginas_por_codigo.setdefault(codigo, [pagina])

        esperados: dict[str, list[float]] = {}
        for d in registros:
            esperados.setdefault(d.codigo, []).append(d.valor)

        todas = sorted({p for ps in paginas_por_codigo.values() for p in ps})
        # Página de comprovante em branco = "sem anexo" só nos condomínios que pedem (parser_config.pagina_em_branco_sem_anexo).
        brancas = paginas_em_branco(caminho, todas) if (self.config.get("parser_config") or {}).get("pagina_em_branco_sem_anexo") else set()
        textos = ocr.ocr_paginas(caminho, [p - 1 for p in todas if p not in brancas])  # {índice 0-based: texto}, 150 dpi
        # variantes de leitura por página (índice 0-based -> textos), da mais nítida para a mais crua
        extras: dict[int, list[str]] = {}

        def _resolver(codigo: str, definitivo: bool = False) -> tuple[RegistroComprovante, str]:
            ps = paginas_por_codigo[codigo]
            registro = RegistroComprovante(
                pagina=ps[0], tipo_documento="comprovante_anexado", codigo=codigo,
                texto_bruto=f"Comprovante de Despesa {codigo}",
            )
            if all(p in brancas for p in ps):
                registro.texto_bruto = f"{MARCADOR_PAGINA_EM_BRANCO} Comprovante de Despesa {codigo}"
                return registro, "em_branco"
            variantes = [(p, extras.get(p - 1, []) + [textos.get(p - 1, "")]) for p in ps]
            return registro, resolver_comprovante(registro, variantes, esperados.get(codigo, []), definitivo=definitivo)

        def _paginas_reler(codigos: list[str]) -> list[int]:
            """Até _MAX_PAGINAS_REOCR páginas por código (as de pagamento primeiro) — índices 0-based."""
            alvo: set[int] = set()
            for c in codigos:
                ps = paginas_por_codigo[c]
                prioridade = sorted(ps, key=lambda p: 0 if eh_pagina_pagamento(textos.get(p - 1, "")) else 1)
                alvo.update(p - 1 for p in prioridade[:_MAX_PAGINAS_REOCR])
            return sorted(alvo)

        novos: dict[str, RegistroComprovante] = {}
        status_por_codigo: dict[str, str] = {}
        for codigo in paginas_por_codigo:
            novos[codigo], status_por_codigo[codigo] = _resolver(codigo)

        def _nao_confirmados() -> list[str]:
            return [c for c, st in status_por_codigo.items() if st not in ("confirmado", "em_branco") and esperados.get(c)]

        def _nf_em_duvida() -> list[str]:
            # a listagem cita NF, mas nenhuma página lida traz marcador de Nota Fiscal (a NF pode estar
            # numa imagem de letra miúda, como o DANFE, que o OCR a 150 dpi não lê)
            return [c for c in paginas_por_codigo
                    if status_por_codigo.get(c) != "em_branco"
                    and any(RE_NF_NA_DESCRICAO.search(d.descricao or "") for d in registros if d.codigo == c)
                    and not tem_marcador_nf(novos[c].texto_bruto)]

        if ocr.tesseract_disponivel():
            # Estágio 2 (300 dpi): páginas dos códigos cujo valor listado não apareceu em nenhuma página e
            # dos que citam NF sem marcador de NF. O OCR a 150 dpi às vezes troca um dígito ("286,00" lido
            # como "266,00") ou perde letra miúda; só se a leitura mais nítida também não achar o valor
            # ele entra como divergência real.
            pendentes_hd = sorted(set(_nao_confirmados()) | set(_nf_em_duvida()))
            if pendentes_hd:
                alvo = _paginas_reler(pendentes_hd)
                hd = ocr.ocr_paginas(caminho, alvo, dpi=300)
                for i, t in hd.items():
                    if t.strip():
                        extras.setdefault(i, []).insert(0, t)
                for c in pendentes_hd:
                    novos[c], status_por_codigo[c] = _resolver(c)
            # Estágio 2b: a listagem cita NF e ainda não há marcador de NF em nenhuma página — a NF pode ser uma
            # FOTO pequena/inclinada (ex.: DANFE fotografado) que só a imagem original ampliada deixa ler.
            sem_nf = _nf_em_duvida()
            if sem_nf:
                alvo_nf = _paginas_reler(sem_nf)
                for leitura in (ocr.ocr_paginas(caminho, alvo_nf, nativa=True),
                                ocr.ocr_paginas(caminho, alvo_nf, dpi=200, rotacao=True)):  # foto / página girada
                    for i, t in leitura.items():
                        if t.strip():
                            extras.setdefault(i, []).insert(0, t)
                for c in sem_nf:
                    novos[c], status_por_codigo[c] = _resolver(c)
            # Estágio 3 (binarizado): texto sobre fundo cinza (ex.: quadro "TOTAL" da fatura Sabesp).
            ainda = _nao_confirmados()
            if ainda:
                alvo = _paginas_reler(ainda)
                leituras = [ocr.ocr_paginas(caminho, alvo, dpi=200, limiar=lim) for lim in (100, 130)]
                leituras.append(ocr.ocr_paginas(caminho, alvo, dpi=200, rotacao=True))  # página de cabeça para baixo
                leituras.append(ocr.ocr_paginas(caminho, alvo, nativa=True))  # foto pequena/inclinada de documento
                for bin_ in leituras:
                    for i, t in bin_.items():
                        if t.strip():
                            extras.setdefault(i, []).insert(0, t)
                for c in ainda:
                    novos[c], status_por_codigo[c] = _resolver(c)

        # Última leitura: dúvidas que sobraram ("fraco") deixam de ser benefício da dúvida — o comprovante bancário
        # relido em alta resolução continua com valor diferente do listado: o matching aponta a divergência.
        for c in [c for c, st in status_por_codigo.items() if st == "fraco"]:
            novos[c], status_por_codigo[c] = _resolver(c, definitivo=True)

        registros.extend(novos.values())
        return registros

    def _ler_linhas_listagem(self, texto: str, pagina: int, cat_map: dict, registros: list, pendentes: list) -> None:
        for linha in texto.split("\n"):
            m_total = _RE_TOTAL_LINHA.match(linha.strip())
            if m_total:
                categoria_raw = m_total.group(1).strip()
                categoria = cat_map.get(categoria_raw, categoria_raw)
                for r in pendentes:
                    r.categoria_demonstrativo = categoria
                registros.extend(pendentes)
                pendentes.clear()
                continue

            m_item = _RE_ITEM_LINHA.search(linha)
            if not m_item:
                continue
            valor_str, codigo = m_item.groups()
            m_data = _RE_DATA_INICIO.match(linha.strip())
            pendentes.append(RegistroComprovante(
                pagina=pagina,
                tipo_documento="despesa_listada",
                codigo=codigo.zfill(4),
                descricao=linha.strip()[:200],
                vencimento=m_data.group(1) if m_data else None,
                valor=_num(valor_str),
                texto_bruto=linha,
            ))

    def _passada_plumber(self, caminho, doc_fitz, cat_map, registros, pendentes,
                         primeira_pagina_comprovante, paginas_por_codigo) -> None:
        """Plano B (lento): a mesma leitura, página a página, pelo pdfplumber."""
        from conciliacao.pdf_cache import pdf_plumber_aberto

        with pdf_plumber_aberto(caminho) as pdf:
            for i in range(1, len(doc_fitz) + 1):
                page = pdf.pages[i - 1]
                texto = (page.extract_text() or "").replace("ContasData", " ")
                page.flush_cache()
                m_comp = _RE_COMPROVANTE.search(texto)
                if m_comp:
                    codigo = m_comp.group(1).zfill(4)
                    primeira_pagina_comprovante.setdefault(codigo, i)
                    if i not in paginas_por_codigo.setdefault(codigo, []):
                        paginas_por_codigo[codigo].append(i)
                    continue
                if _RE_HEADER_LISTAGEM.search(texto):
                    self._ler_linhas_listagem(texto, i, cat_map, registros, pendentes)

    def _extrair_despesas_listadas(self, caminho: Path) -> tuple[list[RegistroComprovante], dict[str, int]]:
        """Só a listagem (Demonstrativo de Despesas) + em que página cada
        código de comprovante embutido começa — SEM rodar OCR nelas. Método
        separado pra conciliadores condomínio-específicos que sabem ler a
        evidência de outro jeito mais rápido/confiável que o OCR genérico
        daqui (ex.: conciliacao/condominios/ciudad_real.py, cujo upload
        completo tem texto real nas páginas de comprovante — rodar OCR nelas
        só pra descartar o resultado depois seria trabalho puro perdido)."""
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")
        import fitz

        from conciliacao.pdf_cache import pdf_plumber_aberto

        cat_map = self.parser_config.get("cat_map", {})
        registros: list[RegistroComprovante] = []
        pendentes: list[RegistroComprovante] = []  # aguardando a linha "TOTAL DA CONTA X"
        primeira_pagina_comprovante: dict[str, int] = {}
        paginas_por_codigo: dict[str, list[int]] = {}
        self._paginas_por_codigo = paginas_por_codigo

        # As páginas "Comprovante de Despesa" (75% do PDF, todas imagem) e as de listagem são lidas pelo texto
        # nativo do fitz (instantâneo). O pdfplumber só entra como plano B (ver _passada_plumber): em PDFs
        # grandes `pdf.pages` leva MINUTOS (cada página referencia centenas de imagens nos recursos), e a
        # leitura do fitz agrupada em linhas (_texto_em_linhas) produz as mesmas linhas — conferido página a
        # página contra o pdfplumber em 7 PDFs reais (zero diferença nos itens/totais extraídos).
        doc_fitz = fitz.open(str(caminho))
        try:
            candidatas_listagem = 0
            for i in range(1, len(doc_fitz) + 1):
                pagina_fitz = doc_fitz[i - 1]
                texto_nativo = pagina_fitz.get_text().replace("ContasData", " ")
                m_comp = _RE_COMPROVANTE.search(texto_nativo)
                if m_comp:
                    codigo = m_comp.group(1).zfill(4)
                    primeira_pagina_comprovante.setdefault(codigo, i)
                    paginas_por_codigo.setdefault(codigo, []).append(i)
                    continue  # página de evidência não tem linhas de despesa
                # "ContasData" é a marca-d'água do sistema (rodapé) e às vezes cola na mesma linha de uma
                # despesa (ex.: "... 0,40% 0034 ContasData"), empurrando o código pra fora do fim de linha.
                texto = _texto_em_linhas(pagina_fitz).replace("ContasData", " ")
                if not _RE_HEADER_LISTAGEM.search(texto):
                    if re.search(r"Hist[oó]rico", texto_nativo) and "Valor" in texto_nativo:
                        candidatas_listagem += 1
                    continue  # não é página de listagem nem de comprovante — ignora
                self._ler_linhas_listagem(texto, i, cat_map, registros, pendentes)
            if not registros and not pendentes and candidatas_listagem:
                # plano B: nada reconhecido pelo texto do fitz mas há páginas com cara de listagem
                self._passada_plumber(caminho, doc_fitz, cat_map, registros, pendentes,
                                      primeira_pagina_comprovante, paginas_por_codigo)
        finally:
            doc_fitz.close()

        # Sobras sem "TOTAL DA CONTA" explícito até o fim do documento
        # (não deveria acontecer no formato normal, mas não descarta dados).
        registros.extend(pendentes)

        return registros, primeira_pagina_comprovante
