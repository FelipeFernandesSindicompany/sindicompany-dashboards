"""
Adapter Auxiliadora Predial XLS — arquivo Prestacao_de_Contas MM.AAAA.xls
(arquivo binário OLE2 / Excel 97-2003, lido com xlrd)

Estrutura confirmada (Condomínio Patrícia, jun/2026):
  6 abas:
  [0] 'Demonst de Contas'           — movimentos por conta (ORDINARIA, FUNDOS, SALÃO)
  [1] 'Resumo de Emissões'          — emissões: previsto vs realizado por conta
  [2] 'Resumo Financeiro Contabil'  — saldo ant | créditos | débitos | saldo atual
  [3] 'Demonstrativo de Despesas'   — despesas extras (ex: DESP. REFORMA ELEVADORES)
  [4] 'Demonstrativo de Receitas'   — detalhe de cada recibo emitido
  [5] 'Demonst. Financeira'         — saldo bancário final

Extração:
  Aba 2 → saldo_anterior, receita_realizada, despesa_total, saldo_atual, contas_detalhe
           banco (cc = ORDINARIA, cdb = fundos, priv = outros)
  Aba 1 → receita_prevista (ORDINARIA > REC CONDOMINIO > Previsto)
           inadimplencia_valor (ORDINARIA > REC COTAS EM ATRASO > Previsto)
  Aba 0 → categorias_despesa (débitos de ORDINARIA excluindo saldos/totais)
  Aba 5 → banco_total verificação (saldo bancário real)
"""
from __future__ import annotations

import re
from pathlib import Path

from adapters.base import AdapterBase, DadosFinanceiros

# Linhas a ignorar na extração de categorias de despesa (Aba 0, seção ORDINARIA)
_SKIP_PREFIXOS = {
    "POSIÇÃO FINANCEIRA", "POSICAO FINANCEIRA",
    "TOTAIS", "TOTAL",
    "SALDO ATUAL", "SALDO ANTERIOR", "SALDO",
}

# Linhas de crédito (receitas) dentro da seção ORDINARIA — não são despesas
_SKIP_CREDITO_PREFIXOS = {
    "REC CONDOMINIO", "COTAS ANTECIPADAS", "MULTAS", "CORREIO",
    "ALUGUEIS", "DIVERSOS", "DE COTAS",
}

# Contas ORDINÁRIA (conta corrente principal)
_NOMES_CC = {"ordinaria", "ordinária"}

# Contas de reserva / fundo
_NOMES_CDB = {
    "fundo de obras", "fundo obras", "fundo de reserva", "fundo reserva",
    "cdb", "poupança", "poupanca", "aplicação", "aplicacao", "investimento",
}


def _f(val) -> float:
    """Converte célula xlrd para float (positivo)."""
    import math
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        try:
            f = float(val)
            return abs(f) if not (math.isnan(f) or math.isinf(f)) else 0.0
        except (TypeError, ValueError):
            return 0.0
    s = str(val).strip().replace(".", "").replace(",", ".").replace(" ", "")
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return abs(float(s)) if s and s != "-" else 0.0
    except ValueError:
        return 0.0


def _txt(val) -> str:
    return str(val).strip() if val not in (None, "") else ""


def _skip_cat(nome: str) -> bool:
    upper = nome.upper().strip()
    for pref in _SKIP_PREFIXOS:
        if upper.startswith(pref):
            return True
    return False


