"""
Conciliador Alliz PDF — Monte Tabor.

Formato bem diferente dos demais: o "Demonstrativo de Despesas" (seção
"2.1") é só um resumo por categoria, SEM lançamento individual (sem data,
sem fornecedor, sem NF) — não dá pra extrair despesa_listada dali. A
evidência real está mais adiante na pasta: cada pagamento efetivado gera
sua PRÓPRIA página de comprovante bancário Itaú, mas em pelo menos 6
layouts DIFERENTES (confirmado em dados reais, jul/2026):
  "Comprovante de pagamento de boleto"      → Beneficiário + Valor do pagamento
  "Comprovante de pagamento QR Code"        → nome do recebedor + valor da transação
  "Comprovante de pagamento DARF"           → (tributo, sem beneficiário) + valor total
  "Comprovante de Transferência" (PIX)      → nome do recebedor + valor
  "Banco Itaú Comprovante de Transferência" → Nome (conta creditada) + Valor
  "Banco Itaú Comprovante de Pagamento"     → Débito Automático/Tributos Municipais,
                                               Identificação no Extrato + Valor

Cada página é auto-suficiente (mesmo espírito do GCONT — o sistema só gera
a página quando o pagamento é efetivado), então não existe "sem
comprovante" aqui. Só duas checagens de consistência (mesmo padrão do
DataDigitus/Consvicta/LFC/Lello):
  1. Duplicidade: mesmo fornecedor/recebedor + data + valor repetidos.
  2. Soma dos comprovantes extraídos x "Despesas do Período" (RESUMO
     FINANCEIRO, por conta) — ver conciliacao/matching.py::gerar_achados_datadigitus.

Muitas páginas do meio da pasta (Relatório de Recibos, Quadro Estatístico,
NFS-e de apoio) não são página de PAGAMENTO — são ignoradas (não têm
nenhum dos títulos reconhecidos abaixo).

⚠️ Qualidade de digitalização/OCR varia MUITO de mês a mês nesse
condomínio — confirmado em dados reais: jul/2026 extraiu 99,6% do valor
declarado (R$ 39.428,72 de R$ 39.578,17), mas mai/jun-2026 tiveram
corrupção severa (vírgula decimal virando ponto, dígitos virando letras —
ex.: "2.000,00" impresso como "2M00,00"), tornando boa parte dos valores
irrecuperáveis por regex. Nesses meses o achado de "soma diverge" no
relatório reflete essa limitação de qualidade da fonte, não
necessariamente uma divergência real — vale conferir manualmente antes de
tratar como achado grave.
"""
from pathlib import Path
import re

from conciliacao.base import ConciliadorBase, RegistroComprovante

_RE_TITULO = re.compile(r'Comprovante de [A-Za-zçãõáéíóúÇÃÕÁÉÍÓÚ ]+', re.IGNORECASE)

_RE_DESPESAS_PERIODO = re.compile(r'Despesas do Per[ií]odo\s+-?([\d.]+,\d{2})', re.IGNORECASE)

# Padrões de valor tentados em ordem — cada tipo de comprovante rotula o
# valor de um jeito diferente; usa o primeiro que der match.
#
# ⚠️ Algumas pastas têm qualidade de digitalização/OCR ruim — letras somem
# ou trocam no meio de palavras (ex.: "boleto" vira "bolsto"/"boto"/"boieto",
# "pagamento" vira "pagameno", "(R$):" vira "R$)" sem parênteses/dois-pontos).
# Por isso os padrões abaixo evitam depender de palavras inteiras como âncora
# — usam pontuação estrutural (que raramente corrompe) e radicais curtos
# (\w* absorve o resto, corrompido ou não).
_RE_VALORES = [
    # "(=) Valor do pagamento (R$): 405,45" — "(=)" é a âncora mais estável
    # da linha (pontuação, não corrompe); pega o 1º valor decimal depois
    # dele, pulando o CNPJ do meio (que não tem vírgula, só ponto e barra).
    re.compile(r'\(=\)\s*.*?([\d.]+,\d{2})', re.DOTALL),
    re.compile(r'valo\w*\s+(?:da\s+transa\w*|final)\w*\s*[:.]?\s*([\d.]+,\d{2})', re.IGNORECASE),
    re.compile(r'valo\w*\s+total\w*\s*[:.]?\s*R?\$?\s*([\d.]+,\d{2})', re.IGNORECASE),
    re.compile(r'valo\w*\s+do\s+documen\w*\s*[:.]?\s*R?\$?\s*([\d.]+,\d{2})', re.IGNORECASE),
    re.compile(r'valo\w*\s*[:.]?\s*R\$\s*([\d.]+,\d{2})', re.IGNORECASE),
]

