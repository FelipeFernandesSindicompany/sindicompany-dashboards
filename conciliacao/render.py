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
from conciliacao.pdf_cache import pdf_plumber_aberto, total_paginas
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
    cnpj: str | None,
    administradora: str,
    mes_titulo: str,
    logo_data_uri: str | None,
    cor: str,
    achados: list[dict],
    gerado_em: str,
    analise: dict | None = None,
    categorias_novas: list[dict] | None = None,
) -> str:
    """
    achados: lista de dicts já mesclando Achado (fatos) + AchadoRevisado
    (narrativa), no formato esperado por templates/conciliacao_relatorio.html.
    analise: saída de conciliacao/analise_financeira.py::montar_analise, ou
    None para gerar só a seção de divergências (sem resumo executivo).

    Quais verificações (conteúdo/atraso/subconta) rodaram de fato pra este
    condomínio/mês NÃO entra no PDF entregue ao síndico/condomínio — é
    detalhe de implementação interno, sem sentido pra quem recebe o relatório
    (feedback explícito do usuário). Esse registro fica só em
    verificacoes.json, ao lado dos outros artefatos da versão — ver
    scripts/gerar_relatorio_conciliacao.py::etapa_render.
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
        categorias_novas=categorias_novas or [],
    )


def _abrir_navegador(p):
    """Abre o Chromium do Playwright; se ele sumiu/está bloqueado (erro "Executable doesn't exist", visto
    com antivírus/atualização), usa o Edge ou o Chrome instalados no Windows e, por último, reinstala o
    Chromium do Playwright uma vez e tenta de novo. Só levanta erro se nenhuma das saídas funcionar."""
    erro = None
    try:
        return p.chromium.launch()
    except Exception as exc:
        erro = exc
    for canal in ("msedge", "chrome"):
        try:
            return p.chromium.launch(channel=canal)
        except Exception:
            continue
    import subprocess
    import sys
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       check=True, capture_output=True, timeout=600)
        return p.chromium.launch()
    except Exception:
        raise erro


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
            browser = _abrir_navegador(p)
            page = browser.new_page()
            page.goto(html_temp.as_uri())
            page.pdf(path=str(destino_pdf), format="A4", print_background=True,
                     margin={"top": "8mm", "bottom": "10mm", "left": "8mm", "right": "8mm"})
            browser.close()
    finally:
        html_temp.unlink(missing_ok=True)


_GAP_MAXIMO_PT = 60  # além disso, considera o resto rodapé/marca d'água isolada, não conteúdo

# Largura útil dentro de um card .achado (ver templates/conciliacao_relatorio.html):
# A4 = 210mm - padding do body (6mm x2) - padding do .achado (4mm x2) = 190mm.
_CONTEUDO_LARGURA_MM = 190.0
# Acima disso, a evidência sozinha já não cabe ao lado do título/parágrafo/
# rodapé na mesma página (margens de impressão deixam ~279mm úteis por
# página) — o achado inteiro (page-break-inside: avoid) então pula pra
# próxima página, deixando um vão em branco enorme no fim da página atual.
# Um crop de recibo de página inteira (retrato, aspect_pct > 100%) alargado
# pra 100% da largura do card facilmente passa de 240mm de altura — por isso
# a largura é reduzida (nunca a nitidez/qualidade, só o tamanho de exibição)
# quando isso aconteceria, mantendo o crop inteiro na mesma página do texto.
_ALTURA_MAXIMA_EVIDENCIA_MM = 130.0


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


def preparar_evidencia_vetorial(pdf_origem: Path, pagina: int, bbox_override: tuple | None = None) -> dict | None:
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

    `bbox_override` (x0, top, x1, bottom, em pontos pdfplumber) recorta só
    ESSA região da página em vez do bloco de conteúdo inteiro — usado
    quando quem chama já sabe exatamente qual LINHA mostrar (ex.: um
    lançamento "sem_comprovante" da listagem, ver RegistroComprovante.
    bbox_crop) e uma página inteira de dezenas de despesas seria ruído.
    """
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdf_plumber_aberto(pdf_origem) as pdf:
            if bbox_override:
                # Recorte já conhecido: só confere que a página existe, sem
                # listar as páginas pelo pdfplumber (minutos num PDF de 89 MB).
                if not (1 <= pagina <= total_paginas(pdf_origem)):
                    return None
                bbox = bbox_override
            else:
                if not (1 <= pagina <= len(pdf.pages)):
                    return None
                bbox = _bbox_conteudo(pdf.pages[pagina - 1])
            if not bbox:
                return None
            largura, altura = bbox[2] - bbox[0], bbox[3] - bbox[1]
            aspect_pct = (altura / largura * 100.0) if largura else 60.0
            # Dimensões finais em mm ABSOLUTOS, não percentuais — "padding-top:
            # X%" (o truque de caixa de proporção) é resolvido contra a
            # largura do CONTAINING BLOCK, não a largura do próprio elemento;
            # setar width E padding-top no mesmo elemento não reduz a altura
            # reservada, só a largura visual (bug já cometido aqui uma vez:
            # a evidência ficava mais estreita mas continuava alta o
            # suficiente pra empurrar o resto do achado pra outra página).
            altura_mm = _CONTEUDO_LARGURA_MM * (aspect_pct / 100.0)
            largura_mm = _CONTEUDO_LARGURA_MM
            if altura_mm > _ALTURA_MAXIMA_EVIDENCIA_MM:
                largura_mm = _ALTURA_MAXIMA_EVIDENCIA_MM / (aspect_pct / 100.0)
                altura_mm = _ALTURA_MAXIMA_EVIDENCIA_MM
            return {
                "tipo": "pdf",
                "pdf_origem": str(pdf_origem),
                "pagina_origem": pagina,
                "bbox": bbox,
                "largura_mm": largura_mm,
                "altura_mm": altura_mm,
            }
    except Exception:
        return None