class AdapterAuxiliadoraXLS(AdapterBase):
    """
    Lê arquivos .xls da Auxiliadora Predial (binário OLE2).
    Requer: pip install xlrd
    """

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import xlrd
        except ImportError:
            raise ImportError("Instale xlrd: pip install xlrd")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        wb = xlrd.open_workbook(str(caminho))

        # ── Mapeia abas por nome (case-insensitive) ──────────────────────────
        abas = {wb.sheet_by_index(i).name.lower().strip(): wb.sheet_by_index(i)
                for i in range(wb.nsheets)}

        sh_resumo   = self._encontrar_aba(abas, ["resumo financeiro contabil",
                                                   "resumo financeiro contábil"])
        sh_emissoes = self._encontrar_aba(abas, ["resumo de emissões", "resumo de emissoes",
                                                   "resumo emissões", "resumo emissoes"])
        sh_contas   = self._encontrar_aba(abas, ["demonst de contas", "demonstrativo de contas"])
        sh_banco    = self._encontrar_aba(abas, ["demonst. financeira", "demonstrativo financeiro",
                                                   "demonst financeira"])

        # ── Aba 2: Resumo Financeiro Contábil ────────────────────────────────
        if sh_resumo:
            self._processar_resumo(sh_resumo, dados)

        # ── Aba 1: Resumo de Emissões → previsto + inadimplência ─────────────
        if sh_emissoes:
            self._processar_emissoes(sh_emissoes, dados)

        # ── Aba 0: Demonst de Contas → categorias de despesa ─────────────────
        if sh_contas:
            self._processar_categorias(sh_contas, dados)

        # ── Aba 5: Demonst. Financeira → banco ───────────────────────────────
        if sh_banco:
            self._processar_banco(sh_banco, dados)

        # ── Fallback categorias ───────────────────────────────────────────────
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        # ── Resíduo: garante que soma das categorias = ORDINÁRIA.d ────────────
        # Itens contabilizados na Aba 2 mas não detalhados na Aba 0 são
        # absorvidos pela maior categoria para manter o total consistente.
        if dados.categorias_despesa and dados.contas_detalhe:
            ordinaria_d = next(
                (c["debitos"] for c in dados.contas_detalhe
                 if "ordinari" in c["nome"].lower()),
                0.0,
            )
            if ordinaria_d > 0:
                residuo = round(ordinaria_d - sum(dados.categorias_despesa.values()), 2)
                if abs(residuo) > 0.01:
                    maior = max(dados.categorias_despesa, key=dados.categorias_despesa.get)
                    dados.categorias_despesa[maior] = round(
                        dados.categorias_despesa[maior] + residuo, 2
                    )

        # ── Inadimplência percentual ──────────────────────────────────────────
        if dados.receita_realizada > 0 and dados.inadimplencia_valor > 0:
            dados.inadimplencia_percentual = round(
                dados.inadimplencia_valor / dados.receita_realizada * 100, 2
            )

        return dados

    # ─── helpers internos ────────────────────────────────────────────────────

    @staticmethod
    def _encontrar_aba(abas: dict, candidatos: list):
        for nome in candidatos:
            if nome in abas:
                return abas[nome]
        return None

    @staticmethod
    def _linhas(sh) -> list[list]:
        return [[sh.cell(r, c).value for c in range(sh.ncols)] for r in range(sh.nrows)]

    def _processar_resumo(self, sh, dados: DadosFinanceiros) -> None:
        """
        Aba 'Resumo Financeiro Contabil':
        Linha 0: título; Linha 1: cabeçalho; Linhas 2+: contas; última = Total.
        Colunas: Conta Contabil | Saldo Anterior | Créditos | Débitos | Saldo Atual
        """
        linhas = self._linhas(sh)
        contas = []

        for linha in linhas:
            if len(linha) < 5:
                continue
            nome = _txt(linha[0])
            if not nome or nome.lower() in ("conta contabil", "conta contábil",
                                            "resumo financeiro contabil",
                                            "resumo financeiro contábil"):
                continue

            creditos  = _f(linha[2])
            debitos   = _f(linha[3])

            # Saldo anterior e atual podem ser negativos (conta devedora) — preservar sinal
            try:
                saldo_ant = float(str(linha[1]).replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                saldo_ant = 0.0
            try:
                saldo_at_raw = float(str(linha[4]).replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                saldo_at_raw = 0.0
            saldo_at = saldo_at_raw

            if nome.lower() == "total":
                dados.saldo_anterior    = saldo_ant
                dados.receita_realizada = creditos
                dados.despesa_total     = debitos
                dados.saldo_atual       = abs(saldo_at_raw) if saldo_at_raw < 0 else saldo_at_raw
                # Mantém o saldo real (pode ser negativo para ORDINARIA)
                dados.saldo_atual = round(saldo_at_raw, 2)
                continue

            contas.append({
                "nome":       nome,
                "saldo_ant":  round(saldo_ant, 2),
                "creditos":   round(creditos, 2),
                "debitos":    round(debitos, 2),
                "saldo_atual": round(saldo_at_raw, 2),
            })

            # Banco: ORDINARIA → cc; fundos → cdb; resto → priv
            nome_lower = nome.lower()
            if any(k in nome_lower for k in _NOMES_CC):
                dados.banco_cc = round(saldo_at_raw, 2)
            elif any(k in nome_lower for k in _NOMES_CDB):
                dados.banco_cdb += _f(saldo_at_raw)
            else:
                dados.banco_priv += _f(saldo_at_raw)

        dados.contas_detalhe = contas

    def _processar_emissoes(self, sh, dados: DadosFinanceiros) -> None:
        """
        Aba 'Resumo de Emissões':
        - receita_prevista  = linha 'TOTAL DE EMISSÔES' → col Previsto
        - receita_cotas     = linha 'TOTAL DE EMISSÔES' → col Realizado  (→ campo 'real' no BAL)
        - inadimplencia_valor = 'REC COTAS EM ATRASO' dentro da seção ORDINARIA → col Previsto
        """
        linhas = self._linhas(sh)

        em_ordinaria = False
        for linha in linhas:
            nome = _txt(linha[0]).upper() if linha else ""

            # Linha de total geral — fonte autoritativa para prev e real
            if "TOTAL DE EMISS" in nome and len(linha) >= 3:
                dados.receita_prevista = round(_f(linha[1]), 2)
                dados.receita_cotas    = round(_f(linha[2]), 2)
                continue

            # Detecta início da seção ORDINARIA
            if re.match(r"^ORDINARI[AÁ]$", nome):
                em_ordinaria = True
                continue

            # Fim da seção ORDINARIA
            if em_ordinaria and nome and not re.match(r"^(CONTA|REC|ALUGUEI|COTAS|CORREIO)", nome):
                if re.match(r"^(FUNDO|SALÃO|SALAO|TOTAL)", nome):
                    em_ordinaria = False

            if not em_ordinaria:
                continue

            if len(linha) < 2:
                continue
            previsto = _f(linha[1])

            # Inadimplência: REC COTAS EM ATRASO dentro de ORDINARIA — previsto = em aberto
            if "REC COTAS EM ATRASO" in nome and previsto > 0 and dados.inadimplencia_valor == 0:
                dados.inadimplencia_valor = round(previsto, 2)

        # Fallback: usa receita_realizada se total não encontrado
        if dados.receita_prevista == 0 and dados.receita_realizada > 0:
            dados.receita_prevista = dados.receita_realizada

    def _processar_categorias(self, sh, dados: DadosFinanceiros) -> None:
        """
        Aba 'Demonst de Contas':
        Localiza seção ORDINARIA e coleta os débitos que são despesas reais.
        Exclui linhas de saldo, totais e rendimentos inter-fundos.
        """
        linhas = self._linhas(sh)
        em_ordinaria = False
        header_visto = False

        for linha in linhas:
            if len(linha) < 3:
                continue
            nome   = _txt(linha[0]).upper().strip()
            debito = _f(linha[1])

            # Cabeçalho da seção ORDINARIA (linha com o nome + totais)
            if re.match(r"^ORDINARI[AÁ]$", nome):
                em_ordinaria = True
                header_visto = False
                continue

            # Fim da seção: próxima conta de nível alto (linha em branco seguida de nova conta)
            if em_ordinaria and nome and re.match(r"^(FUNDO|SALÃO|SALAO)\b", nome):
                em_ordinaria = False

            if not em_ordinaria:
                continue

            # Ignora a linha de cabeçalho das colunas
            if "POSIÇÃO FINANCEIRA" in nome or "POSICAO FINANCEIRA" in nome:
                header_visto = True
                continue

            if not header_visto:
                continue

            # Ignora linhas de saldo, totais e itens de crédito
            if not nome or _skip_cat(nome):
                continue

            # Inclui apenas itens com débito > 0 (despesas reais)
            if debito > 0:
                dados.categorias_despesa[nome.title()] = (
                    dados.categorias_despesa.get(nome.title(), 0.0) + round(debito, 2)
                )

    def _processar_banco(self, sh, dados: DadosFinanceiros) -> None:
        """
        Aba 'Demonst. Financeira':
        Usada apenas quando nenhum dado bancário foi extraído da Aba 2.
        Evita sobrescrever os saldos contábeis por conta (que podem ser negativos para ORDINARIA).
        """
        # Já temos dados bancários das contas individuais (Aba 2) — não sobrescrever
        if dados.banco_cc != 0 or dados.banco_cdb != 0 or dados.banco_priv != 0:
            return

        linhas = self._linhas(sh)
        for linha in linhas:
            if len(linha) < 2:
                continue
            desc  = _txt(linha[0]).upper()
            valor = _f(linha[1])

            if not desc or valor == 0:
                continue

            # Conta corrente
            if any(k in desc for k in ("C/C", "C/ C", "CONTA CORRENTE", "CORRENTE")):
                if "TOTAL" not in desc and "APLICAÇÃO" not in desc and "SALDO APLIC" not in desc:
                    dados.banco_cc = round(valor, 2)

            # Aplicações / CDB / Poupança
            elif any(k in desc for k in ("APLICAÇÃO", "APLICACAO", "CDB", "POUPANÇA",
                                          "POUPANCA", "INVEST", "VEST")):
                dados.banco_cdb += round(valor, 2)

            # Saldo total — preenche banco_cc se nada extraído
            elif ("SALDO TOTAL" in desc or "TOTAL" in desc) and dados.banco_cc == 0:
                dados.banco_cc = round(valor, 2)
