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
    if d.get("motivo") == "sem_rendimento_consolidado":
        com = d.get("contas_com_rendimento") or []
        sem = d.get("contas_sem_rendimento") or []
        onde = ", ".join(f"{x['nome']} (saldo médio {_moeda(x['saldo_medio'])})" for x in com)
        sem_txt = "; ".join(f"{x['nome']} (saldo médio {_moeda(x['saldo_medio'])})" for x in sem)
        negativa = any((x.get("saldo_medio") or 0) < 0 for x in com)
        total = d.get("rendimento_total_mes") or 0.0
        pos = [x for x in sem if (x.get("saldo_medio") or 0) > 0]
        soma_pos = sum(x["saldo_medio"] for x in pos)
        rateio = "; ".join(f"{x['nome']} {_moeda(round(total * x['saldo_medio'] / soma_pos, 2))}" for x in pos) if soma_pos > 0 else ""
        titulo = f"Rendimento creditado na conta {com[0]['nome'] if com else conta}, que está com saldo negativo; contas com saldo positivo sem rendimento ({_moeda(total)} no mês)"
        paragrafo = (f"O rendimento do mês ({_moeda(total)}) foi creditado somente em: {onde}. "
                     + ("Essa conta está com saldo NEGATIVO — não tem dinheiro próprio aplicado: suas despesas estão sendo pagas com o caixa das demais contas. " if negativa else "")
                     + f"Contas com saldo positivo e sem nenhum rendimento: {sem_txt}. O rendimento das aplicações deve ser distribuído entre as "
                     f"contas na proporção do saldo de cada uma."
                     + (f" Referência: pela proporção do saldo médio das contas com saldo positivo, o rateio de {_moeda(total)} seria de aproximadamente {rateio} "
                        f"(estimativa; depende de em qual conta bancária o dinheiro estava aplicado)." if rateio else ""))
        verificar = ("Perguntar à administradora se o rendimento deve ser creditado na conta "
                     f"{com[0]['nome'] if com else conta} (negativa) ou lançado nas contas com saldo positivo (Fundo de Reserva e demais), solicitar o extrato "
                     "da aplicação para confirmar em qual conta bancária o rendimento foi gerado e se o saldo negativo representa empréstimo do Fundo de Reserva "
                     "(e se foi aprovado em assembleia).")
        return titulo, paragrafo, verificar
    if d.get("motivo") == "sem_rendimento":
        titulo = f"Rendimento não creditado — {conta}"
        esp = f" (pela proporção das demais contas, cerca de {_moeda(a.valor_esperado)})" if a.valor_esperado else ""
        if d.get("exigida_por") == "configuracao" and d.get("contas_com_rendimento"):
            onde = ", ".join(d["contas_com_rendimento"])
            paragrafo = (f"A conta {conta} tem saldo no mês, mas não recebeu nenhum rendimento{esp}. O rendimento do mês "
                         f"({_moeda(d.get('rendimento_total_mes'))}) foi creditado apenas em: {onde}. O rendimento das "
                         f"aplicações deve ser distribuído entre as contas na proporção do saldo de cada uma.")
        else:
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