def preparar_evidencia_externa(caminho_arquivo: str) -> dict | None:
    """
    Como preparar_evidencia_vetorial, mas para uma evidência que NÃO é uma
    página do PDF de origem — um arquivo separado, salvo em disco à parte
    (ver RegistroComprovante.arquivo_evidencia_externa), tipicamente baixado
    de um sistema externo (ex.: conciliacao/condominios/
    central_das_artes.py, comprovantes do sistema Robotton). Sem isso o
    relatório não tem como mostrar essa evidência: não existe página
    nenhuma do PDF original pra recortar.

    PDF avulso (ex.: fatura de concessionária anexada como PDF de verdade):
    reaproveita preparar_evidencia_vetorial na própria página 1 desse
    arquivo — mesmo recorte vetorial nítido de sempre.

    Imagem (JPEG, ex.: comprovante bancário Robotton): não tem vetor pra
    copiar de uma imagem já rasterizada — embute como raster mesmo (ver
    inserir_evidencias_vetoriais), só calcula aqui as dimensões finais em mm.
    """
    caminho = Path(caminho_arquivo)
    if not caminho.exists():
        return None
    if caminho.suffix.lower() == ".pdf":
        return preparar_evidencia_vetorial(caminho, 1)
    try:
        from PIL import Image
        with Image.open(caminho) as img:
            largura_px, altura_px = img.size
        aspect_pct = (altura_px / largura_px * 100.0) if largura_px else 60.0
        altura_mm = _CONTEUDO_LARGURA_MM * (aspect_pct / 100.0)
        largura_mm = _CONTEUDO_LARGURA_MM
        if altura_mm > _ALTURA_MAXIMA_EVIDENCIA_MM:
            largura_mm = _ALTURA_MAXIMA_EVIDENCIA_MM / (aspect_pct / 100.0)
            altura_mm = _ALTURA_MAXIMA_EVIDENCIA_MM
        return {
            "tipo": "imagem",
            "arquivo": str(caminho),
            "largura_mm": largura_mm,
            "altura_mm": altura_mm,
        }
    except Exception:
        return None


