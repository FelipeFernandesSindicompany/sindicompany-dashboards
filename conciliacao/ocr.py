"""
OCR compartilhado para páginas de comprovante sem texto extraível (imagem
raster embutida no PDF) — hoje usado só por conciliacao/lirba_pdf.py
(família ContasData), mas desenhado para ser reaproveitado por qualquer
outro parser que precise do mesmo tipo de comprovante digitalizado.

Nunca lança exceção: qualquer falha (tesseract não instalado, idioma
ausente, imagem ilegível) degrada para string vazia — quem chama decide
entre "sem_comprovante" (nenhum conteúdo confirmado) e
"conteudo_nao_verificavel" (comprovante existe, mas o OCR não confirmou o
valor/data com confiança), ver conciliacao/matching.py.

Resolve o bug de quoting descoberto num spike manual: passar
`--tessdata-dir "C:/pasta com espaço"` como config string pro pytesseract
faz as aspas irem literalmente para o caminho que o tesseract tenta abrir
(o subprocess não passa por um shell que as interpretaria). A variável de
ambiente TESSDATA_PREFIX não tem esse problema.
"""
import io
import os
import re
import shutil
import tempfile
from pathlib import Path

# Instalação via winget (UB-Mannheim.TesseractOCR) cai aqui por padrão no
# Windows; shutil.which("tesseract") cobre quem tiver o binário no PATH.
_TESSERACT_CANDIDATOS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe"]
# O pacote de idioma "por.traineddata" não vem por padrão nem no instalador
# oficial (só eng+osd) — precisa ser baixado à parte (tesseract-ocr/tessdata
# no GitHub) para uma pasta com permissão de escrita do usuário, já que
# escrever direto em Program Files exige elevação.
_TESSDATA_CANDIDATOS = [Path.home() / "tessdata", Path(r"C:\Program Files\Tesseract-OCR\tessdata")]

_disponivel: bool | None = None  # cache do feature-detection (só avisa/checa uma vez por processo)


def tesseract_disponivel() -> bool:
    """Feature-detection cacheada — nunca lança, só retorna True/False."""
    global _disponivel
    if _disponivel is not None:
        return _disponivel

    try:
        import pytesseract
    except ImportError:
        print("[AVISO] pytesseract não instalado (pip install -r requirements.txt) — "
              "comprovantes sem texto extraível ficarão como 'conteudo_nao_verificavel'.")
        _disponivel = False
        return False

    tesseract_cmd = shutil.which("tesseract") or next(
        (p for p in _TESSERACT_CANDIDATOS if Path(p).exists()), None
    )
    tessdata_dir = next(
        (str(p) for p in _TESSDATA_CANDIDATOS if (p / "por.traineddata").exists()), None
    )
    if not (tesseract_cmd and tessdata_dir):
        print("[AVISO] OCR indisponível (tesseract e/ou o idioma 'por' não encontrados nesta "
              "máquina) — comprovantes sem texto extraível ficarão como 'conteudo_nao_verificavel'.")
        _disponivel = False
        return False

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    os.environ["TESSDATA_PREFIX"] = tessdata_dir
    # Cada processo do tesseract usa 1 thread: o paralelismo vem de rodar várias
    # páginas ao mesmo tempo (ver ocr_paginas), que é bem mais rápido que as
    # threads internas do OpenMP disputando os mesmos núcleos.
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    _disponivel = True
    return True


def _angulo_correcao(caminho_png: str) -> int:
    """
    Detecção de orientação do próprio Tesseract (OSD — Orientation and
    Script Detection): confirmado em dados reais (Palm Beach) que algumas
    imagens embutidas vêm giradas 90°/180°/270° dentro da página (não a
    página em si — `page.rotation` do PyMuPDF continua 0, é a imagem que
    está rotacionada), o que produz texto completamente embaralhado no OCR
    direto. Retorna o ângulo a girar EM SENTIDO HORÁRIO pra corrigir (0 se
    não detectar necessidade ou se a detecção falhar — nunca lança).
    """
    try:
        import pytesseract

        osd = pytesseract.image_to_osd(caminho_png)
        for linha in osd.split("\n"):
            if linha.startswith("Rotate:"):
                return int(linha.split(":")[1].strip())
    except Exception:
        pass
    return 0


