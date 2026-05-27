"""
Adapter DataDigitus PDF — Software DataDigitus

Estrutura confirmada (Cap D'Antibes, 6 páginas):
  Pág 1: "Resumo Financeiro Contábil"
    Tabela: CONTA | Saldo Anterior | Créditos | Débitos | Saldo Atual
    "TOTAL GERAL" na última linha
    Exemplo: TOTAL GERAL 419.667,93 80.249,99 -74.530,40 425.387,52
    (Débitos podem vir negativos no texto)

  Pág 1-3: "Demonstrativo de Despesas"
    Categorias em MAIÚSCULAS seguidas de lançamentos
    Subtotal de cada categoria: linha com só o valor após os lançamentos
    Ex: "SALARIOS E ORDENADOS\n  07/04 ...\n  22.322,00"
    "TOTAL DA CONTA ORDINÁRIA..." valor total

  Pág 3+: "Demonstrativo Financeiro por Conta"
    "Condôminos em atraso   36.547,61" por conta

Condomínios: Cap D'Antibes
"""
from pathlib import Path
import re
from adapters.base import AdapterBase, DadosFinanceiros


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.]", "", s.strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except:
        return 0.0


class AdapterDatadigitusPDF(AdapterBase):

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
            texto_total = "\n".join(p.extract_text() or "" for p in pdf.pages)

        # ── Resumo Financeiro Contábil ──
        m = re.search(
            r"TOTAL\s+GERAL\s+([\d.,]+)\s+([\d.,]+)\s+[-]?([\d.,]+)\s+([\d.,]+)",
            texto_total, re.IGNORECASE
        )
        if m:
            dados.saldo_anterior    = _num(m.group(1))
            dados.receita_realizada = _num(m.group(2))
            dados.despesa_total     = _num(m.group(3))
            dados.saldo_atual       = _num(m.group(4))
            dados.receita_prevista  = dados.receita_realizada

        # ── Contas individuais (extraídas do resumo) ──
        contas_match = re.findall(
            r"^(CONTA [^\n]+?)\s+([\d.,]+)\s+([\d.,]+)\s+[-]?([\d.,]+)\s+([\d.,]+)",
            texto_total, re.MULTILINE
        )
        for cm in contas_match:
            pass  # disponível para expansão futura

        # ── Despesas por categoria ──
        # Categorias em MAIÚSCULAS seguidas de seus lançamentos e subtotal
        categorias_raw = re.findall(
            r"^([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ /]+)\n(?:.*?\n)*?([\d.,]+)\n",
            texto_total, re.MULTILINE
        )
        # Abordagem mais robusta: acha as linhas de subtotal de categoria
        # Padrão: linha com apenas um número após bloco de texto em maiúsculas
        linhas = texto_total.split("\n")
        CATEGORIAS_CONHECIDAS = [
            "SALARIOS E ORDENADOS", "ENCARGOS TRABALHISTAS", "ENCARGOS SOCIAIS",
            "MANUT/CONSERV/REPOSIÇÃO", "MANUTENÇÃO", "TARIFAS PÚBLICAS",
            "SEGUROS CONTRATADOS", "MATERIAIS DE CONSUMO", "SERVIÇOS PRESTADOS",
            "IMPOSTOS E TAXAS", "COMPRAS E AQUISIÇÕES", "HONORARIOS E EXPEDIENTE",
            "TERCEIRIZAÇÃO", "SERVIÇOS TERCEIRIZADOS",
        ]
        cat_atual = None
        for linha in linhas:
            l = linha.strip()
            if not l:
                continue
            # Detecta cabeçalho de categoria
            for cat in CATEGORIAS_CONHECIDAS:
                if l.upper().startswith(cat):
                    cat_atual = cat.title()
                    break
            # Linha com apenas número = subtotal da categoria
            if cat_atual and re.match(r"^[\d.,]+$", l):
                val = _num(l)
                if 0 < val < (dados.despesa_total or 99999999) * 0.9:
                    dados.categorias_despesa[cat_atual] = (
                        dados.categorias_despesa.get(cat_atual, 0) + val
                    )
                    cat_atual = None

        # ── Inadimplência ──
        total_inad = 0.0
        for m_inad in re.finditer(
            r"Cond[ôo]menos em atraso\s+([\d.,]+)", texto_total, re.IGNORECASE
        ):
            total_inad += _num(m_inad.group(1))
        dados.inadimplencia_valor = total_inad

        # Fallback
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        dados.total_unidades = self.config.get("unidades", 0)
        if dados.receita_realizada > 0 and total_inad > 0:
            dados.inadimplencia_percentual = round(
                total_inad / dados.receita_realizada * 100, 2
            )
        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        pdf_path = caminho.with_suffix(".pdf")
        if not pdf_path.exists():
            pdf_path = caminho.with_suffix(".PDF")
        return self.ler_pdf(pdf_path, mes_referencia)
