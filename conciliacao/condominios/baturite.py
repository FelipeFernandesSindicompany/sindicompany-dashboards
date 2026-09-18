"""
Conciliador específico — Baturité.

Empresa gestora mudou de "habitacional_xlsx" (planilha) para o sistema
ContasData (PDF) a partir de 2026 — confirmado em dados reais: a pasta de
projeto só tem arquivos ".xlsx" até 2025 e só ".pdf" a partir de 2026 (ver
também adapters/condominios/baturite.py, mesmo motivo). A estrutura do
"Demonstrativo de Despesas" é a mesma família ContasData/Lirba, só sem
coluna de data por lançamento — já suportado por
conciliacao/lirba_pdf.py::ConciliadorLirbaPDF após tornar o cabeçalho
"Data Histórico Valor Total" tolerante à ausência de "Data".
"""
from conciliacao.lirba_pdf import ConciliadorLirbaPDF as Conciliador  # noqa: F401
