"""
Extrator das regras gerais — Vera Cruz (administradora Convivium, `convivium_pdf`).

O PDF "Prestação de Contas MM.AAAA.PDF" (~200 págs, 27-34 MB) é o mesmo software do ContasData/Lirba (marcas "Voltar ao
índice", "Prestação de Contas" + "Condomínio: 0975 -", Resumo Financeiro Contábil, Posição Financeira, "Demostrativo"
(sic) de Receitas e de Despesas, comprovantes anexos nunca lidos). Por isso `contasdata.Extrator` lê o arquivo inteiro
(conferido ao centavo em mai, jun e jul/2026); este módulo só ajusta o que é próprio do condomínio:

  * Modelo "garantidora" (memória feedback_vera_cruz_campos): o condomínio tem UMA conta (ORDINÁRIA), quase toda a receita é
    um único repasse da garantidora LLZ ("Repasse LLZ"/"Repasse Garantidora", prev = real = créditos) mais o "Repasse
    Mercadinho" e as cotas/juros/atualização de poucas unidades (≤ 6 linhas/mês). Não há recibo por unidade.
  * Quando a conta fica devedora (saldo anterior DEVEDOR; mai/2026) a garantidora cobre o saldo no mês seguinte: o
    crédito aparece só na Posição Financeira como "TRANSFERÊNCIA 20.247,51" (sem linha no Demonstrativo de Receitas) —
    o leitor genérico o completa a partir da Posição Financeira (soma fecha ao centavo com os créditos do Resumo) e o
    marca `tipo=transferencia`; o débito do Resumo (120.916,16 em mai) não inclui o saldo devedor anterior que a
    Posição Financeira soma na coluna Débito dos TOTAIS (141.163,67 = 120.916,16 + 20.247,51).
  * Sem aplicação financeira, fundo ou outra conta: não há rendimento a distribuir entre contas. A regra 3 só é dada como
    verificada se o arquivo trouxer alguma linha de rendimento ou mais de uma conta; senão cobertura False + motivo
    (não é limitação do formato: é a estrutura do condomínio).
  * `categoria` = nível da subconta ("TOTAL DA CONTA <subconta>": Pessoal Terceirizado, CONTRATOS/MANUT. MENSAIS,
    CONCES.SERV.PÚBLICOS, MATERIAIS DE CONSUMO, SEGUROS, SERVIÇOS EVENTUAIS/AVULSOS, HONORÁRIOS E EXPEDIENTE, DIVERSOS E
    IMPREVISTOS, + as menores: ENCARGOS SOCIAIS, EQUIPAM. E FERRAMENTAS, IMPOSTOS E TAXAS, DESPESAS BANCÁRIAS). O nível
    abaixo (Elevadores, Água, Energia Elétrica...) vem em `.rubrica`. NÃO se aplica o cat_map do dashboard (merges).
"""
from pathlib import Path

from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ContasData
from conciliacao.regras_gerais.modelo import DadosRegras


class Extrator(_ContasData):
    NIVEL_CATEGORIA = "subconta"

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        dados = super().extrair(caminho, mes)
        if dados.cobertura.get("rendimentos"):
            tem_rendimento = any(c.rendimento > 0 for c in dados.contas)
            if len(dados.contas) < 2 and not tem_rendimento:
                dados.cobertura["rendimentos"] = False
                dados.motivos_nao_cobertos["rendimentos"] = (
                    "o condomínio tem uma única conta (ORDINÁRIA, modelo garantidora), sem aplicação financeira nem fundos: "
                    "não há rendimento a distribuir entre contas")
        return dados
