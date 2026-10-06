"""
Extrator das regras gerais — Auxiliadora Predial "Prestacao_de_Contas MM.AAAA.xls" (condomínio: patricia).

Formato: .xls BINÁRIO (OLE2 / Excel 97-2003), lido com xlrd (só leitura; mesma biblioteca de
adapters/auxiliadora_xls.py e conciliacao/auxiliadora_xls.py). Seis abas:

  'Demonst de Contas'           por conta: linha-título [CONTA | débito total | crédito total], cabeçalho
                                "POSIÇÃO FINANCEIRA", depois UMA linha por rubrica (rótulo | débito | crédito), SEM ordem
                                fixa e com "SALDO ANTERIOR ..."/"TOTAIS"/"SALDO ATUAL ..." no meio. Os totais da linha-título
                                e de "TOTAIS" incluem o saldo anterior devedor (por isso o débito do Resumo é menor).
  'Resumo de Emissões'          previsto x realizado (NÃO usado)
  'Resumo Financeiro Contabil'  conta | saldo anterior | créditos | débitos | saldo atual
  'Demonstrativo de Despesas'   SÓ as contas extraordinárias (ex.: "DESP. REFORMA ELEVADORES", "FDO DE OBRAS"):
                                cabeçalho [RUBRICA | Valor | Total | Percentual], lançamentos "FORNECEDOR - NF. n ... PC. n/t".
                                As despesas da ORDINÁRIA NÃO são itemizadas: só aparecem por categoria na Posição Financeira.
  'Demonstrativo de Receitas'   blocos de recibos [data | unidade | recibo | vencimento | histórico | valor] + linha de total do
                                bloco. Só o 1º bloco de cada conta traz o rótulo (ex.: "REC CONDOMINIO"); os seguintes ficam sem
                                rótulo — o extrator os liga à rubrica pelo VALOR (total do bloco = linha de crédito da Posição Financeira).
  'Demonst. Financeira'         saldos bancários (não usado, só para conferir o período)

Mapeamento para o modelo
  receitas     cada recibo/linha do Demonstrativo de Receitas (sinal como impresso) + créditos que só estão na Posição
  contas       Resumo Financeiro Contábil; `rendimento` = linha "RENDIMENTOS" (crédito) da Posição da conta
  lancamentos  linhas do Demonstrativo de Despesas (só contas extraordinárias). cobertura["lancamentos"] = False porque a
               ORDINÁRIA não é itemizada: marcar como "verificado" um arquivo cujo grosso das despesas não pode ser lido seria
               enganoso. As linhas são preenchidas assim mesmo (úteis a quem quiser tratá-las) e `categoria` = rubrica do cabeçalho.
Parcelas: "PC. 10/24" é convertido para "(PARC 10/24)" no fim da descrição (a regra procura "PARC n/t").
"""
import re
import unicodedata
from pathlib import Path
from typing import Optional

