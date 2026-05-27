import os, re, json
from pathlib import Path

d = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\HTML")
results = []

for f in sorted(d.glob("*.html")):
    if f.name.lower() == "desktop.ini":
        continue
    txt = f.read_text(encoding="utf-8", errors="ignore")

    # Título
    title_m = re.search(r"<title[^>]*>(.*?)</title>", txt[:3000], re.IGNORECASE)
    title = title_m.group(1).strip() if title_m else f.stem.replace("_", " ")

    # Remove prefixo genérico
    title = re.sub(r"^Dashboard Financeiro\s*[–\-]\s*", "", title).strip()
    title = re.sub(r"^Condomínio\s+", "", title).strip()

    # Mês de referência (busca nos primeiros 8000 chars)
    excerpt = txt[:8000]
    mes_m = re.search(
        r"(janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
        r"[^\w]*(?:de\s*)?(20\d\d)",
        excerpt, re.IGNORECASE
    )
    mes = mes_m.group(0).strip().title() if mes_m else ""

    results.append({"file": f.name, "title": title, "mes": mes})

# Saída JSON para usar no próximo script
out = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\Projeto Automatização Dashboard\scripts\_html_info.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Extraídos {len(results)} dashboards")
for r in results:
    print(f"  {r['title']:<45} {r['mes']}")
