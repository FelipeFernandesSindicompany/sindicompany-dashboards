import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
config = json.loads((ROOT / "config" / "condominios.json").read_text(encoding="utf-8"))

fix = {
    "plano_mooca_praca_lion_iii": "lirba_pdf",
    "praca_saude_by_you_comercial": "lirba_pdf",
    "praca_saude_residencial": "lirba_pdf",
    "praca_saude_moradia": "lirba_pdf",
}
for c in config["condominios"]:
    if c["id"] in fix:
        c["empresa_gestora"] = fix[c["id"]]
        print(f"[OK] {c['id']} -> {fix[c['id']]}")

(ROOT / "config" / "condominios.json").write_text(
    json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("Salvo.")