def texto_compensacao(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    grupo = d.get("grupo") or "grupo"
    g = grupo.lower()
    sit = d.get("situacao", "liquido")
    if sit == "sem_lancamentos":
        titulo = f"{grupo}: nenhum lançamento encontrado neste mês"
        paragrafo = (f"Todo mês o {g} deve ter uma entrada (receita) e uma saída (desconto/abatimento) que se anulam. "
                     f"Neste mês não foi encontrado nenhum lançamento de {g} nas receitas.")
        verificar = f"Perguntar à administradora se o {g} deixou de ser lançado neste mês e por quê."
    elif sit == "sem_saida":
        titulo = f"{grupo}: entrada sem a saída correspondente ({_moeda(d.get('entrada'))})"
        paragrafo = (f"O {g} teve entrada de {_moeda(d.get('entrada'))} neste mês, mas nenhuma saída (desconto/abatimento) "
                     f"para compensá-la; todo mês entrada e saída do {g} se anulam.")
        verificar = f"Perguntar à administradora onde está a saída (desconto) correspondente à entrada do {g}."
    elif sit == "sem_entrada":
        titulo = f"{grupo}: saída sem a entrada correspondente ({_moeda(d.get('saida'))})"
        paragrafo = (f"O {g} teve saída de {_moeda(d.get('saida'))} neste mês (desconto/abatimento lançado como receita "
                     f"negativa), mas nenhuma entrada de locação para compensá-la.")
        verificar = f"Perguntar à administradora onde está a entrada (receita) correspondente à saída do {g}."
    else:
        titulo = f"{grupo}: entrada e saída não se anulam no mês (líquido {_moeda(d.get('liquido'))})"
        paragrafo = (f"No mês, as receitas de {g} somam entradas de {_moeda(d.get('entrada'))} e saídas "
                     f"(descontos/abatimentos lançados como receita negativa) de {_moeda(d.get('saida'))}, em "
                     f"{d.get('quantidade')} lançamentos; o líquido de {_moeda(d.get('liquido'))} deveria ser zero.")
        verificar = (f"Perguntar à administradora a que se referem os abatimentos e as diferenças que fazem a entrada e a saída de "
                     f"{g} não fecharem.")
    return titulo, paragrafo, verificar


def texto_previsto_realizado(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    prev, real, pct = d.get("previsto"), d.get("realizado"), d.get("pct")
    titulo = (f"Previsto x Realizado fora do padrão dos meses anteriores — previsto {_moeda(prev)}"
              + (f", realizado {_moeda(real)} ({_pct(pct / 100)})" if pct is not None else ""))
    partes = [f"No Resumo de Emissão deste mês o previsto é {_moeda(prev)} e o realizado {_moeda(real)}"
              + (f" ({str(pct).replace('.', ',')}% do previsto)" if pct is not None else "")
              + f"; a mediana do previsto nos {d.get('meses_comparados')} meses anteriores é {_moeda(d.get('mediana_previsto'))}"
              + (f" (arrecadação típica de {str(d.get('mediana_pct')).replace('.', ',')}%)." if d.get("mediana_pct") is not None else ".")]
    for x in d.get("linhas_ausentes") or []:
        partes.append(f"A linha \"{x['descricao']}\", que aparece em todos os meses anteriores (previsto típico "
                      f"{_moeda(x['mediana_previsto'])}), não consta na tabela deste mês.")
    dp = d.get("difere_posicao")
    if dp:
        partes.append(f"A Posição Financeira da conta registra crédito de {_moeda(dp['posicao'])} em \"EMISSÃO DO PERÍODO\", "
                      f"mas a tabela Previsto x Realizado traz {_moeda(dp['tabela'])} nessa linha — as duas partes do mesmo "
                      f"balancete não conferem.")
    verificar = ("Pedir à administradora o Resumo de Emissão completo deste mês (emissão do período, reembolsos e diversos) e "
                 "a explicação da diferença; enquanto isso, o percentual de arrecadação apresentado no balancete não é confiável.")
    return titulo, " ".join(partes), verificar


def texto_variacao_categoria(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    cat = d.get("categoria") or a.linha_demonstrativo or "categoria"
    pct = str(abs(d.get("variacao_pct") or 0)).replace(".", ",")
    sentido = "subiu" if (d.get("variacao_pct") or 0) > 0 else "caiu"
    itens = d.get("lancamentos") or []
    lista = "; ".join(f"{i.get('descricao') or 'lançamento'} ({_moeda(i.get('valor'))})" for i in itens[:4])
    titulo = f"Despesa da categoria {cat} {sentido} {pct}% em relação ao mês anterior ({_moeda(d.get('mes_anterior'))} → {_moeda(d.get('mes_atual'))})"
    paragrafo = (f"O total de \"{cat}\" foi {_moeda(d.get('mes_atual'))} neste mês contra {_moeda(d.get('mes_anterior'))} no mês anterior "
                 f"({sentido} {pct}%). Maiores lançamentos do mês na categoria: {lista}.")
    verificar = ("Conferir se os lançamentos são despesas do mês (manutenção) ou investimento/aquisição que deveria ter outra classificação, "
                 "se há aprovação para os valores mais altos e se há notas fiscais e comprovantes de todos.")
    return titulo, paragrafo, verificar


def texto_nf_repetida(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    ant = "; ".join(f"{x['mes']} ({_moeda(x['valor'])})" for x in d.get("anteriores", []))
    titulo = f"Mesma Nota Fiscal paga em meses diferentes — NF {d.get('nf')} ({_moeda(d.get('valor'))})"
    paragrafo = (f"O lançamento \"{d.get('descricao')}\" ({_moeda(d.get('valor'))}, {d.get('data') or 'sem data'}) cita a NF {d.get('nf')}, "
                 f"que já aparece paga do mesmo fornecedor em: {ant}. Pode ser pagamento em duplicidade, parcela não identificada ou reaproveitamento "
                 f"do número da nota.")
    verificar = ("Pedir à administradora as notas fiscais e comprovantes dos dois pagamentos e confirmar se são parcelas distintas; se for duplicidade, "
                 "solicitar a devolução/estorno.")
    return titulo, paragrafo, verificar


def texto_cobranca(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    arrec = str(d.get("arrecadacao_pct")).replace(".", ",")
    inad = str(d.get("inadimplencia_pct_da_emissao")).replace(".", ",")
    ant = d.get("arrecadacao_pct_mes_anterior")
    titulo = (f"Arrecadação de {arrec}% da emissão do mês e inadimplência de {_moeda(d.get('inadimplencia_total'))} ({inad}% da emissão mensal)")
    paragrafo = (f"Da emissão do período ({_moeda(d.get('emissao_prevista'))}) foram arrecadados {_moeda(d.get('emissao_realizada'))} ({arrec}%"
                 + (f"; no mês anterior, {str(ant).replace('.', ',')}%" if ant is not None else "")
                 + f"). A inadimplência total em aberto no fim do mês é de {_moeda(d.get('inadimplencia_total'))}, equivalente a {inad}% da emissão mensal; "
                 f"no mês foram recebidos {_moeda(d.get('recebidos_em_atraso'))} de cotas em atraso. Parâmetros do alerta: arrecadação abaixo de "
                 f"{str(d.get('arrecadacao_min_pct')).replace('.', ',')}% ou inadimplência acima de {str(d.get('inad_vs_emissao_pct')).replace('.', ',')}% da emissão.")
    verificar = ("Acompanhar a cobrança com a administradora: relação das unidades inadimplentes, ações de cobrança em andamento e efeito no caixa "
                 "(a Ordinária está sendo coberta por outras contas).")
    return titulo, paragrafo, verificar


def texto_saldo_negativo(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    conta = d.get("conta") or a.linha_demonstrativo or "conta"
    n = d.get("meses_seguidos")
    mais = "pelo menos " if n >= (d.get("meses_lidos") or 0) else ""
    titulo = f"Conta {conta} com saldo negativo há {mais}{n} meses seguidos ({_moeda(d.get('saldo_atual'))})"
    paragrafo = (f"A conta {conta} fechou o mês com saldo de {_moeda(d.get('saldo_atual'))} (anterior: {_moeda(d.get('saldo_anterior'))}) e está negativa "
                 f"{mais}{n} meses seguidos nos balancetes lidos. Saldo negativo significa despesas pagas com o caixa de outras contas.")
    verificar = ("Perguntar à administradora de onde vem o dinheiro que cobre o saldo negativo, se houve aprovação em assembleia para esse uso dos fundos "
                 "e qual o plano de recomposição.")
    return titulo, paragrafo, verificar


TEXTOS = {
    "nf_repetida_entre_meses": texto_nf_repetida,
    "inadimplencia_arrecadacao": texto_cobranca,
    "saldo_negativo_persistente": texto_saldo_negativo,
    "variacao_categoria": texto_variacao_categoria,
    "previsto_realizado_inconsistente": texto_previsto_realizado,
    "receita_negativa": texto_receita_negativa,
    "rendimento_desproporcional": texto_rendimento,
    "pagamento_sem_identificacao": texto_sem_identificacao,
    "parcelas_mesmo_mes": texto_parcelas,
    "lancamento_em_outra_subconta": texto_outra_subconta,
    "compensacao_nao_fecha": texto_compensacao,
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
