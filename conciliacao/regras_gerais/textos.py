"""
Narrativa (título, parágrafo, "o que verificar") dos achados das regras gerais.

Estilo definido pelo usuário nos relatórios do Club Park: dizer o fato com os números e
perguntar à administradora — nunca afirmar uma causa que o arquivo não mostra.
"""
from conciliacao.base import Achado


def _moeda(v) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {s}" if v < 0 else f"R$ {s}"


def _pct(v) -> str:
    return f"{v * 100:.2f}".replace(".", ",") + "%"


def texto_receita_negativa(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    conta = d.get("conta") or "conta não identificada"
    desc = d.get("descricao") or "lançamento de receita"
    quando = f" em {d['data']}" if d.get("data") else ""
    n = d.get("quantidade", 1)
    if n > 1:
        titulo = f"Receita com valor negativo — {conta}: {desc} ({n} lançamentos, {_moeda(a.valor_encontrado)})"
        paragrafo = (f"A receita \"{desc}\", na conta {conta}, aparece com valor negativo em {n} lançamentos "
                     f"neste mês, somando {_moeda(a.valor_encontrado)}. Receita negativa reduz a arrecadação do "
                     f"mês e normalmente indica estorno, devolução ou ajuste.")
    else:
        titulo = f"Receita com valor negativo — {conta} ({_moeda(a.valor_encontrado)})"
        paragrafo = (f"A receita \"{desc}\"{quando}, na conta {conta}, aparece com valor negativo "
                     f"({_moeda(a.valor_encontrado)}). Receita negativa reduz a arrecadação do mês e normalmente "
                     f"indica estorno, devolução ou ajuste.")
    verificar = ("Perguntar à administradora o que originou este lançamento negativo e se existe documento "
                 "(estorno de boleto, devolução, correção) que o sustente.")
    return titulo, paragrafo, verificar


def texto_rendimento(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    conta = d.get("conta") or a.linha_demonstrativo or "conta"
    mediana = d.get("taxa_mediana")
    if d.get("motivo") == "sem_rendimento":
        titulo = f"Rendimento não creditado — {conta}"
        esp = f" (pela proporção das demais contas, cerca de {_moeda(a.valor_esperado)})" if a.valor_esperado else ""
        paragrafo = (f"A conta {conta} tem saldo no mês, e tinha rendimento no mês anterior, mas não recebeu "
                     f"nenhum rendimento neste mês{esp}.")
        verificar = ("Perguntar à administradora se o saldo desta conta permaneceu aplicado e por que o "
                     "rendimento do mês não foi creditado nela.")
        return titulo, paragrafo, verificar
    taxa = d.get("taxa_conta")
    titulo = f"Rendimento fora da proporção do saldo — {conta} ({_moeda(a.valor_encontrado)})"
    paragrafo = (f"O rendimento creditado na conta {conta} foi {_moeda(a.valor_encontrado)}"
                 + (f", equivalente a {_pct(taxa)} do saldo médio da conta" if taxa else "")
                 + (f", enquanto as demais contas renderam em torno de {_pct(mediana)}" if mediana else "")
                 + (f". Pela proporção do saldo, o esperado seria cerca de {_moeda(a.valor_esperado)}." if a.valor_esperado else "."))
    verificar = ("Perguntar à administradora como o rendimento da aplicação foi rateado entre as contas e se "
                 "o valor creditado nesta conta está correto.")
    return titulo, paragrafo, verificar


def texto_sem_identificacao(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    desc = d.get("descricao") or "(sem histórico)"
    cod = f" (lançamento {d['codigo']})" if d.get("codigo") else ""
    quando = f" em {d['data']}" if d.get("data") else ""
    titulo = f"Pagamento sem identificação — {_moeda(a.valor_encontrado)}"
    paragrafo = (f"O lançamento{cod}{quando}, categoria \"{d.get('categoria') or 'não informada'}\", no valor de "
                 f"{_moeda(a.valor_encontrado)}, não identifica a quem foi pago: histórico \"{desc}\".")
    verificar = "Solicitar à administradora o favorecido, o motivo do pagamento e o comprovante deste lançamento."
    return titulo, paragrafo, verificar


def texto_parcelas(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    quem = d.get("fornecedor_ou_despesa") or "mesma despesa"
    parcelas = d.get("parcelas") or []
    nums = ", ".join(f"{p['n']}/{d.get('total_parcelas')}" for p in parcelas)
    valores = "; ".join(f"parcela {p['n']}: {_moeda(p['valor'])}" + (f" em {p['data']}" if p.get("data") else "")
                        for p in parcelas)
    titulo = f"Duas parcelas pagas no mesmo mês — {quem}"
    paragrafo = (f"No mesmo mês foram pagas as parcelas {nums} de \"{quem}\" ({valores}); "
                 f"total de {_moeda(a.valor_encontrado)} no mês.")
    nfs = sorted({p.get("nf") for p in parcelas if p.get("nf")})
    if len(nfs) > 1:
        paragrafo += (f" As parcelas citam notas fiscais diferentes (NF {', '.join(nfs)}), o que pode indicar "
                      f"contratos ou serviços distintos com o mesmo fornecedor.")
    verificar = "Perguntar à administradora por que mais de uma parcela da mesma série foi paga no mesmo mês."
    return titulo, paragrafo, verificar


def texto_outra_subconta(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    if d.get("reclassificacao_em_massa"):
        n = d.get("quantidade", 0)
        exemplos = "; ".join(f"{t['despesa']} ({_moeda(t['valor'])}): de \"{', '.join(t['de'])}\" para \"{t['para']}\""
                             for t in d.get("trocas", [])[:5])
        titulo = f"{n} despesas mudaram de subconta em relação aos meses anteriores ({_moeda(a.valor_encontrado)})"
        paragrafo = (f"Neste mês {n} despesas/fornecedores que estavam em uma subconta nos meses anteriores aparecem em outra, "
                     f"somando {_moeda(a.valor_encontrado)}. Maiores casos: {exemplos}. Tantas mudanças de uma vez costumam indicar "
                     f"reclassificação em massa feita pela administradora.")
        return titulo, paragrafo, "Perguntar à administradora o motivo da reclassificação e se as despesas foram remapeadas de forma consistente entre as subcontas."

    despesa = d.get("despesa") or "despesa"
    antes = ", ".join(f"\"{c}\"" for c in d.get("categorias_mes_anterior", [])) or "outra subconta"
    atual = d.get("categoria_atual") or a.linha_demonstrativo
    nova = " (subconta que não existia no mês anterior)" if d.get("categoria_nova") else ""
    n = len(d.get("lancamentos", []))
    titulo = f"Lançamento em subconta diferente do mês anterior — {despesa} ({_moeda(a.valor_encontrado)})"
    paragrafo = (f"{'O lançamento' if n == 1 else f'Os {n} lançamentos'} de \"{despesa}\" ({_moeda(a.valor_encontrado)}) "
                 f"aparece{'m' if n > 1 else ''} neste mês na subconta \"{atual}\"{nova}; no mês anterior esta "
                 f"despesa estava em {antes}.")
    verificar = "Perguntar à administradora o motivo da mudança de subconta e se a nova classificação está correta."
    return titulo, paragrafo, verificar


TEXTOS = {
    "receita_negativa": texto_receita_negativa,
    "rendimento_desproporcional": texto_rendimento,
    "pagamento_sem_identificacao": texto_sem_identificacao,
    "parcelas_mesmo_mes": texto_parcelas,
    "lancamento_em_outra_subconta": texto_outra_subconta,
}


def texto_subconta_nova(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    cat = d.get("categoria") or a.linha_demonstrativo or "subconta"
    if d.get("reorganizacao"):
        cats = d.get("categorias", [])
        lista = ", ".join(cats[:12]) + (f" e mais {len(cats) - 12}" if len(cats) > 12 else "")
        titulo = f"{len(cats)} subcontas novas neste mês — possível reorganização do plano de contas ({_moeda(a.valor_encontrado)})"
        paragrafo = (f"Neste mês apareceram {len(cats)} subcontas que não existiam nos meses anteriores, somando "
                     f"{_moeda(a.valor_encontrado)}: {lista}. Tantas subcontas novas de uma vez costumam indicar que a "
                     f"administradora reorganizou o plano de contas.")
        return titulo, paragrafo, "Perguntar à administradora se o plano de contas foi alterado e como as subcontas antigas foram mapeadas para as novas."
    if d.get("so_total") and d.get("sumiu"):
        titulo = f"Subconta sem lançamentos neste mês — {cat} ({_moeda(d.get('valor_mes_anterior'))} no mês anterior)"
        paragrafo = (f"A subconta \"{cat}\" teve {_moeda(d.get('valor_mes_anterior'))} no balancete do mês anterior e não "
                     f"aparece neste mês.")
        return titulo, paragrafo, "Perguntar à administradora se a despesa foi encerrada ou se foi lançada em outra subconta."
    if d.get("so_total"):
        titulo = f"Subconta nova neste mês — {cat} ({_moeda(a.valor_encontrado)})"
        paragrafo = (f"A subconta \"{cat}\" não existia no balancete do mês anterior e aparece neste mês com "
                     f"{_moeda(a.valor_encontrado)}. Este formato de balancete informa só o total por subconta, sem listar os lançamentos.")
        return titulo, paragrafo, "Perguntar à administradora por que a subconta foi criada e o que foi lançado nela."
    itens = d.get("lancamentos", [])
    lista = "; ".join(f"{i.get('descricao') or 'lançamento'} ({_moeda(i.get('valor'))})" for i in itens[:5])
    mais = f" e mais {len(itens) - 5}" if len(itens) > 5 else ""
    titulo = f"Subconta nova neste mês — {cat} ({_moeda(a.valor_encontrado)})"
    paragrafo = (f"A subconta \"{cat}\" não existia no balancete do mês anterior e recebeu "
                 f"{len(itens)} lançamento(s) neste mês, somando {_moeda(a.valor_encontrado)}: {lista}{mais}.")
    verificar = "Perguntar à administradora por que a subconta foi criada e se os lançamentos nela estão classificados corretamente."
    return titulo, paragrafo, verificar
