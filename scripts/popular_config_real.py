"""
Popula o config com todos os 51 condomínios reais detectados na pasta HTML.
Lê o título de cada HTML e cria a entrada no config.
Empresa gestora fica em branco — você preenche depois.
Uso: python scripts/popular_config_real.py
"""
import json, re, html as html_mod, unicodedata
from pathlib import Path

ROOT = Path(__file__).parent.parent
HTML_DIR = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\HTML")
CONFIG_PATH = ROOT / "config" / "condominios.json"

CORES = [
    "#2563eb","#7c3aed","#db2777","#ea580c","#ca8a04",
    "#16a34a","#0891b2","#4f46e5","#be185d","#b45309",
    "#0d9488","#dc2626","#9333ea","#2563eb","#16a34a",
]


def slugify(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def titulo_limpo(path: Path) -> str:
    txt = path.read_text(encoding="utf-8", errors="ignore")[:2000]
    m = re.search(r"<title[^>]*>(.*?)</title>", txt, re.IGNORECASE)
    if not m:
        return path.stem.replace("Dashboard_Financeiro_", "").replace("_", " ")
    t = html_mod.unescape(m.group(1))
    # Remove prefixos
    for p in [
        r"^Dashboard Financeiro\s*[–\-—·]\s*",
        r"^Dashboard Financeiro\s+",
        r"^Condom[ií]nio\s+",
        r"^Cond\.\s+",
        r"^Edif[ií]cio\s+",
    ]:
        t = re.sub(p, "", t, flags=re.IGNORECASE).strip()
    return t.strip()


def unidades_html(path: Path) -> int:
    txt = path.read_text(encoding="utf-8", errors="ignore")[:5000]
    m = re.search(r"unidades['\"]?\s*:\s*['\"]?(\d+)", txt, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s+unidades", txt, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


def empresa_html(path: Path) -> str:
    txt = path.read_text(encoding="utf-8", errors="ignore")[:5000]
    m = re.search(r"administradora['\"]?\s*:\s*['\"]([^'\"]+)", txt, re.IGNORECASE)
    if m:
        return slugify(m.group(1))
    return "a_definir"


with open(CONFIG_PATH, encoding="utf-8") as f:
    config = json.load(f)

# Indexa existentes por html_file
existentes_por_html = {c.get("html_file"): c for c in config["condominios"] if c.get("html_file")}
existentes_por_id   = {c["id"]: c for c in config["condominios"]}

htmls = sorted([f for f in HTML_DIR.glob("*.html") if f.name != "index.html"])
adicionados = 0

for i, html_path in enumerate(htmls):
    # Já mapeado?
    if html_path.name in existentes_por_html:
        continue

    nome = titulo_limpo(html_path)
    cond_id = slugify(nome)
    # Garante ID único
    base_id = cond_id
    n = 2
    while cond_id in existentes_por_id:
        cond_id = f"{base_id}_{n}"
        n += 1

    unidades = unidades_html(html_path)
    empresa = empresa_html(html_path)

    novo = {
        "id": cond_id,
        "nome": nome,
        "empresa_gestora": empresa,
        "pasta_dados": f"data/{cond_id}",
        "html_file": html_path.name,
        "ativo": True,
        "cor": CORES[i % len(CORES)],
        "unidades": unidades,
    }
    config["condominios"].append(novo)
    existentes_por_id[cond_id] = novo

    pasta = ROOT / "data" / cond_id
    pasta.mkdir(parents=True, exist_ok=True)

    print(f"[+] {nome:<45} empresa: {empresa}")
    adicionados += 1

# Remove condomínio de exemplo se existir
config["condominios"] = [
    c for c in config["condominios"]
    if c["id"] != "edificio_exemplo"
]

with open(CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print(f"\n[OK] {adicionados} condomínios adicionados ao config.")
if adicionados > 0:
    print("\nPróximo passo:")
    print("  Abra config/condominios.json e ajuste 'empresa_gestora' para cada")
    print("  condomínio (coloque o ID da empresa que envia o XLSX).")
    print("  Depois: python scripts/injetar_mes.py --todos --mes YYYY-MM")
