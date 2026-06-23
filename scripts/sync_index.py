"""
sync_index.py — Sincroniza docs/index.html com os dashboards reais.

Atualiza:
  - card-mes de cada card com o último mês do BAL do dashboard
  - total-badge e contagem de "N dashboards disponíveis"

Rodado automaticamente pelo pre-commit hook.
"""
import os, re, sys

DOCS = os.path.join(os.path.dirname(__file__), '..', 'docs')

MES_ABREV = {
    'Janeiro': 'Jan', 'Fevereiro': 'Fev', 'Março': 'Mar', 'Abril': 'Abr',
    'Maio': 'Mai', 'Junho': 'Jun', 'Julho': 'Jul', 'Agosto': 'Ago',
    'Setembro': 'Set', 'Outubro': 'Out', 'Novembro': 'Nov', 'Dezembro': 'Dez'
}

def ultimo_mes(fname):
    path = os.path.join(DOCS, fname)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    tits = re.findall(r"""tit\s*:\s*['"]([^'"]+)['"]""", content)
    if not tits:
        return '—'
    last = tits[-1]  # e.g. 'Maio / 2026'
    parts = last.split(' / ')
    if len(parts) == 2:
        mes = MES_ABREV.get(parts[0].strip(), parts[0].strip()[:3])
        ano = parts[1].strip()[-2:]
        return f'{mes}/{ano}'
    return last

def sync():
    index_path = os.path.join(DOCS, 'index.html')
    with open(index_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # Collect all dashboard files referenced in the index
    dash_files = sorted(set(re.findall(r'href="(Dashboard[^"]+\.html)"', html)))
    total = len(dash_files)

    # Build a map: filename -> ultimo_mes
    mes_map = {f: ultimo_mes(f) for f in dash_files
               if os.path.exists(os.path.join(DOCS, f))}

    changes = 0

    # Update each card's card-mes
    def replace_card_mes(m):
        nonlocal changes
        href = m.group(1)
        fname = os.path.basename(href)
        mes = mes_map.get(fname, '—')
        old_inner = m.group(2)
        new_inner = mes
        if old_inner != new_inner:
            changes += 1
        return m.group(0).replace(
            f'<div class="card-mes">{old_inner}</div>',
            f'<div class="card-mes">{new_inner}</div>'
        )

    html = re.sub(
        r'href="(Dashboard[^"]+\.html)"[^>]*>.*?'
        r'<div class="card-mes">([^<]*)</div>',
        replace_card_mes,
        html,
        flags=re.DOTALL
    )

    # Update total-badge
    html = re.sub(
        r'<span class="total-badge">\d+ condom[^<]+</span>',
        f'<span class="total-badge">{total} condomínios</span>',
        html
    )

    # Update contagem div (static text)
    html = re.sub(
        r'(<div class="contagem" id="contagem">)\d+ dashboards dispon[^<]+(</div>)',
        rf'\g<1>{total} dashboards disponíveis\g<2>',
        html
    )

    # Update JS reset string
    html = re.sub(
        r'`\$\{vis\} resultado\(s\) para "\$\{q\}"` : `\d+ dashboards dispon[^`]+`',
        f'`${{vis}} resultado(s) para "${{q}}"` : `{total} dashboards disponíveis`',
        html
    )

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'sync_index: {total} condomínios | {changes} card-mes atualizados')

if __name__ == '__main__':
    sync()
