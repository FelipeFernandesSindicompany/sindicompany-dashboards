"""
Conciliador mínimo para o formato SK Condomínios (Reserva Verde, `sk_condominios_pdf`).

O PDF não traz comprovantes pareáveis com a listagem de despesas, então não há registros de
comprovante a extrair: este conciliador devolve lista vazia, e o relatório sai só com os achados
das regras gerais (receita negativa, rendimento, pagamento sem identificação, parcelas, subcontas),
lidos direto do arquivo por conciliacao/regras_gerais/extratores/sk_condominios.py.
"""
from pathlib import Path

from conciliacao.base import ConciliadorBase


class ConciliadorSKCondominiosPDF(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        return []
