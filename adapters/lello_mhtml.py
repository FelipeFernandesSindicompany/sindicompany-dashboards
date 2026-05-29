"""
Adapter Lello MHTML — arquivo prestacaocontas_XXXX_YYYY_MM.xls
(arquivo é na verdade MHTML/HTML disfarçado de XLS — openpyxl/xlrd não conseguem ler)

Estrutura confirmada (Barra Viva I, Villa Park Osasco, Hub Home Club Tatuapé):
  22–28 tabelas HTML dentro do .xls

  Tabela 0 (Resumo Financeiro Contábil):
    Col: Conta | Saldo Anterior | Crédito | Débito | Saldo Atual
    Última linha = "Total" com os somatórios
    Conta "ordinaria" → banco_cc
    Conta "fundo de reserva" → banco_cdb
    Demais contas → banco_priv (soma dos saldos atuais)

  Tabela 1 (Posição Devedores):
    Col: Conta | Anterior (-) | Mês(-) | Recebido(+) | Total Atrasados
    Última linha = Total → inadimplencia_valor (col índice 4)

  Tabela 2 (ORDINARIA — Resumo emissão):
    Col: Descricao | Previsto | Realizado
    Linha "Total Devedores" → receita_prevista (col Previsto)

  Tabela "DEMONSTRATIVO DE DESPESAS" (localizada por heading):
    Hierarquia de despesas:
      Subcategoria: col[1] = "Total NOME" → col[2] = "valor( %)"
      Grupo:        col[0] = "NOME Total:" → col[2] ou col[3] = "valor( %)"
      Conta:        col[0] = "Total CONTA" → col[2] = "valor( %)"
    Linha "Total DESPESAS" → despesa_total (se não extraído da tabela 0)

  Tabela duplicada do Resumo Financeiro (penúltimas): ignorada (usa só a tabela 0)

Condomínios: Barra Viva I, Hub Home Club Tatuapé, Splendor Square, Villa Park Osasco,
             e todos que usam o sistema Lello com exportação MHTML.
"""
from __future__ import annotations

import re
from pathlib import Path

from adapters.base import AdapterBase, DadosFinanceiros

# Contas / grupos a excluir das categorias_despesa (são fundos/reservas, não despesas op.)
_EXCLUIR_CATEGORIAS = {
    "ORDINARIA",
    "DESPESAS",
    "DESPESA - FUNDO DE RESERVA",
    "FUNDO DE RESERVA",
    "FUNDO RESERVA",
    "RECUPERAÇÃO FACHADA",
    "RECUPERACAO FACHADA",
    "SALÃO DE FESTAS",
    "SALAO DE FESTAS",
    "GARAGEM",
    "ESTACIONAMENTO",
}

# Contas que identificam banco_cdb (fundo de reserva / aplicação)
_NOMES_CDB = {"fundo de reserva", "fundo reserva", "cdb", "poupanca", "poupança",
              "aplicacao", "aplicação", "investimento"}

# Contas que identificam banco_cc (conta corrente / cota ordinária)
_NOMES_CC = {"ordinaria", "ordinária", "conta corrente", "c/c"}

