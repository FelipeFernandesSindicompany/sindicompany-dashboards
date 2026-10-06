"""
Extrator das regras gerais — Fatto Morumbi (administradora Manager ADM, `manager_adm_pdf`).

Contém também `ExtratorManagerAdm`, a base de TODO condomínio da Manager ADM (Dueto Morumbi herda dela). O PDF
"Prestação de Contas MM.AAAA" (475-1.185 págs, 48-104 MB; lido em 2-8 s com PyMuPDF, só as páginas dos demonstrativos)
é o mesmo software do ContasData/Lirba — por isso `contasdata.Extrator` faz a leitura — com estas particularidades,
todas conferidas nos arquivos reais:

  * Demonstrativo de Despesas com coluna extra "Nº lancto." (código de 4 dígitos à direita da linha) e a hierarquia
    conta > GRUPO ("TOTAL DA CONTA PESSOAL") > rubrica (SALARIOS, ELEVADORES...) > lançamento.
  * O Resumo Financeiro Contábil vem DEPOIS das Posições Financeiras (fim da seção "Demonstrativo de Contas").
  * Receitas: título da página é só "Receitas"; um recibo por linha (unidade, recibo, vencimento, histórico, valor com
    sinal). Receita negativa = estorno/desconto/taxa paga a maior, impressa com "-".
  * O DÉBITO da conta no Resumo inclui coisas que NÃO estão no Demonstrativo de Despesas e só aparecem na Posição
    Financeira da conta (coluna Débito):
        - "TRANSFERENCIA ENTRE CONTAS" (Dueto: a conta ALUGUEL SALAO DE FESTAS recebe e repassa para ALUGUEL
          S.FESTA /CHURRASQUEIRA; o débito entra nas duas contas — não é despesa),
        - "RECIBOS DIVERGENTES" (débito real da ORDINÁRIA sem lançamento no Demonstrativo; jul/2026 R$ 1.941,36,
          ago/2026 R$ 3.057,25).
    O leitor genérico os completa como lançamentos (categoria = o nome impresso na Posição Financeira, descrição
    "... (Posição Financeira — não consta do Demonstrativo de Despesas)") só quando a soma deles fecha ao centavo com
    o débito do Resumo; senão avisa. Isso faz a conferência da extração fechar com o débito de CADA conta.
  * Conta com a MESMA palavra num grupo: o FUNDO DE OBRAS/FACHADA (Fatto) tem um grupo "MANUTENCAO" próprio
    (rubrica "MATS / SERVICOS", jul/2026 R$ 13.000,00) — o leitor associa o lançamento à conta FUNDO DE OBRAS/FACHADA
    (`conta`) e a conferência do débito é feita por conta, então esse valor NÃO entra na ORDINÁRIA.
  * Rendimento: categoria "RECEITA FINANCEIRA" ("RENTAB.ITAU", "RENTAB.INVEST FACILCRED", "REF MAR/2025") e, nos fundos,
    a linha negativa "REF PROVISAO IR S/ REND" (provisão de IR sobre o rendimento). Entram como `tipo=rendimento`
    (líquido do IR provisionado).

`categoria` = o GRUPO ("TOTAL DA CONTA <grupo>"): PESSOAL, CONSUMO, MANUTENCAO, IMPOSTOS E TAXAS, OUTROS (+ AQUISICOES,
CONTRATOS... conforme o mês); a rubrica fica em `.rubrica` e pode ser usada com
`parser_config.regras_gerais.nivel_categoria = "rubrica"|"caminho"`.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ContasData, _norm
from conciliacao.regras_gerais.modelo import DadosRegras


class ExtratorManagerAdm(_ContasData):
    NIVEL_CATEGORIA = "subconta"

    def _tipo_receita(self, categoria: str, historico: str) -> str:
        c, h = _norm(categoria), _norm(historico)
        if "RECEITA FINANCEIRA" in c or "PROVISAO IR" in h or h.startswith("RENTAB"):
            return "rendimento"
        if "TRANSFER" in h or "TRANSFER" in c:
            return "transferencia"
        return super()._tipo_receita(categoria, historico)

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        dados = super().extrair(caminho, mes)
        if dados.cobertura.get("rendimentos") and not any(abs(c.rendimento) > 0 for c in dados.contas):
            dados.cobertura["rendimentos"] = False
            dados.motivos_nao_cobertos["rendimentos"] = (
                "nenhuma conta deste condomínio tem rendimento de aplicação lançado no mês (sem categoria "
                "'RECEITA FINANCEIRA'/rendimento no Demonstrativo de Receitas): não há o que distribuir entre as contas")
        return dados


class Extrator(ExtratorManagerAdm):
    pass
