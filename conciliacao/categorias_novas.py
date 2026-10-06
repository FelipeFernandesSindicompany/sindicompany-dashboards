"""
Compara, fornecedor a fornecedor, em qual categoria cada lançamento estava
classificado no mês anterior contra a categoria em que está classificado
no mês atual — formato GCONT (ver
conciliacao/condominios/club_park_butanta.py).

Confirmado em dados reais (Club Park Butantã, ago/2026): a RELUX Pinturas
estava 100% em "PINTURA FACHADA" em julho/2026 e passou a aparecer também
em "MATS.-SERVS. PINTURA" em agosto/2026 — mesmo contrato, categoria
diferente. O mesmo aconteceu com a Master Benefícios (estava em "VALE
REFEICAO", passou a aparecer também em "CESTA BASICA"/"VALE TRANSPORTE").
Só entra no relatório quando o MESMO fornecedor é encontrado nos dois
meses — fornecedor sem equivalente no mês anterior é despesa nova, não
reclassificação, e fica de fora desta checagem.
"""
from conciliacao.pdf_cache import pdf_plumber_aberto
import re
from pathlib import Path

_RE_ITEM_RESUMIDO = re.compile(r"^(.+?)\s+([\d.]+,\d{2})\s*$")
_RE_LINHA_DETALHADA = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d.]+,\d{2})\s*$"
)
_RE_CONECTOR_FINAL = re.compile(r"\s+(E|DE|DO|DA|DOS|DAS)\s*$", re.IGNORECASE)


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _fmt_r(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _texto_ate_comprovantes(caminho: Path) -> str:
    """Concatena o texto nativo das páginas ANTES da seção 'Comprovantes de
    despesas' (onde ficam o Resumido e a tabela detalhada) — para antes
    disso por economia, já que o resto do PDF pode ter centenas de páginas
    de comprovante que não importam aqui."""
    import pdfplumber

    partes = []
    with pdf_plumber_aberto(caminho) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            if "Comprovantes de despesas" in texto and partes:
                break
            partes.append(texto)
    return "\n".join(partes)


def _extrair_resumido(texto_completo: str) -> dict[str, float]:
    """{nome_categoria_raw: valor} dentro de 'Total das Receitas X'..'Total das Despesas Y'
    (seção "Demonstrativo de Receitas e Despesas Resumido")."""
    itens: dict[str, float] = {}
    in_desp = False
    for linha in texto_completo.split("\n"):
        l = linha.strip()
        if not l:
            continue
        if re.match(r"^Total das Receitas\s+[\d.,]+", l, re.IGNORECASE):
            in_desp = True
            continue
        if re.match(r"^Total das Despesas\s+[\d.,]+", l, re.IGNORECASE):
            in_desp = False
            continue
        if not in_desp:
            continue
        m = _RE_ITEM_RESUMIDO.match(l)
        if m:
            itens[m.group(1).strip()] = _num(m.group(2))
    return itens


def _extrair_detalhada(texto_completo: str) -> list[tuple[str, float]]:
    """[(texto_fornecedor_e_categoria_combinado, valor), ...] da tabela
    "Despesas por categoria" (vencimento/liquidação/fornecedor/categoria/
    documento/competência/valor — fornecedor e categoria vêm concatenados
    na mesma linha, sem separador estruturado)."""
    linhas = []
    for linha in texto_completo.split("\n"):
        m = _RE_LINHA_DETALHADA.match(linha.strip())
        if m:
            linhas.append((m.group(3).strip(), _num(m.group(4))))
    return linhas


def detectar_categorias_novas(caminho_atual: Path, caminho_anterior: Path | None) -> list[dict]:
    """
    Retorna [{categoria, valor, valor_fmt, fornecedores: [...],
    possivel_reclassificacao: bool, fornecedor_reclassificado: str|None}]
    pras categorias que existem no mês atual mas não no anterior. Nunca
    lança — se o mês anterior não for localizável/legível ou não tiver a
    mesma estrutura de demonstrativo, retorna [] (é uma checagem extra
    opcional, não pode derrubar a geração do relatório).
    """
    try:
        texto_atual = _texto_ate_comprovantes(caminho_atual)
        resumido_atual = _extrair_resumido(texto_atual)
        if not resumido_atual or caminho_anterior is None or not caminho_anterior.exists():
            return []
        texto_anterior = _texto_ate_comprovantes(caminho_anterior)
        resumido_anterior = _extrair_resumido(texto_anterior)
        if not resumido_anterior:
            return []
    except Exception:
        return []

    detalhada_atual = _extrair_detalhada(texto_atual)
    detalhada_anterior = _extrair_detalhada(texto_anterior)
    nomes_categoria_anterior = sorted(resumido_anterior.keys(), key=len, reverse=True)

    novas = []
    for nome, valor in resumido_atual.items():
        if nome in resumido_anterior:
            continue
        candidatos_fornecedor = set()
        for txt, _ in detalhada_atual:
            if nome in txt:
                antes = txt.split(nome)[0].strip()
                antes = _RE_CONECTOR_FINAL.sub("", antes).strip()
                if len(antes) >= 4:
                    candidatos_fornecedor.add(antes)

        # Pra cada fornecedor candidato, procura em qual categoria do mês
        # anterior ele aparecia — olhando a linha detalhada do mês anterior
        # que contém esse fornecedor e vendo qual nome de categoria
        # (do conjunto já conhecido do Resumido anterior) está nela.
        fornecedor_reclassificado = None
        categoria_anterior = None
        for fornecedor in candidatos_fornecedor:
            linha_anterior = next((txt for txt, _ in detalhada_anterior if fornecedor in txt), None)
            if linha_anterior is None:
                continue
            categoria_achada = next((c for c in nomes_categoria_anterior if c in linha_anterior), None)
            if categoria_achada:
                fornecedor_reclassificado = fornecedor
                categoria_anterior = categoria_achada
                break

        novas.append({
            "categoria": nome,
            "valor": valor,
            "valor_fmt": _fmt_r(valor),
            "fornecedores": sorted(candidatos_fornecedor),
            "possivel_reclassificacao": fornecedor_reclassificado is not None,
            "fornecedor_reclassificado": fornecedor_reclassificado,
            "categoria_anterior": categoria_anterior,
        })
    return sorted(novas, key=lambda n: n["valor"], reverse=True)