def ocr_pagina_pdf(caminho_pdf: Path, indice_pagina_0based: int, dpi: int = 300, lang: str = "por",
                    doc_aberto=None) -> str:
    """
    Renderiza 1 página do PDF (via pymupdf, já dependência do projeto),
    corrige rotação se necessário (ver _angulo_correcao) e roda OCR. Retorna
    "" em qualquer falha — inclusive OCR indisponível, página inexistente ou
    imagem ilegível — nunca lança exceção, para não derrubar a extração
    inteira por causa de 1 página problemática.

    `doc_aberto` (opcional): um `fitz.Document` já aberto, reaproveitado em
    vez de reabrir `caminho_pdf` do zero — confirmado em dados reais (Club
    Park Butantã, arquivo de 333MB/1042 páginas, ~166 chamadas no mesmo
    arquivo) que reabrir o PDF inteiro a cada chamada é o gargalo real, não
    o OCR em si. Quem chama é dono do `doc_aberto` (abre e fecha fora desta
    função) — quando omitido, o comportamento é o de sempre (abre e fecha
    aqui, continua seguro pra uso avulso/1 chamada só).
    """
    if not tesseract_disponivel():
        return ""
    try:
        import fitz
        import pytesseract
        from PIL import Image

        doc = doc_aberto if doc_aberto is not None else fitz.open(str(caminho_pdf))
        try:
            if not (0 <= indice_pagina_0based < len(doc)):
                return ""
            pix = doc[indice_pagina_0based].get_pixmap(dpi=dpi)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                pix.save(tmp_path)
                angulo = _angulo_correcao(tmp_path)
                if angulo:
                    # PIL.Image.rotate() gira ANTI-horário por padrão — o
                    # ângulo do Tesseract é EM SENTIDO HORÁRIO, daí o sinal
                    # trocado (confirmado empiricamente contra dados reais).
                    Image.open(tmp_path).rotate(-angulo, expand=True).save(tmp_path)
                return pytesseract.image_to_string(tmp_path, lang=lang)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        finally:
            if doc_aberto is None:
                doc.close()
    except Exception as exc:
        print(f"[AVISO] OCR falhou na página {indice_pagina_0based + 1} de {caminho_pdf.name}: {exc}")
        return ""


