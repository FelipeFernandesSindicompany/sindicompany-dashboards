# Regras gerais da Validação de Balancetes — guia para quem escreve extratores

Projeto: `C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\Projeto Automatização Dashboard`
(Sindicompany — relatório de validação mensal de balancetes de 54 condomínios, 17 administradoras.)

## O que a ferramenta faz (palavras do dono do produto)
O arquivo do mês é inserido no Admin (mês/ano). A ferramenta busca na pasta do projeto o arquivo do
**mês anterior** (já validado e correto) para comparar, e aplica as regras:
1. verificação dos valores em geral; 2. confirmação dos comprovantes (essas duas já existem, por formato, em `conciliacao/matching.py`);
3. **rendimentos distribuídos corretamente entre as contas** — decisão do dono: o rendimento de cada conta deve ser
   **proporcional ao saldo dela** (implementado sobre o saldo médio do mês; ver `regras.py::regra_rendimento`);
4. **receitas com valor negativo** — **qualquer** linha de receita com valor < 0 é divergência;
5. **pagamento sem identificação** (lançamento sem fornecedor/histórico, ou marcado "não identificado");
6. duplicidade de pagamentos (já existe por formato);
7. **duas parcelas pagas no mesmo mês** (mesma série "PARC n/total");
8. **lançamentos nas subcontas corretas a cada mês** (mesma despesa em subconta diferente da do mês anterior; subconta nova).

Quem usa a ferramenta depois **não fará nenhuma correção manual** — tem de funcionar sozinha, para CADA condomínio,
com as subcontas e o arquivo próprios dele. Cada administradora/condomínio tem um formato diferente.

As regras 3, 4, 5, 7, 8 ficam em `conciliacao/regras_gerais/regras.py` e trabalham sobre o modelo `modelo.py`
(`DadosRegras`: receitas, contas, lançamentos). **Seu trabalho é o EXTRATOR do formato: ler o arquivo e preencher o modelo.**

## REGRAS DE OURO (o dono já corrigiu isto antes — não repita)
- **Independência dos dashboards.** Leia SOMENTE os arquivos de prestação de contas (PDF/XLSX/XLS). NUNCA leia
  `docs/*.html` nem `var BAL` de dashboard, nem use dashboard como referência de "valor certo". Não altere nada de
  dashboards, nem `adapters/`, nem `config/condominios.json`.
- Você só pode criar/editar os arquivos do SEU grupo (lista abaixo) e escrever relatório/notas em
  `data/auditoria_categorias/diag/`. Não edite `regras.py`, `modelo.py`, `pipeline.py`, `textos.py`, `evidencias.py`,
  `extratores/__init__.py`, o script do relatório nem os de outros grupos; se achar que precisam mudar, descreva a mudança no seu relatório.
- Nada de `git add/commit`. Não toque nos arquivos originais (só leitura).
- Ferramenta Bash desta sessão reduz `\\` para `\` em heredocs: para código com regex use a ferramenta de edição de arquivos (Write/Edit), não heredoc.
- PDFs grandes (até 340 MB): prefira PyMuPDF (`fitz`) para texto/palavras; `pdfplumber` só em páginas específicas
  (`pdf.pages` num PDF de 80+ MB leva minutos; há cache em `conciliacao/pdf_cache.py::pdf_plumber_aberto`).
  PDF só-imagem (ex.: Palm Beach): OCR com tesseract (`conciliacao/ocr.py`).
- **Cada condomínio individualmente**: abra o arquivo real de CADA condomínio do seu grupo, em vários meses, e confirme que
  o extrator lê as subcontas e valores certos DELE. Não generalize sem testar. Se um condomínio do grupo tem layout próprio,
  crie `extratores/<id_do_condominio>.py` (é descoberto sozinho).
- Honestidade: se um formato NÃO traz algo (ex.: não lista lançamentos individuais, não traz receitas por linha), deixe
  `cobertura[...] = False` e preencha `motivos_nao_cobertos` com a razão — a regra aparece como "não verificada" com o motivo. Nunca invente.

## Contrato do extrator
```python
class Extrator:
    def __init__(self, condo: dict): ...          # cadastro + config da Validação já mesclados (condo["parser_config"], condo["regras"]...)
    def extrair(self, caminho: Path, mes: str) -> DadosRegras: ...   # mes = "AAAA-MM"
