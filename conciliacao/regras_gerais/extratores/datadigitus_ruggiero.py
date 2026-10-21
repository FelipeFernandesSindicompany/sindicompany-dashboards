"""
Leitor do layout NATIVO da administradora Predial Ruggiero (Software DataDigitus) — Maison du Rhône a partir de set/2026.

É outro formato do "Balancete consolidado" que o condomínio recebia até agosto: PDF de texto corrido (retrato, 595 x 842 pt), uma seção por
relatório, todas com o cabeçalho "PREDIAL RUGGIERO LTDA / 0015 - COND.EDIF.MAISON DU RHONE  Setembro / 2026":

  1.1 RELATÓRIO DE PENDÊNCIAS      unidades em atraso (ignorada aqui)
  2.1 DEMONSTRATIVO DE DESPESAS    "NNN - CONTA X" > grupo (TERCEIRIZACAO, SALARIOS...) > lançamentos "histórico ........ valor" (SEM data;
                                   o histórico longo quebra em 2 linhas e o valor fica na 2ª); o subtotal do grupo vem sozinho numa linha;
                                   "TOTAL DA CONTA  valor" fecha a conta
  3.2 RELATÓRIO DE RECEBIMENTOS    por unidade/recibo (cotas, multas, juros) e "TOTAL DOS RECEBIMENTOS"
  4.1 DEMONSTRATIVO FINANCEIRO     por conta: "POSIÇÃO FINANCEIRA" (Saldo Anterior, Receita Realizada: Da emissão do período / De condôminos em
                                   atraso / Antecipações / Multas / Juros e Correção, Outras Receitas = rendimento nas contas de aplicação,
                                   Despesas do Período, Saldo Atual)
  5.4 RESUMO FINANCEIRO            um quadro "| NNN - CONTA X |" por conta, com os mesmos números, e "SALDO ATUAL" total no fim

Só a camada de texto do próprio PDF é usada (nenhum dashboard, nenhum OCR). As conferências aritméticas (subtotal do grupo, total da conta,
saldo anterior + créditos - débitos = saldo atual, créditos x posição financeira, saldo total) viram `avisos` — nunca são "corrigidas".
"""
import re

from conciliacao.regras_gerais.modelo import ContaMes, LancamentoDespesa, LinhaReceita

_RE_SECAO = re.compile(r"^(\d)\.(\d)\s+([A-ZÀ-Ú].+)$")
_RE_CONTA_HDR = re.compile(r"^(\d{3})\s*-\s*(.+?)$")
_COL_VALOR = 470            # x0 mínimo de um valor na coluna da direita (retrato 595 pt; os valores terminam em x ≈ 550)


def _ajudantes():
    from conciliacao.regras_gerais.extratores.datadigitus import _norm, _num
    return _norm, _num


def eh_ruggiero(paginas) -> bool:
    """paginas = [(n, largura, linhas)] do extrator DataDigitus. Layout Ruggiero = tem '2.1 DEMONSTRATIVO DE DESPESAS' e '5.4 RESUMO FINANCEIRO'
    e NÃO tem o 'Resumo Financeiro Contábil' do balancete consolidado."""
    _norm, _ = _ajudantes()
    secoes, contabil = set(), False
    for _pag, _W, linhas in paginas:
        for l in linhas[:10]:
            tn = _norm(l["texto"])
            m = _RE_SECAO.match(l["texto"].strip())
            if m:
                secoes.add(f"{m.group(1)}.{m.group(2)}")
            if tn.startswith("RESUMO FINANCEIRO CONTABIL"):
                contabil = True
    return {"2.1", "5.4"} <= secoes and not contabil


def _ruido(l: dict) -> bool:
    t = l["texto"].strip()
    return bool(not t or t.startswith("PREDIAL RUGGIERO") or re.match(r"^\d{4}\s*-\s*COND", t) or _RE_SECAO.match(t)
                or set(t) <= set("¯_—+-|= ") or "Software DataDigitus" in t or re.match(r"^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}", t))


