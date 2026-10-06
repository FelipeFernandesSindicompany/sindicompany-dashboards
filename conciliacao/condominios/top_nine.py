"""
Conciliador específico — Moema Top Nine (administradora GCONT, sistema "W0xx").

Cadastrado como "lirba_pdf", mas a "Pasta Digital" (ex.: 06.2026, 132 páginas) é do mesmo sistema do Club Park
Butantã: uma página "Comprovantes de despesas" (texto nativo, "Credt. em Jun/2026;Parcela <código>", "Pago a:",
"Destina-se a:") por pagamento — 27 em jun/2026. O parser ContasData devolvia 0 registros (a varredura de out/2026
mostrou 0 comprovantes verificados). Reaproveita o parser GCONT via _gcont_comum.py (que usa o do Club Park sem
alterá-lo): duplicidade, atraso de pagamento, NF ausente e subconta atípica (matching.gerar_achados_gcont).

Sem checagem de total: neste PDF não existe "N itens VALOR" (Livro Caixa) e o "Total de Despesas" do demonstrativo
(R$ 26.676,94 em jun/2026, conta ordinária) é maior que a soma das 27 capas (R$ 22.752,53) por motivos que o
arquivo não explica por lançamento (conferência por valor mostrou lançamentos listados sem capa e capas sem
lançamento correspondente) — comparar os dois geraria um "soma não confere" não confiável, então não é emitido.
"""
from conciliacao.condominios._gcont_comum import ConciliadorGcontNativo


class Conciliador(ConciliadorGcontNativo):
    pass