def _pagina_isolada(src_doc, indice_0based: int):
    """
    Devolve um fitz.Document de 1 página só, com o mesmo conteúdo da página
    `indice_0based` de `src_doc`, sem os XObjects (imagens) que o conteúdo
    da página não desenha (operador "Do" no content stream).

    Por quê: confirmado em dados reais (Club Park Butantã, PDF de 1042
    páginas / 333MB) que o GCONT aponta o dicionário /Resources de CADA
    página pra TODAS as imagens do arquivo (976 imagens referenciadas, 1
    desenhada). Page.show_pdf_page e Document.insert_pdf copiam tudo que
    está referenciado, então um relatório de 3 páginas saía com ~330MB —
    praticamente o PDF de origem inteiro dentro dele. Aqui só poda o
    dicionário /XObject do nível da própria página (formulários aninhados
    ficam intactos, com os resources deles) e só quando o conteúdo da
    página desenha pelo menos 1 XObject; em qualquer dúvida segue sem poda
    (pior caso = comportamento anterior, nunca perde evidência).
    """
    import re

    import fitz

    pagina_src = src_doc[indice_0based]
    resources_original = None
    try:
        # Nomes de XObject que o conteúdo da página realmente desenha ("/Im12 Do").
        # Lê o content stream em vez de Page.get_image_info/get_images, que
        # levavam ~160s por página neste PDF (976 imagens nos resources).
        usados = {
            n.decode("latin-1")
            for n in re.findall(rb"/([^\s/<>\[\]()]+)\s+Do\b", pagina_src.read_contents())
        }

        if usados:
            tipo, valor = src_doc.xref_get_key(pagina_src.xref, "Resources")
            if tipo == "xref":
                texto_res = src_doc.xref_object(int(valor.split()[0]), compressed=False)
            elif tipo == "dict":
                texto_res = valor
            else:
                texto_res = None

            if texto_res is not None:
                def _podar(dict_texto: str) -> str:
                    pares = re.findall(r"/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R", dict_texto)
                    return "<<" + " ".join(
                        f"/{n} {x} 0 R" for n, x in pares if n in usados
                    ) + ">>"

                m_ref = re.search(r"/XObject\s+(\d+)\s+0\s+R", texto_res)
                m_inline = re.search(r"/XObject\s*(<<.*?>>)", texto_res, re.DOTALL)
                novo_res = None
                if m_ref:
                    podado = _podar(src_doc.xref_object(int(m_ref.group(1)), compressed=False))
                    novo_res = texto_res.replace(m_ref.group(0), f"/XObject {podado}")
                elif m_inline:
                    novo_res = texto_res.replace(m_inline.group(0), f"/XObject {_podar(m_inline.group(1))}")

                if novo_res is not None:
                    # Troca SÓ o /Resources desta página, em memória (o arquivo
                    # em disco nunca é tocado) e antes de copiar — o dicionário
                    # original é compartilhado pelas outras páginas, então é
                    # restaurado logo depois do insert_pdf, no finally.
                    resources_original = (tipo, valor)
                    src_doc.xref_set_key(pagina_src.xref, "Resources", novo_res)
    except Exception:
        resources_original = None

    mini = fitz.open()
    try:
        mini.insert_pdf(src_doc, from_page=indice_0based, to_page=indice_0based)
    finally:
        if resources_original is not None:
            src_doc.xref_set_key(pagina_src.xref, "Resources", resources_original[1])
    return mini


