"""
Extrator das regras gerais — Living For Consolação.

Até jul/2026 a pasta tinha só planilhas Habitacional ("prestacao_contas_M_AAAA.xlsx"); em ago/set/2026 a administradora passou a enviar o PDF
"Prestação de Contas" completo (ContasData/desti.net.br, 226 páginas, com comprovantes). Como o arquivo enviado pode ser de qualquer um dos dois
formatos, o extrator despacha pela EXTENSÃO (mesmo desenho do Port Saint Tropez): .xlsx -> planilha Habitacional; .pdf -> ContasData.
A comparação mês a mês de subcontas só vale entre arquivos do mesmo formato (o pipeline avisa quando o mês anterior está em outro formato).

O PDF desta administradora não traz a tabela "Resumo Financeiro Contábil": as contas vêm da "Posição Financeira" de cada conta (Demonstrativo de
Contas, pág. 13-15) e as receitas/despesas dos demonstrativos. O reconhecimento aceita esse layout (cabeçalho "Condomínio: NNNN -", Demonstrativo de
Despesas com "TOTAL DA CONTA" e "Posição Financeira"); a leitura em si é a do ContasData.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ExtratorContasData
from conciliacao.regras_gerais.extratores.port_saint_tropez import ExtratorPlanilhaOuContasData


class _ExtratorPdf(_ExtratorContasData):
    def _reconhecer(self, paginas: list) -> bool:
        try:
            ok = super()._reconhecer(paginas)
        except ValueError:
            ok = False
        if ok:
            return True
        todo = "\n".join(p.texto for p in paginas)
        return bool(re.search(r"Condom[ií]nio:\s*\d+\s*-", todo) and re.search(r"TOTAL DA CONTA", todo, re.I)
                    and re.search(r"Posi[çc][ãa]o Financeira", todo) and any(p.tipo == "despesas" for p in paginas))

    def _contas_da_posicao(self, pf: dict) -> list:
        """Sem a tabela "Resumo Financeiro Contábil", as contas vêm da Posição Financeira de cada conta. Nesse layout a linha TOTAIS inclui o SALDO
        ANTERIOR (credor entra nos créditos, devedor nos débitos) e "Descontos" aparece na coluna Débito: o crédito/débito DO MÊS é o total menos o
        saldo anterior, e o desconto volta para os créditos (negativo). Fecha com anterior + créditos - débitos = atual."""
        from conciliacao.regras_gerais.modelo import ContaMes
        contas = []
        for b in pf.values():
            ant = b["saldo_anterior"]
            cred = b["tot_cred"] - max(ant, 0.0)
            deb = b["tot_deb"] - max(-ant, 0.0)
            # crédito negativo (Descontos) impresso na coluna Débito: está em TOTAIS-débito mas o leitor o pôs entre os créditos (negativo)
            movido = round(deb - sum(v for (_d, v, *_r) in b["debitos"]), 2)
            movido = movido if movido > 0.005 else 0.0
            contas.append(ContaMes(nome=b["nome"], saldo_anterior=ant, saldo_atual=b["saldo_atual"], creditos=round(cred - movido, 2),
                                   debitos=round(deb - movido, 2), pagina=b["pagina"]))
        return contas

    def extrair(self, caminho, mes):
        dados = super().extrair(caminho, mes)
        # a Posição Financeira chama "Acordos" a conta que o Demonstrativo de Despesas chama "Acordos conta transitória": sem o mesmo nome,
        # o leitor cria um débito "da Posição Financeira" duplicando o lançamento real — funde os dois
        lancs = list(dados.lancamentos)
        for x in [l for l in lancs if "Posição Financeira — não consta" in (l.descricao or "")]:
            gemeo = next((l for l in lancs if l is not x and abs(l.valor - x.valor) <= 0.01 and _n(l.categoria) == _n(x.categoria)), None)
            if gemeo is not None:
                lancs.remove(x)
                gemeo.conta = x.conta
        dados.lancamentos = lancs
        return dados


_RE_VALOR = re.compile(r"^-?[\d.]+,\d{2}$")


def _num(t: str) -> float:
    return float(t.replace(".", "").replace(",", "."))


def _indicadores_do_pdf(caminho: Path, mes: str):
    """Previsto x Realizado e Inadimplência do "Resumo de Emissões Colunado" de cada conta (Demonstrativo de Contas, págs. ~13-15), na mesma
    metodologia dos meses em planilha: previsto/realizado = totais da conta ORDINÁRIA (as duas últimas colunas da tabela de emissões);
    inadimplência = "Total geral" da Relação de Cotas em Aberto (plano B: soma, de todas as contas, da linha "Condôminos em Atraso em <último dia do mês>" (valor único, sem previsto))."""
    import calendar

    import fitz

    ano, m = int(mes[:4]), int(mes[5:7])
    fim = f"{calendar.monthrange(ano, m)[1]:02d}/{m:02d}/{ano}"
    prev = real = None
    inad = 0.0
    achou_inad = False
    pagina = None
    with fitz.open(str(caminho)) as doc:
        for i in range(min(len(doc), 40)):
            t = doc[i].get_text()
            if "Resumo de Emissões Colunado" not in t or "Demonstrativo de Contas" not in t[:200]:
                continue
            for blk in re.split(r"\n(?=Resumo de Emissões Colunado)", t):
                if not blk.startswith("Resumo de Emiss"):
                    continue
                ls = [l.strip() for l in blk.split("\n")]
                fim_blk = next((k for k, l in enumerate(ls) if l.startswith("Posição Financeira")), len(ls))
                ls = ls[:fim_blk]
                for k, l in enumerate(ls):
                    if l == f"Condôminos em Atraso em {fim}" and k + 1 < len(ls) and _RE_VALOR.match(ls[k + 1])                             and not (k + 2 < len(ls) and _RE_VALOR.match(ls[k + 2])):
                        inad += _num(ls[k + 1])
                        achou_inad = True
                        pagina = pagina or i + 1
                        # a primeira conta com atraso final é a ORDINÁRIA: os dois números antes da linha são realizado e previsto totais
                        if prev is None and k >= 2 and _RE_VALOR.match(ls[k - 1]) and _RE_VALOR.match(ls[k - 2]):
                            real, prev = _num(ls[k - 2]), _num(ls[k - 1])
    if prev is None and not achou_inad:
        return None
    # Inadimplência = "Total geral" da RELAÇÃO DE COTAS EM ABERTO (decisão do dono, 26/10/2026); a soma dos atrasos de fim de mês das contas é só o plano B
    tot, pg_rel = _total_geral_cotas_em_aberto(caminho)
    if tot is not None:
        inad, achou_inad, pagina = tot, True, pg_rel
    return {"prev": prev or 0.0, "real": real or 0.0, "inad": round(inad, 2) if achou_inad else None, "inadProc": 0.0, "pagina_inad": pagina}


def _total_geral_cotas_em_aberto(caminho: Path):
    """(valor, página) da linha "Total geral:" da página "RELAÇÃO DE COTAS EM ABERTO" (Relação de Devedores), ou (None, None)."""
    import fitz

    with fitz.open(str(caminho)) as doc:
        for i in range(len(doc)):
            t = doc[i].get_text()
            if "RELAÇÃO DE COTAS EM ABERTO" not in t or "Total geral" not in t:
                continue
            ws = doc[i].get_text("words")
            rot = next((w for w in ws if w[4].startswith("geral")), None)
            if rot is None:
                continue
            yc = (rot[1] + rot[3]) / 2
            nums = [w for w in ws if _RE_VALOR.match(w[4]) and abs((w[1] + w[3]) / 2 - yc) <= 4]
            if nums:
                return _num(max(nums, key=lambda w: w[0])[4]), i + 1
    return None, None


def _n(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


class Extrator(ExtratorPlanilhaOuContasData):
    def extrair(self, caminho: Path, mes: str):
        if Path(caminho).suffix.lower() == ".pdf":
            dados = _ExtratorPdf(self.condo).extrair(caminho, mes)
            ind = _indicadores_do_pdf(Path(caminho), mes)
            if ind:
                dados.indicadores = ind
            return dados
        return super().extrair(caminho, mes)
