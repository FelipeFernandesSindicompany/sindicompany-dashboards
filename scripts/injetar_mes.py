"""
Motor de injeção mensal.

Lê o XLSX/PDF de um condomínio, converte para o bloco BAL e injeta no HTML existente.

Uso:
  python scripts/injetar_mes.py --condominio alvorada --mes 2026-05 --xlsx caminho/arquivo.xlsx
  python scripts/injetar_mes.py --todos --mes 2026-05  (processa todos com arquivo na pasta data/)
"""
import argparse, json, re, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

HTML_DIR = ROOT / "docs"

# Garante UTF-8 no terminal Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── Helpers de mês ─────────────────────────────────────────────────────────

MESES_ABREV = {
    1:"jan", 2:"fev", 3:"mar", 4:"abr", 5:"mai", 6:"jun",
    7:"jul", 8:"ago", 9:"set", 10:"out", 11:"nov", 12:"dez",
}
MESES_FULL = {
    1:"Janeiro", 2:"Fevereiro", 3:"Março", 4:"Abril",
    5:"Maio", 6:"Junho", 7:"Julho", 8:"Agosto",
    9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro",
}

def mes_chave(mes_str: str) -> str:
    """'2026-05' → 'mai26'"""
    dt = datetime.strptime(mes_str, "%Y-%m")
    return f"{MESES_ABREV[dt.month]}{str(dt.year)[2:]}"

def mes_titulo(mes_str: str) -> str:
    """'2026-05' → 'Maio / 2026'"""
    dt = datetime.strptime(mes_str, "%Y-%m")
    return f"{MESES_FULL[dt.month]} / {dt.year}"

def mes_periodo(mes_str: str) -> str:
    """'2026-05' → '01/05/2026 a 31/05/2026'"""
    import calendar
    dt = datetime.strptime(mes_str, "%Y-%m")
    ultimo = calendar.monthrange(dt.year, dt.month)[1]
    return f"01/{dt.month:02d}/{dt.year} a {ultimo}/{dt.month:02d}/{dt.year}"

def mes_evo_label(mes_str: str) -> str:
    """'2026-05' → 'Mai/26'"""
    dt = datetime.strptime(mes_str, "%Y-%m")
    return f"{MESES_FULL[dt.month][:3]}/{str(dt.year)[2:]}"


# ── Helpers de ordenação cronológica ──────────────────────────────────────

MESES_NUM = {v: k for k, v in MESES_ABREV.items()}
# {"jan":1, "fev":2, ..., "dez":12}

MESES_LABEL_NUM = {
    "Jan":1,"Fev":2,"Mar":3,"Abr":4,"Mai":5,"Jun":6,
    "Jul":7,"Ago":8,"Set":9,"Out":10,"Nov":11,"Dez":12,
}

def chave_para_ordinal(chave: str) -> int:
    """'mar25' → inteiro para ordenação cronológica."""
    try:
        return int(chave[3:]) * 12 + MESES_NUM.get(chave[:3], 0)
    except (ValueError, IndexError):
        return 0

def label_para_ordinal(label: str) -> int:
    """'Mar/25' → inteiro para ordenação cronológica."""
    parts = label.split('/')
    if len(parts) != 2:
        return 0
    try:
        return int(parts[1].strip()) * 12 + MESES_LABEL_NUM.get(parts[0].strip(), 0)
    except ValueError:
        return 0


