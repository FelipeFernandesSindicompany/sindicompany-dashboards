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


def _trecho(descricao: Optional[str], n: int = 28) -> Optional[str]:
    """Regex tolerante (acentos viram '.') do começo da descrição, para localizar a linha."""
    if not descricao:
        return None
    base = re.sub(r"\s+", " ", descricao.strip())[:n]
    return re.escape(base).replace(r"\ ", r"\s+") if base else None


def _spec(pagina, buscar, legenda) -> dict:
    # linha_inteira: o retângulo cobre a linha do lançamento inteira (não só o trecho encontrado), inclusive as linhas de descrição quebrada
    return {"pagina": pagina, "buscar": buscar, "legenda": legenda, "linha_inteira": True}


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
                busca = _trecho(p.get("descricao")) or re.escape(_br(p["valor"]))
                sp = _spec(p["pagina"], busca, f"Parcela {p['n']}/{d.get('total_parcelas')}")
                # as parcelas da mesma série começam com o mesmo texto: a N-ésima parcela na mesma página é a N-ésima linha que casa
                sp["ocorrencia"] = vistos.get((p["pagina"], busca), 0)
                vistos[(p["pagina"], busca)] = sp["ocorrencia"] + 1
                specs.append(sp)
    elif a.tipo in ("lancamento_em_outra_subconta", "subconta_atipica"):
        for i in d.get("lancamentos", [])[:2]:
            if i.get("pagina"):
                specs.append(_spec(i["pagina"], _trecho(i.get("descricao")) or re.escape(_br(i["valor"])),
                                   "Lançamento na subconta " + (d.get("categoria_atual") or d.get("categoria") or "")))
    elif a.tipo == "saldo_negativo_persistente" and d.get("pagina") and d.get("contas"):
        specs.append(_spec(d["pagina"], re.escape(_br(d["contas"][0]["saldo_atual"])), "Saldo atual da conta " + d["contas"][0]["nome"]))
    elif a.tipo == "observacao_gestor" and d.get("verificacao") == "deficit_conta" and d.get("pagina"):
        specs.append(_spec(d["pagina"], re.escape(_br(d.get("debitos") or 0)), "Débitos da conta " + (d.get("conta") or "")))
    elif a.tipo == "observacao_gestor" and d.get("verificacao") == "recorrente_ausente":
        # a despesa NÃO está neste mês: o print é a linha dela no mês anterior (arquivo do mês anterior, mesma pasta)
        for x in d.get("ausentes", [])[:3]:
            if x.get("pagina") and x.get("arquivo"):
                specs.append({**_spec(x["pagina"], _trecho(x.get("descricao")) or re.escape(_br(x["mediana"])),
                                      f"Lançamento do mês anterior ({x.get('mes')}) que não aparece neste mês"), "arquivo": x["arquivo"]})
    elif a.tipo in ("conta_concessionaria_nao_anexada", "despesa_negativa"):
        for i in d.get("itens", [])[:3]:
            if i.get("pagina"):
                specs.append(_spec(i["pagina"], _trecho(i.get("descricao")) or re.escape(_br(i["valor"])), "Lançamento de concessionária"))
    elif a.tipo == "observacao_gestor":
        for i in d.get("lancamentos", [])[:4]:
            if i.get("pagina"):
                specs.append(_spec(i["pagina"], _trecho(i.get("descricao")) or re.escape(_br(i["valor"])), "Lançamento citado nesta observação"))
    elif a.tipo == "continuidade_saldo" and d.get("pagina") and d.get("contas"):
        specs.append(_spec(d["pagina"], re.escape(_br(d["contas"][0]["saldo_anterior"])), "Saldo anterior da conta " + d["contas"][0]["nome"]))
    elif a.tipo == "movimento_entre_contas" and d.get("pagina"):
        specs.append(_spec(d["pagina"], re.escape(_br(d["movimento"])), "Movimento entre contas de " + (d.get("conta") or "")))
    elif a.tipo == "compensacao_nao_fecha" and d.get("pagina"):
        specs.append(_spec(d["pagina"], r"ESTAC", "Lançamentos do grupo " + (d.get("grupo") or "")))
    elif a.tipo == "rendimento_desproporcional" and d.get("pagina"):
        if d.get("motivo") in ("sem_rendimento", "sem_rendimento_consolidado") and d.get("conta"):
            # conta que NÃO recebeu rendimento: não há linha de rendimento para marcar — marca a linha da própria conta na tabela de contas
            specs.append(_spec(d["pagina"], re.escape(str(d["conta"]))[:40].replace(r"\ ", r"\s+"), "Conta " + str(d["conta"]) + " (sem rendimento no mês)"))
        specs.append({**_spec(d["pagina"], r"REND", "Rendimento creditado na conta " + (d.get("conta") or "")), "linha_inteira": True})
    return [s for s in specs if s["buscar"]]


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
