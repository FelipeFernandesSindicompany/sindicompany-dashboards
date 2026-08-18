"""
Adapter SK Condomínios PDF — "Prestação de Contas MM.YYYY.pdf"

Estrutura do PDF (gerado por Sk Condominio Ltda):

  Pág BALANCETE CONTÁBIL MENSAL:
    SALDO ANTERIOR
      <conta>   <valor>
      TOTAL     <total>
    RECEITAS
      01 RECEITA  <total>  100,00
      01.xx.xx  <sub>  <valor>  <%>
      TOTAL GERAL RECEITAS  <valor>  100,00
    DESPESAS
      02 DESPESA  <total>  100,00
      02.XX  <categoria>  <valor>  <%>    ← nível 2 = categorias
      02.XX.XX  <sub>  <valor>  <%>       ← nível 3 = sub-itens (ignorados)
      TOTAL GERAL DESPESAS  <valor>  100,00
    SALDO FINAL
      <conta>   <valor>
      TOTAL     <total>

  Pág PREVISTO X REALIZADO ÚLTIMOS 12 MESES:
    Item  MÊS1  MÊS2 ...  MÊS12
    Previsto
    Receitas  X  X  ...   <prev_ultimo_mes>
    Despesas  X  X  ...   <desp_prev_ultimo_mes>

  Pág HISTÓRICO DE INADIMPLENTES:
    "Nenhum inadimplente no período."
    OU listagem de devedores + "Total geral: <valor>"

Condomínios: Reserva Verde
"""
from pathlib import Path
import re
from adapters.base import AdapterBase, DadosFinanceiros


def _num(s) -> float:
    """Converte string monetária BR (1.234,56) para float."""
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return abs(float(s))
    s = re.sub(r"[^\d,]", "", str(s).strip())
    if not s:
        return 0.0
    s = s.replace(",", ".")
    # remove pontos de milhar (exceto o decimal)
    parts = s.split(".")
    if len(parts) > 2:
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(s)
    except Exception:
        return 0.0


# Mapeamento padrão: código/nome do PDF → nome canônico das categorias
_DEFAULT_CAT_MAP = {
    # Nível 2 do plano de contas SK
    "MANUTENÇÃO E CONSERVAÇÃO":  "MANUTENÇÃO",
    "MANUTENCAO E CONSERVACAO":  "MANUTENÇÃO",
    "DESPESAS ADMINISTRATIVAS":  "ADMINISTRATIVO",
    "BENS DE CONSUMO":           "CONSUMOS",
    "IMPOSTOS RETIDOS":          "TARIFAS E IMPOSTOS",
    "DESPESA FINANCEIRA":        "ADMINISTRATIVO",   # Jurídico → soma em ADMINISTRATIVO
    "CONTRATOS":                 "CONTRATOS",
    # Variações possíveis
    "MANUTENÇÃO":                "MANUTENÇÃO",
    "ADMINISTRATIVO":            "ADMINISTRATIVO",
    "CONSUMO":                   "CONSUMOS",
    "CONSUMOS":                  "CONSUMOS",
    "IMPOSTOS":                  "TARIFAS E IMPOSTOS",
    "JURÍDICO":                  "ADMINISTRATIVO",
    "JURIDICO":                  "ADMINISTRATIVO",
    "OUTRAS DESPESAS":           "ADMINISTRATIVO",
}

# Classificação das contas bancárias SK
_BANCO_CC  = ("BANCO INTER", "INTER", "CORRENTE", "C/C", "ORDINARIA", "ORDINÁRIA")
_BANCO_CDB = ("APLICAÇÃO", "APLICACAO", "RESERVA", "CDB", "POUPANÇA", "POUPANCA",
               "INVESTIMENTO", "FUNDO")


def _classifica_conta_banco(nome: str):
    """Retorna 'cc', 'cdb' ou 'priv' para o nome da conta."""
    upper = nome.upper()
    if any(k in upper for k in _BANCO_CC):
        return "cc"
    if any(k in upper for k in _BANCO_CDB):
        return "cdb"
    return "priv"


