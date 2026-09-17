"""
Geração do PDF final — Jinja2 (identidade visual) + Playwright/Chromium
headless (HTML -> PDF e recorte das páginas de evidência).

Por que Playwright em vez de WeasyPrint/reportlab: ver seção "Geração de PDF"
do plano em C:\\Users\\MF PRINTER\\.claude\\plans\\humming-swimming-hellman.md.
Chromium também resolve o recorte de evidência (screenshot da página do PDF
original via visualizador nativo), sem precisar de uma segunda dependência
nativa de imagem além do pdfplumber.

Setup manual necessário uma única vez (não roda em runtime):
    pip install playwright
    playwright install chromium
"""
import base64
import hashlib
import re
import unicodedata
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = ROOT / "templates"
# Logo institucional Sindicompany (versão clara, para fundo escuro) — asset fixo
# do relatório, usado quando não se acha um logo específico do condomínio.
LOGO_SINDICOMPANY_PATH = TEMPLATES_DIR / "assets" / "logo_sindicompany_claro.png"
# Pasta onde ficam os projetos por condomínio no Claude Desktop (fora do repo
# git) — mesma raiz "OneDrive - Perfil de E-mail" do próprio projeto, só que
# em Documentos/Claude/Projects em vez de Área de Trabalho/Projeto ....
# É aqui que cada condomínio guarda seus arquivos-fonte, incluindo (às vezes)
# um logo próprio — ver localizar_logo_condominio_projeto().
PASTA_PROJETOS_CONDOMINIO = ROOT.parent.parent / "Documentos" / "Claude" / "Projects"

_RE_LOGO = re.compile(
    r'class="sb-logo">.*?<img\s+src="(data:image/[a-zA-Z]+;base64,[A-Za-z0-9+/=]+)"',
    re.DOTALL,
)
_EXT_IMAGEM = {".png", ".webp", ".jpg", ".jpeg", ".svg"}


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode("ascii")
    return texto.lower()