def reordenar_bal_e_evo(texto: str) -> str:
    """
    Reordena entradas do BAL e arrays EVO_L/EVO_V em ordem cronológica.
    Usa tracking de profundidade de chaves para extrair cada entrada corretamente.
    """
    # ── BAL ──────────────────────────────────────────────────────────────────
    bal_m = re.search(r'(var\s+BAL\s*=\s*\{)(.*?)(\n\s*\};)', texto, re.DOTALL)
    if bal_m:
        body = bal_m.group(2)

        # Extrai entradas com brace-depth tracking
        key_re = re.compile(r'[ \t]*([a-z]{3}\d{2})\s*:\s*\{')
        entries = []
        pos = 0
        while True:
            km = key_re.search(body, pos)
            if not km:
                break
            key = km.group(1)
            # Encontra '{' da entrada e rastreia profundidade
            brace_start = km.end() - 1
            depth = 0
            j = brace_start
            while j < len(body):
                if body[j] == '{':
                    depth += 1
                elif body[j] == '}':
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            # Texto da entrada sem vírgula/espaço trailing
            entry_text = body[km.start():j].rstrip()
            entries.append((key, entry_text))
            # Avança além da vírgula opcional
            pos = j
            while pos < len(body) and body[pos] in ' \t,\n':
                pos += 1

        if len(entries) > 1:
            ords = [chave_para_ordinal(k) for k, _ in entries]
            if ords != sorted(ords):
                entries.sort(key=lambda x: chave_para_ordinal(x[0]))
                # Reconstrói body preservando whitespace inicial
                leading = re.match(r'^[ \t\n]*', body).group(0)
                # Normaliza indentação: usa a do primeiro entry
                ws_m = re.match(r'^([ \t]*)', entries[0][1])
                ws = ws_m.group(1) if ws_m else '  '
                parts = []
                for _, et in entries:
                    stripped = et.lstrip(' \t\n')
                    parts.append(ws + stripped)
                new_body = leading + (',\n').join(parts) + '\n'
                texto = (texto[:bal_m.start()]
                         + bal_m.group(1) + new_body + bal_m.group(3)
                         + texto[bal_m.end():])

    # ── EVO_L + EVO_V ────────────────────────────────────────────────────────
    evo_l_m = re.search(r'(\bEVO_L\s*=\s*\[)([^\]]*?)(\])', texto)
    evo_v_m = re.search(r'(\bEVO_V\s*=\s*\[)([^\]]*?)(\])', texto)
    if evo_l_m and evo_v_m:
        raw_l = [x.strip().strip("'\"") for x in evo_l_m.group(2).split(',') if x.strip()]
        raw_v = [x.strip() for x in evo_v_m.group(2).split(',') if x.strip()]
        if raw_l and len(raw_l) == len(raw_v):
            pairs = list(zip(raw_l, raw_v))
            sorted_pairs = sorted(pairs, key=lambda x: label_para_ordinal(x[0]))
            if sorted_pairs != pairs:
                new_l = ', '.join(f"'{lbl}'" for lbl, _ in sorted_pairs)
                new_v = ', '.join(val for _, val in sorted_pairs)
                texto = (texto[:evo_l_m.start()]
                         + evo_l_m.group(1) + new_l + evo_l_m.group(3)
                         + texto[evo_l_m.end():])
                evo_v_m2 = re.search(r'(\bEVO_V\s*=\s*\[)([^\]]*?)(\])', texto)
                if evo_v_m2:
                    texto = (texto[:evo_v_m2.start()]
                             + evo_v_m2.group(1) + new_v + evo_v_m2.group(3)
                             + texto[evo_v_m2.end():])
    return texto


# ── Conversão DadosFinanceiros → bloco BAL ─────────────────────────────────