# Normalização de categorias → nomes canônicos do dashboard
_CAT_NORM = {
    # Pessoal / mão de obra
    "DESPESAS COM PESSOAL":         "PESSOAL",
    "PESSOAL E ENCARGOS":           "PESSOAL",
    "PESSOAL ORGÂNICO":             "PESSOAL",
    "PESSOAL PRÓPRIO":              "PESSOAL",
    "PESSOAL":                      "PESSOAL",
    # Terceirizados
    "SERVIÇOS TERCEIRIZADOS":       "SERV. TERCEIRIZADOS",
    "SERV. TERCEIRIZADOS":          "SERV. TERCEIRIZADOS",
    "SERVIÇOS CONTRATADOS":         "SERV. TERCEIRIZADOS",
    "TERCEIRIZAÇÃO":                "SERV. TERCEIRIZADOS",
    "TERCEIRIZADAS":                "SERV. TERCEIRIZADOS",
    # Consumos / concessionárias
    "TARIFAS CONCESSIONÁRIAS":      "CONSUMOS",
    "CONCESSIONÁRIAS":              "CONSUMOS",
    "CONSUMOS":                     "CONSUMOS",
    "CONSUMO":                      "CONSUMOS",
    "CONTAS DE CONSUMO":            "CONSUMOS",
    # Manutenção contratos
    "MANUTENÇÃO - CONTRATOS":       "MANUT/CONSERV. CONTRAT.",
    "MANUT/CONSERV. CONTRAT.":      "MANUT/CONSERV. CONTRAT.",
    "MANUT. CONTRATADA":            "MANUT/CONSERV. CONTRAT.",
    "CONSERV./MANUT. CONTRATOS":    "MANUT/CONSERV. CONTRAT.",
    "CONTRATOS":                    "MANUT/CONSERV. CONTRAT.",
    "MANUTENÇÃO MENSAL":            "MANUT/CONSERV. CONTRAT.",
    "MANUTENÇÕES PREVENTIVAS":      "MANUT/CONSERV. CONTRAT.",
    # Manutenção esporádica
    "EVENTUAIS - EXTRAS":           "MANUT/CONSERV. ESPORÁD.",
    "MANUT/CONSERV. ESPORÁD.":      "MANUT/CONSERV. ESPORÁD.",
    "MANUT. EVENTUAIS":             "MANUT/CONSERV. ESPORÁD.",
    "MANUTENÇÃO EVENTUAL":          "MANUT/CONSERV. ESPORÁD.",
    "CONSERV./MANUT. AVULSA":       "MANUT/CONSERV. ESPORÁD.",
    "SERV. TÉCNICOS/REPAROS":       "MANUT/CONSERV. ESPORÁD.",
    "SERVIÇOS EVENTUAIS/REPAROS":   "MANUT/CONSERV. ESPORÁD.",
    "MANUTENÇÃO E CONSERVAÇÃO":     "MANUT/CONSERV. ESPORÁD.",
    # Administrativo
    "ADMINISTRATIVO":               "ADMINISTRATIVO",
    "GESTÃO ADMINISTRATIVA":        "ADMINISTRATIVO",
    "DESPESAS ADMINISTRATIVAS":     "ADMINISTRATIVO",
    "HONORÁRIOS/ADM":               "ADMINISTRATIVO",
    "HONORÁRIOS/ADMIN.":            "ADMINISTRATIVO",
    "TAXA ADMINISTRATIVA":          "ADMINISTRATIVO",
    "TAXA ADM.":                    "ADMINISTRATIVO",
    # Encargos sociais
    "ENCARGOS SOCIAIS":             "ENCARGOS SOCIAIS",
    "ENCARGOS SOCIAIS/TRABALHISTAS":"ENCARGOS SOCIAIS",
    "OBRIG./TAXAS":                 "ENCARGOS SOCIAIS",
    "OBRIG./DECL./TAXAS":           "ENCARGOS SOCIAIS",
    "OBRIGAÇÕES LEGAIS":            "ENCARGOS SOCIAIS",
    "IMPOSTOS E TAXAS":             "ENCARGOS SOCIAIS",
    "IMPOSTOS/TAXAS":               "ENCARGOS SOCIAIS",
    "TARIFAS E IMPOSTOS":           "ENCARGOS SOCIAIS",
    "ENCARGOS/TAXAS/OUTROS":        "ENCARGOS SOCIAIS",
    # Despesas diversas
    "DESP. DIVERSAS":                    "DESP. DIVERSAS",
    "DESPESAS DIVERSAS":                 "DESP. DIVERSAS",
    "DESP. GERAIS":                      "DESP. DIVERSAS",
    "DESPESAS GERAIS":                   "DESP. DIVERSAS",
    "OUTROS":                            "DESP. DIVERSAS",
    "OUTRAS DESPESAS":                   "DESP. DIVERSAS",
    "DIVERSOS":                          "DESP. DIVERSAS",
    "SALÃO DE FESTAS/CHURRASQUEIRA":     "DESP. DIVERSAS",
    "SALÃO DE FESTAS":                   "DESP. DIVERSAS",
    "SALAO DE FESTAS":                   "DESP. DIVERSAS",
    "DESPESAS REEMBOLSÁVEIS":            "DESP. DIVERSAS",
    "DESPESAS REEMBOLSAVEIS":            "DESP. DIVERSAS",
    # Consumos individuais → consolidado
    "CONSUMO DE ÁGUA":                   "CONSUMOS",
    "CONSUMO DE ENERGIA":                "CONSUMOS",
    "CONSUMO DE GÁS":                    "CONSUMOS",
    "CONSUMO GAS":                       "CONSUMOS",
    # Melhorias/obras → manutenção esporádica
    "MELHORIAS/BENFEITORIAS":            "MANUT/CONSERV. ESPORÁD.",
    "OBRAS/MELHORIAS":                   "MANUT/CONSERV. ESPORÁD.",
    "CONSERVAÇÃO/OBRAS":                 "MANUT/CONSERV. ESPORÁD.",
}

