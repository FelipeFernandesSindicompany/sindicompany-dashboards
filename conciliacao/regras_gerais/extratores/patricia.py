"""
Extrator das regras gerais — Maison Patrícia (Auxiliadora Predial).

Até ago/2026 a prestação de contas vem em planilha .xls ("Prestacao_de_Contas MM.AAAA.xls") -> extratores/auxiliadora_xls.py.
Em set/2026 veio um PDF de 8 páginas, impressão do MESMO sistema ("DEMONSTRATIVO DE CONTAS": Posição Financeira por conta, Resumo Financeiro
Contábil, "DESPESAS" e "RECEITAS" por unidade) -> leitor ContasData (extratores/contasdata.py). O formato é escolhido pela EXTENSÃO do arquivo.

No PDF, o "Resumo de Emissões Geral" termina com uma linha só de valores: PREVISTO (coluna da esquerda) e REALIZADO (direita) do total de
emissões — o mesmo "TOTAL DE EMISSÕES" que o leitor da planilha usa para o card "Arrecadação x Previsto". A inadimplência NÃO é lida do PDF:
a planilha usa a "REC COTAS EM ATRASO" da conta Ordinária (cotas atrasadas do mês anterior), conceito diferente do "Total atrasados" do
"Posição de Devedores", e misturar os dois produziria uma comparação mês a mês enganosa.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.modelo import DadosRegras

_RE_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _previsto_realizado(caminho: Path):
    """(previsto, realizado) do total de emissões no PDF, ou None se a linha não for achada."""
    import fitz
    achado = None
    doc = fitz.open(str(caminho))
    try:
        for pg in doc:
            if "Resumo de Emissões Geral" not in pg.get_text():
                continue
            W = pg.rect.width
            linhas: list = []
            for w in sorted(pg.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0])):
                yc = (w[1] + w[3]) / 2
                if linhas and abs(yc - linhas[-1][0]) <= 3:
                    linhas[-1][1].append(w)
                else:
                    linhas.append([yc, [w]])
            for _yc, ws in linhas:
                ws.sort(key=lambda w: w[0])
                # linha só com dois valores, nas colunas da direita (Previsto, Realizado) e sem rótulo: é o total das emissões
                if len(ws) == 2 and all(_RE_VALOR.match(w[4]) and w[0] > 0.6 * W for w in ws):
                    achado = (_num(ws[0][4]), _num(ws[1][4]))
    finally:
        doc.close()
    return achado


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        caminho = Path(caminho)
        if caminho.suffix.lower() == ".pdf":
            from conciliacao.regras_gerais.extratores.contasdata import Extrator as ExtratorPdf
            dados = ExtratorPdf(self.condo).extrair(caminho, mes)
            pr = _previsto_realizado(caminho)
            if pr is not None:
                dados.indicadores = {"prev": pr[0], "real": pr[1], "inad": None, "inadProc": 0.0}
            return dados
        from conciliacao.regras_gerais.extratores.auxiliadora_xls import Extrator as ExtratorPlanilha
        return ExtratorPlanilha(self.condo).extrair(caminho, mes)
