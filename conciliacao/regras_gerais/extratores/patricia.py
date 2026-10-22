"""
Extrator das regras gerais — Maison Patrícia (Auxiliadora Predial).

Até ago/2026 a prestação de contas vem em planilha .xls ("Prestacao_de_Contas MM.AAAA.xls") -> extratores/auxiliadora_xls.py.
Em set/2026 veio um PDF de 8 páginas, impressão do MESMO sistema ("DEMONSTRATIVO DE CONTAS": Posição Financeira por conta, Resumo Financeiro
Contábil, "DESPESAS" e "RECEITAS" por unidade) -> leitor ContasData (extratores/contasdata.py). O formato é escolhido pela EXTENSÃO do arquivo.

No PDF, o "Resumo de Emissões Geral" termina com uma linha só de valores: PREVISTO (coluna da esquerda) e REALIZADO (direita) do total de
emissões — o mesmo "TOTAL DE EMISSÕES" que o leitor da planilha usa para o card "Arrecadação x Previsto". INADIMPLÊNCIA (decisão do dono, 22/10/2026): vale o "Total atrasados" da linha "Totais" da "Posição de Devedores" (cotas em atraso no fim do
mês); o "Total anterior" da mesma linha é o atraso do mês anterior (`indicadores["inad_anterior"]`, usado na regra de inadimplência crescente).
A planilha .xls NÃO tem esse bloco: nos meses em planilha a inadimplência fica sem valor (a "REC COTAS EM ATRASO" da Ordinária, que o
leitor antigo usava, é outro conceito e não pode ser comparada).
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


def _devedores(caminho: Path):
    """(total_anterior, total_recebido, devedores_do_mes, total_atrasados, página) da linha "Totais" da Posição de Devedores, ou None."""
    import fitz
    achado = None
    doc = fitz.open(str(caminho))
    try:
        for pg in doc:
            if "Posição de Devedores" not in pg.get_text():
                continue
            linhas: list = []
            for w in sorted(pg.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0])):
                yc = (w[1] + w[3]) / 2
                if linhas and abs(yc - linhas[-1][0]) <= 3:
                    linhas[-1][1].append(w)
                else:
                    linhas.append([yc, [w]])
            for _yc, ws in linhas:
                ws.sort(key=lambda w: w[0])
                vals = [w for w in ws if _RE_VALOR.match(w[4])]
                if ws and ws[0][4].lower().startswith("totais") and len(vals) == 4:
                    achado = tuple(_num(w[4]) for w in vals) + (pg.number + 1,)
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
            dv = _devedores(caminho)
            if dv is not None:
                dados.indicadores = {**(dados.indicadores or {"prev": 0.0, "real": 0.0}), "inad": dv[3], "inad_anterior": dv[0], "inadProc": dv[1], "pagina_inad": dv[4]}
            return dados
        from conciliacao.regras_gerais.extratores.auxiliadora_xls import Extrator as ExtratorPlanilha
        return ExtratorPlanilha(self.condo).extrair(caminho, mes)
