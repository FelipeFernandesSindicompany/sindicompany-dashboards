"""
Extrator das regras gerais — Splendor Square (Lello).

  .xls (planilha HTML da Lello)                  -> extratores/lello_mhtml.py
  PDF "Pasta Digital" completo (ago-set/2026)    -> extratores/contasdata.py
  PDF resumido (7 págs, out/2026 em diante)      -> contasdata.py com o reconhecimento do formato relaxado (sem as marcas "Voltar ao índice"/
                                                    "ContasData"/"Emitido em" que o leitor exige no PDF completo; ver extratores/baturite.py)
"""
from pathlib import Path

from conciliacao.regras_gerais.extratores.baturite import _extrator_pdf_resumido


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str):
        caminho = Path(caminho)
        if caminho.suffix.lower() != ".pdf":
            from conciliacao.regras_gerais.extratores.lello_mhtml import Extrator as _Lello
            return _Lello(self.condo).extrair(caminho, mes)
        import fitz
        with fitz.open(str(caminho)) as doc:
            resumido = len(doc) <= 30
        if resumido:
            dados = _extrator_pdf_resumido(self.condo).extrair(caminho, mes)
            dados.avisos.append("arquivo em PDF resumido (Resumo Financeiro + Demonstrativos de Receitas e de Despesas): sem comprovantes nem notas fiscais "
                                "além dos baixados pelos links do portal")
            return dados
        from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ContasData
        return _ContasData(self.condo).extrair(caminho, mes)
