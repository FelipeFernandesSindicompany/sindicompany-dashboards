"""
Narrativa (título, parágrafo, "o que verificar") dos achados das regras gerais.

Estilo definido pelo usuário nos relatórios do Club Park: dizer o fato com os números e
perguntar à administradora — nunca afirmar uma causa que o arquivo não mostra.
"""
import re

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
                     f"neste mês, somando {_moeda(a.valor_encontrado)}. Não existe receita negativa: um valor negativo é uma saída (débito, estorno ou "
                     f"devolução) e deve ser lançado como despesa/ajuste na conta correspondente, e não como receita com sinal negativo, que reduz "
                     f"a arrecadação do mês.")
    else:
        titulo = f"Receita com valor negativo — {conta} ({_moeda(a.valor_encontrado)})"
        paragrafo = (f"A receita \"{desc}\"{quando}, na conta {conta}, aparece com valor negativo "
                     f"({_moeda(a.valor_encontrado)}). Não existe receita negativa: um valor negativo é uma saída (débito, estorno ou devolução) "
                     f"e deve ser lançado como despesa/ajuste na conta correspondente, e não como receita com sinal negativo, que reduz a "
                     f"arrecadação do mês.")
    verificar = ("O que é este lançamento e por que foi lançado como receita negativa? Se for uma saída (estorno ou devolução), podem corrigir "
                 "o lançamento (despesa/estorno na conta correspondente) e enviar o documento que o sustenta?")
    return titulo, paragrafo, verificar


