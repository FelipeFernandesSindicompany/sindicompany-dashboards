"""
Extrator das regras gerais — uCondo (empresa `ucondo_pdf`: Saint Simon / Conviver MRV).

PDF com texto. Só interessam as páginas do "Balancete Mensal" (1-2 páginas; no livro completo vêm logo depois da capa e
antes de "Comprovantes de Despesas", "Demonstrativo Financeiro" e "Extrato" — que repetem tabelas e não devem ser lidas):

    Receitas (002 - Conta Banco Inter Empresas)        <- um bloco por conta, com linhas "descrição ... R$ valor"
        Transferência Idealle Garantidora ........ R$ 205.232,41
    Total Receitas : R$ ...
    Despesas (001 - Conta Corrente)                    <- um bloco por conta; grupo (Mensais/Manutenção/Diversas) com itens
        Mensais
            Água e esgoto ........................ R$ 41.136,82
        Total Mensais : R$ ...
        Serviços Terceirizados ................... R$ 58.034,06   <- linha de 1º nível (sem grupo)
    Total Despesas : R$ ...
    Totalizações / Saldos: por conta "Saldo Anterior | Saldo Atual" (+ linha de total sem nome)

Particularidades:
  * Cada linha do balancete é uma categoria (às vezes um item avulso criado como categoria própria — "Playground Junior",
    "Kit Spot LED"); o balancete NÃO traz o fornecedor nem a NF — por isso `descricao` = rótulo da linha e `categoria` = grupo
    (Mensais / Manutenção / Diversas) ou "(sem grupo)" para as linhas de 1º nível;
  * as duas contas: "001 - Conta Corrente" (negativa quando a garantidora paga por ela) e "002 - Conta Banco Inter Empresas";
    o mês pode ter receitas só numa e despesas em ambas;
  * as páginas "Comprovantes de Despesas" (só em fev, mar e jul/26 — nos outros meses o PDF tem só o balancete) detalham
    cada pagamento, mas são ignoradas de propósito: o nível de detalhe mudaria de mês a mês e quebraria a comparação de subcontas.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_RE_VALOR = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")
_RE_BLOCO = re.compile(r"^(Receitas|Despesas)\s*\((\d{3})\s*-\s*(.+)\)$")


def _br(s: str):
    s = (s or "").strip()
    return float(s.replace(".", "").replace(",", ".")) if _RE_VALOR.match(s) else None


def _linhas(page, tol: float = 3.0) -> list[dict]:
    ws = sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    linhas: list[dict] = []
    for w in ws:
        yc = (w[1] + w[3]) / 2
        if linhas and abs(yc - linhas[-1]["yc"]) <= tol:
            linhas[-1]["w"].append(w)
        else:
            linhas.append({"yc": yc, "w": [w]})
    for l in linhas:
        l["w"].sort(key=lambda w: w[0])
        l["texto"] = " ".join(w[4] for w in l["w"])
        l["bbox"] = (round(min(w[0] for w in l["w"]), 1), round(min(w[1] for w in l["w"]), 1),
                     round(max(w[2] for w in l["w"]), 1), round(max(w[3] for w in l["w"]), 1))
    return linhas


def _valores_rs(linha: dict) -> list:
    """[(valor_com_sinal, x0)] de cada 'R$ 1.234,56' / '-R$ 1.234,56' da linha."""
    ws = linha["w"]
    out = []
    for i, w in enumerate(ws):
        if w[4] in ("R$", "-R$") and i + 1 < len(ws):
            v = _br(ws[i + 1][4])
            if v is not None:
                out.append((-v if w[4].startswith("-") else v, w[0]))
    return out


def _tipo_receita(descricao: str) -> str:
    d = descricao.upper()
    if re.search(r"RENDIMENT|APLICA[CÇ]", d):
        return "rendimento"
    if re.search(r"GARANTIDORA|COTA|TAXA DE CONDOM", d):
        return "cota"
    if re.search(r"MULTA|JUROS", d):
        return "multa_juros"
    if "TRANSFER" in d:
        return "transferencia"
    return "outra"


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        doc = fitz.open(str(caminho))
        try:
            paginas = []
            for i in range(len(doc)):
                linhas = _linhas(doc[i])
                topo = " ".join(l["texto"] for l in linhas[:4]).upper()
                if "COMPROVANTES DE DESPESAS" in topo or "DEMONSTRATIVO FINANCEIRO" in topo:
                    break                           # daqui em diante só detalhe/duplicatas do balancete
                if "BALANCETE MENSAL" in topo:
                    paginas.append((i + 1, linhas))
                elif paginas:
                    break
        finally:
            doc.close()
        if not paginas:
            for k in ("receitas", "rendimentos", "lancamentos"):
                dados.motivos_nao_cobertos[k] = "não encontrei a página 'Balancete Mensal' do uCondo neste PDF"
            return dados

        # o período impresso no cabeçalho do balancete deve ser o do mês pedido
        mper = re.search(r"COMPENSADO ENTRE (\d{2})/(\d{2})/(\d{4}) E (\d{2})/(\d{2})/(\d{4})",
                         " ".join(l["texto"] for _, ls in paginas[:1] for l in ls[:6]).upper())
        if mper:
            d1, m1, a1, d2, m2, a2 = mper.groups()
            if f"{a1}-{m1}" != mes or f"{a2}-{m2}" != mes:
                dados.avisos.append(f"o Balancete Mensal deste PDF traz o período {d1}/{m1}/{a1} a {d2}/{m2}/{a2}, que não é o mês {mes[5:]}/{mes[:4]} "
                                    f"— os valores lidos são os do período impresso; confirmar com a administradora")

        blocos_rec: dict[str, float] = {}
        blocos_desp: dict[str, float] = {}
        modo = None            # "rec" | "desp" | "tot" | "saldos"
        conta = None
        grupo = None
        saldos: dict[str, tuple] = {}
        for pag, linhas in paginas:
            for l in linhas:
                t = l["texto"].strip()
                tn = t.upper()
                if re.match(r"^(BALANCETE MENSAL|SAINT SIMON|COMPENSADO ENTRE|GERADO EM|P[ÁA]GINA)", tn) or tn.startswith("UCONDO"):
                    continue
                if l["bbox"][1] > 800:               # rodapé
                    continue
                mb = _RE_BLOCO.match(t)
                if mb:
                    modo = "rec" if mb.group(1) == "Receitas" else "desp"
                    conta = f"{mb.group(2)} - {mb.group(3).strip()}"
                    grupo = None
                    continue
                if tn.startswith("TOTALIZA"):
                    modo = "tot"
                    continue
                if tn.startswith("SALDOS"):
                    modo = "saldos"
                    continue
                vals = _valores_rs(l)
                if modo in ("rec", "desp"):
                    if tn.startswith("TOTAL RECEITAS") and vals:
                        blocos_rec[conta] = vals[-1][0]
                        modo = None
                        continue
                    if tn.startswith("TOTAL DESPESAS") and vals:
                        blocos_desp[conta] = vals[-1][0]
                        modo = None
                        continue
                    if tn.startswith("TOTAL ") and ":" in t:
                        grupo = None                  # "Total Mensais : R$ ..." fecha o grupo
                        continue
                    ws = l["w"]
                    # rótulo = palavras antes do "R$"
                    idx = next((i for i, w in enumerate(ws) if w[4] in ("R$", "-R$")), None)
                    rotulo = " ".join(w[4] for w in (ws[:idx] if idx is not None else ws)).strip()
                    if not vals:
                        if modo == "desp" and rotulo:
                            grupo = rotulo            # cabeçalho de grupo (Mensais, Manutenção, Diversas)
                        continue
                    valor = vals[-1][0]
                    x_rotulo = ws[0][0]
                    if modo == "rec":
                        dados.receitas.append(LinhaReceita(conta=conta, descricao=rotulo, valor=valor, tipo=_tipo_receita(rotulo),
                                                           pagina=pag, bbox=l["bbox"]))
                    else:
                        em_grupo = grupo is not None and x_rotulo > 50
                        dados.lancamentos.append(LancamentoDespesa(
                            descricao=rotulo, valor=valor, categoria=grupo if em_grupo else "(sem grupo)", conta=conta,
                            pagina=pag, bbox=l["bbox"]))
                    continue
                if modo == "saldos":
                    m = re.match(r"^(\d{3})\s*-\s*(.+?)\s+(?:-?R\$)", t)
                    if m and vals:
                        nome = f"{m.group(1)} - {m.group(2).strip()}"
                        ant = next((v for v, x in vals if x < 500), 0.0)
                        atu = next((v for v, x in vals if x >= 500), 0.0)
                        saldos[nome] = (ant, atu, pag)

        nomes = list(saldos) + [n for n in list(blocos_rec) + list(blocos_desp) if n not in saldos]
        for nome in dict.fromkeys(nomes):
            ant, atu, pag = saldos.get(nome, (0.0, 0.0, None))
            cred = round(sum(r.valor for r in dados.receitas if r.conta == nome), 2)
            deb = round(blocos_desp.get(nome, 0.0), 2)
            dados.contas.append(ContaMes(nome=nome, saldo_anterior=ant, saldo_atual=atu, creditos=cred, debitos=deb, pagina=pag))
            if nome in saldos and abs(ant + cred - deb - atu) > 0.011:
                dados.avisos.append(f"conta {nome}: saldo anterior + receitas - despesas não fecha com o saldo atual impresso "
                                    f"({ant:,.2f} + {cred:,.2f} - {deb:,.2f} != {atu:,.2f})".replace(",", "X").replace(".", ",").replace("X", "."))
            if nome in blocos_rec and abs(blocos_rec[nome] - cred) > 0.011:
                dados.avisos.append(f"receitas lidas da conta {nome} não fecham com o 'Total Receitas' impresso")
        if not saldos:
            dados.avisos.append("não consegui ler a tabela de Saldos (saldo anterior/atual por conta) do balancete")

        n_rend = len({r.conta for r in dados.receitas if r.tipo == "rendimento"})
        dados.cobertura = {"receitas": bool(blocos_rec) or bool(dados.receitas), "rendimentos": bool(dados.contas) and n_rend >= 2,
                           "lancamentos": bool(dados.lancamentos)}
        if not dados.cobertura["receitas"]:
            dados.motivos_nao_cobertos["receitas"] = "o balancete deste mês não traz bloco de receitas"
        if not dados.cobertura["rendimentos"]:
            dados.motivos_nao_cobertos["rendimentos"] = (
                "não consegui ler as contas do balancete" if not dados.contas else
                "as contas do Saint Simon (001 Conta Corrente e 002 Banco Inter) não têm aplicação: o balancete não traz nenhuma linha de rendimento, "
                "então não há proporção entre contas a verificar")
        if not dados.cobertura["lancamentos"]:
            dados.motivos_nao_cobertos["lancamentos"] = "o balancete deste mês não traz despesas"
        return dados
