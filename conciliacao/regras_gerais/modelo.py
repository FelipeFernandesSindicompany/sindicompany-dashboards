"""
Modelo de dados das REGRAS GERAIS da Validação de Balancetes
(rendimentos entre contas, receita negativa, pagamento sem identificação,
duas parcelas no mesmo mês, subcontas).

Cada tipo de arquivo (Lirba/ContasData, Habitacional XLSX, Lello, DataDigitus...)
tem um EXTRATOR que lê o arquivo do mês (e o do mês anterior) e devolve um
`DadosRegras`. As regras (regras.py) trabalham só sobre esse modelo — por isso
são iguais para todos os condomínios; o que muda por condomínio é a leitura.

Fonte dos dados: SOMENTE o arquivo de prestação de contas (PDF/XLSX/XLS).
Nunca dashboards.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LinhaReceita:
    """Uma linha de receita/crédito de uma conta, como impressa no arquivo."""
    conta: str                      # nome da conta como no arquivo ("ORDINÁRIA", "FUNDO DE RESERVA"...)
    descricao: str                  # histórico/descrição da linha
    valor: float                    # COM SINAL, exatamente como impresso (negativo se negativo)
    tipo: str = "outra"             # "cota" | "rendimento" | "multa_juros" | "transferencia" | "outra"
    data: Optional[str] = None      # "DD/MM/AAAA" se a linha tiver data
    pagina: Optional[int] = None    # página do PDF (1-based), para o print de evidência
    local: Optional[str] = None     # planilha: "aba X, linha N"
    bbox: Optional[tuple] = None    # (x0, top, x1, bottom) em pontos pdfplumber, se conhecido


@dataclass
class ContaMes:
    """Saldos e movimento de uma conta no mês (Resumo Financeiro / Posição Financeira)."""
    nome: str
    saldo_anterior: float = 0.0
    saldo_atual: float = 0.0
    creditos: float = 0.0
    debitos: float = 0.0
    rendimento: float = 0.0         # soma das linhas de rendimento CREDITADAS nesta conta no mês
    aplicada: Optional[bool] = None  # True/False se o arquivo diz que o saldo está aplicado; None = desconhecido
    pagina: Optional[int] = None


@dataclass
class LancamentoDespesa:
    """Um lançamento de despesa individual do Demonstrativo de Despesas do mês."""
    descricao: str                  # histórico completo (inclui NF, parcela, referência)
    valor: float
    categoria: str                  # subconta/categoria como aparece no arquivo (nome bruto, sem cat_map)
    conta: str = "ORDINÁRIA"        # conta de origem do lançamento
    codigo: Optional[str] = None    # nº do lançamento na administradora
    data: Optional[str] = None      # "DD/MM/AAAA"
    fornecedor: Optional[str] = None  # só se o arquivo traz o campo; senão None (as regras extraem da descrição)
    cnpj_cpf: Optional[str] = None
    pagina: Optional[int] = None
    local: Optional[str] = None
    bbox: Optional[tuple] = None


@dataclass
class DadosRegras:
    mes: str                        # "AAAA-MM"
    arquivo: str = ""               # nome do arquivo lido
    receitas: list = field(default_factory=list)      # list[LinhaReceita]
    contas: list = field(default_factory=list)        # list[ContaMes]
    lancamentos: list = field(default_factory=list)   # list[LancamentoDespesa]
    # Formatos SEM lançamentos individuais (só categorias com total, ex.: Balancete Mensal Iello/Lello):
    # {nome da categoria: total do mês}. Permite só a regra de subcontas em nível de categoria.
    categorias: dict = field(default_factory=dict)
    # O que ESTE formato permite verificar. Falso = a regra correspondente aparece no
    # relatório como "não aplicável a este formato" (com o motivo), nunca omitida.
    #   receitas    -> receita negativa
    #   rendimentos -> rendimento proporcional entre contas
    #   lancamentos -> pagamento sem identificação, parcelas no mesmo mês, subcontas
    cobertura: dict = field(default_factory=lambda: {"receitas": False, "rendimentos": False, "lancamentos": False})
    motivos_nao_cobertos: dict = field(default_factory=dict)  # {"receitas": "formato só traz totais", ...}
    avisos: list = field(default_factory=list)        # limitações da leitura, em texto
