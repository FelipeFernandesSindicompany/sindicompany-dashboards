"""
Adapter específico para Patrícia.
Empresa gestora: auxiliadora_xls (Auxiliadora Predial)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRAS EXCLUSIVAS DESTE CONDOMÍNIO — NÃO COMPARTILHAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONTAS DO BALANCETE:
  • ORDINARIA
  • FUNDO DE OBRAS
  • FUNDO REFORMA ELEVADORES
  • SALÃO DE FESTAS/ CHURRASQUEIRA
  • RATEIO EXTRA (aparece esporadicamente)

GRÁFICO "Saldo por Conta" (cContas) e TABELA "Saldo Bancário por Mês":
  Os dados NÃO vêm de banco.cc/vest/cdb mas sim diretamente de contas[].s:
    - Ordinária      → contas.find(n === 'ORDINARIA').s
    - Fundo de Obras → contas.find(n === 'FUNDO DE OBRAS').s
    - Demais Contas  → soma dos saldos de todas as demais contas
  Motivo: o condomínio não tem posição bancária segmentada acessível no XLS;
  o agrupamento por conta contábil reflete melhor a posição patrimonial.

MAPEAMENTO banco{} na injeção:
  banco.cc   = saldo da conta ORDINARIA
  banco.cdb  = saldo do FUNDO DE OBRAS
  banco.priv = soma das contas restantes (REFORMA ELEVADORES + SALÃO + extras)
  Nunca usar banco.vest (campo legado de meses anteriores a jun/2026).

INADIMPLÊNCIA:
  inad e inadProc extraídos normalmente pelo adapter genérico auxiliadora_xls.
"""
from adapters.auxiliadora_xls import AdapterAuxiliadoraXLS
from adapters.base import DadosFinanceiros
from pathlib import Path


class Adapter(AdapterAuxiliadoraXLS):
    """Adapter exclusivo de Patrícia — gráfico Saldo por Conta usa contas[], não banco."""

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        dados = super().ler_xlsx(caminho, mes_referencia)

        # Remapear banco{} a partir dos saldos das contas contábeis
        contas = dados.contas_detalhe  # list[dict] com chave 'nome' e 'saldo_atual'
        if contas:
            def _s(nome: str) -> float:
                for c in contas:
                    if c.get("nome", "").upper() == nome.upper():
                        return c.get("saldo_atual", 0.0)
                return 0.0

            ordinaria = _s("ORDINARIA")
            fundo_obras = _s("FUNDO DE OBRAS")
            demais = sum(
                c.get("saldo_atual", 0.0)
                for c in contas
                if c.get("nome", "").upper() not in ("ORDINARIA", "FUNDO DE OBRAS")
            )

            dados.banco_cc   = ordinaria
            dados.banco_cdb  = fundo_obras
            dados.banco_priv = round(demais, 2)

        return dados
