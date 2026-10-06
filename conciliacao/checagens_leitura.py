"""
Checagens de SANIDADE DA LEITURA — pegam erro do adapter/arquivo antes que ele
vire número errado num relatório. Não julgam o balancete; só avisam quando a
leitura não se sustenta. Saem como linhas "[AVISO]" no log (Admin mostra em
destaque); nunca derrubam a geração.

Nasceram da auditoria de 05/10/2026 (53 condomínios), que achou categorias
perdidas, contadas em dobro ou lidas do arquivo errado sem nenhum sinal:
  - Padre Carvalho: faltavam R$ 5.269,86 nas categorias (cat_map somava errado);
  - Fatto Morumbi: R$ 13.000 contados duas vezes;
  - Baturité: o arquivo "09.2026" era, de fato, setembro/2025.
"""
import re
from pathlib import Path

_TOLERANCIA = 0.01


def _br(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")

_MESES = {1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
          7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"}
# Só vale o "Período:" no INÍCIO de uma linha (cabeçalho da página): o mesmo texto aparece dentro de
# históricos de lançamentos (ex.: "VALE TRANSPORTE PERIODO: 06/07/2026 A 05/08/2026"), que não é o
# período do balancete.
_RE_PERIODO = re.compile(
    r"^[ \t]*Per[ií]odo\s*:?\s*(\d{2})/(\d{2})/(\d{4})\s*(?:a|à|até|-)\s*(\d{2})/(\d{2})/(\d{4})",
    re.IGNORECASE | re.MULTILINE)


def periodo_do_pdf(pdf: Path, paginas: int = 4) -> tuple[int, int] | None:
    """(mês, ano) do "Período: dd/mm/aaaa a dd/mm/aaaa" impresso nas primeiras
    páginas, ou None se o PDF não traz (ou não é PDF / não tem texto)."""
    if pdf.suffix.lower() != ".pdf":
        return None
    try:
        import fitz

        doc = fitz.open(str(pdf))
        try:
            for i in range(min(paginas, len(doc))):
                m = _RE_PERIODO.search(doc[i].get_text())
                if m:
                    return int(m.group(5)), int(m.group(6))  # mês/ano do FIM do período
        finally:
            doc.close()
    except Exception:
        return None
    return None


def verificar_periodo(pdf: Path, mes: str) -> str | None:
    """Mensagem de aviso se o período impresso no PDF não for o mês pedido
    (mes = "AAAA-MM"). Pega arquivo salvo com o nome do mês errado."""
    achado = periodo_do_pdf(pdf)
    if achado is None:
        return None
    mes_pdf, ano_pdf = achado
    if (ano_pdf, mes_pdf) == (int(mes[:4]), int(mes[5:7])):
        return None
    return (f"o período impresso em {pdf.name} é {_MESES[mes_pdf]}/{ano_pdf}, mas a validação foi "
            f"pedida para {_MESES[int(mes[5:7])]}/{mes[:4]} — confira se o arquivo é do mês certo "
            f"(nome do arquivo trocado?).")


def _debito_conta_ordinaria(contas: list[dict]) -> float | None:
    """Débito da conta que concentra as despesas operacionais: ORDINÁRIA, ou
    CONTA CONDOMINIO (Iello). None se não houver como identificar."""
    for c in contas:
        nome = (c.get("n") or c.get("nome") or "").upper()
        # "ORDINARIA", "1000 ORDINARIA" (Habitacional), "CONTA CONDOMINIO" (Iello);
        # "ORDINÁRIA APLICAÇÃO" é outra conta (Blue Sky), não a ordinária.
        if ("ORDIN" in nome and "APLIC" not in nome) or nome.startswith("CONTA CONDOM"):
            return float(c.get("d", c.get("debitos", 0.0)) or 0.0)
    return None


def verificar_fechamento_categorias(condo: dict, bal: dict) -> str | None:
    """Aviso quando a soma de bal["desp"] não fecha com NENHUM dos totais que o
    próprio arquivo declara (débito da conta ordinária, total de despesas lido
    pelo adapter, débito de todas as contas). Cada adapter cobre um universo
    diferente (só a ordinária; todas as contas), por isso fechar com qualquer
    um deles basta — o que se quer pegar é categoria PERDIDA ou EM DOBRO.

    Não roda para GCONT: lá o relatório já tem a Divergência própria de
    "Total das Despesas x Livro Caixa". Condomínio com diferença estrutural já
    entendida pode silenciar com parser_config["fechamento_categorias_ignorar"]
    (texto livre com o motivo)."""
    pcfg = condo.get("parser_config") or {}
    if pcfg.get("fechamento_categorias_ignorar") or bal.get("debitos_incluem_transferencias") is not None and \
            bal.get("debitos_incluem_transferencias"):
        return None
    desp = bal.get("desp") or []
    if not desp:
        return None
    soma = round(sum(float(d.get("v", 0.0)) for d in desp), 2)
    referencias = {
        "débito da conta ordinária": _debito_conta_ordinaria(bal.get("contas") or []),
        "total de despesas lido": bal.get("tDesp"),
        "débito de todas as contas": bal.get("tDeb"),
    }
    validas = {k: round(float(v), 2) for k, v in referencias.items() if v}
    if not validas or any(abs(soma - v) <= _TOLERANCIA for v in validas.values()):
        return None
    mais_proxima = min(validas.items(), key=lambda kv: abs(soma - kv[1]))
    dif = round(soma - mais_proxima[1], 2)
    return (f"as categorias de despesa somam {_br(soma)} e não fecham com o {mais_proxima[0]} "
            f"({_br(mais_proxima[1])}; diferença de {_br(dif)}) — possível categoria perdida, "
            f"contada em dobro ou transferência entre contas; confira a leitura antes de usar a "
            f"tabela \"Despesas por Categoria\".")
