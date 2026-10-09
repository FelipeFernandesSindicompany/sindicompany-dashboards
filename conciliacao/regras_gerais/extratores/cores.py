"""
Extrator das regras gerais — Cores.

O Cores entrega a prestação de contas em TRÊS formatos, todos mantidos:
  .xlsx  → planilha Habitacional (até jul/2026)                      → extratores/habitacional_xlsx.py
  .pdf   → "Demonstrativo de Contas" (ago/2026: "Emitido em...")     → extratores/contasdata.py
  .pdf   → portal CondoPro impresso em PDF (set/2026: logo CondoPro) → extratores/condopro_pdf.py
O PDF é reconhecido pelo conteúdo (o do CondoPro não tem "Emitido em" e traz o seletor de mês "Consultar").
"""
from pathlib import Path

from conciliacao.regras_gerais.modelo import DadosRegras


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        caminho = Path(caminho)
        ext = caminho.suffix.lower()
        if ext in (".xlsx", ".xlsm"):
            from conciliacao.regras_gerais.extratores.habitacional_xlsx import Extrator as ExtratorPlanilha
            return ExtratorPlanilha(self.condo).extrair(caminho, mes)
        if ext == ".pdf":
            from conciliacao.regras_gerais.extratores.condopro_pdf import Extrator as ExtratorCondoPro
            condopro = ExtratorCondoPro(self.condo)
            if condopro.reconhece(caminho):
                return condopro.extrair(caminho, mes)
            from conciliacao.regras_gerais.extratores.contasdata import Extrator as ExtratorContasData
            return ExtratorContasData(self.condo).extrair(caminho, mes)
        raise ValueError(f"formato de arquivo não suportado para o Cores: {caminho.suffix or 'sem extensão'}")
