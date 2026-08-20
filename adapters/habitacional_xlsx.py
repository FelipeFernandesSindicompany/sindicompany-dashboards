"""
Adapter Habitacional XLSX — arquivo prestacao_contas_N_YYYY.xlsx

Estrutura confirmada (uma única aba):
  Resumo (linhas 5-11):
    col E (idx 4) = Saldo Anterior
    col G (idx 6) = Créditos (receita)
    col I (idx 8) = Débitos (despesa)
    col K (idx 10) = Saldo Atual
    Linha com "TOTAL" nas primeiras 20 = totais consolidados

  Despesas categorizadas (~linhas 88-161):
    Linhas cujo col A começa com "TOTAL" têm o valor do subtotal em col H (idx 7)
    Ex: "TOTAL PESSOAL" | ... | 38619.46 | ...

  Inadimplência (~linhas 292+):
    Seção "Resumo de Recebimentos" — col F (idx 5) com valor em linhas sem data/recibo
"""
from pathlib import Path
import re
import openpyxl
from adapters.base import AdapterBase, DadosFinanceiros


# Mapa de normalização: variantes → nome canônico (UPPERCASE)
_CAT_NORM = {
    # Receita / créditos (excluir das despesas)
    "CONSUMO":                  "CONSUMOS",
    "CONSUMOS":                 "CONSUMOS",
    # Contratos e manutenção
    "CONTRATOS/MANUTENCAO":          "CONTRATOS/MANUT.",
    "CONTRATOS/MANUTENÇAO":          "CONTRATOS/MANUT.",
    "CONTRATOS/MANUT":               "CONTRATOS/MANUT.",
    "CONTRATOS/MANUT.":              "CONTRATOS/MANUT.",
    "MANUTENCAO":                    "CONTRATOS/MANUT.",
    "MANUT/CONSERV. CONTRAT.":       "CONTRATOS/MANUT.",
    "MANUT/CONSERV.":                "CONTRATOS/MANUT.",
    "MANUT. CONTRAT.":               "CONTRATOS/MANUT.",
    # Manutenção contratada / esporádica (Cinque Terre e similares)
    "MANUT/CONSERVAÇÃO-CONTRATADAS": "MANUT/CONSERV. CONTRAT.",
    "MANUT/CONSERVACAO-CONTRATADAS": "MANUT/CONSERV. CONTRAT.",
    "MANUT/CONSERV.-CONTRATADAS":    "MANUT/CONSERV. CONTRAT.",
    "MANUT/CONSERV. CONTRAT.":       "MANUT/CONSERV. CONTRAT.",
    "MANUT/CONSERVAÇÃO-ESPORADICAS": "MANUT/CONSERV. ESPORÁD.",
    "MANUT/CONSERVACAO-ESPORADICAS": "MANUT/CONSERV. ESPORÁD.",
    "MANUT/CONSERV.-ESPORADICAS":    "MANUT/CONSERV. ESPORÁD.",
    "MANUT/CONSERV. ESPORÁD.":       "MANUT/CONSERV. ESPORÁD.",
    # Materiais
    "MATERIAIS/SUPRIMENTOS":    "MATERIAIS",
    "MATERIAIS":                "MATERIAIS",
    # Serviços
    "SERVICOS PRESTADOS":       "SERV. PRESTADOS",
    "SERVIÇOS PRESTADOS":       "SERV. PRESTADOS",
    "SERV. PRESTADOS":          "SERV. PRESTADOS",
    "SERVICOS":                 "SERV. PRESTADOS",
    # Serviços terceirizados (Cinque Terre e similares)
    "SERV.TERCEIRIZADOS":       "SERV. TERCEIRIZADOS",
    "SERV. TERCEIRIZADOS":      "SERV. TERCEIRIZADOS",
    "TERCEIRIZADOS":            "SERV. TERCEIRIZADOS",
    # Despesas operacionais / administrativo
    "DESPESAS OPERACIONAIS":    "DESP. OPERACIONAIS",
    "DESP. OPERACIONAIS":       "DESP. OPERACIONAIS",
    "ADMINISTRATIVO":           "ADMINISTRATIVO",
    # Pessoal e encargos
    "PESSOAL":                  "PESSOAL",
    # Seguros
    "SEGUROS":                  "SEGUROS",
    # Melhorias / obras
    "MELHORIAS":                "MELHORIAS/OBRAS",
    "OBRAS":                    "MELHORIAS/OBRAS",
    "MELHORIAS/OBRAS":          "MELHORIAS/OBRAS",
    # Reparações
    "REPARACAO DA FACHADA":     "REPARAÇÃO FACHADA",
    "REPARAÇÃO DA FACHADA":     "REPARAÇÃO FACHADA",
    "REPARAÇÃO FACHADA":        "REPARAÇÃO FACHADA",
}

