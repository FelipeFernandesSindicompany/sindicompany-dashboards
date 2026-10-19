---
name: conferir-relatorios
description: Último check dos relatórios de Validação de Balancetes (PDF "Validação Balancete - <Condomínio> MM.AAAA.pdf") contra todas as correções já feitas — identidade, saldos x arquivo de origem, continuidade, sinais, perguntas terminando em "?", NF de benefício/seguro, atraso com data impossível, escopo, saldo negativo, rendimento, cobertura do lote. Use antes de entregar relatórios à administradora/síndico ou quando pedirem "conferir/auditar os relatórios gerados".
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

## Gravidade

- **ALTA**: não entregar; corrigir (regenerar o relatório, ajustar leitor/config — avisando o usuário antes de mexer em regra).
- **MÉDIA**: abrir a imagem do anexo / revisar (ex.: "valor não confirma — possível erro de OCR", comprovante não confirmado, rendimento sem pergunta).
- **INFO**: esperado e explicado (continuidade já perguntada, total por categoria x transferências).

## Regras (ver aba "Regras verificadas")

Identidade e mês; nome padrão do arquivo e sem "(versão vN)"; saldos x origem; fechamento por conta/consolidado/categorias; continuidade (e o arquivo pode ser de outro condomínio se NENHUMA conta bate); sinais negativos; perguntas terminam em "?"; sem "None/nan/{{"; atraso com datas plausíveis; benefício/seguro sem NF; seção "Escopo da Validação" onde exigida; alerta de saldo negativo; pergunta de rendimento; cobertura do lote (planilha em branco x relatório; nenhum relatório de condomínio excluído — Saint Afonso, Go Barra Funda).

## Depois de rodar

1. Resuma ao usuário em português simples: quantos relatórios, ALTA/MÉDIA, e cada ALTA com condomínio/mês e o que fazer.
2. Para MÉDIA de OCR, confirme visualmente na imagem do anexo antes de afirmar erro ou acerto.
3. Relatórios antigos (gerados antes das correções) não são sobrescritos sem perguntar ao usuário.
4. Nunca declarar "tudo certo" se o check não cobriu o condomínio (sem leitura de origem = avisar).
