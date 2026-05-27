"""
Gera index.html na pasta HTML com links para todos os dashboards existentes.
"""
import json, re, html
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
JSON_PATH = ROOT / "scripts" / "_html_info.json"
HTML_DIR  = Path(r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Área de Trabalho\HTML")
OUT_PATH  = HTML_DIR / "index.html"

dados = json.loads(JSON_PATH.read_text(encoding="utf-8"))


def limpar_titulo(t: str) -> str:
    # Decodifica entidades HTML
    t = html.unescape(t)
    # Remove prefixos genéricos
    prefixos = [
        r"^Dashboard Financeiro\s*[–\-—·•]\s*",
        r"^Dashboard Financeiro\s+",
        r"^Condomínio\s+",
        r"^Cond\.\s+",
        r"^Edifício\s+",
        r"^Residencial\s+",
        r"^Res\.\s+",
    ]
    for p in prefixos:
        t = re.sub(p, "", t, flags=re.IGNORECASE).strip()
    return t.strip()


# Paleta de cores por inicial (visual variado)
CORES = [
    "#2563eb","#7c3aed","#db2777","#ea580c","#ca8a04",
    "#16a34a","#0891b2","#4f46e5","#be185d","#b45309",
    "#0d9488","#dc2626","#9333ea","#2563eb","#16a34a",
]

cards_html = []
for i, item in enumerate(dados):
    nome = limpar_titulo(item["title"])
    arquivo = item["file"]
    mes = item["mes"] or "—"
    cor = CORES[i % len(CORES)]
    inicial = nome[0].upper() if nome else "?"

    card = f"""
    <a href="{arquivo}" class="card" style="--cor:{cor}" target="_blank">
      <div class="card-avatar">{inicial}</div>
      <div class="card-body">
        <div class="card-nome">{nome}</div>
        <div class="card-mes">{mes}</div>
      </div>
      <span class="card-arrow">→</span>
    </a>"""
    cards_html.append(card)

total = len(dados)
gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M")

PAGE = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Sindicompany — Central de Dashboards Financeiros</title>
  <style>
    :root {{
      --brand: #171B2E;
      --accent: #E87722;
      --bg: #F0F2F8;
      --card: #ffffff;
      --text: #1e293b;
      --muted: #64748b;
      --border: #e2e8f0;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}

    /* ── Header ── */
    header {{
      background: var(--brand);
      color: white;
      padding: 1.4rem 2rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 1rem;
      position: sticky;
      top: 0;
      z-index: 10;
      box-shadow: 0 2px 12px rgba(0,0,0,.3);
    }}
    .header-left {{ display: flex; align-items: center; gap: 1rem; }}
    .logo-badge {{
      width: 40px; height: 40px;
      background: var(--accent);
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-weight: 900; font-size: 1.1rem; color: white; flex-shrink: 0;
    }}
    header h1 {{ font-size: 1.2rem; font-weight: 700; }}
    header .sub {{ font-size: .8rem; opacity: .65; margin-top: 2px; }}
    .total-badge {{
      background: rgba(232,119,34,.25);
      border: 1px solid rgba(232,119,34,.5);
      color: #E87722;
      padding: .35rem .9rem;
      border-radius: 999px;
      font-size: .82rem;
      font-weight: 700;
    }}

    /* ── Barra de busca ── */
    .search-wrap {{
      max-width: 1200px;
      margin: 2rem auto 1.5rem;
      padding: 0 1.5rem;
    }}
    .search-box {{
      display: flex;
      align-items: center;
      background: var(--card);
      border: 1.5px solid var(--border);
      border-radius: 12px;
      padding: .6rem 1.1rem;
      gap: .6rem;
      box-shadow: 0 1px 4px rgba(0,0,0,.06);
      max-width: 480px;
    }}
    .search-box input {{
      border: none; outline: none;
      font-size: .95rem; width: 100%;
      background: transparent; color: var(--text);
    }}
    .search-icon {{ color: var(--muted); font-size: 1.1rem; }}

    /* ── Grid ── */
    .grid-wrap {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 0 1.5rem 3rem;
    }}
    .contagem {{
      font-size: .78rem;
      color: var(--muted);
      margin-bottom: 1rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .05em;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 1rem;
    }}

    /* ── Card ── */
    .card {{
      background: var(--card);
      border-radius: 14px;
      padding: 1rem 1.1rem;
      display: flex;
      align-items: center;
      gap: .9rem;
      text-decoration: none;
      color: var(--text);
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
      border: 1.5px solid transparent;
      transition: transform .15s, box-shadow .15s, border-color .15s;
      border-left: 4px solid var(--cor);
    }}
    .card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(0,0,0,.11);
      border-color: var(--cor);
      border-left-color: var(--cor);
    }}
    .card-avatar {{
      width: 40px; height: 40px; flex-shrink: 0;
      border-radius: 10px;
      background: var(--cor);
      color: white;
      display: flex; align-items: center; justify-content: center;
      font-weight: 800; font-size: 1.1rem;
      opacity: .9;
    }}
    .card-body {{ flex: 1; min-width: 0; }}
    .card-nome {{
      font-weight: 700;
      font-size: .9rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      line-height: 1.3;
    }}
    .card-mes {{
      font-size: .75rem;
      color: var(--muted);
      margin-top: .2rem;
    }}
    .card-arrow {{
      color: var(--muted);
      font-size: 1rem;
      transition: transform .15s, color .15s;
      flex-shrink: 0;
    }}
    .card:hover .card-arrow {{
      transform: translateX(3px);
      color: var(--cor);
    }}

    /* ── Empty state ── */
    .empty {{
      grid-column: 1/-1;
      text-align: center;
      padding: 3rem;
      color: var(--muted);
      font-size: .95rem;
    }}

    /* ── Footer ── */
    footer {{
      text-align: center;
      font-size: .74rem;
      color: var(--muted);
      padding: 0 0 2.5rem;
    }}

    @media (max-width: 600px) {{
      header {{ padding: 1rem; }}
      .card-nome {{ font-size: .85rem; }}
    }}
  </style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="logo-badge">S</div>
    <div>
      <h1>Sindicompany</h1>
      <div class="sub">Central de Dashboards Financeiros</div>
    </div>
  </div>
  <span class="total-badge">{total} condomínios</span>
