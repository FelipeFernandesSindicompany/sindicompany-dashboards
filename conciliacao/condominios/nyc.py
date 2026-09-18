"""
Conciliador específico — NYC (empresa_gestora="lirba_pdf", parser_config.
extract_cats="webware" — sub-formato ContasData sem "Demonstrativo de
Despesas" separado, ver conciliacao/webware_pdf.py).
"""
from conciliacao.webware_pdf import ConciliadorWebwarePDF as Conciliador  # noqa: F401
