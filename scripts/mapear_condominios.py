"""
Utilitário interativo: mapeia cada HTML real para um condomínio no config.
Roda uma vez, atualiza config/condominios.json com o campo 'html_file'.
Uso: python scripts/mapear_condominios.py
"""
import json, re, html as html_mod
from pathlib import Path

ROOT = Path(__file__).parent.parent
HTML_DIR = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\HTML")
CONFIG_PATH = ROOT / "config" / "condominios.json"

with open(CONFIG_PATH, encoding="utf-8") as f:
    config = json.load(f)

htmls = sorted([f for f in HTML_DIR.glob("*.html") if f.name != "index.html"])


def titulo_html(path: Path) -> str:
    txt = path.read_text(encoding="utf-8", errors="ignore")[:2000]
    m = re.search(r"<title[^>]*>(.*?)</title>", txt, re.IGNORECASE)
    if not m:
        return path.stem
    t = html_mod.unescape(m.group(1))
    t = re.sub(r"^Dashboard Financeiro\s*[–\-—]\s*", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"^Condom[ií]nio\s+", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"^Cond\.\s+", "", t, flags=re.IGNORECASE).strip()
    return t


def slugify(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


print("\n=== Mapeamento HTML → Condomínios ===")
print("Este script lê cada HTML e cria/atualiza as entradas no config.\n")

# Condomínios já mapeados
mapeados = {c.get("html_file") for c in config["condominios"] if c.get("html_file")}

novos = 0
for html_path in htmls:
    if html_path.name in mapeados:
        continue  # já mapeado

    titulo = titulo_html(html_path)
    id_sugerido = slugify(titulo)

    # Verifica se já existe no config pelo id
    existente = next((c for c in config["condominios"] if c["id"] == id_sugerido), None)

    if existente:
        existente["html_file"] = html_path.name
        print(f"[OK mapeado] {html_path.name} → {existente['nome']}")
        novos += 1
        continue

    # Novo condomínio — adiciona ao config
    print(f"\n[NOVO] {html_path.name}")
    print(f"  Título detectado: {titulo}")

    nome = input(f"  Nome do condomínio (Enter = '{titulo}'): ").strip() or titulo
    empresa = input(f"  Empresa gestora (ex: empresa_a): ").strip() or "empresa_a"
    unidades = input(f"  Número de unidades: ").strip()
    try:
        unidades = int(unidades)
    except ValueError:
        unidades = 0

    novo = {
        "id": id_sugerido,
        "nome": nome,
        "empresa_gestora": empresa,
        "pasta_dados": f"data/{id_sugerido}",
        "html_file": html_path.name,
        "ativo": True,
        "cor": "#2563eb",
        "unidades": unidades,
    }
    config["condominios"].append(novo)

    pasta = ROOT / "data" / id_sugerido
    pasta.mkdir(parents=True, exist_ok=True)
    novos += 1

with open(CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print(f"\n[OK] {novos} entradas atualizadas em config/condominios.json")
print("Agora rode: python scripts/injetar_mes.py --todos --mes YYYY-MM")
