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
        registros, primeira_pagina_comprovante = self._extrair_despesas_listadas(caminho)

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

    def _extrair_despesas_listadas(self, caminho: Path) -> tuple[list[RegistroComprovante], dict[str, int]]:
        """Só a listagem (Demonstrativo de Despesas) + em que página cada
        código de comprovante embutido começa — SEM rodar OCR nelas. Método
        separado pra conciliadores condomínio-específicos que sabem ler a
        evidência de outro jeito mais rápido/confiável que o OCR genérico
        daqui (ex.: conciliacao/condominios/ciudad_real.py, cujo upload
        completo tem texto real nas páginas de comprovante — rodar OCR nelas
        só pra descartar o resultado depois seria trabalho puro perdido)."""
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

        return registros, primeira_pagina_comprovante