# Padrões de fornecedor/recebedor, em ordem de prioridade (best-effort — só
# afeta o rótulo cosmético e a chave de duplicidade, nunca a soma).
_RE_FORNECEDORES = [
    re.compile(r'Benefici[aá]ri\w*:\s*(.+?)\s+CPF', re.IGNORECASE),
    re.compile(r'nome do receb\w*:\s*(.+)', re.IGNORECASE),
    re.compile(r'Identifica[cç][aã]o no Extrato:\s*(.+)', re.IGNORECASE),
]

# Data do pagamento/transação, em ordem de prioridade.
_RE_DATAS = [
    re.compile(r'Data de pag\w*:\s*\n?\s*(\d{2}/\d{2}/\d{4})', re.IGNORECASE),
    re.compile(r'data da transfer\w*:\s*(\d{2}/\d{2}/\d{4})', re.IGNORECASE),
    re.compile(r'(?:efetuada|realizado|efetuado)\s+em\s+(\d{2}/\d{2}/\d{4})', re.IGNORECASE),
]


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


def _primeiro_match(padroes, texto):
    for p in padroes:
        m = p.search(texto)
        if m:
            return m.group(1).strip()
    return None


class ConciliadorAllizPDF(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import pdfplumber

        registros: list[RegistroComprovante] = []
        # As páginas de comprovante (bem depois no arquivo) não carregam
        # nenhuma referência à "conta" (001-ORDINARIA/002-FUNDO RESERVA/...)
        # de que veio o pagamento — só a seção RESUMO FINANCEIRO (início do
        # arquivo) tem essa granularidade, e não dá pra propagar com
        # segurança até lá na frente. Por isso soma TODAS as "Despesas do
        # Período" (todas as contas) num total único e trata o condomínio
        # como uma "conta" só, igual ao Consvicta/DataDigitus/LFC.
        total_despesas_acumulado = 0.0
        achou_total = False
        # A seção "5.4 RESUMO FINANCEIRO" (única fonte confiável de
        # "Despesas do Período" por conta) é REIMPRESSA mais adiante no
        # arquivo (confirmado: mesmos valores repetidos 3x) — sem parar de
        # acumular no fim da 1ª ocorrência, o total sairia inflado ~3x.
        dentro_resumo_financeiro = True

        with pdfplumber.open(str(caminho)) as pdf:
            for pagina_num, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""
                page.flush_cache()

                if "DEMONSTRATIVO DE DESPESAS" in texto.upper():
                    dentro_resumo_financeiro = False

                if dentro_resumo_financeiro:
                    for m_desp in _RE_DESPESAS_PERIODO.finditer(texto):
                        total_despesas_acumulado += _num(m_desp.group(1))
                        achou_total = True

                if not _RE_TITULO.search(texto):
                    continue  # não é página de comprovante de pagamento

                valor_str = _primeiro_match(_RE_VALORES, texto)
                if not valor_str:
                    continue  # título reconhecido mas não achou valor — não conta como despesa
                fornecedor = _primeiro_match(_RE_FORNECEDORES, texto)
                data = _primeiro_match(_RE_DATAS, texto)

                registros.append(RegistroComprovante(
                    pagina=pagina_num,
                    codigo=str(pagina_num),
                    tipo_documento="despesa_listada",
                    descricao=fornecedor,
                    vencimento=data,
                    valor=_num(valor_str),
                    conta="TOTAL",
                    texto_bruto=texto,
                ))

        if achou_total:
            registros.append(RegistroComprovante(
                pagina=1,
                codigo="total",
                tipo_documento="total_conta_declarado",
                conta="TOTAL",
                descricao="TOTAL",
                valor=total_despesas_acumulado,
                texto_bruto=f"soma de 'Despesas do Período' de todas as contas: {total_despesas_acumulado}",
            ))

        return registros
