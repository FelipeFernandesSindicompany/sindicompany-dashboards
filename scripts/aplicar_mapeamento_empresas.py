"""
Aplica o mapeamento correto de empresa_gestora para cada condomínio
com base nos arquivos identificados.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "condominios.json"

with open(CONFIG_PATH, encoding="utf-8") as f:
    config = json.load(f)

# Mapeamento: id_condominio → empresa_gestora
MAPEAMENTO = {
    # ── Habitacional XLSX (prestacao_contas_N_YYYY.xlsx) ──
    "alvorada":               "habitacional_xlsx",
    "baturite":               "habitacional_xlsx",
    "cinque_terre_residenza": "habitacional_xlsx",
    "cores":                  "habitacional_xlsx",
    "elo_elo_duo":            "habitacional_xlsx",
    "816_fit_casa_rio_bonito":"habitacional_xlsx",
    "go_barra_funda":         "habitacional_xlsx",
    "go_liberdade":           "habitacional_xlsx",
    "living_for_consolacao":  "habitacional_xlsx",
    "onze_22":                "habitacional_xlsx",
    "port_saint_tropez":      "habitacional_xlsx",
    "sublime":                "habitacional_xlsx",
    "victoria":               "habitacional_xlsx",
    "vista_verde":            "habitacional_xlsx",
    "vivaz_vila_guilherme":   "habitacional_xlsx",

    # ── Lello XLS (prestacaocontas_XXXX_YYYY_MM.xls) ──
    "barra_viva_i_alegria":       "lello_xls",
    "hub_home_club_tatuape":      "lello_xls",
    "splendor_square":            "lello_xls",
    "residencial_villa_park_osasco": "lello_xls",

    # ── LIRBA PDF (Prestação de Contas MM.YYYY.PDF — grande) ──
    "gravura_residencial":        "lirba_pdf",
    "gravura_studio":             "lirba_pdf",
    "highlights_dr_nelson_moretti": "lirba_pdf",
    "organy_residencial":         "lirba_pdf",
    "organy_studio":              "lirba_pdf",
    "730_padre_carvalho":         "lirba_pdf",
    "pra_a_saude_by_you_comercial": "lirba_pdf",
    "pra_a_saude_residencial":    "lirba_pdf",
    "pra_a_saude_moradia":        "lirba_pdf",
    "residencial_napoleao":       "lirba_pdf",
    "parque_saint_afonso":        "lirba_pdf",
    "serra_da_mantiqueira":       "lirba_pdf",
    "upper_itaim":                "lirba_pdf",
    "vibra_butanta":              "lirba_pdf",
    "res_villa_sardenha":         "lirba_pdf",
    "reserva_verde":              "lirba_pdf",
    "top_nine":                   "lirba_pdf",
    "residencial_blue_sky":       "lirba_pdf",
    "club_park_butanta":          "lirba_pdf",
    "i_gloo_alphaville":          "lirba_pdf",
    "monte_tabor":                "lirba_pdf",
    "palm_beach":                 "lirba_pdf",
    "platinum_building_berrini":  "lirba_pdf",
    "nyc":                        "lirba_pdf",
    "maison_du_rhone":            "lirba_pdf",

    # ── DataDigitus PDF ──
    "cap_d_antibes":              "datadigitus_pdf",

    # ── Iello PDF ──
    "giardino_d_italia":          "iello_pdf",
    "vita_parque":                "iello_pdf",

    # ── Patrícia (XLS próprio — verificar formato) ──
    "patricia":                   "lirba_pdf",  # provisório até verificar

    # ── Plano (verificar) ──
    "plano_estacao_campo_limpo":  "lirba_pdf",
    "plano_mooca_pra_a_lion_iii": "lirba_pdf",
    "plano_rio_bonito":           "lirba_pdf",
}

# Aplica mapeamento
atualizados = 0
nao_encontrados = []
for cond in config["condominios"]:
    cid = cond["id"]
    empresa = MAPEAMENTO.get(cid)
    if empresa:
        cond["empresa_gestora"] = empresa
        atualizados += 1
    else:
        nao_encontrados.append(cid)

with open(CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print(f"[OK] {atualizados} condomínios mapeados.")
if nao_encontrados:
    print(f"\nSem mapeamento definido ({len(nao_encontrados)}):")
    for c in nao_encontrados:
        print(f"  - {c}")