from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CENTAVO = 0.011


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _chave(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", _sem_acento(str(s or "")).upper())).strip()


def _txt(v) -> str:
    return " ".join(str(v if v is not None else "").replace("\xa0", " ").split())


def _num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("R$", "").replace(" ", "").replace("\xa0", "")
    if not s:
        return None
    neg = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()-")
    if not re.fullmatch(r"\d[\d.]*(,\d+)?|,\d+|\d+\.\d+", s):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _fmt(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data(v, datemode: int = 0) -> Optional[str]:
    """'2026-07-07' ou serial do Excel -> 'DD/MM/AAAA'."""
    if isinstance(v, (int, float)) and v > 20000:
        import xlrd
        try:
            a, m, d, *_ = xlrd.xldate_as_tuple(v, datemode)
            return f"{d:02d}/{m:02d}/{a:04d}"
        except Exception:
            return None
    s = _txt(v)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    if re.match(r"^\d{2}/\d{2}/\d{4}$", s):
        return s
    return None


def _tipo_receita(label: str) -> str:
    c = _chave(label)
    if "RENDIMENTO" in c:
        return "rendimento"
    if re.search(r"TRANSFER|APLICACAO|RESGATE", c):
        return "transferencia"
    if re.search(r"MULTA|JURO|ATUALIZACAO", c):
        return "multa_juros"
    if re.search(r"CUSTAS|CORREIO|ALUGUE|DIVERSOS", c):
        return "outra"
    if re.search(r"COTA|REC|ANTECIPA|EMISSAO", c):
        return "cota"
    return "outra"


_RE_PC = re.compile(r"\bP\.?C\.?\s*(\d{1,2})\s*/\s*(\d{1,2})\b", re.IGNORECASE)


def _marca_parcela(descricao: str) -> str:
    """'... PC. 10/24' (parcela 10 de 24) -> acrescenta ' (PARC 10/24)' para a regra de parcelas."""
    if re.search(r"\bPARC", descricao, re.IGNORECASE):
        return descricao
    m = _RE_PC.search(descricao)
    if m:
        n, t = int(m.group(1)), int(m.group(2))
        if t >= 2 and 1 <= n <= t <= 99:
            return f"{descricao} (PARC {n}/{t})"
    return descricao


def _aba(wb, *nomes):
    alvo = {_chave(n) for n in nomes}
    for i in range(wb.nsheets):
        if _chave(wb.sheet_by_index(i).name) in alvo:
            return wb.sheet_by_index(i)
    return None


def _linha(ws, r: int, n: int = 6) -> list:
    return [ws.cell_value(r, c) if c < ws.ncols else "" for c in range(n)]


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo
        self.cfg = condo.get("parser_config") or {}

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        try:
            import xlrd
        except ImportError as exc:  # pragma: no cover
            raise ImportError("Instale xlrd (pip install xlrd) para ler os arquivos Auxiliadora .xls") from exc
        caminho = Path(caminho)
        wb = xlrd.open_workbook(str(caminho))
        dados = DadosRegras(mes=mes, arquivo=caminho.name)

        ws_resumo = _aba(wb, "Resumo Financeiro Contabil")
        ws_pos = _aba(wb, "Demonst de Contas", "Demonstrativo de Contas")
        ws_rec = _aba(wb, "Demonstrativo de Receitas")
        ws_desp = _aba(wb, "Demonstrativo de Despesas")
        ws_banco = _aba(wb, "Demonst. Financeira", "Demonstrativo Financeiro")
        if ws_resumo is None:
            raise ValueError("A aba 'Resumo Financeiro Contabil' não existe no arquivo (não parece uma prestação de contas Auxiliadora)")

        self._confere_periodo(ws_banco, mes, dados)
        contas = self._resumo(ws_resumo)
        pos = self._posicoes(ws_pos, contas) if ws_pos is not None else {}
        blocos = self._receitas(ws_rec, wb.datemode, dados) if ws_rec is not None else []
        self._montar_receitas(dados, contas, pos, blocos)
        lanc = self._despesas(ws_desp, contas, pos, dados) if ws_desp is not None else []
        for k, c in contas.items():
            # rendimento BRUTO creditado na conta (linhas do Demonstrativo de Receitas; o IR s/ resgate é lançado à parte, com
            # sinal negativo, e entra como tipo "transferencia"); sem o Demonstrativo, cai para o crédito da Posição Financeira.
            rend_linhas = [r.valor for r in dados.receitas if _chave(r.conta) == k and r.tipo == "rendimento"]
            b = pos.get(k)
            c.rendimento = round(sum(rend_linhas), 2) if rend_linhas else (
                round(sum(cred for l, d, cred, _ in b["linhas"] if "RENDIMENTO" in _chave(l)), 2) if b else 0.0)
        self._conferir_debitos(dados, contas, pos)
        dados.contas = list(contas.values())
        dados.lancamentos = lanc

        dados.cobertura = {
            "receitas": bool(blocos) or bool(pos),
            "rendimentos": bool(contas) and bool(pos),
            "lancamentos": False,
        }
        if not dados.cobertura["receitas"]:
            dados.motivos_nao_cobertos["receitas"] = "o arquivo não traz o Demonstrativo de Receitas nem a Posição Financeira por conta"
        if not dados.cobertura["rendimentos"]:
            dados.motivos_nao_cobertos["rendimentos"] = "o arquivo não traz a Posição Financeira por conta"
        ordinaria = next((c for k, c in contas.items() if k.startswith("ORDINARIA")), None)
        extras = sorted({l.conta for l in lanc})
        dados.motivos_nao_cobertos["lancamentos"] = (
            "o arquivo da Auxiliadora só lista lançamentos individuais das contas extraordinárias"
            + (f" ({', '.join(extras)})" if extras else " (neste mês, nenhum)")
            + "; as despesas da ORDINÁRIA"
            + (f" ({_fmt(ordinaria.debitos)} no mês)" if ordinaria else "")
            + " aparecem só por categoria na Posição Financeira, sem fornecedor/histórico/parcela")
        return dados

    # -- período ---------------------------------------------------------------
    @staticmethod
    def _confere_periodo(ws, mes: str, dados: DadosRegras):
        if ws is None:
            return
        for r in range(ws.nrows):
            m = re.match(r"^(\d{2})/(\d{2})/(\d{4})\s*-", _txt(ws.cell_value(r, 0)))
            if m:
                if f"{m.group(3)}-{m.group(2)}" != mes:
                    dados.avisos.append(f"o fechamento impresso no arquivo é {m.group(2)}/{m.group(3)}, diferente do mês informado ({mes[5:]}/{mes[:4]})")
                return

    # -- Resumo Financeiro Contábil -------------------------------------------
    @staticmethod
    def _resumo(ws) -> dict:
        contas: dict[str, ContaMes] = {}
        ini = next((r for r in range(ws.nrows) if _chave(ws.cell_value(r, 0)) == "CONTA CONTABIL"), None)
        if ini is None:
            return contas
        for r in range(ini + 1, ws.nrows):
            nome = _txt(ws.cell_value(r, 0))
            if not nome:
                continue
            if _chave(nome) == "TOTAL":
                break
            v = [_num(ws.cell_value(r, c)) for c in range(1, 5)]
            if None in v:
                continue
            contas[_chave(nome)] = ContaMes(nome=nome.upper(), saldo_anterior=v[0], creditos=v[1], debitos=v[2], saldo_atual=v[3])
        return contas

    # -- Posição Financeira (aba 'Demonst de Contas') --------------------------
    @staticmethod
    def _posicoes(ws, contas) -> dict:
        """{chave da conta: {"nome", "linhas": [(rótulo, débito, crédito, local)], "tot_deb", "tot_cred"}} na ordem do arquivo."""
        res: dict = {}
        r = 0
        while r < ws.nrows:
            nome = _txt(ws.cell_value(r, 0))
            prox = _txt(ws.cell_value(r + 1, 0)) if r + 1 < ws.nrows else ""
            if nome and _chave(prox) == "POSICAO FINANCEIRA" and _chave(nome) != "POSICAO FINANCEIRA":
                bloco = {"nome": nome, "linhas": [], "tot_deb": None, "tot_cred": None, "sa_deb": 0.0, "sa_cred": 0.0}
                j = r + 2
                while j < ws.nrows:
                    rot = _txt(ws.cell_value(j, 0))
                    if not rot:
                        break
                    ck = _chave(rot)
                    if _chave(_txt(ws.cell_value(j + 1, 0)) if j + 1 < ws.nrows else "") == "POSICAO FINANCEIRA":
                        break  # próximo título (arquivo sem linha em branco entre contas)
                    deb, cred = _num(ws.cell_value(j, 1)) or 0.0, _num(ws.cell_value(j, 2)) or 0.0
                    if ck == "TOTAIS":
                        bloco["tot_deb"], bloco["tot_cred"] = deb, cred
                    elif ck.startswith("SALDO ANTERIOR"):
                        bloco["sa_deb"], bloco["sa_cred"] = deb, cred
                    elif ck.startswith("SALDO ATUAL"):
                        pass
                    else:
                        bloco["linhas"].append((rot, deb, cred, f"aba 'Demonst de Contas', linha {j + 1}"))
                    j += 1
                chave = _chave(nome)
                if chave not in contas:
                    cand = [k for k in contas if k.startswith(chave) or chave.startswith(k)]
                    chave = cand[0] if len(cand) == 1 else chave
                res[chave] = bloco
                r = j
            r += 1
        return res

    # -- Demonstrativo de Receitas --------------------------------------------
    @staticmethod
    def _receitas(ws, datemode, dados) -> list:
        """[{"rotulo": rótulo impresso (só no 1º bloco da conta) ou None, "linhas": [...], "total": impresso, "linha": nº}]"""
        blocos, rotulo, atual = [], None, []
        for r in range(ws.nrows):
            row = _linha(ws, r)
            c0 = _txt(row[0])
            if _chave(c0) in ("DEMONSTRATIVO DE RECEITAS", "DATA"):
                continue
            if _chave(row[4]).startswith("TOTAL DAS RECEITAS"):
                break
            data = _data(row[0], datemode)
            val = _num(row[5])
            if data and val is not None:
                atual.append({"data": data, "unidade": _txt(row[1]), "recibo": _txt(row[2]), "hist": _txt(row[4]), "valor": val,
                              "local": f"aba 'Demonstrativo de Receitas', linha {r + 1}"})
            elif c0 and not any(_txt(x) for x in row[1:]):
                rotulo = c0
            elif not c0 and not any(_txt(x) for x in row[1:5]) and val is not None:
                soma = round(sum(l["valor"] for l in atual), 2)
                if abs(soma - val) > _CENTAVO:
                    dados.avisos.append(f"Demonstrativo de Receitas (linha {r + 1}): recibos do bloco somam {_fmt(soma)}, total impresso {_fmt(val)}")
                blocos.append({"rotulo": rotulo, "linhas": atual, "total": val, "linha": r + 1})
                rotulo, atual = None, []
        if atual:
            dados.avisos.append(f"Demonstrativo de Receitas: {len(atual)} recibo(s) no fim da aba sem linha de total")
        return blocos

    def _montar_receitas(self, dados, contas, pos, blocos):
        """Liga cada bloco de recibos a uma conta e a uma rubrica da Posição Financeira.

        Só o 1º bloco de cada conta traz o rótulo; os demais ficam sem. Como o total do bloco é igual à linha de crédito da
        Posição (ao centavo), o pareamento é por VALOR, avançando só para frente na ordem das contas do arquivo (o rótulo
        desempata). Bloco que não casa por valor (ex.: total 0,00 de recibo + estorno) fica na conta do próximo bloco casado
        quando traz rótulo (começo de conta) ou na conta do bloco anterior quando não traz."""
        ordem = list(pos)                              # contas na ordem do arquivo
        usados: dict = {k: set() for k in ordem}       # linhas de crédito da Posição já ligadas a um bloco

        def creditos(k):
            return [(i, l) for i, l in enumerate(pos[k]["linhas"]) if l[2]]

        idx_bloco: list = [None] * len(blocos)
        rot_bloco: list = [None] * len(blocos)
        ponteiro = 0
        for n, b in enumerate(blocos):
            if abs(b["total"]) < 0.005:
                continue
            alvo = _chave(b["rotulo"]) if b["rotulo"] else None
            cand = [(ix, i, l) for ix in range(ponteiro, len(ordem)) for i, l in creditos(ordem[ix])
                    if i not in usados[ordem[ix]] and abs(l[2] - b["total"]) <= _CENTAVO]
            if not cand:
                continue
            pref = [c for c in cand if alvo and _chave(c[2][0]) == alvo]
            ix, i, l = (pref or cand)[0]
            usados[ordem[ix]].add(i)
            idx_bloco[n], rot_bloco[n], ponteiro = ix, l[0], ix
        for n, b in enumerate(blocos):          # blocos sem pareamento por valor
            if idx_bloco[n] is not None:
                continue
            if b["rotulo"]:
                prox = next((idx_bloco[m] for m in range(n + 1, len(blocos)) if idx_bloco[m] is not None), None)
                idx_bloco[n] = prox if prox is not None else next((idx_bloco[m] for m in range(n - 1, -1, -1) if idx_bloco[m] is not None), 0)
            else:
                idx_bloco[n] = next((idx_bloco[m] for m in range(n - 1, -1, -1) if idx_bloco[m] is not None), 0)

        for n, b in enumerate(blocos):
            k = ordem[idx_bloco[n]] if ordem else None
            cnome = (contas[k].nome if k in contas else pos[k]["nome"].upper()) if k else ""
            rot = rot_bloco[n] or b["rotulo"] or ""
            for l in b["linhas"]:
                # IR retido no resgate (negativo, lançado junto do rendimento) é movimento de aplicação, não receita
                if re.match(r"^\s*IR\b", l["hist"], re.IGNORECASE) or _chave(l["hist"]).startswith("IOF"):
                    tipo = "transferencia"
                elif rot:
                    tipo = _tipo_receita(rot)
                else:
                    tipo = "rendimento" if "REND" in _chave(l["hist"]) else _tipo_receita(l["hist"])
                dados.receitas.append(LinhaReceita(
                    conta=cnome,
                    descricao=f"{l['hist']} [{rot.title()}" + (f"; unid. {l['unidade']}" if l["unidade"] not in ("", "0") else "")
                              + (f"; recibo {l['recibo']}" if l["recibo"] not in ("", "0") else "") + "]",
                    valor=l["valor"], tipo=tipo, data=l["data"], local=l["local"]))

        # créditos da Posição sem bloco de recibos: só entram se forem necessários para fechar o crédito do Resumo
        # (ex.: transferência). Linhas "memória" da Posição (ex.: "DE COTAS ANTECIPADAS" do Salão) ficam de fora.
        for k in ordem:
            cnome = contas[k].nome if k in contas else pos[k]["nome"].upper()
            sobras = [(i, l) for i, l in creditos(k) if i not in usados[k]]
            c = contas.get(k)
            soma = round(sum(r.valor for r in dados.receitas if _chave(r.conta) == k), 2)
            if c is None:
                continue
            alvo_cred = round(c.creditos, 2)
            if abs(soma - alvo_cred) <= _CENTAVO:
                continue
            falta = round(alvo_cred - soma, 2)
            escolha = None
            if sobras:
                import itertools
                for r in range(1, min(len(sobras), 6) + 1):
                    for comb in itertools.combinations(sobras, r):
                        if abs(sum(l[2] for _, l in comb) - falta) <= _CENTAVO:
                            escolha = comb
                            break
                    if escolha:
                        break
            if escolha:
                for _, (label, deb, cred, loc) in escolha:
                    dados.receitas.append(LinhaReceita(conta=cnome, descricao=f"{label} [somente na Posição Financeira]",
                                                       valor=cred, tipo=_tipo_receita(label), local=loc))
            else:
                dados.avisos.append(f"{cnome}: receitas lidas somam {_fmt(soma)}, mas o crédito da conta no Resumo é {_fmt(alvo_cred)} (diferença de {_fmt(-falta)})")

    # -- Demonstrativo de Despesas (só contas extraordinárias) ----------------
    def _despesas(self, ws, contas, pos, dados) -> list:
        lanc: list[LancamentoDespesa] = []
        rubrica, conta, total_decl = None, None, None
        somas: dict = {}
        for r in range(ws.nrows):
            row = _linha(ws, r, 4)
            c0 = _txt(row[0])
            if not c0 and _txt(row[2]).lower().startswith("total da conta"):
                total_decl = _num(row[3])
                continue
            if _chave(c0) in ("DEMONSTRATIVO DE DESPESAS", ""):
                continue
            if _chave(c0).startswith("TOTAL DE DESPESAS"):
                break
            if _txt(row[1]).lower() == "valor":      # cabeçalho de rubrica
                rubrica = c0
                conta = self._conta_da_rubrica(rubrica, contas, pos)
                if conta is None:
                    dados.avisos.append(f"Demonstrativo de Despesas: não achei a conta da rubrica '{rubrica}' na Posição Financeira")
                continue
            v = _num(row[1])
            if v is not None and rubrica:
                nome_conta = contas[conta].nome if conta in contas else (conta or rubrica)
                lanc.append(LancamentoDespesa(descricao=_marca_parcela(c0), valor=v, categoria=rubrica, conta=nome_conta,
                                              local=f"aba 'Demonstrativo de Despesas', linha {r + 1}"))
                somas[(nome_conta, rubrica)] = round(somas.get((nome_conta, rubrica), 0.0) + v, 2)
        for (nome_conta, rubrica), s in somas.items():
            k = _chave(nome_conta)
            b = pos.get(k)
            if b:
                pos_deb = round(sum(d for l, d, _, _ in b["linhas"] if _chave(l) == _chave(rubrica)), 2)
                if abs(pos_deb - s) > _CENTAVO:
                    dados.avisos.append(f"{nome_conta}: lançamentos da rubrica '{rubrica}' somam {_fmt(s)}, mas a Posição Financeira registra {_fmt(pos_deb)}")
        return lanc

    @staticmethod
    def _conta_da_rubrica(rubrica: str, contas, pos) -> Optional[str]:
        alvo = _chave(rubrica)
        for k, b in pos.items():
            if any(_chave(l[0]) == alvo and l[1] for l in b["linhas"]):
                return k
        return None

    # -- débitos do Resumo x Posição ------------------------------------------
    @staticmethod
    def _conferir_debitos(dados, contas, pos):
        """O "TOTAIS" de débito da Posição inclui o saldo anterior devedor (e deixa de fora linhas-memória como
        "DESPESAS INTERNAS"); tirando o saldo anterior devedor deve fechar com o débito do Resumo. Quando a Posição
        mostra "RENDIMENTOS" na coluna de DÉBITO (rendimento líquido negativo depois do IR), o Resumo separa o rendimento
        bruto (crédito) e o IR (débito): soma-se o rendimento bruto da conta."""
        for k, c in contas.items():
            b = pos.get(k)
            if not b or b["tot_deb"] is None:
                continue
            esperado = round(b["tot_deb"] - b["sa_deb"], 2)
            if any("RENDIMENTO" in _chave(l) and d for l, d, _, _ in b["linhas"]):
                esperado = round(esperado + c.rendimento, 2)
            if abs(esperado - round(c.debitos, 2)) > _CENTAVO:
                dados.avisos.append(f"{c.nome}: débito da Posição Financeira (sem o saldo anterior) é {_fmt(esperado)}, mas o Resumo mostra {_fmt(c.debitos)} "
                                    f"(diferença de {_fmt(esperado - c.debitos)})")
