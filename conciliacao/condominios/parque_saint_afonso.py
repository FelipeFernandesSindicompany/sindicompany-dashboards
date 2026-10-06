"""
Conciliador específico — Parque Saint Afonso (administradora GCONT).

Cadastrado como empresa_gestora="lirba_pdf" em condominios.json, mas o PDF de
"Prestação de Contas" (ex.: 06.2026, 325 páginas) é do MESMO sistema do Club
Park Butantã (GCONT): cada pagamento tem a sua página "Comprovantes de
despesas" ("Parcela <código>", "Pago a:", "Destina-se a:", "Valor Emitido")
em TEXTO NATIVO, e o relatório "Despesas por categoria" (Livro Caixa) fecha
com "N itens VALOR_TOTAL" (ex.: 67 itens / R$ 99.290,41 em jun/2026, igual à
soma das 67 páginas-capa). O parser genérico do Lirba/ContasData procura
"Comprovante de Despesa" + código de 4 dígitos e por isso devolvia 0
registros (a varredura de out/2026 mostrou 0 comprovantes verificados).

O formato é idêntico ao já validado em conciliacao/condominios/club_park_butanta.py
(que NÃO é alterado): reaproveita a classe dele via _gcont_comum.py (que ainda
repara fornecedor com nome em duas linhas). As regras de matching são as de
`matching.gerar_achados_gcont` (duplicidade, soma x Livro Caixa, atraso, NF
ausente, subconta atípica).

Meses antigos (jun-ago/2025, out-dez/2025) vêm em outro formato (PDF escaneado
sem texto): nenhuma página "Comprovantes de despesas" é achada e o conciliador
devolve [] (mesmo comportamento anterior, sem inventar leitura).
"""
from conciliacao.condominios._gcont_comum import ConciliadorGcontNativo


class Conciliador(ConciliadorGcontNativo):
    pass
