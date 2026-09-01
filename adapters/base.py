"""
Adapter base — todo adapter de empresa deve herdar desta classe.

Cada condomínio pode ter um campo "parser_config" no condominios.json com
regras de extração específicas para o seu formato de arquivo. Isso elimina
adivinhações genéricas e garante consistência entre os meses.

Estrutura do parser_config (campos suportados por adapter):

  ── Todos os adapters ──────────────────────────────────────────────────────
  cat_map          dict   Override de nomes canônicos de categorias.
                          Chave = nome bruto (PDF/XLSX), Valor = nome canônico.
                          Ex: {"SERVICOS GERAIS": "Serv. Gerais"}

  ── AdapterLirbaPDF ────────────────────────────────────────────────────────
  extract_cats     str    Método de extração de categorias de despesa:
                          "posicao_financeira" → lê da seção Posição Financeira
                              da conta ORDINÁRIA (padrão da maioria dos condos Lirba)
                          "total_da_conta"     → usa linhas TOTAL DA CONTA
                              (Blue Sky, Gravura — têm sub-cats explícitos)
                          "webware"            → formato Webware (NYC Berrini)
                          "auto"               → detecção automática (fallback)

  contas_separadas list   Contas de nível alto além de ORDINÁRIA que devem
                          entrar como categorias. Ex: ["CONSUMO", "I.P.T.U."]
  consumo_name     str    Nome canônico para a conta CONSUMO. Default: "Consumos"
  iptu_name        str    Nome canônico para a conta I.P.T.U.  Default: "IPTU"
  excluir_contas   list   Contas adicionais a excluir das categorias.

  ── AdapterHabitacionalXLSX ────────────────────────────────────────────────
  sheet_name       str    Nome da aba Excel a ler (se diferente do padrão)

  ── AdapterLelloMHTML / LelloXLS ───────────────────────────────────────────
  (sem campos extras por ora — formato uniforme)

  ── AdapterDatadigitusPDF ──────────────────────────────────────────────────
  (sem campos extras por ora — formato uniforme)

  ── AdapterIelloPDF ────────────────────────────────────────────────────────
  (sem campos extras por ora — formato uniforme)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


@dataclass
class DadosFinanceiros:
    condominio_id: str
    mes_referencia: str          # "2026-05"
    receita_prevista: float = 0.0
    receita_realizada: float = 0.0
    # receita_cotas: cotas efetivamente recebidas no período (para campo 'real' no BAL).
    # Quando 0.0, usa receita_realizada como fallback.
    # Formato Blue Sky colunado: linha "CONDOMINIO X Y" → Y = receita_cotas
    receita_cotas: float = 0.0
    # inadimplencia_recebida: valor efetivamente recebido de cotas em atraso no período
    # (para campo 'inadRec' no BAL — aba Inadimplência).
    # Formato Blue Sky colunado: linha "INADIMPLENCIA X Y" → Y = inadimplencia_recebida
    inadimplencia_recebida: float = 0.0
    despesa_total: float = 0.0
    saldo_anterior: float = 0.0
    saldo_atual: float = 0.0
    inadimplencia_valor: float = 0.0
    inadimplencia_percentual: float = 0.0
    total_unidades: int = 0
    unidades_inadimplentes: int = 0
    categorias_despesa: dict = field(default_factory=dict)
    # {"Manutenção": 1500.0, "Limpeza": 800.0, ...}
    contas_detalhe: list = field(default_factory=list)
    # [{"nome":"ORDINÁRIA","saldo_ant":0,"creditos":0,"debitos":0,"saldo_atual":0}, ...]
    banco_cc: float = 0.0    # conta corrente / ordinária
    banco_cdb: float = 0.0   # fundo de reserva / CDB / poupança
    banco_priv: float = 0.0  # demais fundos (melhorias, obras, etc.)
    banco_extra: dict = field(default_factory=dict)  # campos adicionais (ex: itauvest)
    fac: float = 0.0         # faturas anteriores cobradas (juros + multas recebidos)
    historico_meses: list = field(default_factory=list)
    # [{"mes": "2026-04", "receita": ..., "despesa": ..., "saldo": ...}, ...]
    observacoes: str = ""


class AdapterBase(ABC):
    """Interface que todos os adapters devem implementar."""

    def __init__(self, config: dict):
        self.config = config
        # Regras específicas do condomínio (lidas de condominios.json → parser_config)
        self.parser_config: dict = config.get("parser_config", {})

    @abstractmethod
    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """Lê arquivo XLSX e retorna dados normalizados."""
        ...

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> Optional[DadosFinanceiros]:
        """Lê arquivo PDF (opcional — implementar se a empresa usa PDF)."""
        raise NotImplementedError(f"{self.__class__.__name__} não suporta PDF")

    def calcular_saldo(self, dados: DadosFinanceiros) -> float:
        return dados.saldo_anterior + dados.receita_realizada - dados.despesa_total

    def _valor_celula(self, ws, linha: int, coluna) -> float:
        """Lê célula de forma segura, retornando 0.0 se vazia ou inválida."""
        try:
            val = ws.cell(row=linha, column=coluna).value
            return float(val) if val is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _encontrar_linha(self, ws, coluna, texto: str) -> Optional[int]:
        """Busca linha onde célula contém o texto (case-insensitive)."""
        texto = texto.lower().strip()
        for row in ws.iter_rows():
            cell = row[coluna - 1] if coluna <= len(row) else None
            if cell and cell.value and texto in str(cell.value).lower():
                return cell.row
        return None
