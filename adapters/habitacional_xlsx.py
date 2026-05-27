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

        # ── Resumo: encontra linha TOTAL nas primeiras 20 ──
        for row in linhas[:20]:
            desc = str(col(row, 0) or "").upper().strip()
            if "TOTAL" in desc:
                v_ant = _f(col(row, 4))   # col E
                v_cred = _f(col(row, 6))  # col G
                v_deb  = _f(col(row, 8))  # col I
                v_sal  = _f(col(row, 10)) # col K
                if v_ant > 0 or v_cred > 0:
                    dados.saldo_anterior    = v_ant
                    dados.receita_realizada = v_cred
                    dados.despesa_total     = v_deb
                    dados.saldo_atual       = v_sal
                    dados.receita_prevista  = v_cred
                    break

        # ── Despesas por categoria ──
        # Padrão confirmado: col E (idx 4) = "TOTAL DA CONTA PESSOAL", col H (idx 7) = valor
        EXCLUIR = {"ORDINARIA", "ORDINÁRIA", "MELHORAMENTOS", "FUNDO DE RESERVA",
                   "REPARACAO DA FACHADA", "PROVISAO", "CLT", "GERAL"}
        for row in linhas[70:]:
            desc_e = str(col(row, 4) or "").strip().upper()
            val_h  = _f(col(row, 7))
            if desc_e.startswith("TOTAL DA CONTA") and val_h > 0:
                # Remove "TOTAL DA CONTA " do início
                cat = re.sub(r"^TOTAL DA CONTA\s*", "", desc_e).strip().title()
                if cat and not any(ex in cat.upper() for ex in EXCLUIR):
                    dados.categorias_despesa[cat] = (
                        dados.categorias_despesa.get(cat, 0) + val_h
                    )

        # Fallback
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

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
