"""
Extrator das regras gerais — Baturité.

Baturité migrou da planilha Habitacional (XLSX "prestacao_contas_M_AAAA", abr a ago/2025 na pasta do projeto) para o
PDF "Prestação de Contas" ContasData (out/2025 em diante; set/2025 não existe na pasta). O cadastro ainda diz
`habitacional_xlsx`, então o despacho de `extratores/__init__.py` cairia só no extrator de planilha e um PDF
daria erro; este módulo resolve pela EXTENSÃO do arquivo, igual ao Port Saint Tropez:

  .xlsx/.xlsm -> extratores/habitacional_xlsx.py  (planilha; conferido nos 5 meses da pasta)
  .pdf        -> extratores/contasdata.py         (importado de forma preguiçosa; se faltar, cobertura False com motivo)

Observação: as planilhas de Baturité NÃO têm "Demonstrativo de Receitas" (só Posição Financeira por conta) — as
receitas e o rendimento saem das linhas de crédito da Posição Financeira (ver habitacional_xlsx.py).
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.extratores.port_saint_tropez import ExtratorPlanilhaOuContasData

# PDF "Demonstrativo de Contas" RESUMIDO (6 págs, out/2026 em diante, com link do portal em cada despesa): sai sem as marcas que o leitor ContasData
# usa para reconhecer o software ("Voltar ao índice", "ContasData", "Nº lancto.", "Emitido em") e sem coluna de data/Nº de lançamento no
# "Demonstrativo de Despesas". O restante do layout (Resumo Financeiro Contábil, Posição Financeira, Demonstrativos) é o mesmo.


def _extrator_pdf_resumido(condo: dict):
    from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ContasData

    class _ContasDataResumido(_ContasData):
        def _reconhecer(self, paginas: list) -> bool:
            try:
                return super()._reconhecer(paginas)
            except ValueError:
                inicio = "\n".join(p.texto for p in paginas[:40])
                if not (re.search(r"Demonstra(?:tivo|[çc][ãa]o) de Contas|Demonstrativo de Despesas", inicio) and re.search(r"Condom[ií]nio:\s*\d+\s*-", inicio)):
                    raise
                todo = "\n".join(p.texto for p in paginas if p.tipo != "outro")
                return bool(re.search(r"Resumo Financeiro Cont[áa]bil", todo, re.I) and re.search(r"TOTAL DA CONTA", todo, re.I)
                            and any(p.tipo == "despesas" for p in paginas))

    return _ContasDataResumido(condo)


class Extrator(ExtratorPlanilhaOuContasData):
    def extrair(self, caminho: Path, mes: str):
        if Path(caminho).suffix.lower() == ".pdf":
            import fitz
            with fitz.open(str(caminho)) as doc:
                resumido = len(doc) <= 30
            if resumido:
                dados = _extrator_pdf_resumido(self.condo).extrair(caminho, mes)
                dados.avisos.append("arquivo em PDF resumido (Resumo Financeiro + Demonstrativos de Receitas e de Despesas): sem comprovantes nem notas fiscais "
                                    "além dos baixados pelos links do portal")
                return dados
        return super().extrair(caminho, mes)