</header>

<div class="search-wrap">
  <div class="search-box">
    <span class="search-icon">🔍</span>
    <input type="text" id="busca" placeholder="Buscar condomínio..." oninput="filtrar()" autocomplete="off"/>
  </div>
</div>

<div class="grid-wrap">
  <div class="contagem" id="contagem">{total} dashboards disponíveis</div>
  <div class="grid" id="grid">
    {"".join(cards_html)}
    <div class="empty" id="empty" style="display:none">Nenhum condomínio encontrado.</div>
  </div>
</div>

<footer>Gerado em {gerado_em} · Sindicompany Administradora</footer>

<script>
function filtrar() {{
  const q = document.getElementById('busca').value.toLowerCase().trim();
  const cards = document.querySelectorAll('#grid .card');
  let vis = 0;
  cards.forEach(c => {{
    const nome = c.querySelector('.card-nome').textContent.toLowerCase();
    const show = !q || nome.includes(q);
    c.style.display = show ? '' : 'none';
    if (show) vis++;
  }});
  document.getElementById('contagem').textContent =
    q ? `${{vis}} resultado(s) para "${{q}}"` : `{total} dashboards disponíveis`;
  document.getElementById('empty').style.display = vis === 0 ? '' : 'none';
}}
</script>
</body>
</html>
"""

OUT_PATH.write_text(PAGE, encoding="utf-8")
print(f"[OK] index.html gerado em: {OUT_PATH}")
print(f"     {total} links criados")
