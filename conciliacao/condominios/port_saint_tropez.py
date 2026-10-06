"""
Conciliador específico — Port Saint Tropez.

Cadastrado como empresa_gestora="habitacional_xlsx" em condominios.json, mas
a administradora (Verti) mudou pra PDF ContasData em algum mês entre a
última planilha conhecida e março/2026 (confirmado em dados reais: o
arquivo de março/2026 é um PDF de 238 páginas com "Comprovante de Despesa",
"TOTAL DA CONTA" e a marca-d'água "ContasData" — mesmo padrão de migração
já visto em Baturité, ver conciliacao/condominios/baturite.py) — o
conciliador genérico associado a "habitacional_xlsx" (openpyxl) quebrava
com InvalidFileException ao tentar abrir o PDF como planilha.
"""
from conciliacao.lirba_pdf import ConciliadorLirbaPDF as Conciliador  # noqa: F401
