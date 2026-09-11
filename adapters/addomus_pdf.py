"""
Adapter Addomus PDF — Software Addomus (Pasta de Prestação de Contas)

Estrutura confirmada (Spazio Jardins da Orla):

  Linha "RESULTADO" (resumo geral, todas as contas somadas):
      RESULTADO Saldo Inicial Receitas Despesas Resultado Saldo Final
      Do Período  <saldo_ant> <receitas> <-despesas> <resultado> <saldo_atual>

  Tabela "DISPONÍVEL" (fundos — 5 números: saldo_ini créditos débitos
  transferências saldo_final):
      DISPONÍVEL Saldo inicial Créditos Débitos Transferências Saldo Final
      Fundo Ordinário / Fundo de Reserva / Fundo de Obras /
      Salão de Festas / Consumo individual / Garantidora
      Total do DISPONÍVEL   ← ignorado (linha de fechamento)

  banco_cc / banco_cdb / banco_priv — classificação por FUNDO (usada no
  gráfico "Saldo por Conta" da Visão Geral), igual à convenção dos demais
  dashboards Sindicompany (confirmado em Alvorada: banco.cc = saldo do
  fundo ORDINÁRIA, banco.cdb = saldo do FUNDO DE RESERVA, banco.priv =
  soma dos demais fundos):
      banco_cc   = saldo atual de "Fundo Ordinário"
      banco_cdb  = saldo atual de "Fundo de Reserva"
      banco_priv = soma do saldo atual dos demais fundos (Obras, Salão de
                   Festas, Consumo individual, Garantidora, ...)

  banco_extra — contas bancárias/aplicações REAIS (usadas na aba "Saldo
  Bancário", diferente do "Saldo por Conta" acima que é por fundo), da
  tabela "FINANCEIRO" (6 números: saldo_ini créditos débitos
  transferências tarifa saldo_final — só o saldo_final é usado):
      FINANCEIRO Saldo inicial Créditos Débitos Transferências Tarifa Saldo Final
      Itaú / ProSíndico / Caixa Síndico /
      Fundo Investimento PRIVILEGE / CDB iTAÚ
      Total do FINANCEIRO   ← ignorado (linha de fechamento)
  Restrito ao bloco entre "FINANCEIRO Saldo inicial" e "Total do
  FINANCEIRO" — o PDF inteiro tem centenas de páginas de anexos que, por
  coincidência, também casam "nome + 6 números" fora desse bloco.

  Despesas por categoria — SOMENTE Conta Ordinária:
  O relatório mistura, dentro de cada categoria de despesa (2.1, 2.2, ...),
  pagamentos feitos por fundos DIFERENTES (ex: água/esgoto sai do fundo
  "Consumo individual", gás do "Salão de Festas", obras do "Fundo de
  Obras"). O padrão de todos os outros dashboards Sindicompany (ver
  adapters/datadigitus_pdf.py) é mostrar despesas apenas da CONTA
  ORDINÁRIA — replicado aqui via as páginas "Despesa" (uma por pagamento),
  cada uma com uma tabela "Composição da Despesa":

      Descrição Conta Contábil Conta Disponibilidade Rat Valor
      2.1.5.1 - Portaria                3.1 - Fundo Ordinário   Não   27.205,15

  Extraímos TODAS essas linhas (código de categoria + fundo pagador +
  valor), somamos apenas as marcadas "Fundo Ordinário" e agrupamos pelo
  código de categoria de nível 2 (ex.: "2.1.5.1" → grupo "2.1"). A
  categoria "2.8 — Obras e Benfeitorias" é 100% paga pelo Fundo de Obras
  e por isso nunca aparece no resultado. O total bate exatamente com o
  débito da linha "Fundo Ordinário" da tabela DISPONÍVEL (validado em
  Jun/26 e Jul/26).

  Inadimplência: presente apenas em alguns meses, como anexo
  "202xxx Inadimplencia Prosindico no tempo.pdf" ("Anexos da Prestação de
  Contas", perto do Termo de Encerramento):

      Mês 2020 2021 2022 2023 2024 2025 2026 Total Geral
      Total Valor em R$ devido na [época]: 2.103 9.930 ... 76.726 291.259
      NN unidades estão inadimplentes ... perfazendo XX% do total de unidades.

  O valor relevante é a INADIMPLÊNCIA DO ANO CORRENTE (penúltima coluna,
  ex.: 76.726 = dívidas originadas em 2026), não o "Total Geral" (última
  coluna, soma histórica de 2020 a 2026 — não é o saldo em aberto do
  período). Se o anexo não existir no mês (ex.: Jul/26), inadimplencia_valor
  fica 0.0 — o chamador (script de injeção) deve decidir se repete o
  último valor conhecido ou deixa em aberto.

Condomínios: Spazio Jardins da Orla
"""
from pathlib import Path
import re
from adapters.base import AdapterBase, DadosFinanceiros


