"""
Adapter específico para Dueto Morumbi.
Empresa gestora: manager_adm_pdf

Diferença do genérico:
  inadProc — o genérico soma linhas com padrão "{valor}TOTAL COTAS EM ATRASO",
  que corresponde ao saldo devedor total. Para Dueto Morumbi, o campo correto é
  "Recebido de Cotas em Atraso" (valor efetivamente recebido de inadimplentes).
"""
import re
from pathlib import Path

from adapters.manager_adm_pdf import AdapterManagerAdmPDF, _num
from adapters.base import DadosFinanceiros


class Adapter(AdapterManagerAdmPDF):
    """Adapter de Dueto Morumbi — corrige inadProc para 'Recebido de Cotas em Atraso'."""

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        dados = super().ler_pdf(caminho, mes_referencia)

        # Re-lê o texto para extrair inadProc pelo label correto
        from pypdf import PdfReader
        reader = PdfReader(str(caminho))
        lines = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                lines.extend([l.strip() for l in t.replace("\xa0", " ").split("\n") if l.strip()])

        inadproc = 0.0
        for l in lines:
            # Formato A: "1.234,56Recebido de Cotas em Atraso" (número colado antes do label)
            m = re.match(
                r"(-?\d{1,3}(?:\.\d{3})*,\d{2})Recebido\s+de\s+Cotas\s+em\s+Atraso",
                l, re.IGNORECASE
            )
            if m:
                inadproc += _num(m.group(1))
                continue
            # Formato B: "Recebido de Cotas em Atraso  1.234,56"
            m = re.match(
                r"Recebido\s+de\s+Cotas\s+em\s+Atraso\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})",
                l, re.IGNORECASE
            )
            if m:
                inadproc += _num(m.group(1))

        if inadproc > 0:
            dados.inadimplencia_recebida = inadproc

        return dados
