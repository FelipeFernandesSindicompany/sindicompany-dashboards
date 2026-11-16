"""
Extrator das regras gerais — Highlights Dr. Nelson Moretti (GK ADM, ContasData).

  PDF "Pasta Digital" completo (até set/2026)   -> extratores/contasdata.py, como sempre
  PDF resumido (8 págs, out/2026 em diante)     -> o mesmo leitor, com duas diferenças de rótulo deste layout: a tabela de saldos das contas se chama
                                                   "Resumo Contábil" (no padrão é "Resumo Financeiro Contábil") e o cabeçalho é "Demonstração de Contas".
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ContasData
from conciliacao.regras_gerais.extratores.contasdata import _norm, _num
from conciliacao.regras_gerais.modelo import ContaMes

_RE_TITULO = re.compile(r"^Resumo (?:Financeiro )?Cont[áa]bil", re.IGNORECASE)


class _ContasDataHighlights(_ContasData):
    def _reconhecer(self, paginas: list) -> bool:
        todo = "\n".join(p.texto for p in paginas if p.tipo != "outro")
        return bool(re.search(r"Resumo (?:Financeiro )?Cont[áa]bil", todo, re.I) and re.search(r"TOTAL DA CONTA", todo, re.I)
                    and any(p.tipo == "despesas" for p in paginas))

    def _ler_resumo(self, paginas: list, dados) -> list:
        contas: list[ContaMes] = []
        em_resumo = False
        for p in paginas:
            if p.tipo not in ("contas", "despesas", "receitas") and not (em_resumo and len(p.texto) > 150):
                continue
            for l in p.linhas:
                if _RE_TITULO.match(l.texto) and re.search(r"Saldo\s+anterior", l.texto, re.I):
                    em_resumo = True
                    continue
                if not em_resumo:
                    continue
                if l.texto.upper().startswith("TOTAL"):
                    return contas
                din = l.dinheiro()
                if len(din) >= 4 and l.texto[:1].isalpha():
                    v = [_num(w[4]) for w in din[-4:]]
                    nome = " ".join(w[4] for w in l.pal if w[2] < din[-4][0] - 0.5).strip()
                    if nome and _norm(nome) not in {_norm(c.nome) for c in contas}:
                        contas.append(ContaMes(nome=nome, saldo_anterior=v[0], creditos=v[1], debitos=v[2], saldo_atual=v[3], pagina=p.n))
        return contas


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str):
        caminho = Path(caminho)
        import fitz
        with fitz.open(str(caminho)) as doc:
            resumido = len(doc) <= 30
        if resumido:
            dados = _ContasDataHighlights(self.condo).extrair(caminho, mes)
            dados.avisos.append("arquivo em PDF resumido (Resumo Contábil + Demonstrativos de Receitas e de Despesas): sem comprovantes nem notas fiscais "
                                "além dos baixados pelos links do portal")
            return dados
        return _ContasData(self.condo).extrair(caminho, mes)