def ocr_imagem_bytes(dados: bytes, lang: str = "por") -> str:
    """
    Como ocr_pagina_pdf, mas para uma imagem já em mãos (ex.: comprovante
    baixado de um sistema externo via link, não embutido no PDF — ver
    conciliacao/condominios/central_das_artes.py). Mesma correção de
    rotação e mesma política de nunca lançar exceção.
    """
    if not tesseract_disponivel():
        return ""
    try:
        import pytesseract
        from PIL import Image

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            Image.open(io.BytesIO(dados)).convert("RGB").save(tmp_path)
            angulo = _angulo_correcao(tmp_path)
            if angulo:
                Image.open(tmp_path).rotate(-angulo, expand=True).save(tmp_path)
            return pytesseract.image_to_string(tmp_path, lang=lang)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except Exception as exc:
        print(f"[AVISO] OCR de imagem falhou: {exc}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# OCR em lote com cache persistente (usado por conciliacao/lirba_pdf.py para ler
# TODAS as páginas de cada "Comprovante de Despesa", não só a primeira).
#
# Por que cache em disco: o OCR de um PDF ContasData inteiro (150–360 páginas de
# imagem) leva minutos; o relatório do mesmo mês é gerado várias vezes (versões
# v1, v2..., testes) e o mês anterior é relido. A chave do cache é uma impressão
# digital do CONTEÚDO do arquivo (tamanho + trechos), não o caminho — o arquivo é
# copiado para uma pasta de versão a cada execução e continua acertando o cache.
# O cache vive em data/_ocr_cache (data/ nunca é versionada).
# ─────────────────────────────────────────────────────────────────────────────
import hashlib
import json
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

_CACHE_DIR = (
    Path(os.environ["OCR_CACHE_DIR"]) if os.environ.get("OCR_CACHE_DIR")
    else Path(__file__).resolve().parent.parent / "data" / "_ocr_cache"
)
_cache_mem: dict[str, dict] = {}
_cache_lock = threading.Lock()


def _impressao_arquivo(caminho: Path) -> str:
    st = Path(caminho).stat()
    h = hashlib.sha1(str(st.st_size).encode())
    with open(caminho, "rb") as f:
        for pos in (0, max(0, st.st_size // 2 - 524288), max(0, st.st_size - 1048576)):
            f.seek(pos)
            h.update(f.read(1048576))
    return h.hexdigest()[:24]


def _cache_do_arquivo(impressao: str) -> dict:
    with _cache_lock:
        if impressao in _cache_mem:
            return _cache_mem[impressao]
        dados: dict = {}
        arq = _CACHE_DIR / f"{impressao}.jsonl"
        if arq.exists():
            try:
                for linha in arq.read_text(encoding="utf-8").splitlines():
                    try:
                        o = json.loads(linha)
                        dados[o["k"]] = o["t"]
                    except Exception:
                        continue
            except Exception:
                pass
        _cache_mem[impressao] = dados
        return dados


def _cache_gravar(impressao: str, chave: str, texto: str) -> None:
    with _cache_lock:
        _cache_mem.setdefault(impressao, {})[chave] = texto
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(_CACHE_DIR / f"{impressao}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"k": chave, "t": texto}, ensure_ascii=False) + "\n")
        except Exception:
            pass  # cache é só otimização


def _texto_pobre(texto: str) -> bool:
    """Leitura que quase certamente falhou (imagem girada, escura...): quase nenhuma palavra."""
    return len(re.findall(r"[A-Za-zÀ-ÿ]{3,}", texto)) < 8



def _ocr_imagem_pil(img, lang: str) -> str:
    import pytesseract
    # --oem 1: só o motor LSTM (o padrão ainda roda o legado junto, ~25% mais lento, sem ganho aqui)
    return pytesseract.image_to_string(img, lang=lang, config="--oem 1")


def _reocr_com_rotacao(doc, indice: int, lang: str, mascarar: bool = False) -> str:
    """Segunda tentativa para páginas de leitura pobre: resolução maior + correção de orientação (OSD)."""
    img0 = _renderizar(doc[indice], 250, mascarar)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        img0.save(tmp_path)
        angulo = _angulo_correcao(tmp_path)
        img = img0.rotate(-angulo, expand=True) if angulo else img0
        return _ocr_imagem_pil(img.convert("RGB"), lang)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _imagem_nativa(doc, pagina):
    """A maior imagem DESENHADA na página, nos pixels originais (ex.: foto de 722x1021 de uma NF), ou None.
    Renderizar a página reamostra essa imagem e, em fotos pequenas/inclinadas, o OCR perde quase tudo; a imagem
    original ampliada (LANCZOS) com leitura de texto esparso recupera o conteúdo."""
    import fitz
    from PIL import Image

    try:
        nomes = set(re.findall(rb"/(\w+)\s+Do", pagina.read_contents()))
        candidatas = [i for i in pagina.get_images(full=True) if i[7].encode() in nomes]
        if not candidatas:
            return None
        maior = max(candidatas, key=lambda i: i[2] * i[3])
        pix = fitz.Pixmap(doc, maior[0])
        if pix.n - pix.alpha > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if img.width < 1800:
            esc = 1800 / img.width
            img = img.resize((int(img.width * esc), int(img.height * esc)), Image.LANCZOS)
        return img
    except Exception:
        return None


def _ocr_imagem_pil_esparso(img, lang: str) -> str:
    """Leitura em dois modos (layout normal + texto esparso) — fotos de documentos inclinadas."""
    import pytesseract
    return (pytesseract.image_to_string(img, lang=lang, config="--oem 1") + "\n"
            + pytesseract.image_to_string(img, lang=lang, config="--oem 1 --psm 11"))


_PALAVRAS_COMUNS = re.compile(
    r"\b(?:de|da|do|das|dos|para|valor|total|data|nota|fiscal|cnpj|cpf|cliente|pagamento|documento|servi[cç]os?|"
    r"banco|conta|vencimento|numero|n[uú]mero|descri[cç][aã]o|empresa|endere[cç]o)\b", re.IGNORECASE)


def _pontuacao_texto(texto: str) -> int:
    """Quantas palavras comuns de documento em português o texto tem (texto girado/espelhado quase não tem)."""
    return len(_PALAVRAS_COMUNS.findall(texto))


def _ocr_imagem_pil_com_rotacao(img, lang: str) -> str:
    """OCR corrigindo a orientação: páginas escaneadas de cabeça para baixo ou de lado saem como texto embaralhado.
    Lê na orientação original e, se o texto quase não tem palavras comuns de documento, tenta o OSD do tesseract e as
    rotações de 180/90/270 graus, ficando com a leitura de maior pontuação."""
    melhor = _ocr_imagem_pil(img.convert("RGB"), lang)
    pontos = _pontuacao_texto(melhor)
    if pontos >= 8:
        return melhor
    candidatos = []
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        img.save(tmp_path)
        angulo = _angulo_correcao(tmp_path)
        if angulo:
            candidatos.append(angulo)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    candidatos += [a for a in (180, 90, 270) if a not in candidatos]
    for angulo in candidatos:
        texto = _ocr_imagem_pil(img.rotate(-angulo, expand=True).convert("RGB"), lang)
        p = _pontuacao_texto(texto)
        if p > pontos:
            melhor, pontos = texto, p
        if pontos >= 8:
            break
    return melhor


def _tem_valor_no_texto_nativo(pagina) -> bool:
    """A página traz, como TEXTO NATIVO (cabeçalho do sistema), algum valor monetário? Nos PDFs de vários sistemas
    (Robotton, Hausy, Manager...) o cabeçalho de cada página "Comprovante de Despesa" repete a linha da listagem,
    inclusive o VALOR — que o OCR da página renderizada leria como se fosse parte do comprovante."""
    try:
        return any(re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}", w[4]) for w in pagina.get_text("words"))
    except Exception:
        return False


def _renderizar(pagina, dpi: int, mascarar: bool, limiar: int | None = None):
    """Imagem PIL da página. Com `mascarar`, pinta de branco todo o texto nativo (cabeçalho do sistema): o OCR
    enxerga só o documento anexado (a imagem), nunca a linha da listagem repetida no cabeçalho."""
    from PIL import Image, ImageDraw

    pix = pagina.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if mascarar:
        esc = dpi / 72.0
        desenho = ImageDraw.Draw(img)
        for x0, y0, x1, y1, *_ in pagina.get_text("words"):
            desenho.rectangle([x0 * esc - 2, y0 * esc - 2, x1 * esc + 2, y1 * esc + 2], fill=(255, 255, 255))
    if limiar:
        img = img.convert("L").point(lambda v, lim=limiar: 255 if v > lim else 0)
    return img


def ocr_paginas(caminho_pdf: Path, indices_0based, dpi: int = 150, lang: str = "por",
                workers: int | None = None, limiar: int | None = None, rotacao: bool = False,
                nativa: bool = False) -> dict[int, str]:
    """
    OCR de várias páginas do mesmo PDF, em paralelo e com cache em disco.
    Retorna {índice_0based: texto}; "" para páginas que falharam (nunca lança).

    150 dpi é a resolução NATIVA das imagens embutidas nos PDFs ContasData
    (1240x1754 px por página A4) — renderizar acima disso só gasta tempo.
    Páginas cuja leitura sai pobre (imagem girada etc.) são refeitas a 250 dpi
    com correção de orientação.

    Páginas cujo cabeçalho NATIVO já traz um valor monetário (linha da listagem repetida no cabeçalho) são lidas
    com o texto nativo mascarado (ver _renderizar) — chave de cache com sufixo "|m". As demais usam a mesma
    chave de sempre (o cabeçalho delas é só "Comprovante de Despesa NNNN / Página N", sem valores).

    `limiar` (0-255): binariza a imagem (preto/branco) antes do OCR — recupera texto sobre fundo
    cinza/colorido (ex.: o quadro "TOTAL" cinza da fatura Sabesp), que a binarização automática do
    tesseract perde. Entra na chave do cache.
    """
    # `rotacao`: detecta a orientação (OSD) de cada página e a corrige antes do OCR — recupera páginas escaneadas
    # de cabeça para baixo, cujo texto sai espelhado/embaralhado. Entra na chave do cache.
    # `nativa`: lê a imagem embutida nos pixels originais, ampliada, em dois modos de layout (ver _imagem_nativa).
    sufixo = (f"|b{limiar}" if limiar else "") + ("|r" if rotacao else "") + ("|n" if nativa else "")
    indices = sorted({int(i) for i in indices_0based})
    resultado: dict[int, str] = {}
    if not indices or not tesseract_disponivel():
        return {i: "" for i in indices}
    try:
        import fitz
    except Exception as exc:
        print(f"[AVISO] OCR em lote indisponível: {exc}")
        return {i: "" for i in indices}
    try:
        impressao = _impressao_arquivo(caminho_pdf)
    except Exception:
        impressao = None
    cache = _cache_do_arquivo(impressao) if impressao else {}
    workers = workers or int(os.environ.get("OCR_WORKERS", 0)) or max(1, min(6, (os.cpu_count() or 4) - 2))
    doc = fitz.open(str(caminho_pdf))
    try:
        mascarar = {i: (0 <= i < len(doc) and _tem_valor_no_texto_nativo(doc[i])) for i in indices}

        def _chave(i: int) -> str:
            return f"{i}|{dpi}|{lang}{sufixo}" + ("|m" if mascarar[i] else "")

        faltam = []
        for i in indices:
            t = cache.get(_chave(i))
            if t is None:
                faltam.append(i)
            else:
                resultado[i] = t
        if not faltam:
            return resultado
        pendentes: dict = {}
        with ThreadPoolExecutor(max_workers=workers) as ex:
            def _coletar(concluidos):
                for fut in concluidos:
                    i = pendentes.pop(fut)
                    try:
                        resultado[i] = fut.result()
                        if impressao and not _texto_pobre(resultado[i]):
                            _cache_gravar(impressao, _chave(i), resultado[i])
                    except Exception as exc:
                        print(f"[AVISO] OCR falhou na página {i + 1} de {Path(caminho_pdf).name}: {exc}")
                        resultado[i] = ""
            for i in faltam:
                if not (0 <= i < len(doc)):
                    resultado[i] = ""
                    continue
                img = _imagem_nativa(doc, doc[i]) if nativa else None
                if img is None:
                    img = _renderizar(doc[i], dpi, mascarar[i], limiar)
                funcao = (_ocr_imagem_pil_esparso if nativa else _ocr_imagem_pil_com_rotacao if rotacao else _ocr_imagem_pil)
                pendentes[ex.submit(funcao, img, lang)] = i
                if len(pendentes) >= workers * 2:
                    feitos, _ = wait(list(pendentes), return_when=FIRST_COMPLETED)
                    _coletar(feitos)
            while pendentes:
                feitos, _ = wait(list(pendentes), return_when=FIRST_COMPLETED)
                _coletar(feitos)
        # segunda tentativa para leituras pobres (sequencial: poucas páginas)
        for i in faltam:
            if not limiar and not rotacao and not nativa and 0 <= i < len(doc) and _texto_pobre(resultado.get(i, "")):
                try:
                    novo = _reocr_com_rotacao(doc, i, lang, mascarar[i])
                    if len(novo.strip()) > len(resultado.get(i, "").strip()):
                        resultado[i] = novo
                except Exception:
                    pass
        if impressao:
            for i in faltam:
                if i in resultado and _chave(i) not in _cache_mem.get(impressao, {}):
                    _cache_gravar(impressao, _chave(i), resultado[i])
    finally:
        doc.close()
    return {i: resultado.get(i, "") for i in indices}