```
`DadosRegras` (modelo.py):
- `receitas: list[LinhaReceita]` — TODA linha de receita/crédito de cada conta, **com o sinal exatamente como impresso**
  (negativo = negativo; cuidado com "(5,06)", "-5,06", "5,06-" conforme o formato). `tipo`: cota/rendimento/multa_juros/transferencia/outra.
  Inclua `pagina` (PDF, 1-based) ou `local` ("linha N", planilha) e, se souber, `bbox` (pontos pdfplumber) para o print de evidência.
- `contas: list[ContaMes]` — por conta: saldo anterior, saldo atual, créditos, débitos (Resumo Financeiro Contábil) e `rendimento`
  = soma das linhas de rendimento creditadas NAQUELA conta no mês (preencha a partir de `receitas` tipo "rendimento" ou da Posição Financeira da conta).
- `lancamentos: list[LancamentoDespesa]` — cada despesa do Demonstrativo de Despesas: descrição completa (com NF e "PARC n/total"),
  valor, **categoria = a subconta como aparece no arquivo (nome bruto, sem cat_map)**, conta de origem, código, data, página/linha.
  Se o formato tem hierarquia (conta > grupo > subconta), `categoria` é o nível de subconta usado no balancete.
- `cobertura = {"receitas": bool, "rendimentos": bool, "lancamentos": bool}` e `motivos_nao_cobertos`.
- `avisos`: limitações da leitura em texto.

**Conferência obrigatória da extração** (`regras.py::verificar_extracao`): a soma dos `lancamentos` de cada conta deve fechar com
o **débito dessa conta** no Resumo Financeiro (±0,01). Se não fecha, falta/sobra lançamento: corrija o extrator até fechar em TODOS os meses
disponíveis, ou explique no relatório por que o arquivo não fecha (ex.: transferências entre contas dentro do débito — nesse caso marque no aviso).
Para receitas, confira: soma das `receitas` de cada conta ≈ créditos da conta (diferenças explicadas ao centavo ou avisadas).

## Como testar
`python -X utf8 data/auditoria_categorias/testar_extrator.py <id_condominio> [--meses AAAA-MM,AAAA-MM] [--achados]`
roda o extrator em TODOS os meses da pasta do projeto do condomínio (ordem cronológica), mostra cobertura, conferência da extração,
receitas negativas, taxas de rendimento por conta e (com `--achados`) os achados das regras de cada mês comparado ao mês anterior.
Teste de ponta a ponta (gera o PDF do relatório em pasta temporária, sem tocar em `data/`):
`python -X utf8 data/auditoria_categorias/e2e_regras.py <id> <AAAA-MM> "<caminho do arquivo do mês>"` (veja os PNG `e2e_<id>_N.png`).
Referência pronta: `extratores/habitacional_xlsx.py` (planilha Habitacional, Alvorada) — leia antes de começar.
A pasta de cada condomínio: `conciliacao.pasta_prestacao.pasta_do_condominio(condo)` com `condo = config_validacao.aplicar(<item do condominios.json>)`.
Despacho dos módulos: `extratores/__init__.py` (por `empresa_gestora`, ou arquivo `extratores/<id_condominio>.py`).

## O que entregar no relatório (`data/auditoria_categorias/diag/extrator_<grupo>.md`)
1. Para CADA condomínio do grupo: formato lido, cobertura das 5 regras (sim/não + motivo), e resultado da conferência da extração em todos os meses testados.
2. **Achados reais das regras** nos meses históricos (receita negativa, rendimento, sem identificação, parcelas, subcontas): liste os que parecem
   verdadeiros (com valores/mês) e os falsos positivos que você viu, com a causa.
3. **Calibração do rendimento** (regra 3): por condomínio, a taxa rendimento/saldo médio de cada conta em cada mês (saída do testar_extrator),
   dizendo em quais contas ele é proporcional (tolerância 25% sobre a mediana) e quais contas têm comportamento próprio; proponha, quando preciso,
   `regras.rendimento = {"ignorar_contas": [...], "tolerancia": x}` para `config/validacao_balancetes.json` (descreva; não edite o arquivo).
4. Ruído: nº médio de achados das regras por mês "normal" por condomínio; alvo ≤ 5; explique e proponha ajuste se maior (ex.: normalização de nomes de subconta entre meses).
5. Mudanças que você acha necessárias em arquivos que não são seus.

---
## Estado em 07/10/2026 (leia antes de mexer)
- **Cobertura:** 53 dos 54 condomínios têm extrator (só `demonstracao` não tem arquivo). Matriz regra x condomínio:
  `data/auditoria_categorias/matriz_regras.md` (regerar com `matriz_regras.py`).
- **Config por condomínio:** `config/validacao_balancetes.json` (mesclada sobre `config/condominios.json` por
  `conciliacao/config_validacao.py`; o cadastro compartilhado NÃO é alterado). Chaves usadas em `regras`:
  `rendimento` {base, tolerancia, ignorar_contas, contas_aplicadas}, `receita_negativa` {ignorar_tipos,
  ignorar_descricao, estruturais}, `compensacoes` [{nome, regex, tolerancia}], `subcontas` {equivalentes};
  fora de `regras`: `pasta_prestacao`, `parser_config` extra, `leitor_financeiro`, `fechamento_categorias_ignorar`.
- **Leitores financeiros:** `conciliacao/leitores_validacao/` (adaptadores corrigidos só para a Validação) e, quando o
  adaptador não lê o arquivo, a ponte `demonstrativo_reader._bal_pelo_extrator_das_regras`.
- **Velocidade:** `conciliacao/pdf_cache.py` guarda em `data/cache_texto_pdf/` o texto de cada página lido pelo
  pdfplumber (mesmo texto; chave = caminho + tamanho + data do arquivo) e evita reabrir PDF já lido por inteiro.
  `scripts/aquecer_cache_pdf.py` lê o PDF mais recente de cada condomínio uma vez (log em `data/aquecer_cache_pdf.log`).
  Desligar o cache: `SINDICOMPANY_SEM_CACHE_TEXTO=1`.
- **Checagens de leitura** (`checagens_leitura.py`): período impresso x mês pedido; categorias que não fecham.
  `localizar_arquivo_mes` ignora PDF cujo período impresso contradiz o nome do arquivo e prefere a mesma extensão.
- **Ferramentas de teste:** `data/auditoria_categorias/` → `testar_extrator.py`, `ruido_regras.py`, `e2e_regras.py`,
  `varredura_extrair.py` (etapa extrair completa em todos os condomínios), `auditar_categorias.py`.
- **Planilhas com link** (Habitacional etc.): link na coluna Anexo = comprovante existe (`gerar_achados_planilha_com_links`).
