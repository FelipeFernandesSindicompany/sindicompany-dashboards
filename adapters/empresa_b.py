"""
Adapter Empresa B — planilha unificada (uma única aba):
  - col A = Tipo  ("R" = receita, "D" = despesa)
  - col B = Categoria
  - col C = Descrição
  - col D = Valor
  - col E = Mês (ex: "2026-05")

Também suporta PDF de resumo via pdfplumber (opcional).
"""
from pathlib import Path
import openpyxl
from adapters.base import AdapterBase, DadosFinanceiros


class AdapterEmpresaB(AdapterBase):

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        wb = openpyxl.load_workbook(caminho, data_only=True)
        ws = wb.active  # usa primeira aba

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        receita = 0.0
        despesa = 0.0

        for row in ws.iter_rows(min_row=2, values_only=True):
            tipo, categoria, _desc, valor, mes = (row + (None,) * 5)[:5]
            if tipo is None or valor is None:
                continue
            # Filtra apenas o mês de referência se a coluna existir
            if mes and str(mes).strip() != mes_referencia:
                continue
            valor = float(valor)
            tipo = str(tipo).upper().strip()
            categoria = str(categoria or "Outros")

            if tipo == "R":
                receita += valor
            elif tipo == "D":
                despesa += valor
                dados.categorias_despesa[categoria] = (
                    dados.categorias_despesa.get(categoria, 0) + valor
                )

        dados.receita_realizada = receita
        dados.receita_prevista  = receita  # empresa B não fornece previsto
        dados.despesa_total     = despesa
        dados.total_unidades    = self.config.get("unidades", 0)
        dados.saldo_atual       = self.calcular_saldo(dados)
        return dados

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """Extrai saldo anterior e inadimplência do PDF de resumo."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        with pdfplumber.open(caminho) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)

        # Exemplo de parsing por regex — ajuste conforme o layout do PDF real
        import re
        m = re.search(r"Saldo Anterior[:\s]+R?\$?\s*([\d.,]+)", texto, re.IGNORECASE)
        if m:
            dados.saldo_anterior = float(m.group(1).replace(".", "").replace(",", "."))

        m = re.search(r"Inadimpl[eê]ncia[:\s]+R?\$?\s*([\d.,]+)", texto, re.IGNORECASE)
        if m:
            dados.inadimplencia_valor = float(m.group(1).replace(".", "").replace(",", "."))

        m = re.search(r"Inadimpl[eê]ncia[^\n]*?([\d,]+)\s*%", texto, re.IGNORECASE)
        if m:
            dados.inadimplencia_percentual = float(m.group(1).replace(",", "."))

        return dados