class AdapterSKCondominiosPDF(AdapterBase):
    """
    Adapter para PDFs da administradora SK Condomínios.
    Formato: BALANCETE CONTÁBIL MENSAL com seções RECEITAS / DESPESAS / SALDO FINAL.
    """

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
            total_unidades=self.config.get("unidades", 0),
        )

        with pdfplumber.open(str(caminho)) as pdf:
            textos = [p.extract_text() or "" for p in pdf.pages]

        texto_completo = "\n".join(textos)

        self._parsear_balancete(textos, texto_completo, dados)
        self._parsear_previsto(textos, texto_completo, dados, mes_referencia)
        self._parsear_inadimplencia(textos, texto_completo, dados)

        if dados.receita_prevista == 0:
            dados.receita_prevista = dados.receita_realizada

        return dados

    # ──────────────────────────────────────────────────────────────────────────
    # 1. BALANCETE CONTÁBIL MENSAL
    # ──────────────────────────────────────────────────────────────────────────

    def _parsear_balancete(self, textos: list, texto_completo: str,
                           dados: DadosFinanceiros):
        """Lê a página BALANCETE CONTÁBIL MENSAL."""

        # Encontra a página que contém "BALANCETE CONTÁBIL MENSAL" com dados reais
        # (não o índice - o índice não tem "SALDO ANTERIOR")
        balancete_txt = ""
        for txt in textos:
            if ("BALANCETE CONT" in txt.upper() and
                    "SALDO ANTERIOR" in txt.upper() and
                    "TOTAL GERAL" in txt.upper()):
                balancete_txt = txt
                break

        if not balancete_txt:
            return  # Página não encontrada

        linhas = [l.strip() for l in balancete_txt.split("\n") if l.strip()]

        secao = None   # "saldo_ant" | "receitas" | "despesas" | "saldo_final"

        saldo_ant_contas: dict = {}   # nome → valor
        saldo_fin_contas: dict = {}   # nome → valor
        despesas_nivel2: dict = {}    # nome_cat → valor (acumulado)

        cat_map_extra = self.parser_config.get("cat_map", {})

        for linha in linhas:
            upper = linha.upper()

            # ── Troca de seção ──────────────────────────────────────────────
            if re.match(r"^SALDO ANTERIOR\s*$", upper):
                secao = "saldo_ant"
                continue
            if re.match(r"^RECEITAS?\s*$", upper):
                secao = "receitas"
                continue
            if re.match(r"^DESPESAS?\s*$", upper):
                secao = "despesas"
                continue
            if re.match(r"^RESUMO DE RECEITAS", upper):
                secao = "resumo"
                continue
            if re.match(r"^SALDO FINAL\s*$", upper):
                secao = "saldo_final"
                continue
            if re.match(r"^RESUMO DA MOVIMENTA", upper):
                secao = None  # restante não é necessário
                continue

            # ── SALDO ANTERIOR ───────────────────────────────────────────────
            if secao == "saldo_ant":
                # "TOTAL   32.139,95"
                m = re.match(r"^TOTAL\s+([\d.,]+)\s*$", linha, re.IGNORECASE)
                if m:
                    dados.saldo_anterior = _num(m.group(1))
                    continue
                # "<conta> <valor>" — nome seguido de valor BR no final da linha
                m2 = re.match(r"^(.+?)\s+([\d.]+,\d{2})\s*$", linha)
                if m2:
                    nome = m2.group(1).strip()
                    val = _num(m2.group(2))
                    if val > 0 and nome.upper() not in ("CONTA FINANCEIRA", "VALOR"):
                        saldo_ant_contas[nome] = val
                continue

            # ── RECEITAS ─────────────────────────────────────────────────────
            if secao == "receitas":
                # "TOTAL GERAL RECEITAS  27.252,22  100,00"
                m = re.match(r"^TOTAL GERAL RECEITAS\s+([\d.,]+)", linha, re.IGNORECASE)
                if m:
                    dados.receita_realizada = _num(m.group(1))
                continue

            # ── DESPESAS ─────────────────────────────────────────────────────
            if secao == "despesas":
                # "TOTAL GERAL DESPESAS  24.595,58  100,00"
                m_tot = re.match(r"^TOTAL GERAL DESPESAS\s+([\d.,]+)", linha, re.IGNORECASE)
                if m_tot:
                    dados.despesa_total = _num(m_tot.group(1))
                    continue

                # Linhas de nível 2: "02.XX  <descrição>  <valor>  <%>"
                # Linhas de nível 3: "02.XX.XX  ..." → ignorar
                m_cat = re.match(
                    r"^02\.(\d{2})\s+(.+?)\s+([\d.,]+)\s+[\d.,]+\s*$", linha
                )
                if m_cat:
                    nome_raw = m_cat.group(2).strip()
                    val = _num(m_cat.group(3))
                    if val > 0:
                        canonical = self._canonico(nome_raw, cat_map_extra)
                        despesas_nivel2[canonical] = (
                            despesas_nivel2.get(canonical, 0.0) + val
                        )
                continue

            # ── SALDO FINAL ──────────────────────────────────────────────────
            if secao == "saldo_final":
                # "TOTAL  34.796,59"
                m = re.match(r"^TOTAL\s+([\d.,]+)\s*$", linha, re.IGNORECASE)
                if m:
                    dados.saldo_atual = _num(m.group(1))
                    continue
                # "<conta> <valor>" — nome seguido de valor BR no final da linha
                m2 = re.match(r"^(.+?)\s+([\d.]+,\d{2})\s*$", linha)
                if m2:
                    nome = m2.group(1).strip()
                    val = _num(m2.group(2))
                    if val > 0 and nome.upper() not in ("CONTA FINANCEIRA", "VALOR"):
                        saldo_fin_contas[nome] = val
                continue

        # ── Banco: distribui saldo final por tipo ────────────────────────────
        for nome, val in saldo_fin_contas.items():
            tipo = _classifica_conta_banco(nome)
            if tipo == "cc":
                dados.banco_cc = round(dados.banco_cc + val, 2)
            elif tipo == "cdb":
                dados.banco_cdb = round(dados.banco_cdb + val, 2)
            else:
                dados.banco_priv = round(dados.banco_priv + val, 2)

        # Fallback banco: se não encontrou contas no SALDO FINAL, usa SALDO ANTERIOR
        if dados.banco_cc == 0 and dados.banco_cdb == 0 and saldo_ant_contas:
            for nome, val in saldo_ant_contas.items():
                tipo = _classifica_conta_banco(nome)
                if tipo == "cc":
                    dados.banco_cc = round(dados.banco_cc + val, 2)
                elif tipo == "cdb":
                    dados.banco_cdb = round(dados.banco_cdb + val, 2)
                else:
                    dados.banco_priv = round(dados.banco_priv + val, 2)

        # ── Categorias de despesa ─────────────────────────────────────────────
        for cat, val in despesas_nivel2.items():
            dados.categorias_despesa[cat] = (
                dados.categorias_despesa.get(cat, 0.0) + val
            )

        # Fallback final
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        # ── contas_detalhe: usa saldo anterior/final das contas bancárias ────
        if saldo_ant_contas and saldo_fin_contas:
            for nome, saldo_a in saldo_ant_contas.items():
                saldo_f = saldo_fin_contas.get(nome, saldo_a)
                dados.contas_detalhe.append({
                    "nome":       nome.upper(),
                    "saldo_ant":  saldo_a,
                    "creditos":   0.0,
                    "debitos":    0.0,
                    "saldo_atual": saldo_f,
                })

    # ──────────────────────────────────────────────────────────────────────────
    # 2. PREVISTO X REALIZADO ÚLTIMOS 12 MESES
    # ──────────────────────────────────────────────────────────────────────────

    def _parsear_previsto(self, textos: list, texto_completo: str,
                          dados: DadosFinanceiros, mes_referencia: str):
        """
        Lê a tabela PREVISTO X REALIZADO ÚLTIMOS 12 MESES.
        A última coluna da linha 'Receitas' é o previsto do mês de referência.
        """
        for txt in textos:
            if "PREVISTO X REALIZADO" not in txt.upper():
                continue
            if "ÚLTIMOS 12 MESES" not in txt.upper() and "ULTIMOS 12 MESES" not in txt.upper():
                continue

            linhas = txt.split("\n")
            cabecalho_cols = []
            in_table = False

            for linha in linhas:
                l = linha.strip()
                upper = l.upper()

                # Linha de cabeçalho: "Item AGO 2025 SET 2025 ... JUL 2026"
                if re.match(r"^Item\s+", l, re.IGNORECASE):
                    # Extrai os nomes de coluna (meses)
                    partes = l.split()
                    # Formato: Item MES ANO MES ANO ...
                    cabecalho_cols = []
                    i = 1
                    while i < len(partes) - 1:
                        try:
                            mes_nome = partes[i]
                            ano = partes[i + 1]
                            if re.match(r"^\d{4}$", ano):
                                cabecalho_cols.append(f"{mes_nome} {ano}")
                                i += 2
                            else:
                                i += 1
                        except IndexError:
                            break
                    in_table = True
                    continue

                if not in_table:
                    continue

                # Seção "Previsto" — linha de título, não tem dados
                if re.match(r"^Previsto\s*$", l, re.IGNORECASE):
                    continue

                # Linha "Receitas  X  X  ...  X" — valores numéricos por coluna
                if re.match(r"^Receitas\s+[\d.,]", l, re.IGNORECASE):
                    valores = re.findall(r"[\d.,]+", l[len("Receitas"):].strip())
                    if valores and cabecalho_cols:
                        # O último valor corresponde à última coluna (mês mais recente)
                        if len(valores) >= len(cabecalho_cols):
                            prev_val = _num(valores[len(cabecalho_cols) - 1])
                        else:
                            prev_val = _num(valores[-1])
                        if prev_val > 0:
                            dados.receita_prevista = prev_val
                    return  # Encontrou — pode sair

    # ──────────────────────────────────────────────────────────────────────────
    # 3. HISTÓRICO DE INADIMPLENTES
    # ──────────────────────────────────────────────────────────────────────────

    def _parsear_inadimplencia(self, textos: list, texto_completo: str,
                                dados: DadosFinanceiros):
        """
        Lê a página HISTÓRICO DE INADIMPLENTES.
        "Nenhum inadimplente no período." → inad = 0
        Ou "Total geral: <valor>" ao final dos devedores.
        """
        for txt in textos:
            if "INADIMPLENTES" not in txt.upper() and "INADIMPLÊNCIA" not in txt.upper():
                continue
            if "HISTÓRICO" not in txt.upper() and "HISTORICO" not in txt.upper():
                continue

            # Verifica se não tem inadimplentes
            if re.search(r"nenhum inadimplente", txt, re.IGNORECASE):
                dados.inadimplencia_valor = 0.0
                return

            # Procura "Total geral: <valor>"
            m = re.search(r"Total geral:\s*([\d.,]+)", txt, re.IGNORECASE)
            if m:
                dados.inadimplencia_valor = _num(m.group(1))
                return

            # Fallback: soma de "Total da unidade: <valor>"
            total_u = sum(
                _num(m2.group(1))
                for m2 in re.finditer(r"Total da unidade:\s*([\d.,]+)", txt)
            )
            if total_u > 0:
                dados.inadimplencia_valor = total_u
                return

        # Se página não encontrada, mantém 0

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _canonico(self, nome_raw: str, cat_map_extra: dict) -> str:
        """Resolve nome bruto da categoria para o nome canônico."""
        upper = nome_raw.upper().strip()
        # 1. Override do parser_config do condomínio
        if nome_raw in cat_map_extra:
            return cat_map_extra[nome_raw]
        if upper in cat_map_extra:
            return cat_map_extra[upper]
        # 2. Mapeamento padrão SK
        if upper in _DEFAULT_CAT_MAP:
            return _DEFAULT_CAT_MAP[upper]
        # 3. Title case como fallback
        return nome_raw.title()

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """SK Condomínios usa PDF — tenta trocar extensão."""
        for ext in [".pdf", ".PDF"]:
            p = caminho.parent / (caminho.stem + ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        pdfs = sorted(
            list(caminho.parent.glob("*.pdf")) +
            list(caminho.parent.glob("*.PDF")),
            key=lambda x: x.stat().st_mtime, reverse=True,
        )
        if pdfs:
            return self.ler_pdf(pdfs[0], mes_referencia)
        raise FileNotFoundError(
            f"Nenhum PDF SK Condomínios encontrado em {caminho.parent}"
        )