def _desenhar_destaques(pagina_destino, rect_destino, bbox_origem, destaques) -> None:
    """Retângulos amarelos (borda vermelha, semitransparentes — o texto de baixo
    continua legível) sobre as regiões `destaques`, dadas no espaço do recorte
    de origem `bbox_origem` (x0, top, x1, bottom) e convertidas pro retângulo
    final `rect_destino` do relatório."""
    import fitz

    if not destaques:
        return
    cx0, ctop, cx1, _ = bbox_origem
    escala = rect_destino.width / (cx1 - cx0)
    for hx0, htop, hx1, hbottom in destaques:
        pagina_destino.draw_rect(
            fitz.Rect(
                rect_destino.x0 + (hx0 - cx0) * escala,
                rect_destino.y0 + (htop - ctop) * escala,
                rect_destino.x0 + (hx1 - cx0) * escala,
                rect_destino.y0 + (hbottom - ctop) * escala,
            ),
            color=(0.8, 0.1, 0.1), fill=(1.0, 0.92, 0.0), fill_opacity=0.35, width=1.3,
        )


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
    paginas_isoladas: dict[tuple, fitz.Document] = {}
    try:
        for a in relevantes:
            ev = a["evidencia_vetorial"]
            # "imagem" (ver render.py::preparar_evidencia_externa) — sem
            # página de PDF nenhuma pra copiar como vetor, é um arquivo
            # raster (JPEG) já em disco; embute direto via insert_image.
            if ev.get("tipo") == "imagem":
                marca_ini, marca_fim = f"@@EVID_INI_{a['numero']}@@", f"@@EVID_FIM_{a['numero']}@@"
                for pagina_destino in dest:
                    rects_ini = pagina_destino.search_for(marca_ini)
                    rects_fim = pagina_destino.search_for(marca_fim)
                    if not (rects_ini and rects_fim):
                        continue
                    rect_destino = fitz.Rect(
                        rects_ini[0].x0, rects_ini[0].y0, rects_fim[0].x1, rects_fim[0].y1
                    )
                    pagina_destino.insert_image(rect_destino, filename=ev["arquivo"])
                    if ev.get("bbox"):
                        _desenhar_destaques(pagina_destino, rect_destino, ev["bbox"], ev.get("destaque"))
                    break
                continue

            if ev["pdf_origem"] not in fontes_origem:
                fontes_origem[ev["pdf_origem"]] = fitz.open(ev["pdf_origem"])
            chave_pagina = (ev["pdf_origem"], ev["pagina_origem"])
            if chave_pagina not in paginas_isoladas:
                paginas_isoladas[chave_pagina] = _pagina_isolada(
                    fontes_origem[ev["pdf_origem"]], ev["pagina_origem"] - 1
                )
            src_doc = paginas_isoladas[chave_pagina]

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
                    rect_destino, src_doc, 0,
                    clip=fitz.Rect(x0, top, x1, bottom),
                )
                _desenhar_destaques(pagina_destino, rect_destino, ev["bbox"], ev.get("destaque"))
                break

        temp_path = destino_pdf.with_name(destino_pdf.stem + "_tmp" + destino_pdf.suffix)
        dest.save(str(temp_path), garbage=4, deflate=True)
    finally:
        dest.close()
        for doc in fontes_origem.values():
            doc.close()
        for doc in paginas_isoladas.values():
            doc.close()
    temp_path.replace(destino_pdf)


def preparar_evidencia_extra(pdf_origem: Path, spec: dict) -> dict | None:
    """
    Evidência ADICIONAL de um achado (um achado pode ter várias, cada uma
    com legenda e destaque) — usada principalmente nos achados agregados
    ("soma não confere"), que não têm um lançamento único pra mostrar e
    onde um print marcando EXATAMENTE as linhas que causam a divergência é
    o que torna o achado verificável.

    `spec` (vem de evidencias_extra.json da versão, curado pra aquele
    relatório): {"pagina": int, "legenda": str} mais UM dos formatos:
      - "buscar": regex de texto a localizar na página (pdfplumber.search,
        sem acentos — usar "." no lugar, o texto extraído do GCONT vem com
        acento quebrado). Recorta a linha achada + `linhas_contexto` linhas
        acima/abaixo (default 3) e destaca a linha inteira.
      - sem "buscar": recorta `bbox` [x0, top, x1, bottom] (pontos
        pdfplumber) ou, se omitido, o bloco de conteúdo da página;
        `destaques` = lista de [x0, top, x1, bottom] a marcar (opcional).
    Devolve None se a página/trecho não for encontrado — o achado sai sem
    esse print em vez de derrubar o relatório.
    """
    try:
        import pdfplumber
    except ImportError:
        return None
    pagina = spec["pagina"]
    destaques: list[tuple] = []
    bbox = spec.get("bbox")
    try:
        if spec.get("buscar"):
            with pdf_plumber_aberto(pdf_origem) as pdf:
                if not (1 <= pagina <= len(pdf.pages)):
                    return None
                page = pdf.pages[pagina - 1]
                achados = page.search(spec["buscar"], regex=True, case=False)
                if not achados:
                    return None
                m = achados[0]
                palavras = page.extract_words()
                if not palavras:
                    return None
                esquerda = max(0.0, min(w["x0"] for w in palavras) - 4)
                direita = min(float(page.width), max(w["x1"] for w in palavras) + 4)
                altura_linha = m["bottom"] - m["top"]
                contexto = altura_linha * (spec.get("linhas_contexto", 3) + 0.6)
                topo = max(0.0, m["top"] - contexto)
                base = min(float(page.height), m["bottom"] + contexto)
                # Estende o recorte até linhas inteiras — um corte no meio de
                # uma linha de texto deixa meia linha visível no topo/base.
                for _ in range(6):
                    mudou = False
                    for w in palavras:
                        if w["top"] < topo < w["bottom"]:
                            topo, mudou = max(0.0, w["top"] - 0.5), True
                        if w["top"] < base < w["bottom"]:
                            base, mudou = min(float(page.height), w["bottom"] + 0.5), True
                    if not mudou:
                        break
                bbox = (esquerda, topo, direita, base)
                da_linha = [w for w in palavras if w["top"] >= m["top"] - 2 and w["bottom"] <= m["bottom"] + 2]
                x_ini = min([w["x0"] for w in da_linha] + [m["x0"]])
                destaques = [(x_ini - 2, m["top"] - 1.5, m["x1"] + 2, m["bottom"] + 1.5)]
        else:
            destaques = [tuple(d) for d in spec.get("destaques", [])]
    except Exception:
        return None

    ev = preparar_evidencia_vetorial(pdf_origem, pagina, bbox_override=tuple(bbox) if bbox else None)
    if ev is None:
        return None
    ev["destaque"] = destaques
    ev["legenda"] = spec.get("legenda", "")
    # "meia_largura": dois prints lado a lado (cada um em ~metade da página);
    # "largura_mm": largura explícita. Altura sempre pela proporção do recorte.
    ev["meia_largura"] = bool(spec.get("meia_largura"))
    largura = spec.get("largura_mm") or (92.0 if ev["meia_largura"] else None)
    if largura and ev.get("bbox"):
        bx0, btop, bx1, bbottom = ev["bbox"]
        ev["largura_mm"] = float(largura)
        ev["altura_mm"] = float(largura) * (bbottom - btop) / (bx1 - bx0)
    return ev


