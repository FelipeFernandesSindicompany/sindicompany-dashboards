"""
Auditoria dos ALERTAS (falso positivo): roda as regras gerais no mês mais recente de cada condomínio (contra o histórico dele),
e para cada alerta confere MECANICAMENTE no arquivo-fonte que os fatos citados existem (valor impresso, trecho da descrição, página).
Só lê arquivos. Saída: data/auditoria_integridade/alertas.jsonl (um registro por alerta).
Uso: python scripts/auditoria_alertas_validacao.py [id1 id2 ...]
"""
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from conciliacao import config_validacao, pasta_prestacao  # noqa: E402
from conciliacao.demonstrativo_reader import _extrair_mes_ano  # noqa: E402
from conciliacao.regras_gerais import pipeline  # noqa: E402
from conciliacao.regras_gerais.textos import TEXTOS  # noqa: E402


def _br(v) -> str:
    return f"{abs(float(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _texto_arquivo(arq: Path) -> tuple[set, str]:
    s = arq.suffix.lower()
    nums: set = set()
    txt = ""
    if s in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(arq, data_only=True, read_only=True)
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for v in row:
                    if isinstance(v, (int, float)):
                        nums.add(round(abs(v), 2))
                    elif isinstance(v, str):
                        txt += v + "\n"
    elif s == ".xls":
        try:
            import xlrd
            wb = xlrd.open_workbook(str(arq))
            for ws in wb.sheets():
                for r in range(ws.nrows):
                    for v in ws.row_values(r):
                        if isinstance(v, (int, float)):
                            nums.add(round(abs(v), 2))
                        elif isinstance(v, str):
                            txt += v + "\n"
        except Exception:
            import quopri
            raw = arq.read_bytes()
            try:
                raw = quopri.decodestring(raw)
            except Exception:
                pass
            txt = raw.decode("latin-1")
    else:
        import fitz
        for pg in fitz.open(arq):
            txt += pg.get_text() + "\n"
    return nums, txt


def _norm(s: str) -> str:
    import unicodedata
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").upper())


def conferir(a, nums: set, txt: str, txt_norm: str) -> list[str]:
    """Fatos do achado que NÃO foram achados no arquivo."""
    d = a.detalhes or {}
    faltou = []
    itens = list(d.get("lancamentos") or []) + list(d.get("itens") or []) + list(d.get("parcelas") or [])
    for i in itens[:12]:
        v = i.get("valor")
        if v is not None and abs(v) > 0.005 and round(abs(v), 2) not in nums and _br(v) not in txt:
            faltou.append(f"valor {_br(v)} do lançamento '{(i.get('descricao') or '')[:40]}' não está no arquivo")
        desc = _norm((i.get("descricao") or "")[:25])
        if len(desc) >= 8 and desc not in txt_norm:
            faltou.append(f"descrição '{(i.get('descricao') or '')[:40]}' não está no arquivo")
    if a.valor_encontrado is not None and abs(a.valor_encontrado) > 0.005 and a.tipo not in ("observacao_gestor", "previsto_realizado_inconsistente"):
        v = a.valor_encontrado
        somas_ok = a.tipo in ("parcelas_mesmo_mes", "receita_negativa", "rendimento_desproporcional", "nf_repetida_entre_meses")
        if not somas_ok and round(abs(v), 2) not in nums and _br(v) not in txt:
            faltou.append(f"valor do alerta {_br(v)} não está no arquivo")
    return faltou


def main():
    ids = sys.argv[1:]
    saida = RAIZ / "data" / "auditoria_integridade"
    saida.mkdir(parents=True, exist_ok=True)
    with open(saida / "alertas.jsonl", "w", encoding="utf-8") as fo:
        for c in json.load(open(RAIZ / "config/condominios.json", encoding="utf-8"))["condominios"]:
            if not c.get("ativo", True) or c["id"] == "demonstracao" or (ids and c["id"] not in ids):
                continue
            try:
                condo = config_validacao.aplicar(c)
                pasta = pasta_prestacao.pasta_do_condominio(condo)
                arqs = {}
                for a in pasta.rglob("*"):
                    if a.is_file() and a.suffix.lower() in (".pdf", ".xlsx", ".xls") and not a.name.lower().startswith(("valida", "logo")):
                        ma = _extrair_mes_ano(a.name)
                        if ma and (ma not in arqs or a.parent == pasta):
                            arqs[ma] = a
                m, y = sorted(arqs, key=lambda k: (k[1], k[0]), reverse=True)[0]
                mes = f"{y}-{m:02d}"
                achados, status, avisos = pipeline.executar(condo, mes, arqs[(m, y)], pasta)
                nums, txt = _texto_arquivo(arqs[(m, y)])
                txt_norm = _norm(txt)
                for a in achados:
                    t = TEXTOS[a.tipo](a) if a.tipo in TEXTOS else ("(sem texto)", "", "")
                    fo.write(json.dumps({"id": c["id"], "mes": mes, "arquivo": arqs[(m, y)].name, "achado": a.id, "tipo": a.tipo,
                                         "regra": a.regra_aplicada, "valor": a.valor_encontrado, "titulo": t[0], "texto": t[1],
                                         "nao_achado_no_arquivo": conferir(a, nums, txt, txt_norm)}, ensure_ascii=False) + "\n")
                fo.flush()
                print(c["id"], mes, len(achados), flush=True)
            except Exception as e:
                print(c["id"], "ERRO", type(e).__name__, str(e)[:150], flush=True)
                fo.write(json.dumps({"id": c["id"], "erro": str(e)[:200]}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