def dados_para_bal(dados, mes_str: str) -> dict:
    """
    Converte DadosFinanceiros (do adapter) para o dict no formato BAL
    que os HTMLs reais esperam.
    """
    from adapters.base import DadosFinanceiros

    # tDesp = total usado para % nas despesas (soma das categorias, == total ordinária)
    t_desp = round(sum(dados.categorias_despesa.values()), 2) or round(dados.despesa_total, 2)

    # prev = orçamento previsto (usa receita_prevista se disponível, senão tCred)
    prev = round(dados.receita_prevista, 2) if dados.receita_prevista > 0 else round(dados.receita_realizada, 2)
    # real = cotas efetivamente recebidas (para Previsto x Realizado).
    # Usa receita_cotas se disponível (Blue Sky colunado: linha CONDOMINIO X Y),
    # caso contrário usa receita_realizada (total de créditos).
    receita_cotas = getattr(dados, 'receita_cotas', 0.0)
    real = round(receita_cotas, 2) if receita_cotas > 0 else round(dados.receita_realizada, 2)
    # fac = faturas anteriores cobradas (juros + multas recebidos de inadimplentes)
    fac  = round(getattr(dados, 'fac', 0.0), 2)

    # ── Contas individuais ──────────────────────────────────────────────────
    if dados.contas_detalhe:
        contas = [
            {"n": c["nome"],
             "a": round(c["saldo_ant"],   2),
             "c": round(c["creditos"],    2),
             "d": round(c["debitos"],     2),
             "s": round(c["saldo_atual"], 2)}
            for c in dados.contas_detalhe
        ]
    else:
        contas = [{"n": "ORDINÁRIA",
                   "a": round(dados.saldo_anterior,    2),
                   "c": round(dados.receita_realizada, 2),
                   "d": round(dados.despesa_total,     2),
                   "s": round(dados.saldo_atual,       2)}]

    # ── Banco (cc / cdb / priv) ──────────────────────────────────────────────
    # Gráficos de pizza não suportam valores negativos. Se qualquer conta
    # está em saldo devedor (cheque especial), usa o saldo líquido total na cc.
    has_banco = dados.banco_cc or dados.banco_cdb or dados.banco_priv
    has_negative = dados.banco_cc < 0 or dados.banco_cdb < 0 or dados.banco_priv < 0
    if has_banco and not has_negative:
        banco = {
            "cc":   round(dados.banco_cc,   2),
            "cdb":  round(dados.banco_cdb,  2),
            "priv": round(dados.banco_priv, 2),
        }
    else:
        # Saldo líquido total na cc (evita valores negativos nos gráficos)
        banco = {"cc": round(dados.saldo_atual, 2), "cdb": 0.0, "priv": 0.0}

    bloco = {
        "tit":    mes_titulo(mes_str),
        "per":    mes_periodo(mes_str),
        "tAnt":   round(dados.saldo_anterior, 2),
        "tCred":  round(dados.receita_realizada, 2),
        "tDeb":   round(dados.despesa_total, 2),
        "tAtual": round(dados.saldo_atual, 2),
        "prev":   prev,
        "real":   real,
        "fac":    fac,
        "tDesp":  t_desp,
        "inad":     round(dados.inadimplencia_valor, 2),
        "inadProc": round(getattr(dados, 'inadimplencia_recebida', 0.0), 2),
        "inadRec":  round(getattr(dados, 'inadimplencia_recebida', 0.0), 2),
        "banco":  banco,
        "contas": contas,
        "desp": [
            {"c": cat.upper(), "v": round(val, 2)}
            for cat, val in sorted(
                dados.categorias_despesa.items(),
                key=lambda x: x[1], reverse=True
            )
        ],
    }
    return bloco


# ── Injeção no HTML ────────────────────────────────────────────────────────

def _detectar_formato_bal(html_path: Path) -> dict:
    """
    Lê o HTML e detecta o formato das entradas BAL já existentes.
    Retorna {'compact': bool, 'tem_inadrec': bool}.
    compact=True  → linha única sem espaços (ex: I-Gloo)
    compact=False → multi-linha com recuo     (ex: Blue Sky)
    inadRec só é True em formato expanded que já usava esse campo antes.
    """
    try:
        texto = html_path.read_text(encoding="utf-8", errors="ignore")
        bal_m = re.search(r'var\s+BAL\s*=\s*\{', texto)
        if not bal_m:
            return {"compact": True, "tem_inadrec": False}
        body_pos = bal_m.end()
        # Primeiro char após o '{' da primeira entrada revela o estilo
        entry_m = re.search(r'\s*\w{3}\d{2}\s*:\s*\{(.)', texto[body_pos:])
        compact = True
        if entry_m:
            compact = entry_m.group(1) != '\n'
        # inadRec só faz sentido em dashboards expanded que já tinham esse campo
        # Formato compact (linha única) NUNCA inclui inadRec
        tem_inadrec = (not compact) and bool(re.search(r'[,\s{]inadRec\s*:', texto[body_pos:]))
        return {"compact": compact, "tem_inadrec": tem_inadrec}
    except Exception:
        return {"compact": True, "tem_inadrec": False}