def _norm_cat(cat: str) -> str:
    up = cat.strip().upper()
    return _CAT_NORM.get(up, up)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _f(v) -> float:
    """Converte valor BR ou numérico para float (sempre positivo)."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        import math
        return abs(float(v)) if not (math.isnan(float(v)) or math.isinf(float(v))) else 0.0
    s = str(v).strip().replace("\xa0", "").replace(" ", "")
    # Remove percentual: "54.274,08( 49,45%)" → "54.274,08"
    s = re.sub(r"\(.*?\)", "", s).strip()
    if not s or s in ("-", ""):
        return 0.0
    # Formato BR: "1.234,56" → 1234.56  |  "- 7.506,96" → 7506.96
    s_clean = re.sub(r"[^\d,.\-]", "", s)
    if "," in s_clean:
        s_clean = s_clean.replace(".", "").replace(",", ".")
    s_clean = re.sub(r"[^\d.\-]", "", s_clean)
    if not s_clean or s_clean in ("-",):
        return 0.0
    try:
        return abs(float(s_clean))
    except ValueError:
        return 0.0


def _texto(celula) -> str:
    """Retorna texto limpo de uma célula BeautifulSoup td/th."""
    return celula.get_text(separator=" ", strip=True)


def _linhas(tabela) -> list[list[str]]:
    """Retorna lista de linhas como listas de strings de uma tabela BeautifulSoup."""
    resultado = []
    for tr in tabela.find_all("tr"):
        cells = [_texto(td) for td in tr.find_all(["td", "th"])]
        resultado.append(cells)
    return resultado


# ─── adapter ─────────────────────────────────────────────────────────────────

class AdapterLelloMHTML(AdapterBase):
    """
    Lê arquivos .xls da Lello que são na verdade MHTML/HTML.
    Usa BeautifulSoup para parsear as tabelas HTML embarcadas.
    """

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ImportError("Instale beautifulsoup4: pip install beautifulsoup4 lxml")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        # ── Leitura do arquivo ──
        conteudo = self._ler_conteudo(caminho)

        soup = BeautifulSoup(conteudo, "html.parser")
        tabelas = soup.find_all("table")

        if not tabelas:
            raise ValueError(f"Nenhuma tabela HTML encontrada em {caminho}")

        # ── Tabela 0: Resumo Financeiro Contábil ──
        self._processar_resumo(tabelas[0], dados)

        # ── Tabela 1: Posição Devedores (inadimplência) ──
        if len(tabelas) > 1:
            self._processar_devedores(tabelas[1], dados)

        # ── Tabela 2: ORDINARIA — receita prevista ──
        if len(tabelas) > 2:
            self._processar_ordinaria_previsto(tabelas[2], dados)

        # ── Localizar e processar DEMONSTRATIVO DE DESPESAS ──
        tab_desp = self._encontrar_tabela(tabelas, "DEMONSTRATIVO DE DESPESAS")
        if tab_desp is not None:
            self._processar_despesas(tab_desp, dados)

        # Fallback categorias
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        # Cálculo de inadimplência percentual
        dados.total_unidades = self.config.get("unidades", 0)
        if dados.receita_realizada > 0 and dados.inadimplencia_valor > 0:
            dados.inadimplencia_percentual = round(
                dados.inadimplencia_valor / dados.receita_realizada * 100, 2
            )

        return dados

    # ─── helpers internos ────────────────────────────────────────────────────

    @staticmethod
    def _ler_conteudo(caminho: Path) -> str:
        """Tenta UTF-8 primeiro, depois latin-1 / cp1252."""
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                with open(str(caminho), "r", encoding=enc, errors="strict") as fh:
                    return fh.read()
            except (UnicodeDecodeError, LookupError):
                continue
        # Último recurso: ignora erros
        with open(str(caminho), "r", encoding="latin-1", errors="replace") as fh:
            return fh.read()

    @staticmethod
    def _encontrar_tabela(tabelas, heading: str):
        """Retorna a primeira tabela cujo primeiro texto contém o heading."""
        heading_upper = heading.upper()
        for t in tabelas:
            texto_t = t.get_text(" ", strip=True).upper()
            if heading_upper in texto_t:
                # Confirma que a primeira linha (ou primeiras células) tem o heading
                primeiras_linhas = _linhas(t)[:3]
                for linha in primeiras_linhas:
                    for cel in linha:
                        if heading_upper in cel.upper():
                            return t
        return None

    def _processar_resumo(self, tabela, dados: DadosFinanceiros) -> None:
        """
        Tabela 0: Resumo Financeiro Contábil
        Colunas: Conta | Saldo Anterior | Crédito | Débito | Saldo Atual
        """
        linhas = _linhas(tabela)
        contas = []

        for linha in linhas:
            if len(linha) < 5:
                continue
            nome = linha[0].strip().lower()
            if not nome or nome in ("conta",):
                continue
            # Linha de Total (totais globais)
            if nome == "total":
                try:
                    dados.saldo_anterior    = _f(linha[1])
                    dados.receita_realizada = _f(linha[2])
                    dados.despesa_total     = _f(linha[3])
                    dados.saldo_atual       = _f(linha[4])
                    dados.receita_prevista  = dados.receita_realizada
                except (IndexError, ValueError):
                    pass
                continue
            # Linhas de contas individuais
            try:
                saldo_ant = _f(linha[1])
                creditos  = _f(linha[2])
                debitos   = _f(linha[3])
                saldo_at  = _f(linha[4])
            except (IndexError, ValueError):
                continue

            contas.append({
                "nome":       linha[0].strip().title(),
                "saldo_ant":  saldo_ant,
                "creditos":   creditos,
                "debitos":    debitos,
                "saldo_atual": saldo_at,
            })

            # Classificação banco_cc / banco_cdb / banco_priv
            if any(k in nome for k in _NOMES_CC):
                dados.banco_cc = saldo_at
            elif any(k in nome for k in _NOMES_CDB):
                dados.banco_cdb = saldo_at
            else:
                dados.banco_priv += saldo_at

        dados.contas_detalhe = contas

    def _processar_devedores(self, tabela, dados: DadosFinanceiros) -> None:
        """
        Tabela 1: Posição Devedores
        Colunas: Conta | Anterior (-) | Mês(-) | Recebido(+) | Total Atrasados
        Última linha = Total → col[4] = inadimplencia_valor
        """
        linhas = _linhas(tabela)
        for linha in reversed(linhas):
            if not linha:
                continue
            nome = linha[0].strip().lower()
            if nome == "total" and len(linha) >= 5:
                dados.inadimplencia_valor = _f(linha[4])
                return
        # Fallback: última linha não vazia
        for linha in reversed(linhas):
            if len(linha) >= 5 and any(c for c in linha):
                dados.inadimplencia_valor = _f(linha[4])
                return

    def _processar_ordinaria_previsto(self, tabela, dados: DadosFinanceiros) -> None:
        """
        Tabela 2 (ORDINARIA): extrai receita_prevista da linha 'Total Devedores' (col Previsto).
        Col índices (após header 'Descricao | Previsto | Realizado'):
            linha[''] | descricao | previsto | realizado
        """
        linhas = _linhas(tabela)
        for linha in linhas:
            texto = " ".join(linha).lower()
            if "total devedores" in texto:
                # Localiza o valor previsto: normalmente 3ª e 4ª células não-vazias
                vals = [c for c in linha if c.strip()]
                if len(vals) >= 2:
                    # O último par não-vazio são Previsto e Realizado
                    dados.receita_prevista = _f(vals[-2])
                return

    def _processar_despesas(self, tabela, dados: DadosFinanceiros) -> None:
        """
        Tabela DEMONSTRATIVO DE DESPESAS.

        Hierarquia de linhas no arquivo Lello MHTML:

          1. Subcategoria (sub-item):
               col[0]='' | col[1]="Total SUBCAT" | col[2]="valor(%)"  (3 cols)
               → subtotal de sub-categoria dentro de um grupo operacional

          2. Grupo Total (agrupamento de despesas):
               col[0]="GRUPO Total:" | col[1]="valor(%)"              (2 cols)
               → soma de sub-categorias

          3. Conta top-level (total de toda uma conta):
               col[0]="Total CONTA" | col[1]="valor(%)"               (2 cols)
               → total geral de uma conta (ORDINARIA, SALÃO, MELHORIAS, ÁGUA etc.)

          4. Grand total:
               col[0]="Total DESPESAS" | …

        De-duplicação por fronteira ORDINARIA:
          Grupos ("NOME Total:", 2 cols) antes de "Total ORDINARIA" → categorias
          de despesa operacional da ORDINARIA.
          Grupos após "Total ORDINARIA" → sub-grupos de contas separadas, ignorados
          (a conta entra pelo seu total próprio).
          Contas top-level ("Total CONTA", 2 cols) não-excluídas → uma categoria por conta.
          ORDINARIA, DESPESAS e assemelhados são sempre excluídos.
        """
        linhas = _linhas(tabela)

        # ── Estratégia de extração em dois passes ──
        #
        # O arquivo Lello tem seções de contas aninhadas. A conta ORDINARIA tem
        # grupos operacionais (Despesas com Pessoal, Serviços Terceirizados…) que
        # devem virar categorias individuais. As demais contas (Salão, Melhorias,
        # Tarifas Concessionárias…) têm seus próprios grupos internos, mas queremos
        # incluí-las como UMA categoria só pelo total da conta.
        #
        # Regra:
        #   1. Grupos ("NOME Total:", 2 colunas) que aparecem ANTES de "Total ORDINARIA"
        #      → são grupos ORDINARIA → incluir como categoria individual.
        #   2. Grupos que aparecem APÓS "Total ORDINARIA" → são sub-grupos de contas
        #      não-ORDINARIA → ignorar (a conta já entra pelo passo 3).
        #   3. Contas top-level ("Total CONTA", 2 colunas) não-excluídas → incluir
        #      pelo nome da conta (Salão, Melhorias, etc.).
        #   4. "Total DESPESAS" → atualiza despesa_total.

        # Determinar posição de "Total ORDINARIA" (linha-fronteira)
        idx_total_ordinaria = len(linhas)  # default: sem fronteira
        for idx_l, linha in enumerate(linhas):
            if len(linha) == 2:
                c0_l = linha[0].strip()
                if re.match(r"^Total\s+ORDINARI[AÁ]\s*$", c0_l, re.IGNORECASE):
                    idx_total_ordinaria = idx_l
                    break

        contas_inseridas: set[str] = set()

        for idx_l, linha in enumerate(linhas):
            if not linha:
                continue

            c0 = linha[0].strip() if len(linha) > 0 else ""
            c1 = linha[1].strip() if len(linha) > 1 else ""
            c2 = linha[2].strip() if len(linha) > 2 else ""
            c3 = linha[3].strip() if len(linha) > 3 else ""
            n_cols = len(linha)

            # ─ Grand total: "Total DESPESAS" ─
            if re.match(r"^Total\s+DESPESAS\s*$", c0, re.IGNORECASE):
                val = _f(c3) or _f(c2) or _f(c1)
                if val > 0:
                    dados.despesa_total = val
                continue

            # ─ Grupo Total: "NOME Total:" em col[0] ─
            # Incluir SOMENTE grupos antes da fronteira ORDINARIA (grupos da ORDINARIA)
            if re.search(r"\bTotal:\s*$", c0, re.IGNORECASE):
                if idx_l > idx_total_ordinaria:
                    continue  # grupo de conta não-ORDINARIA, ignorar
                cat = re.sub(r"\s*Total:\s*$", "", c0, flags=re.IGNORECASE).strip()
                cat_upper = cat.upper()
                if cat_upper in _EXCLUIR_CATEGORIAS:
                    continue
                val = _f(c3) or _f(c2) or _f(c1)
                if val <= 0:
                    continue
                chave = _norm_cat(cat)
                dados.categorias_despesa[chave] = (
                    dados.categorias_despesa.get(chave, 0.0) + val
                )
                continue

            # ─ Conta top-level: "Total CONTA" em col[0], 2 colunas ─
            if n_cols == 2 and re.match(r"^Total\s+\S", c0, re.IGNORECASE):
                cat = re.sub(r"^Total\s+", "", c0, flags=re.IGNORECASE).strip()
                cat_upper = cat.upper()
                if cat_upper in _EXCLUIR_CATEGORIAS:
                    continue
                if cat_upper in contas_inseridas:
                    continue
                val = _f(c1)
                if val > 0:
                    chave = _norm_cat(cat)
                    dados.categorias_despesa[chave] = (
                        dados.categorias_despesa.get(chave, 0.0) + val
                    )
                    contas_inseridas.add(cat_upper)
                continue

            # Subcategorias (3+ cols, c0 vazio, c1="Total NOME") são intencionalmente
            # ignoradas — já estão somadas nos Grupos acima.