def _normalizar_categoria(cat: str) -> str:
    """Normaliza nome de categoria para o formato canônico do dashboard."""
    cat_up = cat.strip().upper()
    return _CAT_NORM.get(cat_up, cat_up)


def _f(v) -> float:
    """Converte valor de célula Excel para float, seja float ou string BR."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\xa0", "")
    # Formato BR: "1.234,56"
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    # Remove tudo que não seja dígito, ponto ou sinal
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except:
        return 0.0


class AdapterHabitacionalXLSX(AdapterBase):

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        wb = openpyxl.load_workbook(str(caminho), data_only=True, read_only=True)
        ws = wb.active

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        linhas = list(ws.iter_rows(values_only=True))

        def col(row, idx):
            return row[idx] if len(row) > idx else None

        # ── Resumo por conta ──────────────────────────────────────────────────────
        # Suporte a dois formatos do software Habitacional:
        #
        # Formato A (padrão): "Resumo" nas primeiras ~20 linhas
        #   col E=saldo_ant  col G=creditos  col I=debitos  col K=saldo_atual
        #   Linha "TOTAL" consolida todas as contas.
        #
        # Formato B ("Demonstrações Por Conta"): resumo na seção específica
        #   As primeiras seções têm detalhes por conta (colunas I/K apenas).
        #   O "Resumo Financeiro Contábil" (mais abaixo) tem cols E/G/I/K.
        #   Linha "TOTAL" nessa seção consolida tudo.
        #
        CONTAS_CDB  = {"FUNDO DE RESERVA", "FUNDO RESERVA", "RESERVA", "CDB", "POUPANÇA", "POUPANCA"}
        CONTAS_EXCL = {"TOTAL", "CONTA"}

        def _processa_resumo(rows):
            """
            Lê linhas de resumo no formato E/G/I/K.
            Retorna True se encontrou o TOTAL consolidado.
            """
            for row in rows:
                desc = str(col(row, 0) or "").strip()
                desc_up = desc.upper()
                v_ant  = _f(col(row, 4))
                v_cred = _f(col(row, 6))
                v_deb  = _f(col(row, 8))
                v_sal  = _f(col(row, 10))

                # TOTAL consolidado: tem "TOTAL" no nome e pelo menos saldo_ant ou cred
                if "TOTAL" in desc_up and (v_ant != 0 or v_cred != 0):
                    dados.saldo_anterior    = v_ant
                    dados.receita_realizada = v_cred
                    dados.despesa_total     = v_deb
                    dados.saldo_atual       = v_sal
                    dados.receita_prevista  = v_cred
                    return True

                # Conta individual: tem nome, tem pelo menos um valor, e tem E ou G preenchido
                # CONTAS_EXCL usa match exato para não excluir contas como "CONTA EVENTOS"
                if not desc or desc_up in CONTAS_EXCL:
                    continue
                if not any([v_ant, v_cred, v_deb, v_sal]):
                    continue
                if v_ant == 0 and v_cred == 0:
                    continue  # Formato B: linhas com só I/K são detalhes, não contas

                conta = {
                    "nome": desc.upper(),
                    "saldo_ant": v_ant,
                    "creditos":  v_cred,
                    "debitos":   v_deb,
                    "saldo_atual": v_sal,
                }
                dados.contas_detalhe.append(conta)
                nome_up = desc.upper()
                if "ORDINARI" in nome_up:
                    dados.banco_cc  += v_sal
                elif any(kw in nome_up for kw in CONTAS_CDB):
                    dados.banco_cdb += v_sal
                else:
                    dados.banco_priv += v_sal
            return False

        # Tenta Formato A: primeiras 25 linhas
        found = _processa_resumo(linhas[:25])

        # Formato B: procura seção "Resumo Financeiro Contábil" no resto do arquivo
        if not found or dados.saldo_atual == 0:
            dados.contas_detalhe.clear()
            dados.banco_cc = dados.banco_cdb = dados.banco_priv = 0.0
            resumo_start = None
            for i, row in enumerate(linhas):
                desc = str(col(row, 0) or col(row, 1) or "").strip()
                if "RESUMO FINANCEIRO CONT" in desc.upper():
                    resumo_start = i
                    break
            if resumo_start is not None:
                _processa_resumo(linhas[resumo_start:resumo_start + 30])

        # Fallback: se ainda não extraiu, usa totais como ORDINÁRIA
        if not dados.contas_detalhe and dados.saldo_atual:
            dados.contas_detalhe = [{
                "nome": "ORDINÁRIA",
                "saldo_ant":  dados.saldo_anterior,
                "creditos":   dados.receita_realizada,
                "debitos":    dados.despesa_total,
                "saldo_atual": dados.saldo_atual,
            }]
            dados.banco_cc = dados.saldo_atual

        # ── Composição de Saldo Bancário — lê valores reais do extrato ──────────────
        # Seção "COMPOSIÇÃO DE SALDO" tem linhas com descrição do banco e valor em col K
        # Ex: "BCO.ITAÚ - C/CORRENTE ..." → cc | "APLIC.CDB-DI" → cdb | "ITAUVEST" → priv
        for i, row in enumerate(linhas):
            desc_h = str(col(row, 0) or "").upper()
            if "COMPOSI" in desc_h and "SALDO" in desc_h:
                _cc = _cdb = _priv = 0.0
                for row2 in linhas[i + 1: i + 20]:
                    d2 = str(col(row2, 0) or "").upper()
                    if "SALDO FINAL" in d2:
                        break
                    raw = str(col(row2, 10) or "").strip().replace(".", "").replace(",", ".")
                    try:
                        v2 = float(raw)
                    except ValueError:
                        continue
                    if v2 <= 0:
                        continue
                    if "C/CORRENTE" in d2 or ("CORRENTE" in d2 and "CDB" not in d2):
                        _cc += v2
                    elif "CDB" in d2 or "POUPAN" in d2:
                        _cdb += v2
                    else:
                        _priv += v2
                if _cc + _cdb + _priv > 0:
                    dados.banco_cc  = _cc
                    dados.banco_cdb = _cdb
                    dados.banco_priv = _priv
                break

        # ── Receita Prevista / Realizada — Resumo de Emissão (ORDINÁRIA) ───────────
        # Após o header "Resumo de Emissão" (col A), a primeira linha com col A
        # vazia e col I + col K numéricos positivos é o total do período:
        #   col I (idx 8) = Previsto (orçamento aprovado em assembleia)
        #   col K (idx 10) = Realizado (créditos recebidos no período)
        # Sobrescreve o fallback prev=tCred que _processa_resumo() define.
        _in_emissao = False
        _emissao_linhas = 0
        for _row in linhas:
            _a = str(col(_row, 0) or "").strip()
            if "RESUMO DE EMISS" in _a.upper():
                _in_emissao = True
                _emissao_linhas = 0
                continue
            if not _in_emissao:
                continue
            _emissao_linhas += 1
            _v_prev = _f(col(_row, 8))
            _v_real = _f(col(_row, 10))
            if not _a and _v_prev > 0 and _v_real > 0:
                dados.receita_prevista = _v_prev
                dados.receita_cotas    = _v_real
                break
            if _emissao_linhas > 20:
                _in_emissao = False

        # ── Despesas por categoria ──
        # col E (idx 4) = "TOTAL DA CONTA PESSOAL", col H (idx 7) = valor
        # Nomes de contas/fundos que NÃO são categorias operacionais de despesa
        EXCLUIR_DESP = {
            "ORDINARIA", "ORDINÁRIA", "ORDINARIO",       # conta ordinária (qualquer grafia)
            "CAIXA ORDINARIO", "CAIXA ORDINÁRIA",        # conta principal de caixa
            "MELHORAMENTOS", "FUNDO DE RESERVA",
            "REPARACAO DA FACHADA", "PROVISAO", "CLT",
            "SEGURO PROTECAO",                            # conta de seguro opcional
        }
        # Marcador: ao encontrar "TOTAL DA CONTA CAIXA ORDINARIO", a seção CAIXA encerrou.
        # Linhas seguintes pertencem a outras contas (CONSUMOS, etc.) e NÃO devem
        # ser somadas — causaria dupla contagem dos débitos da conta CONSUMOS.
        caixa_section_done = False
        for row in linhas[70:]:
            desc_e = str(col(row, 4) or "").strip().upper()
            val_h  = _f(col(row, 7))
            if not desc_e.startswith("TOTAL DA CONTA"):
                continue
            if val_h <= 0:
                continue
            # Verifica se chegamos ao total da conta principal (encerra seção CAIXA)
            # Aceita tanto "CAIXA ORDINÁRIO" (formato antigo) quanto "ORDINÁRIA"
            # diretamente (ex: "TOTAL DA CONTA ORDINÁRIA" sem prefixo CAIXA).
            is_main_account = (
                "CAIXA ORDINARIO" in desc_e or "CAIXA ORDINÁRIA" in desc_e
                or desc_e in ("TOTAL DA CONTA ORDINARIA", "TOTAL DA CONTA ORDINÁRIA")
            )
            if is_main_account:
                caixa_section_done = True
                continue  # exclui o total da conta, mas marca fim da seção
            # Após o TOTAL DA CONTA CAIXA ORDINARIO, ignora tudo
            # (pertencem a outras contas: CONSUMOS, SEGURO, etc.)
            if caixa_section_done:
                continue
            # Mantém UPPERCASE para consistência com os demais meses
            cat = re.sub(r"^TOTAL DA CONTA\s*", "", desc_e).strip()
            cat = _normalizar_categoria(cat)
            if cat and not any(ex in cat for ex in EXCLUIR_DESP):
                dados.categorias_despesa[cat] = (
                    dados.categorias_despesa.get(cat, 0) + val_h
                )

        # Fallback
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["DESPESAS GERAIS"] = dados.despesa_total

        # ── Inadimplência ──
        # Formato A: "COTAS EM ATRASO" na faixa 250+ com valor na col F (idx 5)
        # Formato B: linhas "CONDOMINOS EM ATRASO EM 30/MM" e "COTAS EM ABERTO EM 30/MM"
        #            com valor na col K (idx 10) — somadas por conta
        inad = 0.0
        in_inad = False
        for row in linhas[250:]:
            desc = str(col(row, 0) or "").upper().strip()
            if "COTAS EM ATRASO" in desc or ("TOTAL" in desc and "INADIMPL" in desc):
                v = _f(col(row, 5))  # col F
                if v > 0:
                    inad += v
                    in_inad = True
            elif in_inad and desc == "TOTAL":
                v = _f(col(row, 5))
                if v > 0:
                    inad = v
                    break

        # Formato B: linhas "... EM DD/MM/YYYY" do fim do período atual.
        # Usa "/MM/AAAA" como padrão para evitar ambiguidade entre meses (ex: /4/ vs /14/).
        if inad == 0:
            if "-" in mes_referencia:
                ano_ref, mes_ref = mes_referencia.split("-")[:2]
                fim_mes_patterns = [f"/{mes_ref}/{ano_ref}"]
            else:
                fim_mes_patterns = []
            for row in linhas:
                desc = str(col(row, 0) or "").upper().strip()
                is_overdue = "ATRASO" in desc or "ABERTO" in desc or "COBRAN" in desc
                has_fim_mes = any(p in desc for p in fim_mes_patterns)
                if is_overdue and has_fim_mes:
                    v = _f(col(row, 10))
                    if v > 0:
                        inad += v

        # Fallback padrão
        if inad == 0:
            for row in linhas[10:30]:
                desc = str(col(row, 0) or "").upper()
                if "COTA" in desc and "ATRASO" in desc:
                    v = _f(col(row, 10))
                    if v > 0:
                        inad += v

        dados.inadimplencia_valor = inad
        dados.total_unidades = self.config.get("unidades", 0)
        if dados.receita_realizada > 0 and inad > 0:
            dados.inadimplencia_percentual = round(inad / dados.receita_realizada * 100, 2)

        # ── Recebidos em Atraso (inadProc) ──
        # Formato 1: "Total Recebido (Com Baixa de Recibo)" — coluna I (idx 8) ou vizinhas
        for row in linhas:
            for j, cell in enumerate(row):
                if cell and "Com Baixa" in str(cell):
                    for k in range(j + 1, min(len(row), j + 5)):
                        v = _f(row[k])
                        if v > 0:
                            dados.inadimplencia_recebida = v
                            break
                    break

        # Formato 2 (Elo/Habitacional): "CONDOMINOS EM ATRASO RECEBIDOS" col K — soma por conta
        if dados.inadimplencia_recebida == 0:
            _inadp = 0.0
            for row in linhas:
                desc = str(col(row, 0) or "").upper().strip()
                if "ATRASO RECEBIDO" in desc:
                    v = _f(col(row, 10))
                    if v > 0:
                        _inadp += v
            if _inadp > 0:
                dados.inadimplencia_recebida = _inadp

        wb.close()
        return dados
