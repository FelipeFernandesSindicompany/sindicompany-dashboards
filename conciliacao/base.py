"""
Base do motor de conciliação — todo extrator de comprovantes deve herdar
ConciliadorBase, no mesmo espírito de adapters/base.py::AdapterBase.

Três camadas de dados, nunca misturadas (ver plano em
C:\\Users\\MF PRINTER\\.claude\\plans\\humming-swimming-hellman.md):

  1. RegistroComprovante — um por documento extraído do PDF da pasta de
     prestação de contas (determinístico, camada de extração).
  2. Achado — resultado do cruzamento determinístico entre os registros e o
     demonstrativo já lido pelo adapter existente (DadosFinanceiros). Nunca
     contém texto narrativo livre, só fatos e a regra que os gerou.
  3. AchadoRevisado — camada de interpretação (severidade final + narrativa),
     sempre referenciando o Achado por id, nunca substituindo os números.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RegistroComprovante:
    """Um documento de evidência extraído do PDF da pasta de prestação de contas."""
    pagina: int  # índice físico da página no PDF (1-based), usado para o crop de evidência
    tipo_documento: str
    # "despesa_interna" | "listagem_despesas" | "pix" | "darf" | "boleto" |
    # "debito_automatico" | "email" | "relatorio_fiscal" | "nao_extraivel_texto" | "outro"
    codigo: Optional[str] = None          # código do lançamento na administradora (ex: "1214")
    descricao: Optional[str] = None
    fornecedor: Optional[str] = None
    cnpj_cpf: Optional[str] = None
    conta: Optional[str] = None           # conta/banco (ex: "Itaú")
    competencia: Optional[str] = None     # "MM/YYYY"
    vencimento: Optional[str] = None
    pagamento: Optional[str] = None       # data efetiva do pagamento
    valor: float = 0.0
    forma_pagamento: Optional[str] = None
    autenticacao: Optional[str] = None
    pagina_original_texto: Optional[str] = None  # "241 de 365", como impresso no documento
    categoria_demonstrativo: Optional[str] = None  # nome canônico da categoria (só em tipo="despesa_interna")
    # Linhas da tabela "Retenções de Impostos" da própria página (só em tipo=
    # "despesa_interna"): cada retenção listada aqui tem SEU PRÓPRIO código de
    # despesa em outro lugar da pasta, geralmente pago via DARF consolidado.
    # [{"imposto": "INSS", "codigo_despesa": "1221", "vencimento": "20/07/2026", "valor": 3633.96}, ...]
    retencoes_vinculadas: list = field(default_factory=list)
    # Valores individuais do quadro "Detalhamento por Periodicidade, Natureza
    # de Rendimento e Código de Receita" (só em tipo="relatorio_fiscal", ex.:
    # EFD-Reinf) — usados para confirmar por valor quais retenções entraram
    # nesse fechamento consolidado.
    valores_detalhamento_fiscal: list = field(default_factory=list)
    texto_bruto: str = ""                 # texto integral da página, preservado para releitura
    bbox_crop: Optional[tuple] = None      # (x0, top, x1, bottom) em pontos pdfplumber, se aplicável


# Tipos fechados de achado — qualquer coisa fora disso é erro de programação, não achado válido.
TIPOS_ACHADO = {
    "divergencia_valor",
    "sem_comprovante",
    "sem_lancamento_correspondente",
    "duplicidade",
    "cnpj_ausente",
    "consolidacao_multipla_pendente_julgamento",
    "ok_verificado",
}

SEVERIDADES = {"critico", "alto", "atencao", "informativo"}


@dataclass
class Achado:
    """Resultado do matching determinístico. Sem texto narrativo — só fatos rastreáveis."""
    id: str
    tipo: str
    severidade_sugerida: str
    regra_aplicada: str                    # nome da regra determinística que gerou o achado
    registros_relacionados: list = field(default_factory=list)  # páginas/códigos de RegistroComprovante
    linha_demonstrativo: Optional[str] = None  # categoria/conta correspondente em DadosFinanceiros
    valor_esperado: Optional[float] = None
    valor_encontrado: Optional[float] = None
    confianca_deterministica: float = 1.0  # 1.0 = fato puro (soma bate/não bate); menor = julgamento aberto

    def __post_init__(self):
        if self.tipo not in TIPOS_ACHADO:
            raise ValueError(f"tipo de achado desconhecido: {self.tipo!r} (válidos: {TIPOS_ACHADO})")
        if self.severidade_sugerida not in SEVERIDADES:
            raise ValueError(f"severidade desconhecida: {self.severidade_sugerida!r} (válidas: {SEVERIDADES})")


@dataclass
class AchadoRevisado:
    """Camada de interpretação. Referencia o Achado bruto por id — nunca o substitui."""
    achado_id: str
    titulo: str
    paragrafo: str
    severidade_final: str
    o_que_verificar: str
    confianca_ia: float
    revisado_por: str    # "claude-code-agente" | "humano:<email>"
    revisado_em: str     # ISO 8601
    motivo_divergencia_da_sugestao: Optional[str] = None  # obrigatório se severidade_final != sugerida

    def __post_init__(self):
        if self.severidade_final not in SEVERIDADES:
            raise ValueError(f"severidade desconhecida: {self.severidade_final!r} (válidas: {SEVERIDADES})")


class ConciliadorBase(ABC):
    """Interface que todo extrator de comprovantes por administradora deve implementar."""

    def __init__(self, config: dict):
        self.config = config
        # Regras específicas do condomínio, lidas de condominios.json → parser_config
        # (mesma convenção de adapters/base.py::AdapterBase — reaproveitado, não reinventado).
        self.parser_config: dict = config.get("parser_config", {})

    @abstractmethod
    def extrair_comprovantes(self, caminho: Path) -> list:
        """Lê o PDF da pasta de prestação de contas e retorna list[RegistroComprovante]."""
        ...
