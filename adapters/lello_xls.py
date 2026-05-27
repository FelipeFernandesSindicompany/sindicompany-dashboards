"""
Adapter Lello XLS — arquivo prestacaocontas_XXXX_YYYY_MM.xls

Estrutura confirmada (Barra Viva I · Alegria):
  22 tabelas HTML dentro do .xls

  Tabela 0 (Resumo Financeiro Contábil): 10 linhas x 5 colunas
    Linha 0 = cabeçalho (Conta | Saldo Anterior | Crédito | Débito | Saldo Atual)
    Linhas 1-8 = contas individuais
    Linha 9 = Total (valores como Python float: 290832.14, não BR)
    OBS: valores negativos podem estar em string BR "- 7.506,96"

  Tabela 1 (Posição Devedores): col 4 (Total Atrasados), linha -1 = Total
    Valor = Python float (e.g. 37682.49)

  Tabela 17 (DEMONSTRATIVO DE DESPESAS): 125 linhas x 6 colunas
    Grupos de despesa: col 0 = "GRUPO Total:" → col 3 = "54.274,08( 49,45%)"
    Contas top-level: col 0 = "Total CONTA" → col 2 = "11.000,00( 100,00%)"
    Grand total: col 0 = "Total DESPESAS" → col 3 = float
    Grupos úteis: SERVIÇOS TERCEIRIZADOS, TARIFAS CONCESSIONÁRIAS,
                  MANUTENÇÃO - CONTRATOS, EVENTUAIS - EXTRAS,
                  ADMINISTRATIVO, DESPESAS DIVERSAS, DESPESAS COM PESSOAL
    Contas úteis: FUNDO DE RESERVA (além de ORDINARIA que já tem os grupos)

Condomínios: Barra Viva I, Hub Home Club Tatuapé, Splendor Square, Villa Park Osasco
"""
from pathlib import Path
import re
from adapters.base import AdapterBase, DadosFinanceiros

_EXCLUIR_GRUPOS = {
    "ORDINARIA", "DESPESAS",
    "DESPESA - FUNDO DE RESERVA",   # duplica a conta FUNDO DE RESERVA
    "RECUPERAÇÃO FACHADA",
}
_EXCLUIR_CONTAS = {"ORDINARIA", "DESPESAS"}


def _num(v) -> float:
    """Converte valor de célula pandas (numpy float, Python float, ou string BR) para float."""
    import math
    if v is None:
        return 0.0
    # numpy.float64 e Python float: tenta float() diretamente
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return 0.0
        return abs(f)
    except (TypeError, ValueError):
        pass
    # String em formato BR: "- 7.506,96" → 7506.96
    s = re.sub(r"[^\d,.\-]", "", str(v).strip())
    if not s or s in ("-",):
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


def _num_br(s) -> float:
    """Extrai número de string BR com percentual, ex: '54.274,08( 49,45%)'."""
    if not s or str(s).strip() in ("nan", ""):
        return 0.0
    m = re.search(r"([\d]{1,3}(?:\.[\d]{3})*,\d{2})", str(s))
    if m:
        return float(m.group(1).replace(".", "").replace(",", "."))
    # Fallback: tenta número simples
    return _num(s)


class AdapterLelloXLS(AdapterBase):

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("Instale pandas: pip install pandas lxml")

        from io import StringIO
        # Tenta UTF-8 primeiro (maioria dos arquivos Lello); fallback para latin-1
        for _enc in ("utf-8", "latin-1"):
            try:
                with open(str(caminho), "r", encoding=_enc, errors="strict") as _f:
                    _conteudo = _f.read()
                break
            except UnicodeDecodeError:
                continue
        else:
            with open(str(caminho), "r", encoding="latin-1", errors="replace") as _f:
                _conteudo = _f.read()
        tabelas = pd.read_html(StringIO(_conteudo), thousands=".", decimal=",")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        # ── Tabela 0: Resumo Financeiro ──
        if tabelas:
            df = tabelas[0]
            ultima = df.iloc[-1]
            try:
                dados.saldo_anterior    = _num(ultima.iloc[1])
                dados.receita_realizada = _num(ultima.iloc[2])
                dados.despesa_total     = _num(ultima.iloc[3])
                dados.saldo_atual       = _num(ultima.iloc[4])
                dados.receita_prevista  = dados.receita_realizada
            except Exception:
                pass

        # ── Tabela 1: Inadimplência (Posição Devedores) ──
        if len(tabelas) > 1:
            df_inad = tabelas[1]
            try:
                ultima_inad = df_inad.iloc[-1]
                dados.inadimplencia_valor = _num(ultima_inad.iloc[-1])
            except Exception:
                pass

        # ── Tabela de Despesas: "DEMONSTRATIVO DE DESPESAS" ──
        tab_desp = None
        for df in tabelas:
            if "DEMONSTRATIVO DE DESPESAS" in str(df.columns).upper():
                tab_desp = df
                break

        if tab_desp is not None:
            for _, row in tab_desp.iterrows():
                c0 = str(row.iloc[0] if len(row) > 0 else "").strip()
                c2 = str(row.iloc[2] if len(row) > 2 else "")
                c3 = str(row.iloc[3] if len(row) > 3 else "")

                # Grupo de despesas: "NOME Total:"
                if re.search(r"\bTotal:\s*$", c0, re.IGNORECASE):
                    cat = re.sub(r"\s*Total:\s*$", "", c0, flags=re.IGNORECASE).strip()
                    cat_upper = cat.upper()
                    if cat_upper in _EXCLUIR_GRUPOS:
                        continue
                    val = _num_br(c3) or _num_br(c2)
                    if val > 0:
                        dados.categorias_despesa[cat.title()] = (
                            dados.categorias_despesa.get(cat.title(), 0) + val
                        )

                # Conta top-level: "Total CONTA"
                elif re.match(r"^Total\s+\S", c0, re.IGNORECASE):
                    conta = re.sub(r"^Total\s+", "", c0, flags=re.IGNORECASE).strip()
                    conta_upper = conta.upper()
                    if conta_upper in _EXCLUIR_CONTAS:
                        continue
                    val = _num_br(c2) or _num_br(c3)
                    if val > 0:
                        dados.categorias_despesa[conta.title()] = (
                            dados.categorias_despesa.get(conta.title(), 0) + val
                        )

        # Fallback
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        dados.total_unidades = self.config.get("unidades", 0)
        if dados.receita_realizada > 0 and dados.inadimplencia_valor > 0:
            dados.inadimplencia_percentual = round(
                dados.inadimplencia_valor / dados.receita_realizada * 100, 2
            )

        return dados