def _num(s: str) -> float:
    """Converte string numérica brasileira (1.234,56) para float."""
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


# Linhas de fundo na tabela DISPONÍVEL, na ordem em que aparecem.
_FUNDOS = [
    "Fundo Ordinário",
    "Fundo de Reserva",
    "Fundo de Obras",
    "Salão de Festas",
    "Consumo individual",
    "Garantidora",
]

_LINHA_NUM = r"(-?[\d.]+,\d{2})"

# Nome canônico de cada grupo de despesa nível 2 (código "2.X").
_CATEGORIAS_NIVEL2 = {
    "2.1": "Despesas com Pessoal",
    "2.2": "Consumo",
    "2.3": "Manutenção e Conservação Recorrente",
    "2.4": "Administrativas",
    "2.6": "Material para Consumo e Reposição",
    "2.7": "Despesas Extraordinárias",
    "2.8": "Obras e Benfeitorias (Aprovado AGO)",  # sempre Fundo de Obras — nunca somado
}

# Linha de "Composição da Despesa": código da categoria (2.X.Y...), texto
# livre (fornecedor/descrição, pode ficar vazio se quebrar de linha), código
# do fundo pagador (3.Y), nome do fundo, rateio (Sim/Não) e valor.
_RE_COMPOSICAO = re.compile(
    r"(\d\.\d+(?:\.\d+)*)\s*-\s*.*?(\d\.\d+)\s*-\s*(.*?)\s+(Sim|Não)\s+(-?[\d.]+,\d{2})\s*$",
    re.MULTILINE,
)