def texto_rendimento(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    conta = d.get("conta") or a.linha_demonstrativo or "conta"
    mediana = d.get("taxa_mediana")
    if d.get("motivo") == "sem_rendimento_consolidado":
        com = d.get("contas_com_rendimento") or []
        sem = d.get("contas_sem_rendimento") or []
        if not com:
            sem_txt = "; ".join(f"{x['nome']} (saldo médio {_moeda(x['saldo_medio'])})" for x in sem)
            if d.get("perguntar_aplicacoes"):
                return ("Nenhuma conta recebeu rendimento no mês; há aplicações financeiras?",
                        f"Nenhuma conta recebeu rendimento neste mês, embora tenham recebido em meses anteriores ou tenham saldo: {sem_txt}. "
                        + ("Conta com saldo negativo não deveria receber rendimento; o" if any((x.get("saldo_medio") or 0) < 0 for x in sem) else "O")
                        + " rendimento das aplicações deve ser creditado nas contas com saldo e distribuído na proporção do saldo de cada uma.",
                        "O condomínio possui aplicações financeiras (fundos de reserva, locação e obras)? Por que não houve rendimento em nenhuma conta neste mês? "
                        "O rendimento está sendo creditado nas contas corretas? Podem enviar o extrato das aplicações do mês?")
            return ("Nenhuma conta recebeu rendimento no mês",
                    f"Nenhuma conta recebeu rendimento neste mês, embora tenham recebido em meses anteriores ou tenham saldo: {sem_txt}. "
                    "O rendimento das aplicações deve ser distribuído entre as contas na proporção do saldo de cada uma.",
                    "As contas permaneceram aplicadas no mês? Por que não houve rendimento creditado em nenhuma delas? "
                    "Podem enviar o extrato da aplicação do mês?")
        onde = ", ".join(f"{x['nome']} (saldo médio {_moeda(x['saldo_medio'])})" for x in com)
        sem_txt = "; ".join(f"{x['nome']} (saldo médio {_moeda(x['saldo_medio'])})" for x in sem)
        negativa = any((x.get("saldo_medio") or 0) < 0 for x in com)
        total = d.get("rendimento_total_mes") or 0.0
        pos = [x for x in sem if (x.get("saldo_medio") or 0) > 0]
        soma_pos = sum(x["saldo_medio"] for x in pos)
        rateio = "; ".join(f"{x['nome']} {_moeda(round(total * x['saldo_medio'] / soma_pos, 2))}" for x in pos) if soma_pos > 0 else ""
        titulo = (f"Rendimento creditado na conta {com[0]['nome'] if com else conta}"
                  + (", que está com saldo negativo" if negativa else "")
                  + f"; contas com saldo positivo sem rendimento ({_moeda(total)} no mês)")
        paragrafo = (f"O rendimento do mês ({_moeda(total)}) foi creditado somente em: {onde}. "
                     + ("Essa conta está com saldo NEGATIVO — não tem dinheiro próprio aplicado: suas despesas estão sendo pagas com o caixa das demais contas. " if negativa else "")
                     + f"Contas com saldo positivo e sem nenhum rendimento: {sem_txt}. O rendimento das aplicações deve ser distribuído entre as "
                     f"contas na proporção do saldo de cada uma."
                     + (f" Referência: pela proporção do saldo médio das contas com saldo positivo, o rateio de {_moeda(total)} seria de aproximadamente {rateio} "
                        f"(estimativa; depende de em qual conta bancária o dinheiro estava aplicado)." if rateio else ""))
        if d.get("perguntar_aplicacoes"):
            verificar = ("O condomínio possui aplicações financeiras (fundos de reserva, locação e obras)? O rendimento está sendo creditado nas contas corretas? "
                         + (f"A conta {com[0]['nome']} está com saldo negativo e não deveria receber rendimento. " if negativa else "")
                         + "Em qual conta bancária o rendimento foi gerado e por que não foi creditado nas contas com saldo positivo "
                         "(podem enviar o extrato das aplicações do mês)?")
            return titulo, paragrafo, verificar
        verificar = ("O rendimento do mês deve ser creditado na conta "
                     f"{com[0]['nome'] if com else conta} (negativa) ou lançado nas contas com saldo positivo (Fundo de Reserva e demais)? Em qual conta bancária "
                     "o rendimento foi gerado (podem enviar o extrato da aplicação)? O saldo negativo representa empréstimo do Fundo de Reserva e foi aprovado "
                     "em assembleia?")
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
        verificar = ("O saldo desta conta permaneceu aplicado no mês? Por que o rendimento do mês não foi creditado nela?")
        return titulo, paragrafo, verificar
    taxa = d.get("taxa_conta")
    titulo = f"Rendimento fora da proporção do saldo — {conta} ({_moeda(a.valor_encontrado)})"
    paragrafo = (f"O rendimento creditado na conta {conta} foi {_moeda(a.valor_encontrado)}"
                 + (f", equivalente a {_pct(taxa)} do saldo médio da conta" if taxa else "")
                 + (f", enquanto as demais contas renderam em torno de {_pct(mediana)}" if mediana else "")
                 + (f". Pela proporção do saldo, o esperado seria cerca de {_moeda(a.valor_esperado)}." if a.valor_esperado else "."))
    verificar = ("Como o rendimento da aplicação foi rateado entre as contas? O valor creditado nesta conta está correto? "
                 "Podem explicar o critério do rateio?")
    return titulo, paragrafo, verificar


def texto_sem_identificacao(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    desc = d.get("descricao") or "(sem histórico)"
    cod = f" (lançamento {d['codigo']})" if d.get("codigo") else ""
    quando = f" em {d['data']}" if d.get("data") else ""
    titulo = f"Pagamento sem identificação — {_moeda(a.valor_encontrado)}"
    if a.regra_aplicada == "historico_marcado_como_nao_identificado":
        paragrafo = (f"O lançamento{cod}{quando}, no valor de {_moeda(a.valor_encontrado)}, foi classificado pela própria administradora na categoria "
                     f"\"{d.get('categoria') or 'não informada'}\" (histórico \"{desc}\"): o histórico pode citar um nome, mas a despesa a que o pagamento "
                     f"se refere não está identificada.")
    else:
        paragrafo = (f"O lançamento{cod}{quando}, categoria \"{d.get('categoria') or 'não informada'}\", no valor de "
                     f"{_moeda(a.valor_encontrado)}, não identifica a quem foi pago: histórico \"{desc}\".")
    verificar = "Quem é o favorecido deste pagamento e qual o motivo dele? Podem enviar o comprovante deste lançamento?"
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
    verificar = "Por que mais de uma parcela da mesma série foi paga no mesmo mês? Houve antecipação ou atraso de parcelas anteriores?"
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
        return titulo, paragrafo, "Qual o motivo da reclassificação em massa das despesas entre subcontas? As despesas foram remapeadas de forma consistente?"

    despesa = d.get("despesa") or "despesa"
    antes = ", ".join(f"\"{c}\"" for c in d.get("categorias_mes_anterior", [])) or "outra subconta"
    atual = d.get("categoria_atual") or a.linha_demonstrativo
    nova = " (subconta que não existia no mês anterior)" if d.get("categoria_nova") else ""
    n = len(d.get("lancamentos", []))
    titulo = f"Lançamento em subconta diferente do mês anterior — {despesa} ({_moeda(a.valor_encontrado)})"
    paragrafo = (f"{'O lançamento' if n == 1 else f'Os {n} lançamentos'} de \"{despesa}\" ({_moeda(a.valor_encontrado)}) "
                 f"aparece{'m' if n > 1 else ''} neste mês na subconta \"{atual}\"{nova}; no mês anterior esta "
                 f"despesa estava em {antes}.")
    verificar = "Qual o motivo da mudança de subconta desta despesa? A nova classificação está correta?"
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
        verificar = f"O {g} deixou de ser lançado neste mês? Por quê?"
    elif sit == "sem_saida":
        titulo = f"{grupo}: entrada sem a saída correspondente ({_moeda(d.get('entrada'))})"
        paragrafo = (f"O {g} teve entrada de {_moeda(d.get('entrada'))} neste mês, mas nenhuma saída (desconto/abatimento) "
                     f"para compensá-la; todo mês entrada e saída do {g} se anulam.")
        verificar = f"Onde está a saída (desconto) correspondente à entrada do {g}? Por que ela não foi lançada?"
    elif sit == "sem_entrada":
        titulo = f"{grupo}: saída sem a entrada correspondente ({_moeda(d.get('saida'))})"
        paragrafo = (f"O {g} teve saída de {_moeda(d.get('saida'))} neste mês (desconto/abatimento lançado como receita "
                     f"negativa), mas nenhuma entrada de locação para compensá-la.")
        verificar = f"Onde está a entrada (receita) correspondente à saída do {g}? Por que ela não foi lançada?"
    else:
        titulo = f"{grupo}: entrada e saída não se anulam no mês (líquido {_moeda(d.get('liquido'))})"
        paragrafo = (f"No mês, as receitas de {g} somam entradas de {_moeda(d.get('entrada'))} e saídas "
                     f"(descontos/abatimentos lançados como receita negativa) de {_moeda(d.get('saida'))}, em "
                     f"{d.get('quantidade')} lançamentos; o líquido de {_moeda(d.get('liquido'))} deveria ser zero.")
        verificar = (f"A que se referem os abatimentos e as diferenças que fazem a entrada e a saída de "
                     f"{g} não fecharem? Podem explicar?")
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
    partes.append("Enquanto não houver explicação, o percentual de arrecadação apresentado no balancete não é confiável.")
    verificar = ("Qual é o Resumo de Emissão completo deste mês (emissão do período, reembolsos e diversos) e como se explica a diferença "
                 "apontada?")
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
    verificar = ("Os lançamentos dessa categoria são despesas do mês (manutenção) ou investimento/aquisição que deveria ter outra classificação? "
                 "Houve aprovação para os valores mais altos e existem notas fiscais e comprovantes de todos?")
    return titulo, paragrafo, verificar


def texto_nf_repetida(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    ant = "; ".join(f"{x['mes']} ({_moeda(x['valor'])})" for x in d.get("anteriores", []))
    titulo = f"Mesma Nota Fiscal paga em meses diferentes — NF {d.get('nf')} ({_moeda(d.get('valor'))})"
    paragrafo = (f"O lançamento \"{d.get('descricao')}\" ({_moeda(d.get('valor'))}, {d.get('data') or 'sem data'}) cita a NF {d.get('nf')}, "
                 f"que já aparece paga do mesmo fornecedor em: {ant}. Pode ser pagamento em duplicidade, parcela não identificada ou reaproveitamento "
                 f"do número da nota.")
    verificar = ("Os dois pagamentos desta nota fiscal são parcelas distintas ou houve duplicidade? Podem enviar as notas fiscais e os comprovantes dos dois "
                 "pagamentos e, se for duplicidade, providenciar a devolução/estorno?")
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
    verificar = ("Qual é a relação das unidades inadimplentes e quais ações de cobrança estão em andamento? Qual o efeito no caixa "
                 "(a Ordinária está sendo coberta por outras contas)? Como se explica a arrecadação abaixo do esperado?")
    return titulo, paragrafo, verificar


def texto_saldo_negativo(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    if d.get("contas"):
        def _tempo(c):
            n = c["meses"]
            return f"há {'pelo menos ' if c.get('ate_o_limite_lido') else ''}{n} {'mês' if n == 1 else 'meses'} seguido{'' if n == 1 else 's'}"
        itens = "; ".join(f"{c['nome']} {_tempo(c)} ({_moeda(c['saldo_atual'])}, saldo anterior {_moeda(c['saldo_anterior'])})" for c in d["contas"])
        nomes = ", ".join(c["nome"] for c in d["contas"][:3]) + (f" e mais {len(d['contas']) - 3}" if len(d["contas"]) > 3 else "")
        titulo = f"Contas com saldo negativo e há quanto tempo — {nomes}"
        paragrafo = (f"Fecharam o mês com saldo negativo: {itens}. Saldo negativo significa despesas pagas com o caixa de outras contas. "
                     f"A contagem considera o mês deste balancete e os balancetes dos meses anteriores (até {d.get('meses_lidos')} meses); "
                     f"'pelo menos' indica que a conta já estava negativa em todos esses meses.")
        return titulo, paragrafo, ""
    conta = d.get("conta") or a.linha_demonstrativo or "conta"
    n = d.get("meses_seguidos")
    mais = "pelo menos " if n >= (d.get("meses_lidos") or 0) else ""
    titulo = f"Conta {conta} com saldo negativo há {mais}{n} meses seguidos ({_moeda(d.get('saldo_atual'))})"
    paragrafo = (f"A conta {conta} fechou o mês com saldo de {_moeda(d.get('saldo_atual'))} (anterior: {_moeda(d.get('saldo_anterior'))}) e está negativa "
                 f"{mais}{n} meses seguidos nos balancetes lidos. Saldo negativo significa despesas pagas com o caixa de outras contas.")
    verificar = ("De onde vem o dinheiro que cobre o saldo negativo desta conta? Houve aprovação em assembleia para esse uso dos fundos "
                 "e qual é o plano de recomposição?")
    return titulo, paragrafo, verificar


def _lista_itens(d: dict, n: int = 6) -> str:
    itens = d.get("lancamentos") or []
    txt = "; ".join(f"{i.get('descricao') or 'lançamento'} ({_moeda(i.get('valor'))}{', ' + i['data'] if i.get('data') else ''})" for i in itens[:n])
    resto = (d.get("total_itens") or len(itens)) - min(len(itens), n)
    return txt + (f" e mais {resto}" if resto > 0 else "")


def _ver_ordinaria(d: dict) -> str:
    """Pergunta de gestor quando uma despesa de valor alto foi paga pela conta Ordinária."""
    itens = d.get("pergunta_ordinaria") or []
    if not itens:
        return ""
    quais = "; ".join(f"{i['descricao']} ({_moeda(i['valor'])})" for i in itens[:3])
    saldo = d.get("saldo_ordinaria")
    return (f" Esse valor ({quais}) é despesa de valor alto e fora do custeio mensal"
            + (f", e a Ordinária fechou o mês com saldo de {_moeda(saldo)}" if saldo is not None else "")
            + ". Ele tem que sair mesmo da conta Ordinária ou deveria ser pago por outra conta (Fundo de Reserva, Obras ou Extraordinária)?")


def texto_observacao_gestor(a: Achado) -> tuple[str, str, str]:
    """Pontos de um gestor condominial sem regra própria. Redação cautelosa: é pergunta ao revisor, não afirmação de erro."""
    d = a.detalhes
    v = d.get("verificacao")
    n = d.get("total_itens") or len(d.get("lancamentos") or [])
    total = _moeda(a.valor_encontrado)
    pre = "Ponto de atenção de gestor — "
    if v == "compra_marketplace":
        titulo = pre + f"{n} compra(s) em marketplace/intermediador de pagamento ({total})"
        par = (f"Há despesas pagas em marketplace ou intermediador de pagamento, o que normalmente não traz a nota fiscal de um fornecedor "
               f"cadastrado: {_lista_itens(d)}.")
        ver = ("Por que esta compra foi feita em marketplace/intermediador de pagamento? Onde estão a nota fiscal em nome do condomínio e a cotação/aprovação "
               "da compra? O bem é despesa do mês ou patrimônio que deveria constar no inventário?")
    elif v == "valor_redondo":
        titulo = pre + f"{n} despesa(s) de valor redondo e alto ({total})"
        par = (f"Despesas a partir de {_moeda(d.get('minimo'))} com valor exato em centenas de reais e sem repetição de valor em meses anteriores: "
               f"{_lista_itens(d)}. Valores redondos podem ser contrato/orçamento fechado, mas também estimativa ou adiantamento.")
        ver = "O valor pago é o valor real do serviço (nota fiscal/contrato) ou é uma estimativa/adiantamento? Podem enviar a nota fiscal ou o contrato?" + _ver_ordinaria(d)
    elif v == "fornecedor_novo":
        titulo = pre + f"{n} fornecedor(es) sem lançamento nos {d.get('meses_lidos')} meses anteriores ({total})"
        par = (f"Lançamentos de valor alto (a partir de {_moeda(d.get('minimo'))}) de fornecedores/despesas que não aparecem em nenhum dos "
               f"{d.get('meses_lidos')} meses anteriores lidos: {_lista_itens(d)}.")
        if d.get("redondos"):
            par += f" O valor {', '.join(_moeda(x) for x in d['redondos'])} é redondo (centenas exatas) e não se repetia em meses anteriores — pode ser orçamento/sinal fechado ou estimativa."
        ver = "Como foi a contratação desse fornecedor novo (cotações, aprovação do síndico/conselho) e onde está a nota fiscal?" + _ver_ordinaria(d)
        lancs = d.get("lancamentos") or []
        projetos = [l for l in lancs if re.search(r"\bPROJETO\b", (l.get("descricao") or "").upper())]
        if projetos:
            # locação/contrato de "projeto" (ex.: projeto de segurança): a pergunta é sobre o fim do projeto e as parcelas, não sobre a contratação
            pergunta_projeto = ("Esse projeto já acabou? Quantas parcelas já foram pagas (identificar o número de parcelas no lançamento)?")
            if len(projetos) == len(lancs):
                ver = pergunta_projeto
            else:
                nomes = "; ".join((l.get("descricao") or "").strip() for l in projetos)
                ver = (f"Em relação aos demais fornecedores: como foi a contratação (cotações, aprovação do síndico/conselho) e onde está a nota fiscal? "
                       f"Em relação ao projeto ({nomes}): {pergunta_projeto}") + _ver_ordinaria(d)
    elif v == "recorrente_ausente":
        itens = d.get("ausentes") or []
        lista = "; ".join(f"{i['descricao']} (mediana {_moeda(i['mediana'])})" for i in itens[:6])
        titulo = pre + f"{n} despesa(s) recorrente(s) que não aparece(m) neste mês ({total} por mês)"
        par = (f"Despesas presentes em todos os últimos {len(d.get('meses_comparados') or [])} meses lidos e ausentes neste: {lista}. "
               f"Pode ser fim de contrato, mas também lançamento que ficou para o mês seguinte ou conta não paga.")
        ver = "O contrato dessas despesas terminou ou o lançamento foi postergado? Existe pagamento em atraso?"
    elif v == "valor_atipico":
        itens = d.get("medianas") or []
        acumulos = [i for i in itens if i.get("acumulo")]
        outros = [i for i in itens if not i.get("acumulo")]
        partes_par, partes_ver = [], []
        for i in acumulos:
            comps = ", ".join(i.get("competencias") or [])
            datas = "; ".join(f"{q} em {dt}" for dt, q in (i.get("datas") or {}).items())
            if i.get("sem_comparacao") or i.get("mediana") is None:
                partes_par.append(
                    f"{i['descricao']}: foram pagos {i['n']} lançamentos no mês, cada um de {_moeda(i['valor_unitario'])}, totalizando {_moeda(i['valor'])}"
                    + (f", referentes às competências {comps}" if comps else "") + (f" e pagos nas datas: {datas}" if datas else "")
                    + ". Há mais de uma competência paga no mesmo mês, incluindo meses anteriores.")
            else:
                partes_par.append(
                    f"{i['descricao']}: foram pagos {i['n']} lançamentos no mês, cada um de {_moeda(i['valor_unitario'])} (o valor mensal de sempre; mediana dos "
                    f"meses anteriores {_moeda(i['mediana'])}), totalizando {_moeda(i['valor'])}" + (f", referentes às competências {comps}" if comps else "")
                    + (f" e pagos nas datas: {datas}" if datas else "")
                    + ". Não é aumento de valor: são pagamentos de meses anteriores feitos juntos neste mês.")
        if outros:
            def _pct(i):
                return f", {str(i['acima_pct']).replace('.', ',')}% acima" if (i.get("acima_pct") is not None and i.get("variavel")) else ""
            lista = "; ".join(f"{i['descricao']} ({_moeda(i['valor'])} contra mediana de {_moeda(i['mediana'])}{_pct(i)})" for i in outros[:6])
            fixos = [i for i in outros if not i.get("variavel")]
            if fixos and len(fixos) == len(outros):
                partes_par.append(f"O valor pago é mais de {str(d.get('fator')).replace('.', ',')} vezes a mediana dos meses anteriores do mesmo fornecedor: {lista}.")
            elif not fixos:
                partes_par.append(f"Conta de concessionária/cartão com valor mais de 10% acima da mediana dos meses anteriores do mesmo fornecedor: {lista}.")
            else:
                partes_par.append(f"O valor pago está acima da mediana dos meses anteriores do mesmo fornecedor (mais de {str(d.get('fator')).replace('.', ',')} vezes; "
                                  f"concessionárias e cartão: mais de 10%): {lista}.")
            for i in outros:
                if i.get("competencias_anteriores"):
                    partes_par.append(
                        f"Em {i['descricao']}, os {i['n']} lançamentos do mês incluem competências de meses anteriores pagas agora "
                        f"({', '.join(i['competencias_anteriores'])}) — parte do total vem de pagamentos atrasados/acumulados, não necessariamente de aumento de valor.")
                    partes_ver.append(f"Por que {i['descricao']} teve competências de meses anteriores ({', '.join(i['competencias_anteriores'])}) pagas neste mês "
                                      f"(atraso, lançamento acumulado)? Houve multa ou juros?")
        if acumulos:
            nomes = ", ".join(i["descricao"] for i in acumulos)
            partes_ver.append(f"Por que {nomes} está com várias competências pagas juntas neste mês (pagamentos de meses anteriores "
                              f"na mesma data)? Houve atraso no pagamento, multa ou juros, e as notas dos meses anteriores já estavam em aberto?")
        if outros and all(i.get("variavel") for i in outros):
            partes_ver.append("Qual a justificativa do aumento do valor (consumo, tarifa/reajuste, multa ou juros)? Podem enviar a conta (fatura) do mês?")
        elif outros:
            partes_ver.append("Qual a justificativa do aumento (reajuste, serviço extra, acúmulo de meses)? Podem enviar a nota fiscal?")
        if acumulos and not outros and all(i.get("sem_comparacao") or i.get("mediana") is None for i in acumulos):
            titulo = pre + (f"{acumulos[0]['descricao']}: {acumulos[0]['n']} competências pagas no mesmo mês ({total})"
                            if len(acumulos) == 1 else f"{len(acumulos)} fornecedores com mais de uma competência paga neste mês ({total})")
        elif acumulos and not outros:
            titulo = pre + (f"{acumulos[0]['descricao']}: {acumulos[0]['n']} meses pagos juntos em um só mês ({total}) — pagamentos de meses anteriores, não aumento"
                            if len(acumulos) == 1 else f"{len(acumulos)} fornecedores com meses anteriores pagos juntos neste mês ({total}) — não é aumento")
        elif outros and all(i.get("variavel") for i in outros) and not acumulos:
            titulo = pre + f"{n} conta(s) de concessionária/cartão acima da mediana dos meses anteriores ({total})"
        else:
            titulo = pre + f"{n} despesa(s) muito acima do histórico do próprio fornecedor ({total})"
        par = " ".join(partes_par)
        ver = " ".join(partes_ver)
    elif v == "apropriacao_despesa":
        liquido = round(a.valor_encontrado or 0.0, 2)
        correcao = bool(d.get("estornos")) and abs(liquido) < 0.01
        aprop = d.get("tem_aprop", True)
        reclass = d.get("reclassificacoes") or []
        if correcao and aprop:
            titulo = pre + f"{n} lançamentos de apropriação de despesa estornados e relançados no mês (efeito líquido {_moeda(0)})"
        elif correcao:
            titulo = pre + (f"despesa de {_moeda(abs(reclass[0]['valor']))} estornada e relançada em outra subconta (reclassificação, efeito líquido {_moeda(0)})"
                            if reclass else f"{n} lançamentos estornados e relançados no mês (efeito líquido {_moeda(0)})")
        else:
            titulo = pre + f"{n} apropriação(ões) de despesa no mês ({total})"
        descritor = ("Lançamentos de \"apropriação de despesa\" (lançamento contábil interno, sem comprovante de pagamento próprio)" if aprop
                     else "Lançamentos estornados e relançados")
        par = f"{descritor}: {_lista_itens(d)}."
        if correcao:
            par += (" Os mesmos valores foram estornados (negativos) e lançados novamente no mesmo mês, com efeito líquido zero no resultado: "
                    "tem aparência de correção contábil, mas não há, neste arquivo, explicação do que foi corrigido.")
            for r_ in reclass:
                par += f" A subconta mudou de \"{r_['de']}\" para \"{r_['para']}\" ({_moeda(abs(r_['valor']))})."
        else:
            extras = []
            if d.get("estornos"):
                extras.append("há lançamento negativo (estorno) de " + ", ".join(_moeda(x) for x in d["estornos"]))
            for s_ in d.get("parcelas_juntas") or []:
                extras.append(f"as parcelas {', '.join(f'{x}/{s_['total']}' for x in s_['parcelas'])} da NF {s_['nf'] or '(sem nº)'} foram apropriadas no mesmo mês")
            if extras:
                par += " Chama a atenção: " + "; ".join(extras) + "."
        if aprop:
            ver = ("A que se referem essas apropriações? Qual erro foi corrigido pelo estorno e relançamento (se for o caso)? Qual o "
                   "comprovante da compra original a que a apropriação se refere (NF e fornecedor)?")
        else:
            ver = ("Qual o motivo do estorno e do relançamento" + (" e da mudança de subconta (de que subconta o gasto saiu e por que foi para a outra)"
                   if reclass else "") + "? A nota fiscal e o pagamento originais continuam corretos e documentados?")
    elif v == "duplicidade_no_mes":
        titulo = pre + f"mesmo lançamento repetido {d.get('vezes')}x no mês ({_moeda(d.get('valor_unitario'))} cada)"
        par = (f"{_lista_itens(d)} aparecem com a mesma descrição e o mesmo valor mais de uma vez no mês. "
               f"Pode ser pagamento em duplicidade ou duas cobranças legítimas com o mesmo histórico.")
        ver = "Estes lançamentos repetidos são cobranças distintas ou houve duplicidade? Podem enviar as notas fiscais e os comprovantes de cada um e, se for duplicidade, estornar?"
    elif v == "uso_fundo":
        titulo = pre + f"{n} despesa(s) paga(s) direto do {', '.join(d.get('contas') or ['fundo'])} ({total})"
        par = f"Despesas de valor relevante pagas com recursos de fundo: {_lista_itens(d)}."
        ver = "Qual a finalidade dessas despesas pagas direto do fundo? Houve aprovação em assembleia/previsão orçamentária e existe plano de reposição do fundo?"
    elif v == "deficit_conta":
        titulo = pre + f"conta {d.get('conta')} pagou {_moeda(a.valor_encontrado)} a mais do que recebeu no mês"
        par = (f"Na conta {d.get('conta')}, os créditos do mês foram {_moeda(d.get('creditos'))} e os débitos {_moeda(d.get('debitos'))} "
               f"(saldo anterior {_moeda(d.get('saldo_anterior'))}, saldo final {_moeda(d.get('saldo_atual'))}).")
        _ant, _atu = d.get("saldo_anterior") or 0.0, d.get("saldo_atual") or 0.0
        if _atu >= 0 and _ant > 0:
            # a diferença foi paga com o saldo que a conta já tinha: perguntar "de onde veio o caixa" não faz sentido
            _pct = f"{(_ant - _atu) / _ant * 100:.1f}".replace(".", ",")
            par = (f"Na conta {d.get('conta')}, os créditos do mês foram {_moeda(d.get('creditos'))} e os débitos {_moeda(d.get('debitos'))}; "
                   f"a diferença foi paga com o saldo que a conta já tinha, que caiu de {_moeda(_ant)} para {_moeda(_atu)} ({_pct}% de redução).")
            ver = "Essa redução do saldo da conta é esperada (pagamento sazonal, obra, despesa concentrada no mês)? Existe previsão de recompor o saldo?"
        else:
            ver = "De onde veio o caixa que cobriu a diferença (outra conta, reserva)? Existe plano de recomposição?"
    elif v == "inadimplencia_crescente":
        serie = " → ".join(f"{x['mes']}: {_moeda(x['inad'])}" for x in reversed(d.get("serie") or []))
        titulo = pre + f"inadimplência subiu {str(d.get('variacao_pct')).replace('.', ',')}% em relação ao mês anterior ({_moeda(d.get('anterior'))} → {_moeda(d.get('atual'))})"
        par = "A inadimplência total em aberto cresceu de um mês para o outro" + (f" (série recente: {serie})." if serie else ".")
        ver = "Por que a inadimplência cresceu neste mês? Quais ações de cobrança estão em andamento e qual a relação das unidades inadimplentes?"
    else:
        titulo = pre + (a.linha_demonstrativo or "ponto a verificar")
        par = f"Regra aplicada: {a.regra_aplicada}."
        ver = "Podem explicar este apontamento?"
    return titulo, par + " Observação baseada apenas nos arquivos do próprio condomínio; não é, por si só, prova de irregularidade.", ver


def texto_movimento_entre_contas(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    conta = d.get("conta") or a.linha_demonstrativo or "conta"
    mov = _moeda(d.get("movimento"))
    sentido = "saiu da" if d.get("saida") else "entrou na"
    titulo = f"Movimento de {mov} que {sentido} conta {conta} fora das despesas e receitas"
    paragrafo = (f"Na conta {conta}, o saldo anterior ({_moeda(d.get('saldo_anterior'))}) mais os créditos ({_moeda(d.get('creditos'))}) menos as despesas "
                 f"({_moeda(d.get('debitos'))}) não resulta no saldo final ({_moeda(d.get('saldo_atual'))}): a diferença de {mov} {sentido} conta como "
                 f"movimento que não é despesa nem receita (transferência entre contas, aplicação ou resgate), conforme o próprio arquivo.")
    verificar = (f"{'Para' if d.get('saida') else 'De'} qual conta ou aplicação {'foi' if d.get('saida') else 'veio'} o valor de {mov} "
                 f"{'retirado da' if d.get('saida') else 'recebido na'} conta {conta}? Qual o motivo e a aprovação (assembleia/conselho) dessa movimentação, "
                 f"e onde está o comprovante?")
    return titulo, paragrafo, verificar


def _mes_extenso(m: str) -> str:
    nomes = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    try:
        return f"{nomes[int(m[5:7]) - 1]}/{m[:4]}"
    except (ValueError, IndexError):
        return m


def texto_continuidade_saldo(a: Achado) -> tuple[str, str, str]:
    d = a.detalhes
    atual, ant = _mes_extenso(d.get("mes", "")), _mes_extenso(d.get("mes_anterior", ""))
    contas = d["contas"]
    itens = "; ".join(f"{c['nome']}: saldo anterior de {atual} {_moeda(c['saldo_anterior'])}, saldo final de {ant} {_moeda(c['saldo_final_mes_anterior'])} "
                      f"(diferença de {_moeda(c['diferenca'])})" for c in contas)
    nomes = ", ".join(c["nome"] for c in contas[:3]) + (f" e mais {len(contas) - 3}" if len(contas) > 3 else "")
    titulo = f"Saldo anterior de {atual} diferente do saldo final de {ant} — {nomes}"
    paragrafo = (f"O saldo anterior de uma conta deve ser igual ao saldo final do mês anterior. Neste arquivo isso não ocorre em {len(contas)} "
                 f"conta{'s' if len(contas) > 1 else ''}: {itens}.")
    verificar = (f"Por que o saldo anterior de {atual} não é igual ao saldo final de {ant} nessas contas? Houve ajuste, estorno, lançamento "
                 f"retroativo ou reabertura de {ant}? Podem enviar o balancete corrigido de {ant}?")
    return titulo, paragrafo, verificar


TEXTOS = {
    "observacao_gestor": texto_observacao_gestor,
    "nf_repetida_entre_meses": texto_nf_repetida,
    "inadimplencia_arrecadacao": texto_cobranca,
    "saldo_negativo_persistente": texto_saldo_negativo,
    "continuidade_saldo": texto_continuidade_saldo,
    "movimento_entre_contas": texto_movimento_entre_contas,
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
        return titulo, paragrafo, "O plano de contas foi alterado? Como as subcontas antigas foram mapeadas para as novas? Podem enviar o de-para?"
    if d.get("so_total") and d.get("sumiu"):
        titulo = f"Subconta sem lançamentos neste mês — {cat} ({_moeda(d.get('valor_mes_anterior'))} no mês anterior)"
        paragrafo = (f"A subconta \"{cat}\" teve {_moeda(d.get('valor_mes_anterior'))} no balancete do mês anterior e não "
                     f"aparece neste mês.")
        return titulo, paragrafo, "Esta despesa foi encerrada ou foi lançada em outra subconta? Em qual?"
    if d.get("so_total"):
        titulo = f"Subconta nova neste mês — {cat} ({_moeda(a.valor_encontrado)})"
        paragrafo = (f"A subconta \"{cat}\" não existia no balancete do mês anterior e aparece neste mês com "
                     f"{_moeda(a.valor_encontrado)}. Este formato de balancete informa só o total por subconta, sem listar os lançamentos.")
        return titulo, paragrafo, "Por que esta subconta foi criada e o que foi lançado nela? Podem explicar a classificação?"
    itens = d.get("lancamentos", [])
    lista = "; ".join(f"{i.get('descricao') or 'lançamento'} ({_moeda(i.get('valor'))})" for i in itens[:5])
    mais = f" e mais {len(itens) - 5}" if len(itens) > 5 else ""
    titulo = f"Subconta nova neste mês — {cat} ({_moeda(a.valor_encontrado)})"
    paragrafo = (f"A subconta \"{cat}\" não existia no balancete do mês anterior e recebeu "
                 f"{len(itens)} lançamento(s) neste mês, somando {_moeda(a.valor_encontrado)}: {lista}{mais}.")
    verificar = "Por que esta subconta foi criada? Os lançamentos nela estão classificados corretamente? Podem explicar?"
    return titulo, paragrafo, verificar
