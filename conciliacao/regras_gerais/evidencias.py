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
    return {"pagina": pagina, "buscar": buscar, "legenda": legenda}


def specs_para(a: Achado) -> list[dict]:
    d = a.detalhes or {}
    specs: list[dict] = []
    if a.tipo == "receita_negativa" and d.get("pagina"):
        specs.append(_spec(d["pagina"], re.escape(_br(a.valor_encontrado)), "Linha de receita com valor negativo"))
    elif a.tipo == "pagamento_sem_identificacao" and d.get("pagina"):
        specs.append(_spec(d["pagina"], re.escape(_br(a.valor_encontrado)), "Lançamento sem identificação do favorecido"))
    elif a.tipo == "parcelas_mesmo_mes":
        for p in d.get("parcelas", [])[:3]:
            if p.get("pagina"):
                specs.append(_spec(p["pagina"], _trecho(p.get("descricao")) or re.escape(_br(p["valor"])),
                                   f"Parcela {p['n']}/{d.get('total_parcelas')}"))
    elif a.tipo in ("lancamento_em_outra_subconta", "subconta_atipica"):
        for i in d.get("lancamentos", [])[:2]:
            if i.get("pagina"):
                specs.append(_spec(i["pagina"], _trecho(i.get("descricao")) or re.escape(_br(i["valor"])),
                                   "Lançamento na subconta " + (d.get("categoria_atual") or d.get("categoria") or "")))
    elif a.tipo == "rendimento_desproporcional" and d.get("pagina"):
        specs.append(_spec(d["pagina"], r"REND", "Rendimento creditado na conta " + (d.get("conta") or "")))
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
    elif a.tipo in ("lancamento_em_outra_subconta", "subconta_atipica"):
        locais = [w for i in d.get("lancamentos", [])[:3] if (w := _onde(i))]
    else:
        w = _onde(d)
        locais = [w] if w else []
    if not locais:
        return None
    return "Origem no arquivo: " + "; ".join(locais) + "."
