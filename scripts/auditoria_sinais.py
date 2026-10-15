"""Compara o sinal dos lançamentos: leitura das regras gerais (com sinal) x registros do conciliador legado (registros_comprovantes.json)."""
import glob
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
RAIZ = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\Projeto Automatização Dashboard")
sys.path.insert(0, str(RAIZ))
from conciliacao import config_validacao, pasta_prestacao
from conciliacao.demonstrativo_reader import localizar_arquivo_mes
from conciliacao.regras_gerais.extratores import get_extrator

C = {x["id"]: x for x in json.load(open(RAIZ / "config" / "condominios.json", encoding="utf-8"))["condominios"]}
alvos = [(p.replace("\\", "/").split("/")[1], p.replace("\\", "/").split("/")[3]) for p in glob.glob(str(RAIZ / "data" / "*" / "conciliacao" / "2026-0[5-8]").replace("\\", "/"))]
alvos = sorted({(Path(p).parts[-3], Path(p).parts[-1]) for p in glob.glob(str(RAIZ / "data" / "*" / "conciliacao" / "2026-0[78]"))})


def ultima(cid, mes):
    vs = glob.glob(str(RAIZ / "data" / cid / "conciliacao" / mes / "v*"))
    vs = sorted(vs, key=lambda p: int(re.search(r"v(\d+)$", p.replace("\\", "/")).group(1)))
    return Path(vs[-1]) if vs else None


for cid, mes in alvos:
    if cid not in C:
        continue
    condo = config_validacao.aplicar(C[cid])
    pasta = pasta_prestacao.pasta_do_condominio(condo)
    if pasta is None:
        continue
    arq = localizar_arquivo_mes(pasta, int(mes[5:]), int(mes[:4]))
    ex = get_extrator(condo)
    v = ultima(cid, mes)
    if arq is None or ex is None or v is None or not (v / "registros_comprovantes.json").exists():
        continue
    try:
        d = ex.extrair(arq, mes)
    except Exception as e:
        print(f"{cid} {mes}: falha leitura {e}")
        continue
    reg = json.load(open(v / "registros_comprovantes.json", encoding="utf-8"))
    reg = reg.get("registros", reg) if isinstance(reg, dict) else reg
    desp = [r for r in reg if r["tipo_documento"] == "despesa_listada"]
    neg_verdade = [l for l in d.lancamentos if l.valor < -0.005]
    neg_receita = [r for r in d.receitas if r.valor < -0.005]
    neg_legado = [r for r in desp if r["valor"] < -0.005]
    # lançamentos negativos da verdade cujo valor absoluto aparece POSITIVO no legado com descrição parecida
    perdidos = []
    for l in neg_verdade:
        chave = re.sub(r"\W+", "", (l.descricao or "").lower())[:20]
        for r in desp:
            if abs(abs(r["valor"]) - abs(l.valor)) < 0.005 and chave and chave in re.sub(r"\W+", "", (r["descricao"] or "").lower()):
                if r["valor"] > 0:
                    perdidos.append((l.descricao[:50], l.valor, r["valor"]))
                break
    print(f"{cid:30s} {mes} lanc={len(d.lancamentos):4d} neg(verdade)={len(neg_verdade):2d} neg(legado)={len(neg_legado):2d} receitas_neg={len(neg_receita):2d} SINAL_PERDIDO={len(perdidos)}"
          + (f" {perdidos[:3]}" if perdidos else ""))