def _reconstruir_evo_do_bal(texto: str) -> str:
    """
    Reconstrói EVO_L e EVO_V inteiramente a partir dos dados reais do BAL.
    Garante alinhamento perfeito, eliminando duplicatas geradas por re-injeções.
    """
    bal_m = re.search(r'var\s+BAL\s*=\s*\{', texto)
    if not bal_m:
        return texto

    # Encontra o fechamento do BAL com brace tracking
    bal_open = bal_m.end() - 1
    depth, j = 0, bal_open
    while j < len(texto):
        if texto[j] == '{':
            depth += 1
        elif texto[j] == '}':
            depth -= 1
            if depth == 0:
                break
        j += 1
    body = texto[bal_m.end():j]

    # Extrai chave → tAtual de cada entrada
    key_re = re.compile(r'\b([a-z]{3}\d{2})\s*:\s*\{')
    entries_data = {}
    pos = 0
    while True:
        km = key_re.search(body, pos)
        if not km:
            break
        key = km.group(1)
        brace_s = km.end() - 1
        depth2, j2 = 0, brace_s
        while j2 < len(body):
            if body[j2] == '{':
                depth2 += 1
            elif body[j2] == '}':
                depth2 -= 1
                if depth2 == 0:
                    break
            j2 += 1
        entry_chunk = body[km.start():j2 + 1]
        m_tat = re.search(r'tAtual\s*:\s*([\d.]+)', entry_chunk)
        if m_tat:
            entries_data[key] = float(m_tat.group(1))
        pos = j2 + 1

    if not entries_data:
        return texto

    sorted_keys = sorted(entries_data.keys(), key=chave_para_ordinal)

    def _chave_para_evo_label(k):
        """'abr26' → 'Abr/26'"""
        mes_n = MESES_NUM.get(k[:3], 0)
        if mes_n == 0:
            return k
        return f"{MESES_FULL[mes_n][:3]}/{k[3:]}"

    new_labels = ', '.join(f"'{_chave_para_evo_label(k)}'" for k in sorted_keys)
    new_values = ', '.join(str(round(entries_data[k], 2)) for k in sorted_keys)

    evo_l_m = re.search(r'(\bEVO_L\s*=\s*\[)([^\]]*?)(\])', texto)
    if evo_l_m:
        texto = (texto[:evo_l_m.start()] + evo_l_m.group(1)
                 + new_labels + evo_l_m.group(3) + texto[evo_l_m.end():])

    evo_v_m = re.search(r'(\bEVO_V\s*=\s*\[)([^\]]*?)(\])', texto, re.DOTALL)
    if evo_v_m:
        texto = (texto[:evo_v_m.start()] + evo_v_m.group(1)
                 + new_values + evo_v_m.group(3) + texto[evo_v_m.end():])

    return texto


def bal_para_js(bloco: dict, chave: str,
                compact: bool = True, tem_inadrec: bool = False) -> str:
    """
    Serializa o bloco como JavaScript replicando o formato das entradas existentes.
    compact=True  → linha única, single quotes, sem espaços (estilo I-Gloo)
    compact=False → multi-linha, single quotes, com recuo   (estilo Blue Sky)
    tem_inadrec   → inclui campo inadRec somente se o HTML já usa esse campo
    """

    def _n(v):
        """0.0 → '0'; demais → repr Python nativo do float."""
        if v == 0:
            return "0"
        return str(v)

    def _q(s):
        """Envolve em single quotes, escapando barras e aspas simples."""
        return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"

    # ── partes reutilizáveis ──────────────────────────────────────────────────
    b = bloco["banco"]
    banco_js = f"{{cc:{_n(b['cc'])},cdb:{_n(b['cdb'])},priv:{_n(b['priv'])}}}"

    inad_rec_val = _n(bloco.get("inadRec", 0))

    if compact:
        # ── Formato linha única (I-Gloo, Organy, etc.) ───────────────────────
        contas_js = ",".join(
            f"{{n:{_q(c['n'])},a:{_n(c['a'])},c:{_n(c['c'])},d:{_n(c['d'])},s:{_n(c['s'])}}}"
            for c in bloco["contas"]
        )
        desp_js = ",".join(
            f"{{c:{_q(d['c'])},v:{_n(d['v'])}}}"
            for d in bloco["desp"]
        )
        inad_part = f"inadProc:{_n(bloco['inadProc'])}"
        if tem_inadrec:
            inad_part += f",inadRec:{inad_rec_val}"

        parts = ",".join([
            f"tit:{_q(bloco['tit'])}",
            f"per:{_q(bloco['per'])}",
            f"tAnt:{_n(bloco['tAnt'])}",
            f"tCred:{_n(bloco['tCred'])}",
            f"tDeb:{_n(bloco['tDeb'])}",
            f"tAtual:{_n(bloco['tAtual'])}",
            f"contas:[{contas_js}]",
            f"prev:{_n(bloco['prev'])}",
            f"real:{_n(bloco['real'])}",
            f"tDesp:{_n(bloco['tDesp'])}",
            f"fac:{_n(bloco['fac'])}",
            f"inad:{_n(bloco['inad'])}",
            inad_part,
            f"banco:{banco_js}",
            f"desp:[{desp_js}]",
        ])
        return f"  {chave}:{{{parts}}}"

    else:
        # ── Formato multi-linha (Blue Sky) ────────────────────────────────────
        contas_inline = ", ".join(
            f"{{n:{_q(c['n'])}, a:{_n(c['a'])}, c:{_n(c['c'])}, d:{_n(c['d'])}, s:{_n(c['s'])}}}"
            for c in bloco["contas"]
        )
        desp_inline = ", ".join(
            f"{{c:{_q(d['c'])}, v:{_n(d['v'])}}}"
            for d in bloco["desp"]
        )

        inad_field = f"    inad: {_n(bloco['inad'])}, inadProc: {_n(bloco['inadProc'])}"
        if tem_inadrec:
            inad_field += f", inadRec: {inad_rec_val},"
        else:
            inad_field += ","

        linhas = [
            f"  {chave}: {{",
            f"    tit: {_q(bloco['tit'])}, per: {_q(bloco['per'])},",
            f"    tAnt: {_n(bloco['tAnt'])}, tCred: {_n(bloco['tCred'])}, tDeb: {_n(bloco['tDeb'])}, tAtual: {_n(bloco['tAtual'])},",
        ]
        if len(bloco["contas"]) > 2:
            linhas.append("    contas: [")
            for i, c in enumerate(bloco["contas"]):
                sep = "," if i < len(bloco["contas"]) - 1 else ""
                linhas.append(
                    f"      {{n:{_q(c['n'])}, a:{_n(c['a'])}, c:{_n(c['c'])}, d:{_n(c['d'])}, s:{_n(c['s'])}}}{sep}"
                )
            linhas.append("    ],")
        else:
            linhas.append(f"    contas: [{contas_inline}],")
        linhas += [
            f"    prev: {_n(bloco['prev'])}, real: {_n(bloco['real'])}, tDesp: {_n(bloco['tDesp'])}, fac: {_n(bloco['fac'])},",
            inad_field,
            f"    banco: {banco_js},",
            f"    desp: [{desp_inline}]",
            "  }",
        ]
        return "\n".join(linhas)


