"""
Adapter Addomus PDF — Software Addomus (Pasta de Prestação de Contas)

Estrutura confirmada (Spazio Jardins da Orla):

  "Demonstrativo de Receitas e Despesas" (resumo, ~pág. 20) e
  "Demonstrativo Analítico de Receitas e Despesas" (detalhado, bem mais
  adiante no arquivo) — ambos contêm, ao final de cada grupo, uma linha de
  subtotal no formato:

      [TOTAL: ]1.X - Nome da Receita   valor
      [TOTAL: ]2.X - Nome da Despesa   -valor

  onde X é um único nível (ex: "2.1", "2.7"), nunca "2.1.5" ou "2.1.5.1"
  (essas são sub-categorias e são ignoradas). O detalhado sempre prefixa
  "TOTAL:"; o resumo às vezes não. Usamos apenas o padrão "TOTAL: N.X -"
  (presente em ambas as seções) para não contar em dobro, e paramos de ler
  páginas assim que virmos "TOTAL: 2 - DESPESAS" (fecha a seção detalhada).

  Linha "RESULTADO":
      RESULTADO Saldo Inicial Receitas Despesas Resultado Saldo Final
      Do Período  <saldo_ant> <receitas> <-despesas> <resultado> <saldo_atual>

  Tabela "DISPONÍVEL" (fundos — 5 números: saldo_ini créditos débitos
  transferências saldo_final):
      DISPONÍVEL Saldo inicial Créditos Débitos Transferências Saldo Final
      Fundo Ordinário / Fundo de Reserva / Fundo de Obras /
      Salão de Festas / Consumo individual / Garantidora
      Total do DISPONÍVEL   ← ignorado (linha de fechamento)

  Tabela "FINANCEIRO" (contas bancárias reais — 6 números: saldo_ini
  créditos débitos transferências tarifa saldo_final):
      FINANCEIRO Saldo inicial Créditos Débitos Transferências Tarifa Saldo Final
      Itaú / ProSíndico / Caixa Síndico /
      Fundo Investimento PRIVILEGE / CDB iTAÚ
      Total do FINANCEIRO   ← ignorado (linha de fechamento)

  Classificação bancária (banco_cc / banco_cdb / banco_priv), pelo saldo
  final (6º número da linha):
      conta corrente (Itaú, ProSíndico, Caixa Síndico)  → banco_cc
      aplicação/CDB (nome contém "CDB")                 → banco_cdb
      demais fundos de investimento (ex: PRIVILEGE)     → banco_priv

  Inadimplência: este relatório não traz um resumo consolidado de
  inadimplência (só o livro-razão de cobranças por unidade); fica 0.0
  até que um relatório específico de inadimplência seja mapeado.

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

        # O documento traz o resumo (RESULTADO/DISPONÍVEL/FINANCEIRO) perto do
        # início e o detalhamento por categoria ("Demonstrativo Analítico")
        # bem mais adiante — só então paramos, para não ler as 300+ páginas
        # de anexos (livro-razão por unidade) que vêm depois.
        textos = []
        with pdfplumber.open(str(caminho)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                textos.append(t)
                # "TOTAL: 2 - DESPESAS" (com dois-pontos) só aparece uma vez,
                # fechando a seção detalhada — a versão resumida usa
                # "Total de 2 - DESPESAS" (sem dois-pontos, casing variável),
                # que não deve disparar a parada prematuramente.
                if "TOTAL: 2 - DESPESAS" in t:
                    break

        texto_total = "\n".join(textos)

        # ── 1. RESULTADO ──────────────────────────────────────────────────
        m_result = re.search(
            r"Do Per[íi]odo\s+" + r"\s+".join([_LINHA_NUM] * 5),
            texto_total,
        )
        if m_result:
            dados.saldo_anterior = _num(m_result.group(1))
            dados.receita_realizada = _num(m_result.group(2))
            dados.despesa_total = _num(m_result.group(3))
            dados.saldo_atual = _num(m_result.group(5))

        # ── 2. Categorias de despesa — "TOTAL: 2.X - Nome  valor" ─────────
        # Nível único (2.X, nunca 2.X.Y) — ignora "TOTAL: 2 - DESPESAS".
        vistos = set()
        for m in re.finditer(
            r"^TOTAL:\s*2\.(\d+)\s*-\s*(.+?)\s+-?([\d.]+,\d{2})\s*$",
            texto_total,
            re.MULTILINE,
        ):
            nivel, nome, valor = m.group(1), m.group(2).strip(), m.group(3)
            chave = f"2.{nivel}"
            if chave in vistos:
                continue
            vistos.add(chave)
            nome_canonico = nome.strip().title() if nome.isupper() else nome.strip()
            dados.categorias_despesa[nome_canonico] = dados.categorias_despesa.get(
                nome_canonico, 0.0
            ) + _num(valor)

        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        # ── 3. DISPONÍVEL — contas_detalhe (fundos) ────────────────────────
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
                "saldo_atual": _num(m.group(5)),
            })

        # ── 4. FINANCEIRO — saldos bancários reais ─────────────────────────
        # "Nome  saldo_ini  creditos  debitos  transferencias  tarifa  saldo_final"
        # 7 grupos ao todo: group(1)=nome, group(2..7)=os 6 números.
        for m in re.finditer(
            r"^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 ./'-]*?)\s+" + r"\s+".join([_LINHA_NUM] * 6) + r"\s*$",
            texto_total,
            re.MULTILINE,
        ):
            nome_conta = m.group(1).strip()
            if nome_conta.lower().startswith("total"):
                continue
            saldo_final = _num(m.group(7))
            n = nome_conta.upper()
            if "CDB" in n or "APLICA" in n:
                dados.banco_cdb += saldo_final
            elif "ITA" in n or "PROS" in n or "CAIXA" in n or "CORRENTE" in n:
                dados.banco_cc += saldo_final
            else:
                dados.banco_priv += saldo_final

        dados.total_unidades = self.config.get("unidades", 0)
        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """Redireciona para ler_pdf — Addomus usa PDF, não XLSX."""
        for ext in [".pdf", ".PDF"]:
            p = caminho.parent / (caminho.stem + ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        raise FileNotFoundError(f"Nenhum PDF Addomus encontrado em {caminho.parent}")
