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
    "CONTRATOS/MANUTENCAO":     "CONTRATOS/MANUT.",
    "CONTRATOS/MANUTENÇAO":     "CONTRATOS/MANUT.",
    "CONTRATOS/MANUT":          "CONTRATOS/MANUT.",
    "CONTRATOS/MANUT.":         "CONTRATOS/MANUT.",
    "MANUTENCAO":               "CONTRATOS/MANUT.",
    "MANUT/CONSERV. CONTRAT.":  "CONTRATOS/MANUT.",
    "MANUT/CONSERV.":           "CONTRATOS/MANUT.",
    "MANUT. CONTRAT.":          "CONTRATOS/MANUT.",
    # Materiais
    "MATERIAIS/SUPRIMENTOS":    "MATERIAIS",
    "MATERIAIS":                "MATERIAIS",
    # Serviços
    "SERVICOS PRESTADOS":       "SERV. PRESTADOS",
    "SERVIÇOS PRESTADOS":       "SERV. PRESTADOS",
    "SERV. PRESTADOS":          "SERV. PRESTADOS",
    "SERVICOS":                 "SERV. PRESTADOS",
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

        # ── Resumo por conta (linhas ~1-20, antes do TOTAL) ──
        # Cada linha representa uma conta; linha com "TOTAL" é o consolidado
        CONTAS_CDB  = {"FUNDO DE RESERVA", "FUNDO RESERVA", "RESERVA", "CDB", "POUPANÇA", "POUPANCA"}
        CONTAS_EXCL = {"TOTAL", "CONTA"}  # linhas de cabeçalho/rodapé a ignorar

        for row in linhas[:25]:
            desc = str(col(row, 0) or "").strip()
            desc_up = desc.upper()
            v_ant  = _f(col(row, 4))
            v_cred = _f(col(row, 6))
            v_deb  = _f(col(row, 8))
            v_sal  = _f(col(row, 10))

            # Linha de totais consolidados — encerra leitura de contas aqui
            if "TOTAL" in desc_up and (v_ant > 0 or v_cred > 0):
                dados.saldo_anterior    = v_ant
                dados.receita_realizada = v_cred
                dados.despesa_total     = v_deb
                dados.saldo_atual       = v_sal
                dados.receita_prevista  = v_cred
                break  # Para antes da seção "Demonstrações Por Conta" que não tem contas bancárias

            # Linha de conta individual (tem nome + pelo menos um valor)
            if not desc or any(ex in desc_up for ex in CONTAS_EXCL):
                continue
            if not any([v_ant, v_cred, v_deb, v_sal]):
                continue

            conta = {
                "nome":       desc.upper(),
                "saldo_ant":  v_ant,
                "creditos":   v_cred,
                "debitos":    v_deb,
                "saldo_atual": v_sal,
            }
            dados.contas_detalhe.append(conta)

            # Classifica para o objeto banco
            nome_up = desc.upper()
            if "ORDINARI" in nome_up:
                dados.banco_cc  += v_sal
            elif any(kw in nome_up for kw in CONTAS_CDB):
                dados.banco_cdb += v_sal
            else:
                dados.banco_priv += v_sal

        # Fallback: se não extraiu contas individuais, usa totais como ORDINÁRIA
        if not dados.contas_detalhe and dados.saldo_atual:
            dados.contas_detalhe = [{
                "nome": "ORDINÁRIA",
                "saldo_ant":  dados.saldo_anterior,
                "creditos":   dados.receita_realizada,
                "debitos":    dados.despesa_total,
                "saldo_atual": dados.saldo_atual,
            }]
            dados.banco_cc = dados.saldo_atual

        # ── Despesas por categoria ──
        # col E (idx 4) = "TOTAL DA CONTA PESSOAL", col H (idx 7) = valor
        EXCLUIR_DESP = {"ORDINARIA", "ORDINÁRIA", "MELHORAMENTOS", "FUNDO DE RESERVA",
                        "REPARACAO DA FACHADA", "PROVISAO", "CLT", "GERAL"}
        for row in linhas[70:]:
            desc_e = str(col(row, 4) or "").strip().upper()
            val_h  = _f(col(row, 7))
            if desc_e.startswith("TOTAL DA CONTA") and val_h > 0:
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
        # Linha "TOTAL" da seção Resumo de Recebimentos / cotas em atraso
        # Tipicamente na faixa 290-334
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

        # Fallback: procura em col K as inadimplências por conta
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

        wb.close()
        return dados
