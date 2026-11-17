"""
Conciliador específico — 730 Padre Carvalho (administradora Loan, a mesma do Upper Itaim).

Cadastrado como "lirba_pdf" (formato ContasData), mas o arquivo mensal pode vir no formato RESUMIDO "Demonstrativo de Contas" (3 a 8
páginas, sem as páginas de comprovante), com um link do portal GoControleDocumentos (loanimoveis.dyndns.org) em cada despesa e sem o
código de 4 dígitos — exatamente o formato do Upper Itaim. O leitor por links dele serve sem mudanças; o arquivo completo (centenas de
páginas, com os comprovantes embutidos) continua indo para o leitor ContasData padrão (decisão tomada dentro do próprio conciliador).
"""
from conciliacao.condominios.upper_itaim import Conciliador as _ConciliadorUpperItaim


class Conciliador(_ConciliadorUpperItaim):
    pass