def _secao(linhas: list) -> str | None:
    for l in linhas[:10]:
        m = _RE_SECAO.match(l["texto"].strip())
        if m:
            return f"{m.group(1)}.{m.group(2)}"
    return None


def _split(l: dict, so_direita: bool = True):
    """(texto, [valores com bbox]) de uma linha: valores = palavras numéricas (na coluna da direita, se so_direita)."""
    _norm, _num = _ajudantes()
    vals = [w for w in l["w"] if _num(w[4]) is not None and (not so_direita or w[0] >= _COL_VALOR)]
    texto = " ".join(w[4] for w in l["w"] if w not in vals).strip().strip("|").strip()
    return texto, vals


def _uniao(bbs):
    return (round(min(b[0] for b in bbs), 1), round(min(b[1] for b in bbs), 1), round(max(b[2] for b in bbs), 1), round(max(b[3] for b in bbs), 1))


def ler(paginas) -> dict:
    """Devolve {'contas': [ContaMes], 'lancamentos': [LancamentoDespesa], 'totais_conta': [(conta, valor, pagina)], 'receitas': [LinhaReceita],
    'saldo_total': float|None, 'avisos': [str]}."""
    _norm, _num = _ajudantes()
    out = {"contas": [], "lancamentos": [], "totais_conta": [], "receitas": [], "saldo_total": None, "avisos": []}
    br = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # ── 2.1 Demonstrativo de Despesas ───────────────────────────────────────
    conta, grupo, pend = None, None, []
    soma_grupo = soma_conta = 0.0
    n_grupo = 0
    for pag, W, linhas in paginas:
        if _secao(linhas) != "2.1":
            continue
        for l in linhas:
            if _ruido(l):
                continue
            texto, vals = _split(l)
            tn = _norm(texto)
            m = _RE_CONTA_HDR.match(texto)
            if m and not vals and not pend:
                if conta != m.group(2).strip():
                    conta, grupo, soma_conta = m.group(2).strip(), None, 0.0
                continue
            if tn.startswith("TOTAL DA CONTA") and vals:
                decl = _num(vals[-1][4])
                out["totais_conta"].append((conta, decl, pag))
                if abs(round(soma_conta, 2) - decl) > 0.011:
                    out["avisos"].append(f"Demonstrativo de Despesas da conta {conta}: a soma dos lançamentos ({br(soma_conta)}) não fecha com o total declarado ({br(decl)})")
                grupo, pend, soma_grupo, n_grupo = None, [], 0.0, 0
                continue
            if vals and not texto:                       # subtotal do grupo (só o valor)
                decl = _num(vals[-1][4])
                if grupo and abs(round(soma_grupo, 2) - decl) > 0.011:
                    out["avisos"].append(f"Demonstrativo de Despesas, grupo {grupo}: a soma dos lançamentos ({br(soma_grupo)}) não fecha com o subtotal declarado ({br(decl)})")
                grupo, pend, soma_grupo, n_grupo = None, [], 0.0, 0
                continue
            if vals:                                      # lançamento (a 2ª linha do histórico traz o valor)
                valor = _num(vals[-1][4])
                desc = " ".join([t for t, _ in pend] + [texto]).strip()
                bbs = [b for _, b in pend] + [l["bbox"]]
                out["lancamentos"].append(LancamentoDespesa(descricao=desc, valor=valor, categoria=grupo or "SEM GRUPO", conta=conta or "", pagina=pag, bbox=_uniao(bbs)))
                soma_grupo += valor
                soma_conta += valor
                n_grupo += 1
                pend = []
                continue
            if grupo is None:                             # linha sem valor logo após o subtotal/cabeçalho da conta = cabeçalho de grupo
                grupo = texto
            else:                                         # 1ª linha de um histórico quebrado em 2
                pend.append((texto, l["bbox"]))

    # ── 4.1 Demonstrativo Financeiro: receitas por conta (Posição Financeira) ─
    conta, em_pos = None, False
    for pag, W, linhas in paginas:
        if _secao(linhas) != "4.1":
            continue
        for l in linhas:
            if _ruido(l):
                continue
            texto, vals = _split(l)
            tn = _norm(texto)
            m = _RE_CONTA_HDR.match(texto)
            if m and not vals:
                conta, em_pos = m.group(2).strip(), False
                continue
            if tn.startswith("POSICAO FINANCEIRA"):
                em_pos = True
                continue
            if not em_pos or conta is None or not vals:
                continue
            if tn.startswith("SALDO ATUAL"):
                em_pos = False
                continue
            if tn.startswith(("SALDO ANTERIOR", "DESPESAS DO PERIODO", "RECEITA REALIZADA")):
                continue
            if tn.startswith(("DA EMISSAO", "DE CONDOMINOS", "ANTECIPACO")):
                tipo = "cota"
            elif re.match(r"^(MULTAS?|JUROS)", tn):
                tipo = "multa_juros"
            elif tn.startswith("OUTRAS RECEITAS") and "APLICA" in _norm(conta):
                tipo = "rendimento"
            else:
                tipo = "outra"
            out["receitas"].append(LinhaReceita(conta=conta, descricao=texto, valor=_num(vals[-1][4]), tipo=tipo, pagina=pag, bbox=tuple(round(x, 1) for x in l["bbox"])))

    # ── 5.4 Resumo Financeiro: quadros por conta ─────────────────────────────
    cur = None
    for pag, W, linhas in paginas:
        if _secao(linhas) != "5.4":
            continue
        for l in linhas:
            if _ruido(l):
                continue
            texto, vals = _split(l, so_direita=False)
            tn = _norm(texto)
            nums = [_num(w[4]) for w in vals]
            m = _RE_CONTA_HDR.match(texto)
            if m and not vals:
                cur = {"nome": m.group(2).strip(), "ant": 0.0, "cred": 0.0, "desp": 0.0, "pag": pag}
                continue
            if tn.startswith("SALDO ATUAL") and cur is None and nums:       # "SALDO ATUAL  406.678,49" (total geral, fora dos quadros)
                out["saldo_total"] = nums[-1]
                continue
            if cur is None or not nums:
                continue
            if tn.startswith("SALDO ANTERIOR"):
                cur["ant"] = nums[0]
            elif tn.startswith(("DA EMISSAO", "DE CONDOMINOS", "ANTECIPACO", "MULTA", "JUROS", "OUTRAS RECEITAS")):
                cur["cred"] += nums[0]
            elif tn.startswith("DESPESAS DO PERIODO"):
                cur["desp"] = abs(nums[0])
            elif tn.startswith("SALDO ATUAL"):
                c = ContaMes(nome=cur["nome"], saldo_anterior=cur["ant"], creditos=round(cur["cred"], 2), debitos=round(cur["desp"], 2), saldo_atual=nums[0], pagina=cur["pag"])
                esperado = round(c.saldo_anterior + c.creditos - c.debitos, 2)
                if abs(esperado - c.saldo_atual) > 0.011:
                    out["avisos"].append(f"Resumo Financeiro da conta {c.nome}: saldo anterior ({br(c.saldo_anterior)}) + créditos ({br(c.creditos)}) - débitos ({br(c.debitos)}) "
                                         f"= {br(esperado)}, mas o saldo atual impresso é {br(c.saldo_atual)}")
                out["contas"].append(c)
                cur = None
    if out["saldo_total"] is not None and out["contas"]:
        soma = round(sum(c.saldo_atual for c in out["contas"]), 2)
        if abs(soma - out["saldo_total"]) > 0.011:
            out["avisos"].append(f"Resumo Financeiro: a soma dos saldos atuais das contas ({br(soma)}) não fecha com o SALDO ATUAL total impresso ({br(out['saldo_total'])})")
    return out
