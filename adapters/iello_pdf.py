"""
Adapter Iello PDF — Iello Condomínios (Balancete Mensal)

Estrutura confirmada (Giardino D'Itália, Vita Parque):
  Pág 1: COMPOSIÇÃO DESPESAS ORDINÁRIA
    DESPESAS COM PESSOAL -44.961,17
    ENCARGOS SOCIAIS -14.623,17
    ...
    TOTAL -137.981,25

  Pág 2-3: RESUMO FINANCEIRO
    DESCRIÇÃO | SALDO ANT. | CREDITOS | DÉBITOS | SALDO FINAL
    CONTA CONDOMINIO 46.109,32 139.841,36 -137.981,25 47.969,43
    ...
    SALDO FINAL 159.676,75 158.703,32 -153.331,25 165.048,82

  Inadimplência:
    TOTAL GERAL DE DEVEDORES 550.123,31
"""
from pathlib import Path
import re
from adapters.base import AdapterBase, DadosFinanceiros


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except:
        return 0.0


class AdapterIelloPDF(AdapterBase):

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        with pdfplumber.open(str(caminho)) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)

        linhas = texto.split("\n")

        # ── Resumo Financeiro: "SALDO FINAL" = totais gerais; "CONTA CONDOMINIO" = ordinária ──
        conta_condominio_c = None
        for linha in linhas:
            l = linha.strip()
            if re.match(r"CONTA CONDOMINIO\b", l, re.IGNORECASE):
                nums = re.findall(r"-?[\d.,]+", re.sub(r"CONTA CONDOMINIO", "", l, flags=re.IGNORECASE))
                nums_f = [_num(n) for n in nums if re.search(r"\d", n)]
                if len(nums_f) >= 4:
                    conta_condominio_c = nums_f[1]
            if l.upper().startswith("SALDO FINAL"):
                nums = re.findall(r"-?[\d.,]+", l.replace("SALDO FINAL", ""))
                nums_f = [_num(n) for n in nums if re.search(r"\d", n)]
                if len(nums_f) >= 4:
                    dados.saldo_anterior    = nums_f[0]
                    dados.receita_realizada = conta_condominio_c if conta_condominio_c else nums_f[1]
                    dados.despesa_total     = nums_f[2]
                    dados.saldo_atual       = nums_f[3]
                    # receita_prevista is set externally via CONFIG.orcamento; leave as 0
                    dados.receita_prevista  = 0.0
                    break

        # ── Despesas por categoria ──
        # Seção "COMPOSIÇÃO DESPESAS ORDINÁRIA" — termina em "TOTAL"
        in_desp = False
        for linha in linhas:
            l = linha.strip()
            if re.search(r"COMPOSI[ÇC][ÃA]O DESPESAS ORDIN", l, re.IGNORECASE):
                in_desp = True
                continue
            if not in_desp:
                continue
            # Termina a seção quando encontra "TOTAL" sozinho (subtotal da seção)
            if re.match(r"^TOTAL\b", l, re.IGNORECASE):
                in_desp = False
                continue
            # Ignora cabeçalhos de página e linhas em branco
            if not l or re.match(r"^(Per[ií]odo|P[aá]g\.|Balancete)", l, re.IGNORECASE):
                continue
            # Linha de categoria: "TEXTO -valor" ou "TEXTO  valor"
            m = re.match(r"^(.+?)\s+-?([\d.,]{4,})\s*$", l)
            if m:
                cat = m.group(1).strip()
                val = _num(m.group(2))
                # Filtra linhas de cabeçalho e totalizadores
                if val > 0 and len(cat) > 3 and not re.match(
                    r"^(TOTAL|RECEBIMENTO|RESUMO|SALDO|ACORDOS|CANCELAMENTO|"
                    r"ANTECIPA|COTAS|CONDÔMINO|ARRECADA|MULTAS|CONSUMO|FUNDO|SALÃO)",
                    cat, re.IGNORECASE
                ):
                    dados.categorias_despesa[cat] = (
                        dados.categorias_despesa.get(cat, 0) + val
                    )

        # ── Acordos recebidos (faturas em atraso cobradas no período) ──
        m_acordos = re.search(r"ACORDOS RECEBIDOS\s+([\d.,]+)", texto, re.IGNORECASE)
        if m_acordos:
            dados.inadimplencia_recebida = _num(m_acordos.group(1))

        # ── Inadimplência ──
        m_inad = re.search(
            r"TOTAL GERAL DE DEVEDORES\s+([\d.,]+)", texto, re.IGNORECASE
        )
        if m_inad:
            dados.inadimplencia_valor = _num(m_inad.group(1))
        else:
            # Fallback: soma todos os "TOTAL DEVEDORES"
            total_inad = 0.0
            for m in re.finditer(r"TOTAL DEVEDORES[^\n]+?([\d.,]+)", texto, re.IGNORECASE):
                total_inad += _num(m.group(1))
            if total_inad > 0:
                dados.inadimplencia_valor = total_inad

        # Fallback despesas
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        dados.total_unidades = self.config.get("unidades", 0)
        if dados.receita_realizada > 0 and dados.inadimplencia_valor > 0:
            dados.inadimplencia_percentual = round(
                dados.inadimplencia_valor / dados.receita_realizada * 100, 2
            )
        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        for ext in [".pdf", ".PDF"]:
            p = caminho.with_suffix(ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        pdfs = list(caminho.parent.glob("*.pdf")) + list(caminho.parent.glob("*.PDF"))
        if pdfs:
            return self.ler_pdf(pdfs[0], mes_referencia)
        raise FileNotFoundError(f"Nenhum PDF encontrado em {caminho.parent}")
