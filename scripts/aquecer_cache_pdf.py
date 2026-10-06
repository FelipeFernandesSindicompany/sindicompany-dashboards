"""
Aquecimento do cache de texto dos PDFs da Validação (conciliacao/pdf_cache.py).

Lê, UMA vez, o PDF mais recente de cada condomínio — o "mês anterior" da próxima validação — e deixa o
texto das páginas gravado em data/cache_texto_pdf. Assim a primeira validação de cada condomínio já
encontra o mês anterior pronto e não precisa ler centenas de páginas de novo.

Seguro para interromper e rodar de novo: PDF já completo no cache é pulado. Só LÊ os arquivos.
uso: python -X utf8 scripts/aquecer_cache_pdf.py [--processos 3] [id_condominio ...]
"""
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
LOG = RAIZ / "data" / "aquecer_cache_pdf.log"


def _registrar(texto: str) -> None:
    linha = f"{time.strftime('%H:%M:%S')} {texto}"
    print(linha, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def _aquecer(args):
    condo_id, caminho = args
    import pdfplumber

    from conciliacao import pdf_cache

    inicio = time.time()
    try:
        chave = pdf_cache._chave_arquivo(caminho)
        if chave is not None and pdf_cache._completo(chave):
            return condo_id, caminho, 0, 0.0, "já estava no cache"
        with pdfplumber.open(caminho) as pdf:
            paginas = len(pdf.pages)
            for pagina in pdf.pages:
                pagina.extract_text()
        pdf_cache._descarregar_tudo()
        return condo_id, caminho, paginas, time.time() - inicio, "ok"
    except Exception as exc:  # um PDF ruim não pára o aquecimento
        return condo_id, caminho, 0, time.time() - inicio, f"ERRO {type(exc).__name__}: {str(exc)[:120]}"


def _ultimos_pdfs(ids):
    from conciliacao import config_validacao, pasta_prestacao
    from conciliacao.demonstrativo_reader import _extrair_mes_ano

    saida = []
    for c in json.load(open(RAIZ / "config" / "condominios.json", encoding="utf-8"))["condominios"]:
        if ids and c["id"] not in ids:
            continue
        pasta = pasta_prestacao.pasta_do_condominio(config_validacao.aplicar(c))
        if pasta is None:
            continue
        arqs = {}
        for a in pasta.rglob("*.pdf"):
            if a.name.lower().startswith(("valida", "logo")):
                continue
            ma = _extrair_mes_ano(a.name)
            if ma and (ma not in arqs or a.parent == pasta):
                arqs[ma] = a
        if arqs:
            k = max(arqs, key=lambda m: (m[1], m[0]))
            saida.append((c["id"], str(arqs[k])))
    return saida


def main():
    argv = sys.argv[1:]
    processos = 3
    if "--processos" in argv:
        i = argv.index("--processos")
        processos = int(argv[i + 1])
        del argv[i:i + 2]
    fila = _ultimos_pdfs(set(argv))
    _registrar(f"início: {len(fila)} PDFs, {processos} processos")
    feitos = 0
    with ProcessPoolExecutor(max_workers=processos) as ex:
        futuros = [ex.submit(_aquecer, item) for item in fila]
        for fut in as_completed(futuros):
            condo_id, caminho, paginas, seg, status = fut.result()
            feitos += 1
            _registrar(f"[{feitos}/{len(fila)}] {condo_id}: {Path(caminho).name} — {paginas} págs, {seg:.0f}s — {status}")
    _registrar("fim")


if __name__ == "__main__":
    main()