def _remover_mes_bal(texto: str, chave: str) -> str:
    """
    Remove a entrada de um mês do objeto BAL usando brace tracking.
    Retorna o texto modificado (sem a entrada) ou o texto original se não encontrar.
    """
    # Localiza a entrada dentro do BAL: "  chave: { ... }"
    pat = re.compile(rf'([ \t]*)({re.escape(chave)}\s*:\s*\{{)', re.DOTALL)
    m = pat.search(texto)
    if not m:
        return texto

    entry_start = m.start()         # inclui whitespace antes da chave
    brace_pos   = m.end() - 1       # posição do '{' de abertura

    # Tracking de chaves para encontrar o '}' final
    depth, j = 0, brace_pos
    while j < len(texto):
        if texto[j] == '{':
            depth += 1
        elif texto[j] == '}':
            depth -= 1
            if depth == 0:
                j += 1              # j aponta após o '}'
                break
        j += 1

    # Consome vírgula e newline depois do '}' se existirem
    rest = texto[j:]
    if rest.startswith(','):
        j += 1
    if j < len(texto) and texto[j] == '\n':
        j += 1

    # Caso a entrada anterior tinha vírgula que agora é a última → limpa
    before = texto[:entry_start]
    after  = texto[j:]
    # Se não sobrou nada depois (entrada era a única/última), remove vírgula anterior
    after_stripped = after.lstrip('\n')
    if after_stripped.startswith('}') and before.rstrip().endswith(','):
        before = before.rstrip()[:-1]   # remove a vírgula final

    return before + after


