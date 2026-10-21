---
name: conferir-relatorios
description: Último check dos relatórios de Validação de Balancetes (PDF "Validação Balancete - <Condomínio> MM.AAAA.pdf") contra todas as correções já feitas — identidade, saldos x arquivo de origem, continuidade, sinais, perguntas terminando em "?", NF/comprovante (marketplace, concessionária, locação, honorários, cartório), atraso com data impossível, escopo, saldo negativo, rendimento, print do local em todo item, cobertura do lote. Use antes de entregar relatórios à administradora/síndico ou quando pedirem "conferir/auditar os relatórios gerados".
---

# Conferir relatórios de Validação de Balancetes

Só **lê** os relatórios e os arquivos de origem; nunca altera relatório, adapter, dashboard ou config.

## Como rodar

```bash
python scripts/check_final_relatorios.py --desde AAAA-MM-DD [--meses 2026-07,2026-08] [--sem-origem] [id_condominio ...]
```

- `--desde`: só audita PDFs modificados a partir da data (use a data da última geração do lote).
- Sem `--sem-origem` ele relê o arquivo de origem de cada condomínio (saldos, continuidade, saldo negativo, rendimento).
- Saída: terminal (só o que é ALTA) + `output/check_final_<data>.xlsx` (abas Resumo por relatório · Pontos a corrigir · Regras verificadas).
- Outras auditorias do projeto: `scripts/auditoria_sinais.py` (sinal dos valores, deve dar SINAL_PERDIDO=0), `scripts/auditoria_integridade_validacao.py` (testes de mutação das regras), `scripts/conferencia_relatorios.py` (conferência mecânica por relatório).
- Para refazer relatórios: `scripts/gerar_relatorio_conciliacao.py --condominio <id> --mes AAAA-MM --etapa extrair|interpretar|render` (extrair exige `--arquivo`). Apague antes o PDF da pasta do projeto, senão o render cria "(versão vN)".

## Gravidade

- **ALTA**: não entregar; corrigir (regenerar o relatório, ajustar leitor/config — avisando o usuário antes de mexer em regra).
- **MÉDIA**: abrir a imagem do anexo / revisar.
- **INFO**: esperado e explicado.

## Regras decididas pelo dono (valem para TODOS os condomínios)

1. **Integridade acima de tudo**: sem falso "tudo certo" e sem falso positivo; toda divergência = pergunta à administradora que termina em "?"; confirmar valor sinalizado olhando a imagem do anexo; número com sinal exato.
2. **Nota fiscal**: cobrada quando a listagem cita nº de NF **e** em toda compra em **marketplace** (Mercado Pago/Livre, Magalu, Amazon...) — o comprovante também. **Dispensam NF** (basta o comprovante de pagamento): benefícios (VT/VR/cesta) e seguro, **honorários advocatícios/custas**, **serviço de cartório** (registro de atas), **locação/aluguel**. "NF-e não disponível" e o texto-padrão do formulário da administradora **não** contam como NF anexada.
3. **Marketplace**: não se pergunta "por que comprou lá"; exige-se comprovante e NF como nas demais despesas.
4. **Concessionárias (Vivo, Claro, Sabesp, Enel, Comgás...)**: sempre pedir a **conta (fatura)** quando o anexo é só comprovante de pagamento/extrato (um item por relatório). Só afirma com todas as páginas lidas e o contador "01/02" da capa não maior que as páginas lidas.
5. **Sem comprovantes anexados** (arquivo lista despesas mas não traz comprovantes): relatório traz automaticamente o aviso "comprovantes e notas fiscais não foram validados, pois o arquivo com os comprovantes não foi enviado pela Administradora".
6. **Valor acima do histórico**: demais fornecedores ≥ 2,5× a mediana (mesmo fornecedor **e** mesmo tipo de serviço — instalação ≠ manutenção, postagens ≠ tarifas); **concessionária e fatura de cartão: mais de 10% acima** da mediana (diferença ≥ R$ 1.000). Fornecedor novo / recorrente ausente conferem o nome por palavras em todo o histórico (inclusive retenções); salário/folha não é fornecedor.
7. **Folha**: diferença entre PIX e líquido do cálculo → perguntar se é imposto. **Projeto** (ex.: projeto de segurança): perguntar se acabou e quantas parcelas foram pagas.
8. **Barreira de identidade** do arquivo (`conciliacao/identidade_arquivo.py`) deve ficar ATIVA.
9. **Prints (evidência)**: todo item tem print do local (planilha XLSX/XLS e PDF), **dentro da moldura do cartão** (174 mm) e com o **retângulo cobrindo a linha inteira** do lançamento (inclusive descrição quebrada). "Evidência não disponível" ou "Origem no arquivo: linha N" **não pode aparecer** — o check marca ALTA.
10. **Conferência visual** (`config/conferencias_visuais/<condomínio>/<AAAA-MM>.json`, também lida de `data/`): registra o que foi visto na imagem (item verificado, ou `divergencia_real` com texto e pergunta reescritos). Vale só para o mesmo código e o mesmo valor.
11. **Princípio financeiro básico — não existe despesa negativa nem receita negativa.** Despesa com valor negativo é crédito (recebimento/reembolso/estorno): NUNCA pedir comprovante/NF dela; um item único "Despesa lançada com valor negativo" pede para lançar como receita (crédito), e uma nota sob a tabela de despesas mostra o total sem ela. Receita negativa é saída: o texto diz "Não existe receita negativa" e pede para lançar como despesa/estorno na conta correta. O check marca ALTA se aparecer pedido de comprovante de valor negativo ou receita negativa sem a explicação. **A pergunta sempre começa pedindo explicação** ("O que é este lançamento e por que foi lançado com sinal negativo?") antes de pedir a correção. Lançamento positivo com nome de crédito (ex.: "Estorno", "Receita não antecipada") dentro das despesas **não** tem regra geral (pode ser reembolso pago pelo condomínio): trata-se caso a caso por conferência visual (`divergencia_real`, vale também para "sem comprovante"), pedindo explicação do que é o lançamento.
12. **Sem jargão interno** nos relatórios (ex.: "pasta do projeto", "lidos"): a administradora não sabe o que é. O check marca ALTA.
13. **Não tocar** em adapters/dashboards; relatórios de outras sessões (ex.: Villa Park fora do lote) não se sobrescrevem sem perguntar.

## O que o check verifica (ver aba "Regras verificadas")

Identidade e mês; nome padrão do arquivo e sem "(versão vN)"; saldos x origem; fechamento por conta/consolidado/categorias; continuidade (e arquivo de outro condomínio se NENHUMA conta bate); sinais; perguntas terminam em "?"; texto sem "None/nan/{{"; atraso com datas plausíveis; benefício/seguro sem NF; escopo; saldo negativo; rendimento; **print do local em todo item e destaque dentro da moldura**; cobertura do lote.

## Depois de rodar

1. Resuma ao usuário em português simples: quantos relatórios, ALTA/MÉDIA, e cada ALTA com condomínio/mês e o que fazer.
2. Para MÉDIA de OCR, confirme visualmente na imagem do anexo antes de afirmar erro ou acerto.
3. Relatórios antigos (gerados antes das correções) não são sobrescritos sem perguntar ao usuário.
4. Nunca declarar "tudo certo" se o check não cobriu o condomínio (sem leitura de origem = avisar).
5. Gerar a relação para envio (condomínio, mês, administradora, caminho do PDF, nº de perguntas, aviso de escopo) em Excel, em `output/`.