def inserir_evidencias_extras(destino_pdf: Path, achados: list[dict]) -> None:
    """
    Como inserir_evidencias_vetoriais, mas pra achado["evidencias_extras"]
    (lista de preparar_evidencia_extra): cada item tem seu próprio par de
    marcadores "@@EVX_INI_<numero>_<k>@@"/"@@EVX_FIM_<numero>_<k>@@" (k a
    partir de 1) no template, e leva um retângulo de destaque (amarelo com
    borda vermelha, semitransparente pro texto de baixo continuar legível)
    por cima de cada região em ev["destaque"], convertida das coordenadas
    da página de origem pras do relatório.
    """
    extras = [
        (a, k, ev)
        for a in achados
        for k, ev in enumerate(a.get("evidencias_extras") or [], start=1)
    ]
    if not extras:
        return

    import fitz  # PyMuPDF

    dest = fitz.open(str(destino_pdf))
    fontes_origem: dict[str, fitz.Document] = {}
    paginas_isoladas: dict[tuple, fitz.Document] = {}
    try:
        for a, k, ev in extras:
            if ev["pdf_origem"] not in fontes_origem:
                fontes_origem[ev["pdf_origem"]] = fitz.open(ev["pdf_origem"])
            chave_pagina = (ev["pdf_origem"], ev["pagina_origem"])
            if chave_pagina not in paginas_isoladas:
                paginas_isoladas[chave_pagina] = _pagina_isolada(
                    fontes_origem[ev["pdf_origem"]], ev["pagina_origem"] - 1
                )
            src_doc = paginas_isoladas[chave_pagina]

            marca_ini, marca_fim = f"@@EVX_INI_{a['numero']}_{k}@@", f"@@EVX_FIM_{a['numero']}_{k}@@"
            for pagina_destino in dest:
                rects_ini = pagina_destino.search_for(marca_ini)
                rects_fim = pagina_destino.search_for(marca_fim)
                if not (rects_ini and rects_fim):
                    continue
                rect_destino = fitz.Rect(
                    rects_ini[0].x0, rects_ini[0].y0, rects_fim[0].x1, rects_fim[0].y1
                )
                cx0, ctop, cx1, cbottom = ev["bbox"]
                pagina_destino.show_pdf_page(
                    rect_destino, src_doc, 0, clip=fitz.Rect(cx0, ctop, cx1, cbottom),
                )
                _desenhar_destaques(pagina_destino, rect_destino, ev["bbox"], ev.get("destaque"))
                break

        temp_path = destino_pdf.with_name(destino_pdf.stem + "_tmp" + destino_pdf.suffix)
        dest.save(str(temp_path), garbage=4, deflate=True)
    finally:
        dest.close()
        for doc in fontes_origem.values():
            doc.close()
        for doc in paginas_isoladas.values():
            doc.close()
    temp_path.replace(destino_pdf)
