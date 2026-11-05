"""
Conciliador específico — NYC (empresa_gestora="lirba_pdf", parser_config.extract_cats="webware").

O condomínio chega em DOIS formatos de PDF (ver conciliacao/regras_gerais/extratores/nyc.py):
  1. Impressão da tela Webware `MMAAAA.pdf` (~43 páginas): só as tabelas, sem comprovantes — sub-formato "webware"
     (conciliacao/webware_pdf.py: a "despesa" e o "comprovante" são a mesma página, não existe "sem comprovante").
  2. "Pasta Digital" da Manager ADM (ago/2026: 381 páginas, índice "Voltar ao índice"): Demonstrativo de Despesas em lista +
     uma página "Comprovante de Despesa NNNN" por lançamento com o comprovante/NF em IMAGEM — é o formato ContasData/Lirba
     padrão (conciliacao/lirba_pdf.py: comprovante pareado por código e lido por OCR), igual ao Onze 22 / Baturité.
O formato é escolhido pelo CONTEÚDO do arquivo, não pelo nome.
"""
from pathlib import Path

from conciliacao.lirba_pdf import ConciliadorLirbaPDF
from conciliacao.webware_pdf import ConciliadorWebwarePDF


def e_pasta_digital(caminho: Path) -> bool:
    """Pasta Digital ContasData: as primeiras páginas trazem o "Voltar ao índice" (a impressão do Webware e o resumo de outras
    administradoras não trazem) e o arquivo tem páginas "Comprovante de Despesa"."""
    try:
        import fitz
        doc = fitz.open(str(caminho))
        try:
            topo = " ".join(doc[i].get_text() for i in range(min(len(doc), 6))).lower()
            if "voltar ao índice" not in topo and "voltar ao indice" not in topo:
                return False
            return any("Comprovante de Despesa" in doc[i].get_text() for i in range(min(len(doc), 200)))
        finally:
            doc.close()
    except Exception:
        return False


class Conciliador(ConciliadorWebwarePDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if e_pasta_digital(Path(caminho)):
            return ConciliadorLirbaPDF(self.config).extrair_comprovantes(caminho)
        return super().extrair_comprovantes(caminho)