def _hash_arquivo(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extrair_logo_data_uri(html_dashboard_path: Path) -> str | None:
    """
    Extrai o <img src="data:image/...;base64,..."> de dentro de .sb-logo no
    dashboard HTML do condomínio (mesma convenção usada por todos os 54
    dashboards — ver docs/Dashboard_Financeiro_*.html). Nunca altera o
    arquivo, só lê.

    ATENÇÃO: nem todo dashboard tem um logo próprio do condomínio embutido —
    alguns (confirmado em Spazio Jardins da Orla) reusam o próprio logo
    institucional da Sindicompany no `.sb-logo`. Por isso `resolver_logo()`
    prefere primeiro o logo da pasta de projeto do condomínio (mais provável
    de ser o logo real do condomínio) e só cai para este extrator depois.
    """
    if not html_dashboard_path.exists():
        return None
    conteudo = html_dashboard_path.read_text(encoding="utf-8", errors="ignore")
    m = _RE_LOGO.search(conteudo)
    return m.group(1) if m else None


def logo_sindicompany_data_uri() -> str | None:
    """Logo institucional Sindicompany (fixo) — último fallback, quando nada específico é achado."""
    if not LOGO_SINDICOMPANY_PATH.exists():
        return None
    b64 = base64.b64encode(LOGO_SINDICOMPANY_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def localizar_logo_condominio_projeto(nome_condominio: str) -> Path | None:
    """
    Procura um arquivo de logo na pasta de projeto do condomínio em
    Documentos/Claude/Projects/Dashboard de An[aá]lise de Balancete <nome>
    (convenção observada em todos os condomínios já criados nessa pasta).
    Retorna o primeiro arquivo de imagem com "logo" no nome, ou None se a
    pasta do condomínio ou o arquivo não existirem. Só leitura — nunca move
    nem altera nada nessa pasta.
    """
    if not PASTA_PROJETOS_CONDOMINIO.exists():
        return None
    alvo = _normalizar(nome_condominio)
    primeira_palavra = alvo.split()[0] if alvo.split() else alvo
    for pasta in PASTA_PROJETOS_CONDOMINIO.iterdir():
        if not pasta.is_dir():
            continue
        nome_pasta = _normalizar(pasta.name)
        if "balancete" not in nome_pasta:
            continue
        if primeira_palavra not in nome_pasta:
            continue
        candidatos = sorted(
            p for p in pasta.iterdir()
            if p.is_file() and p.suffix.lower() in _EXT_IMAGEM and "logo" in _normalizar(p.name)
        )
        if candidatos:
            return candidatos[0]
    return None


def resolver_logo(nome_condominio: str, html_dashboard_path: Path) -> str | None:
    """
    Resolve o logo a usar no relatório, nesta ordem:
      1. Logo específico na pasta de projeto do condomínio (mais confiável —
         ver localizar_logo_condominio_projeto), desde que não seja apenas
         uma cópia do logo institucional da Sindicompany (comparação por hash).
      2. Logo embutido no próprio dashboard HTML (.sb-logo), com a mesma
         checagem — alguns dashboards reusam o logo da Sindicompany ali.
      3. Logo institucional da Sindicompany (sempre disponível, serve de
         identidade visual mínima do relatório).
    """
    hash_sindicompany = (
        _hash_arquivo(LOGO_SINDICOMPANY_PATH) if LOGO_SINDICOMPANY_PATH.exists() else None
    )

    caminho_projeto = localizar_logo_condominio_projeto(nome_condominio)
    if caminho_projeto and (hash_sindicompany is None or _hash_arquivo(caminho_projeto) != hash_sindicompany):
        ext = caminho_projeto.suffix.lstrip(".").lower()
        mime = "svg+xml" if ext == "svg" else ext
        b64 = base64.b64encode(caminho_projeto.read_bytes()).decode("ascii")
        return f"data:image/{mime};base64,{b64}"

    logo_dashboard = extrair_logo_data_uri(html_dashboard_path)
    if logo_dashboard:
        _, b64_part = logo_dashboard.split(",", 1)
        if hash_sindicompany is None or hashlib.sha256(base64.b64decode(b64_part)).hexdigest() != hash_sindicompany:
            return logo_dashboard

    return logo_sindicompany_data_uri()


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def montar_html(
    *,
    condominio_nome: str,
    cnpj: str,
    administradora: str,
    mes_titulo: str,
    logo_data_uri: str | None,
    cor: str,
    achados: list[dict],
    gerado_em: str,
    analise: dict | None = None,
) -> str:
    """
    achados: lista de dicts já mesclando Achado (fatos) + AchadoRevisado
    (narrativa), no formato esperado por templates/conciliacao_relatorio.html.
    analise: saída de conciliacao/analise_financeira.py::montar_analise, ou
    None para gerar só a seção de divergências (sem resumo executivo).
    """
    env = _jinja_env()
    template = env.get_template("conciliacao_relatorio.html")
    return template.render(
        condominio_nome=condominio_nome,
        cnpj=cnpj,
        administradora=administradora,
        mes_titulo=mes_titulo,
        logo_data_uri=logo_data_uri,
        logo_sindicompany_data_uri=logo_sindicompany_data_uri(),
        cor=cor,
        achados=achados,
        gerado_em=gerado_em,
        analise=analise,
    )


def renderizar_pdf(html: str, destino_pdf: Path) -> None:
    """HTML (string) -> PDF, via Chromium headless."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ImportError(
            "Playwright não instalado. Rode: pip install playwright && playwright install chromium"
        ) from exc

    destino_pdf.parent.mkdir(parents=True, exist_ok=True)
    html_temp = destino_pdf.parent / "_render_temp.html"
    html_temp.write_text(html, encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(html_temp.as_uri())
            page.pdf(path=str(destino_pdf), format="A4", print_background=True,
                     margin={"top": "8mm", "bottom": "10mm", "left": "8mm", "right": "8mm"})
            browser.close()
    finally:
        html_temp.unlink(missing_ok=True)


_GAP_MAXIMO_PT = 60  # além disso, considera o resto rodapé/marca d'água isolada, não conteúdo


def _bbox_conteudo(page, margem: float = 8) -> tuple | None:
    """
    Bounding box do bloco PRINCIPAL de conteúdo da página (texto + linhas/
    retângulos de tabela + imagens) — não da página inteira.

    Corta no primeiro salto vertical grande (> _GAP_MAXIMO_PT) entre um
    objeto e o próximo: a maioria das páginas de comprovante Addomus tem um
    rodapé isolado ("Addomus", carimbo) muito abaixo do conteúdo real (ex.:
    conteúdo termina em ~y=320 de uma página de 842pt, rodapé fica em
    y=812) — sem esse corte, o recorte inclui ~500pt de papel em branco.
    None se a página não tiver nenhum objeto identificável.
    """
    objetos = [
        o for objs in (page.chars, page.rects, page.lines, page.images) for o in objs
    ]
    if not objetos:
        return None
    objetos.sort(key=lambda o: o["top"])

    bloco = [objetos[0]]
    bottom = objetos[0]["bottom"]
    for o in objetos[1:]:
        if o["top"] - bottom > _GAP_MAXIMO_PT:
            break
        bloco.append(o)
        bottom = max(bottom, o["bottom"])

    return (
        max(0.0, min(o["x0"] for o in bloco) - margem),
        max(0.0, bloco[0]["top"] - margem),
        min(page.width, max(o["x1"] for o in bloco) + margem),
        min(page.height, bottom + margem),
    )


def preparar_evidencia_vetorial(pdf_origem: Path, pagina: int) -> dict | None:
    """
    Localiza o bloco de conteúdo da página `pagina` (1-based) do PDF original
    — não rasteriza nada aqui. Quem embute de fato é
    inserir_evidencias_vetoriais(), depois que o relatório principal já foi
    gerado, copiando o trecho como VETOR (texto real, não pixels).

    Por quê: a primeira versão tirava um screenshot raster da página
    (pdfplumber.to_image()) e embutia como <img>. Mesmo em resolução alta
    (300 DPI), o resultado é uma "foto" do texto — sempre visivelmente mais
    suave/antialiased do que o texto vetorial nativo do resto do relatório
    quando os dois aparecem lado a lado, por mais que a densidade de pixels
    seja tecnicamente alta. Copiar o PDF de origem como vetor elimina essa
    diferença por completo: a evidência fica com a mesma nitidez do resto do
    relatório em qualquer zoom.
    """
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(str(pdf_origem)) as pdf:
            if not (1 <= pagina <= len(pdf.pages)):
                return None
            bbox = _bbox_conteudo(pdf.pages[pagina - 1])
            if not bbox:
                return None
            largura, altura = bbox[2] - bbox[0], bbox[3] - bbox[1]
            return {
                "pdf_origem": str(pdf_origem),
                "pagina_origem": pagina,
                "bbox": bbox,
                "aspect_pct": (altura / largura * 100.0) if largura else 60.0,
            }
    except Exception:
        return None


def inserir_evidencias_vetoriais(destino_pdf: Path, achados: list[dict]) -> None:
    """
    Pós-processamento do PDF já gerado por renderizar_pdf(): substitui cada
    placeholder de evidência (marcado por texto invisível
    "@@EVID_INI_<numero>@@" / "@@EVID_FIM_<numero>@@" — ver
    templates/conciliacao_relatorio.html) pelo trecho vetorial real da
    página de origem, usando Page.show_pdf_page (PyMuPDF) — copia gráficos/
    texto como objetos vetoriais, não como imagem.

    `achados`: mesma lista passada para render.montar_html(); só os itens
    com achado["evidencia_vetorial"] (ver preparar_evidencia_vetorial) são
    processados — os demais (sem evidência disponível) ficam com o
    placeholder "Evidência não disponível" do template, sem alteração.
    """
    relevantes = [a for a in achados if a.get("evidencia_vetorial")]
    if not relevantes:
        return

    import fitz  # PyMuPDF

    dest = fitz.open(str(destino_pdf))
    fontes_origem: dict[str, fitz.Document] = {}
    try:
        for a in relevantes:
            ev = a["evidencia_vetorial"]
            if ev["pdf_origem"] not in fontes_origem:
                fontes_origem[ev["pdf_origem"]] = fitz.open(ev["pdf_origem"])
            src_doc = fontes_origem[ev["pdf_origem"]]

            marca_ini, marca_fim = f"@@EVID_INI_{a['numero']}@@", f"@@EVID_FIM_{a['numero']}@@"
            for pagina_destino in dest:
                rects_ini = pagina_destino.search_for(marca_ini)
                rects_fim = pagina_destino.search_for(marca_fim)
                if not (rects_ini and rects_fim):
                    continue
                rect_destino = fitz.Rect(
                    rects_ini[0].x0, rects_ini[0].y0, rects_fim[0].x1, rects_fim[0].y1
                )
                x0, top, x1, bottom = ev["bbox"]
                pagina_destino.show_pdf_page(
                    rect_destino, src_doc, ev["pagina_origem"] - 1,
                    clip=fitz.Rect(x0, top, x1, bottom),
                )
                break

        temp_path = destino_pdf.with_name(destino_pdf.stem + "_tmp" + destino_pdf.suffix)
        dest.save(str(temp_path))
    finally:
        dest.close()
        for doc in fontes_origem.values():
            doc.close()
    temp_path.replace(destino_pdf)