def injetar_no_html(html_path: Path, chave: str, bloco_js: str,
                    evo_label: str, saldo_atual: float,
                    inad_valor: float = None, orc_valor: float = None,
                    force: bool = False) -> bool:
    """
    Injeta novo mês no HTML:
    1. Adiciona entrada no objeto BAL
    2. Atualiza EVO_L (labels) e EVO_V (valores de saldo)
    Retorna True se modificou o arquivo.

    Se force=True e o mês já existe, remove a entrada antiga antes de injetar.
    Se force=False e o mês já existe, imprime [JA_EXISTE] e retorna False.
    """
    texto = html_path.read_text(encoding="utf-8", errors="ignore")

    # ── 1. Verifica se o mês já existe (apenas dentro do bloco BAL) ──
    # Usa brace tracking para garantir que encontra o BAL correto
    # (regex .*?\}; pode terminar num }; de outro objeto JS antes do BAL)
    _bal_decl = re.search(r'var\s+BAL\s*=\s*\{', texto)
    if _bal_decl:
        _bal_open = _bal_decl.end() - 1
        _depth, _j = 0, _bal_open
        while _j < len(texto):
            if texto[_j] == '{': _depth += 1
            elif texto[_j] == '}':
                _depth -= 1
                if _depth == 0: break
            _j += 1
        search_area = texto[_bal_decl.start():_j + 1]
    else:
        search_area = texto
    if re.search(rf'\b{re.escape(chave)}\s*:', search_area):
        if not force:
            print(f"  [JA_EXISTE] Mês '{chave}' já existe em {html_path.name}. Use --force para substituir.")
            return False
        # force=True: remove o mês existente e re-injeta
        print(f"  [INFO] Substituindo mês '{chave}' em {html_path.name}...")
        texto = _remover_mes_bal(texto, chave)
        # Também remove das listas EVO_L / EVO_V se presentes
        # (serão reconstruídas pelo processo de injeção abaixo)

    # ── 2. Injeta no BAL usando brace tracking ──────────────────────────────
    # NÃO usa regex .*?\}; pois poderia terminar num }; de outro objeto JS
    # antes do fechamento real do var BAL = { ... };
    bal_decl = re.search(r'var\s+BAL\s*=\s*\{', texto)
    if not bal_decl:
        print(f"  [ERRO] Não encontrou var BAL em {html_path.name}")
        return False

    # brace tracking para encontrar o '}' de fechamento correto do BAL
    bal_open = bal_decl.end() - 1  # posição do '{' de abertura
    depth, j = 0, bal_open
    while j < len(texto):
        if texto[j] == '{':
            depth += 1
        elif texto[j] == '}':
            depth -= 1
            if depth == 0:
                break
        j += 1
    # j aponta para o '}' final do BAL
    bal_close_pos = j

    # Insere o novo bloco antes do '}' final, com vírgula se necessário
    before_close = texto[:bal_close_pos].rstrip()
    if before_close.endswith(','):
        separador = "\n"
    else:
        separador = ",\n"
    texto = before_close + separador + bloco_js + "\n" + texto[bal_close_pos:]

    # ── 3. Atualiza EVO_L ──
    # EVO_L pode ser declarada como "var EVO_L=[...]" ou junto com outra var "..., EVO_L=[...]"
    evo_l_m = re.search(r'(\bEVO_L\s*=\s*\[)([^\]]*?)(\])', texto)
    if evo_l_m:
        labels_atuais = evo_l_m.group(2)
        novo_label = f"'{evo_label}'"
        if novo_label not in labels_atuais:
            nova_lista = labels_atuais.rstrip() + (", " if labels_atuais.strip() else "") + novo_label
            texto = texto[:evo_l_m.start()] + evo_l_m.group(1) + nova_lista + evo_l_m.group(3) + texto[evo_l_m.end():]

    # ── 4. Atualiza EVO_V ──
    # EVO_V pode ser declarada sem "var" separado (ex: "var EVO_L=[...], EVO_V=[...]")
    evo_v_m = re.search(r'(\bEVO_V\s*=\s*\[)([^\]]*?)(\])', texto, re.DOTALL)
    if evo_v_m:
        valores_atuais = evo_v_m.group(2)
        novo_valor = str(round(saldo_atual, 2))
        nova_lista = valores_atuais.rstrip() + (", " if valores_atuais.strip() else "") + novo_valor
        texto = texto[:evo_v_m.start()] + evo_v_m.group(1) + nova_lista + evo_v_m.group(3) + texto[evo_v_m.end():]

    # ── 5. Atualiza INAD_V (inadimplência) ──
    if inad_valor is not None:
        inad_m = re.search(r'(\bINAD_V\s*=\s*\[)([^\]]*?)(\])', texto)
        if inad_m:
            inad_atual = inad_m.group(2)
            novo_inad  = str(round(inad_valor, 2))
            nova_inad_lista = inad_atual.rstrip() + (", " if inad_atual.strip() else "") + novo_inad
            texto = texto[:inad_m.start()] + inad_m.group(1) + nova_inad_lista + inad_m.group(3) + texto[inad_m.end():]

    # ── 6. Atualiza ORC_MESES (orçamento por mês) ──
    if orc_valor is not None and orc_valor > 0:
        orc_m = re.search(r'(var\s+ORC_MESES\s*=\s*\{)([^}]*?)(\})', texto, re.DOTALL)
        if orc_m and chave not in orc_m.group(2):
            orc_atual  = orc_m.group(2)
            novo_orc   = orc_atual.rstrip().rstrip(',') + f",\n  {chave}:{round(orc_valor, 2)},"
            texto = texto[:orc_m.start()] + orc_m.group(1) + novo_orc + orc_m.group(3) + texto[orc_m.end():]

    # ── 7. Reordena BAL cronologicamente ──
    texto = reordenar_bal_e_evo(texto)

    # ── 8. Reconstrói EVO_L e EVO_V do zero a partir do BAL ──
    # Elimina acúmulo de duplicatas gerado por re-injeções com --force
    texto = _reconstruir_evo_do_bal(texto)

    html_path.write_text(texto, encoding="utf-8")
    return True