class AdapterAddomusPDF(AdapterBase):
    """
    Adapter para PDFs gerados pelo software Addomus
    ("Pasta de Prestação de Contas").
    Implementa apenas ler_pdf(); ler_xlsx() redireciona para ler_pdf().
    """

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        # As páginas "Despesa" (Composição da Despesa, necessárias para o
        # filtro por Conta Ordinária) ficam perto do fim do documento —
        # é preciso ler o PDF inteiro (não só o resumo do início).
        with pdfplumber.open(str(caminho)) as pdf:
            texto_total = "\n".join(p.extract_text() or "" for p in pdf.pages)

        # ── 1. RESULTADO (todas as contas somadas) ─────────────────────────
        m_result = re.search(
            r"Do Per[íi]odo\s+" + r"\s+".join([_LINHA_NUM] * 5),
            texto_total,
        )
        if m_result:
            dados.saldo_anterior = _num(m_result.group(1))
            dados.receita_realizada = _num(m_result.group(2))
            dados.saldo_atual = _num(m_result.group(5))

        # ── 2. Despesas por categoria — SOMENTE Fundo Ordinário ────────────
        for m in _RE_COMPOSICAO.finditer(texto_total):
            cod_categoria, cod_fundo, nome_fundo, _rat, valor = m.groups()
            if "Fundo Ordinário" not in nome_fundo and cod_fundo != "3.1":
                continue
            partes = cod_categoria.split(".")
            chave_nivel2 = f"{partes[0]}.{partes[1]}"
            nome_canonico = _CATEGORIAS_NIVEL2.get(chave_nivel2)
            if not nome_canonico:
                continue  # categoria fora do mapa conhecido (ex: receitas "1.x")
            dados.categorias_despesa[nome_canonico] = (
                dados.categorias_despesa.get(nome_canonico, 0.0) + _num(valor)
            )

        # despesa_total = soma das categorias da Conta Ordinária (bate com o
        # débito do Fundo Ordinário na tabela DISPONÍVEL).
        dados.despesa_total = sum(dados.categorias_despesa.values())

        # ── 3. DISPONÍVEL — contas_detalhe (fundos) ────────────────────────
        # 6 números: saldo_ini créditos débitos TRANSFERÊNCIAS saldo_final
        # (a 4ª coluna, "transferencias", é movimentação interna entre
        # fundos — mostrada na tabela do Balanço Mensal, não soma no total).
        for fundo in _FUNDOS:
            m = re.search(
                re.escape(fundo) + r"\s+" + r"\s+".join([_LINHA_NUM] * 5),
                texto_total,
            )
            if not m:
                continue
            dados.contas_detalhe.append({
                "nome": fundo,
                "saldo_ant": _num(m.group(1)),
                "creditos": _num(m.group(2)),
                "debitos": _num(m.group(3)),
                "transferencias": _num(m.group(4)) * (
                    -1.0 if m.group(4).strip().startswith("-") else 1.0
                ),
                "saldo_atual": _num(m.group(5)),
            })

        # ── 4. banco_cc / banco_cdb / banco_priv — por fundo ───────────────
        for c in dados.contas_detalhe:
            if c["nome"] == "Fundo Ordinário":
                dados.banco_cc += c["saldo_atual"]
            elif c["nome"] == "Fundo de Reserva":
                dados.banco_cdb += c["saldo_atual"]
            else:
                dados.banco_priv += c["saldo_atual"]

        # ── 4b. banco_extra — contas bancárias reais (tabela FINANCEIRO) ───
        m_fin_ini = re.search(r"FINANCEIRO\s+Saldo\s+inicial", texto_total)
        m_fin_fim = re.search(r"Total\s+do\s+FINANCEIRO", texto_total)
        bloco_financeiro = (
            texto_total[m_fin_ini.start():m_fin_fim.start()]
            if m_fin_ini and m_fin_fim else ""
        )
        for m in re.finditer(
            r"^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 ./'-]*?)\s+" + r"\s+".join([_LINHA_NUM] * 6) + r"\s*$",
            bloco_financeiro,
            re.MULTILINE,
        ):
            nome_conta = m.group(1).strip()
            if nome_conta.lower().startswith("total"):
                continue
            dados.banco_extra[nome_conta] = _num(m.group(7))  # 7º grupo = saldo final

        # ── 5. Inadimplência (anexo "Inadimplencia Prosindico no tempo") ───
        # Linha (uma só, sem quebra): "Total Valor em R$ devido na [época:]
        # 2.103 9.930 ... 76.726 291.259" — colunas = anos (cabeçalho "Mês
        # 2020 2021 ... 2026 Total Geral") seguidas da coluna "Total Geral".
        # Usa o valor do ANO CORRENTE (dívida originada no próprio ano),
        # não o "Total Geral" (soma histórica desde 2020 — não é o saldo em
        # aberto do período).
        m_inad = re.search(
            r"Total\s+Valor\s+em\s+R\$\s+devido\s+na[^\d\n]*"
            r"((?:[\d.]+\s+)*[\d.]+)",
            texto_total,
        )
        if m_inad:
            numeros = m_inad.group(1).split()
            ano_atual = mes_referencia.split("-")[0]
            m_anos = re.search(r"M[eê]s\s+((?:\d{4}\s+)+)Total\s+Geral", texto_total)
            idx = None
            if m_anos:
                anos = m_anos.group(1).split()
                if ano_atual in anos and len(anos) == len(numeros) - 1:
                    idx = anos.index(ano_atual)
            if idx is not None:
                dados.inadimplencia_valor = _num(numeros[idx])
            elif len(numeros) >= 2:
                dados.inadimplencia_valor = _num(numeros[-2])  # fallback: penúltima = ano corrente
            elif numeros:
                dados.inadimplencia_valor = _num(numeros[-1])
        # Frase quebra em duas linhas: "NN unidades estão inadimplentes ...,
        # \nperfazendo XX% do total de unidades."
        m_pct = re.search(
            r"(\d+)\s+unidades\s+est[aã]o\s+inadimplentes[\s\S]*?perfazendo\s+(\d+)%",
            texto_total,
        )
        if m_pct:
            dados.unidades_inadimplentes = int(m_pct.group(1))
            pct = int(m_pct.group(2))
            if pct > 0:
                dados.total_unidades = round(dados.unidades_inadimplentes / (pct / 100))
            dados.inadimplencia_percentual = float(pct)

        if not dados.total_unidades:
            dados.total_unidades = self.config.get("unidades", 0)
        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """Redireciona para ler_pdf — Addomus usa PDF, não XLSX."""
        for ext in [".pdf", ".PDF"]:
            p = caminho.parent / (caminho.stem + ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        raise FileNotFoundError(f"Nenhum PDF Addomus encontrado em {caminho.parent}")
