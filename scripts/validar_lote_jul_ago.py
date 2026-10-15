"""Validação em lote (julho/agosto 2026): para cada condomínio com arquivo do mês na pasta do projeto,
roda extrair -> interpretar -> render (um processo por condomínio/mês) e salva o relatório na pasta
"Validação de Balancetes" do próprio condomínio.

Não sobrescreve relatório existente (pula o mês) e nunca mexe em outro condomínio além do que está na fila.
  --plano           só lista o que seria feito
  --so ID[,ID]      restringe a condomínios
  --meses 2026-07,2026-08
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from conciliacao import pasta_prestacao
from conciliacao.demonstrativo_reader import localizar_arquivo_mes

EXCLUIR = {"fatto_morumbi"}
PLANILHA = Path.home() / "OneDrive - Perfil de E-mail" / "Verificação Mensal de Balancetes.xlsx"
# nome (normalizado) na planilha de controle -> id do condomínio
ID_PLANILHA = {
    "CINQUE TERRE RESIDENZA": "cinque_terre_residenza", "CAP D ANTIBES": "cap_d_antibes", "CLUB PARK BUTANTA": "club_park_butanta",
    "MOEMA TOP NINE": "top_nine", "PALM BEACH": "palm_beach", "NAPOLEAO": "residencial_napoleao",
    "ELO ELO DUO CAMINHOS DA LAPA": "elo_elo_duo", "FIT CASA RIO BONITO": "fit_casa_rio_bonito",
    "GIARDINO D ITALIA": "giardino_d_italia", "GO BARRA FUNDA": "go_barra_funda", "GO LIBERDADE": "go_liberdade",
    "GUARATAMBE": "guaratambe", "HIGHLIGHRS JARDIM PRUDENCIA": "highlights_dr_nelson_moretti",
    "HUB HOME CLUB TATUAPE": "hub_home_club_tatuape", "IGLOO ALPHAVILLE": "i_gloo_alphaville", "JAU 1894": "jau_1894",
    "LIVING FOR CONSOLACAO": "living_for_consolacao", "MAISON PATRICIA": "patricia", "NYC BERRINI": "nyc",
    "ONZE22": "onze_22", "PARQUE SAINT AFONSO": "parque_saint_afonso", "BLUESKY": "residencial_blue_sky",
    "VITA PARQUE": "vita_parque", "ORGANY": ("organy_residencial", "organy_studio"), "RESIDENCIAL VITA PARQUE": "vita_parque", "RES NAPOLEAO": "residencial_napoleao", "SAINT SIMON": "saint_simon", "SPLENDOR SQUARE": "splendor_square",
    "VIBRA BUTANTA": "vibra_butanta", "VILLA PARK OSASCO": "residencial_villa_park_osasco", "VERA CRUZ": "vera_cruz",
}


def _norm(s):
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"^(CONDOMINIO|ED\.?|EDIFICIO|RES\.?|RESIDENCIAL)\s+", "", s.strip())
    s = re.sub(r"^(ED\.?|RES\.?)\s+", "", s)
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def pendentes_planilha():
    """(id, 'YYYY-MM') com a célula do mês em branco na planilha de controle."""
    import openpyxl
    ws = openpyxl.load_workbook(PLANILHA, data_only=True)["Verificação Mensal"]
    pend = set()
    for r in ws.iter_rows(min_row=4, values_only=True):
        if not r[1]:
            continue
        if str(r[1]).startswith("LEGENDA"):
            break
        cid = ID_PLANILHA.get(_norm(r[1]))
        if cid is None:
            continue
        for um in ((cid,) if isinstance(cid, str) else cid):
            if not r[5]:
                pend.add((um, "2026-07"))
            if not r[6]:
                pend.add((um, "2026-08"))
    return pend
SCRIPT = ROOT / "scripts" / "gerar_relatorio_conciliacao.py"


def fila(meses, so):
    condos = json.load(open(ROOT / "config" / "condominios.json", encoding="utf-8"))["condominios"]
    val = json.load(open(ROOT / "config" / "validacao_balancetes.json", encoding="utf-8"))["condominios"]
    saida = []
    pend = pendentes_planilha()
    for c in condos:
        if c["id"] in EXCLUIR or (so and c["id"] not in so):
            continue
        pasta = pasta_prestacao.pasta_do_condominio({**c, **(val.get(c["id"]) or {})})
        if pasta is None:
            continue
        for mes in meses:
            if (c["id"], mes) not in pend:
                continue
            arq = localizar_arquivo_mes(pasta, int(mes[5:7]), int(mes[:4]))
            if arq is None:
                continue
            existe = [f for f in (pasta / "Validação de Balancetes").glob(f"*{mes[5:7]}.{mes[:4]}*.pdf")] \
                if (pasta / "Validação de Balancetes").is_dir() else []
            saida.append({"id": c["id"], "nome": c["nome"], "mes": mes, "arquivo": arq, "pasta": pasta,
                          "ja_tem_relatorio": bool(existe)})
    return saida


def rodar(item):
    base = [sys.executable, str(SCRIPT), "--condominio", item["id"], "--mes", item["mes"]]
    env = {"PYTHONUTF8": "1"}
    import os
    env = {**os.environ, **env}
    log = []
    for etapa, extra in (("extrair", ["--arquivo", str(item["arquivo"])]), ("interpretar", []), ("render", [])):
        r = subprocess.run(base + extra + ["--etapa", etapa], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, cwd=str(ROOT))
        log.append(f"--- {etapa} (rc={r.returncode})\n{r.stdout[-3000:]}\n{r.stderr[-1500:]}")
        if r.returncode != 0:
            return False, "\n".join(log)
    return True, "\n".join(log)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plano", action="store_true")
    ap.add_argument("--so")
    ap.add_argument("--meses", default="2026-07,2026-08")
    a = ap.parse_args()
    itens = fila(a.meses.split(","), set(a.so.split(",")) if a.so else None)
    pend = [i for i in itens if not i["ja_tem_relatorio"]]
    print(f"{len(itens)} arquivo(s) encontrados; {len(itens) - len(pend)} já têm relatório (pulados); {len(pend)} a validar")
    for i in itens:
        print(f"  {'JÁ TEM' if i['ja_tem_relatorio'] else 'VALIDAR'}  {i['id']:32s} {i['mes']}  {i['arquivo'].name}")
    if a.plano:
        return
    logdir = ROOT / "data" / "_lote_jul_ago"
    logdir.mkdir(parents=True, exist_ok=True)
    resumo = []
    for n, i in enumerate(pend, 1):
        t0 = time.time()
        print(f"\n[{n}/{len(pend)}] {i['id']} {i['mes']} ...", flush=True)
        ok, log = rodar(i)
        (logdir / f"{i['id']}_{i['mes']}.log").write_text(log, encoding="utf-8")
        print(f"   {'OK' if ok else 'FALHOU'} em {time.time() - t0:.0f}s", flush=True)
        resumo.append({"id": i["id"], "mes": i["mes"], "ok": ok})
        (logdir / ("resumo_" + (a.so or "geral").replace(",", "_") + ".json")).write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nFIM", sum(r["ok"] for r in resumo), "ok /", len(resumo))


main()