# ── Processamento principal ────────────────────────────────────────────────

def processar_um(cond: dict, mes_str: str, arquivo: Path, config_global: dict) -> bool:
    from adapters import get_adapter

    empresa_id = cond["empresa_gestora"]
    adapter = get_adapter(empresa_id, cond)

    ext = arquivo.suffix.lower()
    if ext in (".pdf",):
        print(f"  Lendo PDF:  {arquivo.name}")
        dados = adapter.ler_pdf(arquivo, mes_str)
    else:
        print(f"  Lendo XLSX: {arquivo.name}")
        dados = adapter.ler_xlsx(arquivo, mes_str)

    chave = mes_chave(mes_str)
    bloco = dados_para_bal(dados, mes_str)
    evo_label = mes_evo_label(mes_str)

    html_path = HTML_DIR / cond["html_file"]
    if not html_path.exists():
        print(f"  [ERRO] HTML não encontrado: {html_path}")
        return False

    fmt = _detectar_formato_bal(html_path)
    bloco_js = bal_para_js(bloco, chave, compact=fmt["compact"], tem_inadrec=fmt["tem_inadrec"])

    ok = injetar_no_html(
        html_path, chave, bloco_js, evo_label,
        saldo_atual  = dados.saldo_atual,
        inad_valor   = dados.inadimplencia_valor,
        orc_valor    = bloco.get("prev", 0),
        force        = config_global.get("_force", False),
    )
    if ok:
        print(f"  [OK] Mês '{chave}' injetado em {html_path.name}")
        import json as _json
        resumo = {
            "chave": chave,
            "html": html_path.name,
            "tit": bloco["tit"],
            "tAnt": bloco["tAnt"],
            "tCred": bloco["tCred"],
            "tDeb": bloco["tDeb"],
            "tAtual": bloco["tAtual"],
            "inad": bloco["inad"],
            "nContas": len(bloco["contas"]),
            "nDesp": len(bloco["desp"]),
            "banco": bloco["banco"],
        }
        print(f"  [RESUMO] {_json.dumps(resumo, ensure_ascii=False)}")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mes", required=True, help="Mês YYYY-MM")
    parser.add_argument("--condominio", help="ID do condomínio")
    parser.add_argument("--arquivo", "--xlsx", dest="arquivo",
                        help="Caminho para o arquivo XLSX ou PDF (opcional)")
    parser.add_argument("--todos", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Substitui o mês se já existir no dashboard")
    args = parser.parse_args()

    try:
        datetime.strptime(args.mes, "%Y-%m")
    except ValueError:
        print("[ERRO] Use formato YYYY-MM"); sys.exit(1)

    with open(ROOT / "config" / "condominios.json", encoding="utf-8") as f:
        config = json.load(f)

    # Propaga --force para o processamento
    config["_force"] = args.force

    condominios = [c for c in config["condominios"] if c.get("ativo", True)]
    if args.condominio:
        condominios = [c for c in condominios if c["id"] == args.condominio]
    elif not args.todos:
        print("[ERRO] Informe --condominio <id> ou --todos"); sys.exit(1)

    ok = 0
    htmls_atualizados = []
    for cond in condominios:
        print(f"\n> {cond['nome']} [{cond['empresa_gestora']}]")

        if args.arquivo:
            arquivo_path = Path(args.arquivo)
        else:
            pasta = ROOT / cond["pasta_dados"] / args.mes
            arquivos = (list(pasta.glob("*.xlsx")) + list(pasta.glob("*.xls"))
                        + list(pasta.glob("*.pdf")) + list(pasta.glob("*.PDF")))
            if not arquivos:
                print(f"  [AVISO] Nenhum arquivo em {pasta}"); continue
            arquivo_path = arquivos[0]

        if processar_um(cond, args.mes, arquivo_path, config):
            ok += 1
            htmls_atualizados.append(cond["html_file"])

    print(f"\nConcluído: {ok}/{len(condominios)} condomínios atualizados.")

    # ── Auto-publicação no GitHub Pages ───────────────────────────────────────
    if ok > 0 and htmls_atualizados:
        _publicar_github(htmls_atualizados, args.mes)
        # Em modo produção (next start), reinicia o servidor para
        # carregar os HTMLs atualizados sem hot-reload
        _reiniciar_admin()


def _publicar_github(htmls: list, mes_str: str):
    """
    Commit e push automático dos dashboards atualizados para o GitHub Pages.
    Também regenera o snapshot do Vercel para que o admin atualize imediatamente.
    Silencioso se git não estiver disponível ou não houver remote configurado.
    """
    import subprocess
    try:
        # Verifica se está num repositório git
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=10
        )
        if r.returncode != 0:
            return

        # Stage apenas os HTMLs modificados
        paths_relativos = [f"docs/{h}" for h in htmls]
        subprocess.run(
            ["git", "add"] + paths_relativos,
            capture_output=True, cwd=str(ROOT), timeout=10
        )

        # Verifica se há algo staged
        diff = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=10
        )
        if not diff.stdout.strip():
            return  # Nada novo para commitar

        # ── Regenera o snapshot do Vercel com os dados mais recentes ──────────
        # Isso garante que o admin.vercel.app atualize imediatamente sem
        # precisar aguardar o Vercel reconstruir do zero.
        snapshot_script = ROOT / "admin" / "scripts" / "generate-snapshots.mjs"
        if snapshot_script.exists():
            try:
                node_result = subprocess.run(
                    ["node", str(snapshot_script)],
                    capture_output=True, text=True,
                    cwd=str(ROOT / "admin"), timeout=60
                )
                if node_result.returncode == 0:
                    # Stage o snapshot atualizado junto com os HTMLs
                    subprocess.run(
                        ["git", "add", "admin/src/data/snapshots.json"],
                        capture_output=True, cwd=str(ROOT), timeout=10
                    )
                    print(f"  [SNAPSHOT] Regenerado com sucesso.")
                else:
                    print(f"  [AVISO] Snapshot: {node_result.stderr[:100]}")
            except Exception:
                pass  # Se node falhar, continua sem o snapshot

        nomes = ", ".join(h.replace("Dashboard_Financeiro_", "").replace("Dashboard_", "").replace(".html", "") for h in htmls)
        msg = f"data: {mes_str} — {nomes}"
        subprocess.run(
            ["git", "commit", "-m", msg],
            capture_output=True, cwd=str(ROOT), timeout=15
        )
        push = subprocess.run(
            ["git", "push", "origin", "main"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=30
        )
        if push.returncode == 0:
            print(f"\n  [GITHUB] Dashboard publicado automaticamente. Admin Vercel atualizado.")
        else:
            print(f"\n  [AVISO] Push para GitHub falhou (verifique conexão).")
    except Exception:
        pass  # Silencioso — publicação é opcional


def _reiniciar_admin():
    """
    Reinicia o processo sindicompany-admin via PM2 para recarregar os HTMLs
    atualizados no modo produção (next start não tem hot-reload).
    Silencioso se PM2 não estiver disponível.
    """
    import subprocess, os
    pm2_paths = [
        os.path.join(os.environ.get("APPDATA", ""), "npm", "pm2.cmd"),
        "pm2",
    ]
    for pm2 in pm2_paths:
        try:
            r = subprocess.run(
                [pm2, "restart", "sindicompany-admin"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                print("  [ADMIN] Servidor reiniciado para carregar dashboards atualizados.")
                return
        except Exception:
            continue


if __name__ == "__main__":
    main()
