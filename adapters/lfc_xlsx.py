"""
Adapter LFC XLSX — formato Guaratambé/LFC.

Estrutura (diferente do Habitacional padrão):
  Resumo Financeiro Contábil (linhas 1-15):
    col E (idx 4) = Saldo Anterior, G (idx 6) = Créditos,
    col I (idx 8) = Débitos, K (idx 10) = Saldo Atual
    Linha TOTAL consolida todas as contas.

  Resumo de Emissão:
    Linha em branco (sem col A) após "Receitas Previstas e Realizadas":
      col I = Previsto TOTAL (Cotas em Atraso + Emissão do Período + ANTECIPAÇÕES)
      col K = Realizado total

  Inad (inadimplencia_valor):
    Soma de "Cotas em Atraso em {último dia do mês}" col K (idx 10) em TODAS as seções.
  inadProc (inadimplencia_recebida):
    "Total Recebido (Com Baixa de Recibo)" do Acompanhamento de Processos → col 9.

  Posição Financeira (ORDINÁRIA):
    Categorias de despesa simples (sem prefixo "TOTAL DA CONTA"):
      col A = nome, col I (idx 8) = débito
"""
from pathlib import Path
import re
import openpyxl
from adapters.base import AdapterBase, DadosFinanceiros


def _f(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\xa0", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return 0.0


class AdapterLFCXLSX(AdapterBase):

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        wb = openpyxl.load_workbook(str(caminho), data_only=True, read_only=True)
        ws = wb.active

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        linhas = list(ws.iter_rows(values_only=True))
        cat_map = self.parser_config.get("cat_map", {})

        def col(row, idx):
            return row[idx] if len(row) > idx else None

        CONTAS_CDB = {"FUNDO DE RESERVA", "FUNDO RESERVA", "CDB", "POUPANÇA", "POUPANCA", "RESERVA"}

        # ── Resumo Financeiro Contábil (primeiras ~15 linhas) ──────────────────
        for row in linhas[:25]:
            desc = str(col(row, 0) or "").strip()
            desc_up = desc.upper()
            v_ant  = _f(col(row, 4))
            v_cred = _f(col(row, 6))
            v_deb  = _f(col(row, 8))
            v_sal  = _f(col(row, 10))

            if "TOTAL" in desc_up and (v_ant != 0 or v_cred != 0):
                dados.saldo_anterior    = v_ant
                dados.receita_realizada = v_cred
                dados.despesa_total     = v_deb
                dados.saldo_atual       = v_sal
                break

            if not desc or desc_up in ("CONTA", ""):
                continue
            if not any([v_ant, v_cred, v_deb, v_sal]):
                continue
            if v_ant == 0 and v_cred == 0:
                continue

            dados.contas_detalhe.append({
                "nome": desc.upper(),
                "saldo_ant": v_ant, "creditos": v_cred,
                "debitos": v_deb, "saldo_atual": v_sal,
            })
            nome_up = desc.upper()
            nome_up_norm = (nome_up.replace("Á", "A").replace("Ã", "A")
                            .replace("Ó", "O").replace("Â", "A"))
            if nome_up_norm.startswith("ORDINA") and "RATEIO" not in nome_up:
                dados.banco_cc = v_sal
            elif any(kw in nome_up for kw in CONTAS_CDB):
                dados.banco_cdb = v_sal
            else:
                dados.banco_priv += v_sal

        if not dados.contas_detalhe and dados.saldo_atual:
            dados.contas_detalhe = [{
                "nome": "ORDINÁRIA",
                "saldo_ant": dados.saldo_anterior, "creditos": dados.receita_realizada,
                "debitos": dados.despesa_total, "saldo_atual": dados.saldo_atual,
            }]
            dados.banco_cc = dados.saldo_atual

        # ── Prev / real: seção "Resumo de Emissão" ──────────────────────────────
        # prev  = linha "Emissão do Período" col I (apenas o que foi emitido no mês)
        # real  = linha em branco (total) col K (realizado total do período)
        in_resumo = False
        found_hdr = False
        for row in linhas:
            desc = str(col(row, 0) or "").strip()
            desc_up = desc.upper()

            if "RESUMO DE EMISS" in desc_up:
                in_resumo = True
                continue
            if not in_resumo:
                continue
            if "RECEITAS PREVISTAS" in desc_up:
                found_hdr = True
                continue
            if found_hdr:
                # Linha em branco = total → col I = previsto total, col K = realizado total
                # (inclui Cotas em Atraso + Emissão do Período + ANTECIPAÇÕES)
                if not desc and (_f(col(row, 8)) > 0 or _f(col(row, 10)) > 0):
                    dados.receita_prevista = _f(col(row, 8))
                    dados.receita_cotas = _f(col(row, 10))
                    break
                # Próxima seção → para
                if desc and any(k in desc_up for k in ["DEVEDOR", "POSIÇÃO", "POSICAO", "FUNDO"]):
                    break

        if dados.receita_prevista == 0:
            dados.receita_prevista = dados.receita_realizada

        # ── Inad: soma de "Cotas em Atraso em {último dia do mês atual}" col K ──
        # col K (idx 10) = saldo devedor no fechamento do período
        # Soma TODAS as seções (ORDINÁRIA, FUNDO DE RESERVA, OBRAS, etc.)
        fim_mes_patterns: list[str] = []
        if "-" in mes_referencia:
            ano_ref = int(mes_referencia.split("-")[0])
            mes_ref = int(mes_referencia.split("-")[1])
            fim_mes_patterns = [f"/{mes_ref:02d}/{ano_ref}"]

        inad = 0.0
        for row in linhas:
            desc = str(col(row, 0) or "").upper().strip()
            is_overdue = "COTAS EM ATRASO" in desc
            has_fim_mes = any(p in desc for p in fim_mes_patterns) if fim_mes_patterns else False
            if is_overdue and (has_fim_mes or not fim_mes_patterns):
                v = _f(col(row, 10))  # col K = fechamento do mês
                if v > 0:
                    inad += v          # acumula todas as seções
        dados.inadimplencia_valor = inad

        # ── inadProc: "Total Recebido (Com Baixa de Recibo)" do Acompanhamento ──
        inadProc = 0.0
        for row in linhas:
            d5 = str(col(row, 5) or "").upper()
            if "TOTAL RECEBIDO" in d5 and "COM BAIXA" in d5:
                v = _f(col(row, 9))
                if v > 0:
                    inadProc = v
                    break
        dados.inadimplencia_recebida = inadProc

        # ── Categorias de despesa: seção Posição Financeira ────────────────────
        SKIP_DESCS = {
            "SALDO ANTERIOR CREDOR", "SALDO ANTERIOR DEVEDOR",
            "EMISSÃO DO PERÍODO", "EMISSAO DO PERIODO",
            "RENDIMENTOS DE APLICAÇÃO", "RENDIMENTOS DE APLICACAO",
            "COTAS RECEBIDAS EM ATRASO", "ANTECIPAÇÕES", "ANTECIPACOES",
            "ATUALIZAÇÃO MONETÁRIA", "ATUALIZACAO MONETARIA",
            "JUROS", "MULTAS REC. COBRANÇA EM ATRASO",
        }
        STOP_DESCS = {"TOTAIS", "TOTAL", "SALDO ATUAL CREDOR", "SALDO ATUAL DEVEDOR"}

        in_posicao = False
        past_saldo_ant = False

        for row in linhas:
            desc = str(col(row, 0) or "").strip()
            desc_up = desc.upper()

            if "POSIÇÃO FINANCEIRA" in desc_up or "POSICAO FINANCEIRA" in desc_up:
                in_posicao = True
                past_saldo_ant = False
                continue
            if not in_posicao:
                continue
            if "SALDO ANTERIOR" in desc_up:
                past_saldo_ant = True
                continue
            if not past_saldo_ant:
                continue
            if desc_up in STOP_DESCS:
                break
            if not desc or desc_up in SKIP_DESCS:
                continue
            # Próxima conta → para
            if col(row, 8) is None and col(row, 10) is None:
                if any(k in desc_up for k in ["FUNDO", "OBRAS", "RATEIO", "RESERVA"]):
                    break

            v = _f(col(row, 8))
            if v > 0:
                cat = cat_map.get(desc_up, cat_map.get(desc, desc))
                dados.categorias_despesa[cat] = dados.categorias_despesa.get(cat, 0) + v

        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["DESPESAS GERAIS"] = dados.despesa_total

        dados.total_unidades = self.config.get("unidades", 0)
        if dados.receita_realizada > 0 and inad > 0:
            dados.inadimplencia_percentual = round(inad / dados.receita_realizada * 100, 2)

        wb.close()
        return dados
