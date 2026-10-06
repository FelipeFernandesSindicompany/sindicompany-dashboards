"""
Camada de "Análise Financeira do Balancete" — resumo executivo, situação por
conta, previsto x realizado, despesas por categoria e inadimplência, no
mesmo formato do documento de referência fornecido pelo usuário
(Análise_Balancete_Sublime_Vila_Prudente_Ago2026.pdf).

Diferença deliberada em relação à camada de conciliação/achados
(conciliacao/matching.py, conciliacao/interpretacao.py): aqui os números já
vêm consolidados e publicados no próprio dashboard (var BAL, ver
conciliacao/bal_reader.py) — não há comprovante para cruzar, então a
narrativa é gerada por regras determinísticas (limiares claros, sempre
citando o número que motivou a frase), sem precisar de uma revisão humana/IA
por mês como a camada de achados exige. Nenhuma frase aqui deve aparecer sem
um valor real por trás.
"""

LIMIAR_DESPESA_CONCENTRADA_PCT = 40.0   # a partir daqui, vira ponto de atenção
LIMIAR_ARRECADACAO_BAIXA_PCT = 90.0      # realizado/previsto abaixo disso, vira ponto de atenção


def _fmt_r(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(v: float) -> str:
    return f"{v:,.1f}%".replace(".", ",")


def _fmt_pct_arrecadacao(v: float) -> str:
    """
    2 casas decimais (não 1, como _fmt_pct) — confirmado em dados reais
    (Club Park Butantã, ago/2026) que um déficit real de arrecadação pode
    ficar tão perto de 100% (ex.: 99,9516%) que 1 casa decimal arredonda pra
    "100,0%", escondendo que o previsto não foi batido.
    """
    return f"{v:,.2f}%".replace(".", ",")


def montar_analise(bal_atual: dict, bal_anterior: dict | None, mes_titulo: str) -> dict:
    saldo_atual = bal_atual["tAtual"]
    saldo_anterior_mes = bal_anterior["tAtual"] if bal_anterior else None
    variacao_saldo = (saldo_atual - saldo_anterior_mes) if saldo_anterior_mes is not None else None

    contas = []
    for c in bal_atual.get("contas", []):
        contas.append({
            "nome": c["n"],
            "saldo_anterior": c["a"],
            "creditos": c["c"],
            "debitos": c["d"],
            "saldo_atual": c["s"],
            "saldo_anterior_fmt": _fmt_r(c["a"]),
            "creditos_fmt": _fmt_r(c["c"]),
            "debitos_fmt": _fmt_r(c["d"]),
            "saldo_atual_fmt": _fmt_r(c["s"]),
            "deficitaria": c["s"] < 0,
        })
    contas_deficitarias = [c for c in contas if c["deficitaria"]]

    soma_debitos_contas = sum(c["debitos"] for c in contas)

    despesas_total = sum(d["v"] for d in bal_atual.get("desp", []))
    despesas = sorted(
        [
            {
                "categoria": d["c"],
                "valor": d["v"],
                "valor_fmt": _fmt_r(d["v"]),
                "pct": (d["v"] / despesas_total * 100.0) if despesas_total else 0.0,
            }
            for d in bal_atual.get("desp", [])
        ],
        key=lambda d: d["valor"], reverse=True,
    )
    for d in despesas:
        d["pct_fmt"] = _fmt_pct(d["pct"])
    maior_despesa = despesas[0] if despesas else None

    # Confirmado em dados reais (Club Park Butantã, ago/2026 — nota de
    # rodapé do próprio demonstrativo GCONT: "Inclui transferência entre
    # contas."): a coluna "Débitos" de cada conta soma TUDO que saiu dela,
    # inclusive repasses pra OUTRA conta do mesmo condomínio (ex.: Ordinária
    # → Fundo de Reserva) — que não é despesa, é só uma movimentação
    # interna. Por isso a soma dos débitos pode ficar MAIOR que o total de
    # "Despesas por Categoria" (que só soma despesa de verdade, com
    # terceiros). Só mostra a nota quando a diferença é real (>R$1,00).
    # Só afirma a causa (transferência entre contas) quando o próprio PDF do
    # condomínio traz essa nota (bal_atual["debitos_incluem_transferencias"],
    # ver demonstrativo_reader.py) — em outros formatos a diferença pode ter
    # outra origem e a nota seria uma afirmação sem base.
    diferenca_debitos_despesas = round(soma_debitos_contas - despesas_total, 2)
    nota_transferencia_entre_contas = (
        diferenca_debitos_despesas
        if abs(diferenca_debitos_despesas) > 1.0 and bal_atual.get("debitos_incluem_transferencias")
        else None
    )

    previsto = bal_atual.get("prev", 0.0)
    realizado = bal_atual.get("real", 0.0)
    # Confirmado em dados reais (Central das Artes, agosto/2026 — upload
    # parcial só com a listagem de despesas, sem a seção "Resumo de
    # Emissões"): quando o adapter não encontra o previsto de verdade no
    # arquivo, ele cai num fallback "previsto = realizado" pra nunca devolver
    # um campo vazio — isso finge 100% de arrecadação, que é enganoso, não
    # um dado real. 100% de arrecadação batendo exatamente ao centavo é
    # praticamente impossível na prática — previsto==realizado é o sinal
    # confiável desse fallback, não de uma coincidência genuína.
    previsto_confiavel = previsto > 0 and previsto != realizado
    realizado_pct = (realizado / previsto * 100.0) if previsto_confiavel else None

    # bal_atual["inad"] vem None (não 0.0) quando conciliacao/demonstrativo_
    # reader.py::ler_dados_arquivo() não achou nenhuma seção de
    # inadimplência/devedores no arquivo — distingue de "genuinamente zero
    # inadimplência este mês", que também é um valor real e válido.
    inad_disponivel = bal_atual.get("inad") is not None
    inad_atual = bal_atual.get("inad") or 0.0
    inad_proc = bal_atual.get("inadProc", 0.0)
    inad_anterior = bal_anterior.get("inad") if (bal_anterior and inad_disponivel) else None
    inad_variacao = (inad_atual - inad_anterior) if inad_anterior is not None else None

    # ── Pontos de atenção (regras determinísticas, cada uma citando um número real) ──
    pontos_atencao = []
    for c in contas_deficitarias:
        pontos_atencao.append(
            f"Conta {c['nome'].title()} encerrou o mês com saldo devedor de {c['saldo_atual_fmt']} "
            f"— avaliar em assembleia reforço de caixa ou remanejamento formal de reserva."
        )
    if maior_despesa and maior_despesa["pct"] >= LIMIAR_DESPESA_CONCENTRADA_PCT:
        pontos_atencao.append(
            f"A categoria \"{maior_despesa['categoria']}\" concentra {maior_despesa['pct_fmt']} da "
            f"despesa do mês ({maior_despesa['valor_fmt']}) — acompanhar contratos e eventuais "
            f"reajustes/renegociações."
        )
    if realizado_pct is not None and realizado_pct < LIMIAR_ARRECADACAO_BAIXA_PCT:
        pontos_atencao.append(
            f"Arrecadação do mês ficou em {_fmt_pct_arrecadacao(realizado_pct)} do previsto "
            f"({_fmt_r(realizado)} de {_fmt_r(previsto)} orçados) — investigar causa da diferença."
        )
    if inad_variacao is not None and inad_variacao > 0:
        pontos_atencao.append(
            f"Inadimplência total subiu {_fmt_r(inad_variacao)} em relação ao mês anterior "
            f"({_fmt_r(inad_atual)} vs. {_fmt_r(inad_anterior)}) — priorizar ações de cobrança."
        )

    # ── Resumo executivo (prosa determinística, sempre ancorada em número real) ──
    frases = [f"O saldo consolidado do condomínio encerrou {mes_titulo.lower()} em {_fmt_r(saldo_atual)}"]
    if variacao_saldo is not None:
        direcao = "alta" if variacao_saldo >= 0 else "queda"
        frases[0] += (
            f", {'alta' if variacao_saldo >= 0 else 'queda'} de {_fmt_r(abs(variacao_saldo))} "
            f"em relação ao mês anterior ({_fmt_r(saldo_anterior_mes)})."
        )
    else:
        frases[0] += "."
    if contas_deficitarias:
        nomes = ", ".join(c["nome"].title() for c in contas_deficitarias)
        frases.append(f"A(s) conta(s) {nomes} encerrou(aram) o mês com saldo devedor, exigindo atenção.")
    else:
        frases.append("Nenhuma conta encerrou o mês com saldo devedor.")
    if realizado_pct is not None:
        if realizado_pct >= 100.0:
            frases.append(
                f"A arrecadação do mês superou o previsto ({_fmt_pct_arrecadacao(realizado_pct)} do orçado)."
            )
        else:
            frases.append(
                f"A arrecadação do mês ficou em {_fmt_pct_arrecadacao(realizado_pct)} do previsto."
            )
    if inad_variacao is not None:
        if inad_variacao < 0:
            frases.append(
                f"A inadimplência total recuou {_fmt_r(abs(inad_variacao))} em relação ao mês "
                f"anterior, para {_fmt_r(inad_atual)}."
            )
        elif inad_variacao > 0:
            frases.append(
                f"A inadimplência total subiu {_fmt_r(inad_variacao)} em relação ao mês anterior, "
                f"para {_fmt_r(inad_atual)}."
            )
    resumo_executivo = " ".join(frases)

    conclusao = (
        f"{mes_titulo} encerrou com saldo geral de {_fmt_r(saldo_atual)}"
        + (
            f", sem contas devedoras."
            if not contas_deficitarias
            else f", com {len(contas_deficitarias)} conta(s) devedora(s) que merecem acompanhamento."
        )
    )
    if inad_disponivel:
        conclusao += f" A inadimplência total é de {_fmt_r(inad_atual)}"
        # Mesma convenção já usada no dashboard publicado (ver "m.inadProc > 0
        # ? R(m.inadProc) : '-'" em docs/Dashboard_Financeiro_*.html): inadProc
        # não é extraído por todos os formatos de adapter (ex.: GCONT/Club Park
        # Butantã nunca popula inadimplencia_recebida, só fica no default
        # 0.0 do dataclass) — tratar como "zero recuperado" seria inventar um
        # dado que nunca foi confirmado, não um fato real sobre o mês.
        if inad_proc > 0:
            conclusao += f", dos quais {_fmt_r(inad_proc)} foram recuperados no próprio mês."
        else:
            conclusao += "."

    return {
        "saldo_atual": saldo_atual,
        "saldo_atual_fmt": _fmt_r(saldo_atual),
        "saldo_anterior_fmt": _fmt_r(saldo_anterior_mes) if saldo_anterior_mes is not None else None,
        "variacao_saldo_fmt": _fmt_r(variacao_saldo) if variacao_saldo is not None else None,
        "variacao_saldo_positiva": (variacao_saldo is not None and variacao_saldo >= 0),
        "contas": contas,
        "contas_deficitarias": contas_deficitarias,
        "despesas": despesas,
        "despesas_total": despesas_total,
        "despesas_total_fmt": _fmt_r(despesas_total),
        "soma_debitos_contas_fmt": _fmt_r(soma_debitos_contas),
        "nota_transferencia_entre_contas_fmt": (
            _fmt_r(nota_transferencia_entre_contas) if nota_transferencia_entre_contas is not None else None
        ),
        "previsto_fmt": _fmt_r(previsto) if previsto_confiavel else None,
        "realizado_fmt": _fmt_r(realizado) if previsto_confiavel else None,
        "realizado_pct_fmt": _fmt_pct_arrecadacao(realizado_pct) if realizado_pct is not None else None,
        "realizado_pct_ok": (realizado_pct is not None and realizado_pct >= 100.0),
        "inad_disponivel": inad_disponivel,
        "inad_atual_fmt": _fmt_r(inad_atual) if inad_disponivel else None,
        "inad_proc_fmt": _fmt_r(inad_proc) if (inad_disponivel and inad_proc > 0) else None,
        "inad_anterior_fmt": _fmt_r(inad_anterior) if inad_anterior is not None else None,
        "banco": bal_atual.get("banco", {}),
        "pontos_atencao": pontos_atencao,
        "resumo_executivo": resumo_executivo,
        "conclusao": conclusao,
    }
