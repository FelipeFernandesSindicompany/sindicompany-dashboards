"""
Prints de evidência dos achados das regras gerais, no formato de spec que
render.preparar_evidencia_extra já entende ({"pagina", "legenda", "buscar"...}).

Só gera print quando o arquivo é PDF e o extrator registrou a página do lançamento;
planilha (XLSX/XLS) não tem página — o texto do achado cita a linha.
"""
import re
from typing import Optional

from conciliacao.base import Achado


def _br(v: float) -> str:
    return f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _mes_br(mes) -> str:
    """'2026-07' -> '07/2026'."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", mes or "")
    return f"{m.group(2)}/{m.group(1)}" if m else str(mes)


def _trecho(descricao: Optional[str], n: int = 28) -> Optional[str]:
    """Regex tolerante (acentos viram '.') do começo da descrição, para localizar a linha."""
    if not descricao:
        return None
    base = re.sub(r"\s+", " ", descricao.strip())[:n]
    return re.escape(base).replace(r"\ ", r"\s+") if base else None


def _spec(pagina, buscar, legenda) -> dict:
    # linha_inteira: o retângulo cobre a linha do lançamento inteira (não só o trecho encontrado), inclusive as linhas de descrição quebrada
    return {"pagina": pagina, "buscar": buscar, "legenda": legenda, "linha_inteira": True}


def _spec_linha_listagem(i: dict, legenda: str) -> Optional[dict]:
    """Print da LINHA da listagem "Despesas por categoria" (prestação resumida do Club Park, local "W078A, página N"): a linha vem em várias
    colunas e quebras de linha, então não há texto corrido para buscar — o recorte e o destaque usam a posição registrada pelo extrator."""
    bbox = i.get("bbox")
    if not (bbox and i.get("pagina") and str(i.get("local") or "").startswith("W078A")):
        return None
    x0, top, x1, bottom = bbox
    return {"pagina": i["pagina"], "legenda": legenda, "buscar": "", "bbox": [max(0.0, x0 - 4), max(0.0, top - 1), x1 + 4, bottom + 1],
            "destaques": [[x0 - 1, top - 1, x1 + 1, bottom + 1]]}


def _spec_lancamento(i: dict, legenda: str, vistos: dict) -> Optional[dict]:
    """Print de UM lançamento: o começo da descrição + o VALOR na mesma linha (lançamentos do mesmo fornecedor começam com o mesmo texto —
    ex.: três lançamentos da mesma empresa na mesma página — e só a descrição marcaria sempre o primeiro). Se ainda assim duas linhas casam igual
    (mesmo texto e mesmo valor), a N-ésima ocorrência pedida é a N-ésima linha que casa."""
    if not i.get("pagina"):
        return None
    por_posicao = _spec_linha_listagem(i, legenda)
    if por_posicao:
        return por_posicao
    trecho = _trecho(i.get("descricao"))
    sp = _spec(i["pagina"], trecho or re.escape(_br(i["valor"])), legenda)
    if trecho:
        sp["buscar"] = trecho + r"[^\n]{0,90}?" + re.escape(_br(i["valor"]))
        sp["buscar_alt"] = trecho
    chave = (i["pagina"], sp["buscar"])
    sp["ocorrencia"] = vistos.get(chave, 0)
    vistos[chave] = sp["ocorrencia"] + 1
    return sp


def specs_para(a: Achado) -> list[dict]:
    d = a.detalhes or {}
    specs: list[dict] = []
    if a.tipo == "receita_negativa" and d.get("pagina"):
        specs.append(_spec(d["pagina"], re.escape(_br(a.valor_encontrado)), "Linha de receita com valor negativo"))
    elif a.tipo == "pagamento_sem_identificacao" and d.get("pagina"):
        specs.append(_spec(d["pagina"], re.escape(_br(a.valor_encontrado)), "Lançamento sem identificação do favorecido"))
    elif a.tipo == "parcelas_mesmo_mes":
        vistos: dict = {}
        for p in d.get("parcelas", [])[:3]:
            if p.get("pagina"):
                por_posicao = _spec_linha_listagem(p, f"Parcela {p['n']}/{d.get('total_parcelas')}")
                if por_posicao:
                    specs.append(por_posicao)
                    continue
                busca = _trecho(p.get("descricao")) or re.escape(_br(p["valor"]))
                sp = _spec(p["pagina"], busca, f"Parcela {p['n']}/{d.get('total_parcelas')}")
                # as parcelas da mesma série começam com o mesmo texto: a N-ésima parcela na mesma página é a N-ésima linha que casa
                sp["ocorrencia"] = vistos.get((p["pagina"], busca), 0)
                vistos[(p["pagina"], busca)] = sp["ocorrencia"] + 1
                specs.append(sp)
    elif a.tipo in ("lancamento_em_outra_subconta", "subconta_atipica"):
        vistos_l: dict = {}
        # os maiores lançamentos primeiro: são os "maiores casos" citados no texto do item
        for i in sorted(d.get("lancamentos", []), key=lambda x: -abs(x.get("valor") or 0))[:3]:
            sp = _spec_lancamento(i, "Lançamento na subconta " + (d.get("categoria_atual") or d.get("categoria") or i.get("categoria") or ""), vistos_l)
            if sp:
                specs.append(sp)
    elif a.tipo == "saldo_negativo_persistente" and d.get("pagina") and d.get("contas"):
        specs.append(_spec(d["pagina"], re.escape(_br(d["contas"][0]["saldo_atual"])), "Saldo atual da conta " + d["contas"][0]["nome"]))
    elif a.tipo == "observacao_gestor" and d.get("verificacao") == "deficit_conta" and d.get("pagina"):
        specs.append(_spec(d["pagina"], re.escape(_br(d.get("debitos") or 0)), "Débitos da conta " + (d.get("conta") or "")))
    elif a.tipo == "observacao_gestor" and d.get("verificacao") == "inadimplencia_crescente" and d.get("pagina"):
        specs.append(_spec(d["pagina"], "Totais", "Posição de Devedores — total anterior e total atrasados"))
    elif a.tipo == "observacao_gestor" and d.get("verificacao") == "recorrente_ausente":
        # a despesa NÃO está neste mês: o print é a linha dela no mês anterior (arquivo do mês anterior, mesma pasta)
        for x in d.get("ausentes", [])[:3]:
            if x.get("pagina") and x.get("arquivo"):
                por_posicao = _spec_linha_listagem(x, f"Lançamento de {_mes_br(x.get('mes'))} (último mês lido antes deste) que não aparece neste mês")
                if por_posicao:
                    specs.append({**por_posicao, "arquivo": x["arquivo"]})
                    continue
                specs.append({**_spec(x["pagina"], _trecho(x.get("descricao")) or re.escape(_br(x["mediana"])),
                                      f"Lançamento de {_mes_br(x.get('mes'))} (último mês lido antes deste) que não aparece neste mês"), "arquivo": x["arquivo"]})
    elif a.tipo in ("conta_concessionaria_nao_anexada", "despesa_negativa"):
        vistos_c: dict = {}
        for i in d.get("itens", [])[:3]:
            sp = _spec_lancamento(i, "Lançamento de concessionária" if a.tipo == "conta_concessionaria_nao_anexada" else "Lançamento com valor negativo", vistos_c)
            if sp:
                specs.append(sp)
    elif a.tipo == "observacao_gestor":
        # valor acima do histórico: um print por fornecedor citado no texto (o maior lançamento de cada), não os primeiros da lista
        vistos_g: dict = {}
        for i in (d.get("representantes") or d.get("lancamentos", []))[:4]:
            sp = _spec_lancamento(i, "Lançamento citado nesta observação", vistos_g)
            if sp:
                specs.append(sp)
    elif a.tipo == "continuidade_saldo" and d.get("pagina") and d.get("contas"):
        specs.append(_spec(d["pagina"], re.escape(_br(d["contas"][0]["saldo_anterior"])), "Saldo anterior da conta " + d["contas"][0]["nome"]))
    elif a.tipo == "movimento_entre_contas" and d.get("pagina"):
        specs.append(_spec(d["pagina"], re.escape(_br(d["movimento"])), "Movimento entre contas de " + (d.get("conta") or "")))
    elif a.tipo == "compensacao_nao_fecha" and d.get("pagina"):
        specs.append(_spec(d["pagina"], r"ESTAC", "Lançamentos do grupo " + (d.get("grupo") or "")))
    elif a.tipo == "rendimento_desproporcional" and d.get("motivo") == "distribuicao_nao_informada":
        for x in (d.get("linhas_maiores") or [])[:1]:
            if x.get("pagina"):
                specs.append(_spec(x["pagina"], re.escape(_br(x["valor"])), f"Rendimento creditado no livro caixa em {x['data']}"))
    elif a.tipo == "rendimento_desproporcional" and d.get("pagina"):
        if d.get("motivo") in ("sem_rendimento", "sem_rendimento_consolidado") and d.get("conta"):
            # conta que NÃO recebeu rendimento: não há linha de rendimento para marcar — marca a linha da própria conta na tabela de contas
            specs.append(_spec(d["pagina"], re.escape(str(d["conta"]))[:40].replace(r"\ ", r"\s+"), "Conta " + str(d["conta"]) + " (sem rendimento no mês)"))
        specs.append({**_spec(d["pagina"], r"REND", "Rendimento creditado na conta " + (d.get("conta") or "")), "linha_inteira": True})
    return [s for s in specs if s["buscar"] or s.get("bbox")]


def texto_origem(a: Achado) -> Optional[str]:
    """Onde está o dado no arquivo, em texto — usado quando não há print (planilha, ou o
    extrator não registrou a página). None para achados que não são das regras gerais."""
    if not (a.id or "").startswith("RG-"):
        return None
    d = a.detalhes or {}
    locais: list[str] = []

    def _onde(x: dict) -> Optional[str]:
        if x.get("local"):
            return x["local"]
        if x.get("pagina"):
            return f"página {x['pagina']}"
        return None

    if a.tipo == "parcelas_mesmo_mes":
        locais = [f"parcela {p['n']}: {w}" for p in d.get("parcelas", []) if (w := _onde(p))]
    elif a.tipo in ("lancamento_em_outra_subconta", "subconta_atipica", "observacao_gestor"):
        locais = [w for i in d.get("lancamentos", [])[:3] if (w := _onde(i))]
        if not locais and (w := _onde(d)):
            locais = [w]
    else:
        w = _onde(d)
        locais = [w] if w else []
    if not locais:
        return None
    return "Origem no arquivo: " + "; ".join(locais) + "."
