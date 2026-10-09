"""
Extrator das regras gerais — "CondoPro" impresso em PDF (portal da administradora, página impressa pelo navegador).

Layout: o mesmo conteúdo da planilha Habitacional (Resumo Financeiro Contábil, Demonstrações Por Conta com Resumo de Emissão e
Posição Financeira, Demonstrativo de Despesas, Demonstrativo de Receitas), mas impresso como uma página web longa (logo
CondoPro no topo, seletor "Setembro 2026 / Consultar", ícones de anexo). O PDF não tem células: este módulo reconstrói as
LINHAS da planilha (coluna A = rótulo, mesmos índices de coluna) a partir da posição das palavras e entrega ao extrator da
planilha (`habitacional_xlsx.extrair_de_linhas`), de modo que as regras sejam as MESMAS nos dois formatos.

Posições (pontos, página de 842 pt) conferidas em set/2026 no Cores:
  Resumo financeiro   rótulo x=58 | valores com borda direita 511 (saldo ant.), 597 (créd.), 698 (déb.), 786 (saldo atual)
  Emissão / Posição   rótulo x=58 | valores com borda direita 698 (Previsto/Débito) e 786 (Realizado/Crédito)
  Despesas            código x=58 | data x=136 | histórico x>=282 (até 3 linhas) | valor 652 | total 750 | % 786
  Receitas            col0 x=58 | unidade x=136 | recibo x=282 | vencto x=351 | histórico x=447 | valor 698 ou 786

Conferência embutida: o extrator da planilha compara a soma dos lançamentos com o débito de cada conta do Resumo; se a
leitura deste PDF falhar em alguma linha, o aviso aparece e as regras sobre lançamentos não são confiáveis.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.modelo import DadosRegras

_RE_DINHEIRO = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$|^-?\d+,\d{2}$")
_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_PCT = re.compile(r"^-?\d+(?:,\d+)?%$")
_TOL_Y = 3.5


def _num(txt: str) -> float:
    return float(txt.replace(".", "").replace(",", "."))


def _linhas_visuais(pagina) -> list[list[tuple]]:
    """Palavras da página agrupadas em linhas (mesma altura), da esquerda para a direita: (x0, x1, y, texto)."""
    palavras = [(w[0], w[2], w[1], w[4]) for w in pagina.get_text("words") if w[4].strip()]
    palavras.sort(key=lambda t: (round(t[2]), t[0]))
    linhas: list[list[tuple]] = []
    ref = None
    for p in palavras:
        if ref is None or abs(p[2] - ref) > _TOL_Y:
            linhas.append([p])
            ref = p[2]
        else:
            linhas[-1].append(p)
    for l in linhas:
        l.sort(key=lambda t: t[0])
    # Duas situações em que linhas visuais diferentes caem na MESMA altura e precisam ser separadas:
    #  - a última linha do histórico de um grupo e o "TOTAL DA CONTA ..." (começa em x≈351);
    #  - o título de um grupo (x≈58) e a 1ª linha do histórico do lançamento seguinte (x≥282), sem data/valor.
    saida: list[list[tuple]] = []
    for l in linhas:
        corte = next((i for i, t in enumerate(l) if t[3] == "TOTAL" and t[0] >= 340 and i > 0
                      and i + 2 < len(l) and l[i + 1][3] in ("DA", "DAS")), None)
        partes = [l] if corte is None else [l[:corte], l[corte:]]
        for parte in partes:
            eh_dado = any(_RE_DINHEIRO.match(t[3]) or _RE_DATA.match(t[3]) or _RE_PCT.match(t[3]) for t in parte)
            esq = [t for t in parte if t[0] < 270]
            dir_ = [t for t in parte if t[0] >= 270]
            cabecalho = any(t[3].startswith(("Hist", "Lan")) for t in parte) and any(t[3] in ("Data", "Valor", "Anexo", "Recibo", "Vencto") for t in parte)
            titulo_de_tabela = any(t[3] in ("Saldo", "Previsto", "Realizado", "Débito", "Crédito", "Débitos", "Créditos", "Conta") for t in parte)
            if esq and dir_ and not eh_dado and not cabecalho and not titulo_de_tabela and not (len(esq) == 1 and esq[0][3].isdigit()):
                saida.append(esq)
                saida.append(dir_)
            else:
                saida.append(parte)
    return saida


def _juntar(tokens: list[tuple]) -> str:
    return " ".join(t[3] for t in tokens).strip()


def _icones_de_anexo(pagina) -> list:
    """Altura (centro) de cada ícone de clipe da coluna "Anexo" (imagens de ~19x18 pt em x≈212): a linha do lançamento que
    TEM comprovante anexado no portal tem o ícone; sem ícone = sem anexo."""
    try:
        return sorted((i["bbox"][1] + i["bbox"][3]) / 2 for i in pagina.get_image_info()
                      if 195 <= i["bbox"][0] <= 240 and 14 <= (i["bbox"][2] - i["bbox"][0]) <= 26)
    except Exception:
        return []


def _eh_ancora(l) -> bool:
    """Linha de um lançamento do Demonstrativo de Despesas: código de lançamento em x≈58 + algum valor (a data é opcional:
    tarifas bancárias vêm sem data)."""
    return any(t[0] < 70 and t[3].isdigit() for t in l) and any(_RE_DINHEIRO.match(t[3]) and t[1] > 600 for t in l)


def _eh_ancora_receita(l) -> bool:
    """Linha de um recibo do Demonstrativo de Receitas: data (x<110) + algum valor à direita (x>600)."""
    return any(t[0] < 110 and _RE_DATA.match(t[3]) for t in l) and any(_RE_DINHEIRO.match(t[3]) and t[1] > 600 for t in l)


def _col_por_borda(x1: float, ancoras: dict) -> int | None:
    melhor, dist = None, 14.0
    for borda, col in ancoras.items():
        d = abs(x1 - borda)
        if d < dist:
            melhor, dist = col, d
    return melhor


def _linha_vazia(n: int = 14) -> list:
    return [None] * n


def _ler_documento(caminho: Path, paginas: list | None = None) -> list[list]:
    import fitz

    doc = fitz.open(str(caminho))
    total_paginas_doc = len(doc)
    saida: list[list] = []
    secao = None            # "resumo" | "contas" | "despesas" | "receitas" | "outro"
    try:
        for numero_pagina, pg in enumerate(doc, start=1):
            if paginas is not None:
                paginas.extend([numero_pagina - 1] * (len(saida) - len(paginas)))   # linhas da página anterior
            linhas = _linhas_visuais(pg)
            icones_y = _icones_de_anexo(pg)
            # --- despesas: histórico em até 3 linhas ao redor da linha da data; âncora = linha com a data em x≈136
            ancoras_y = [l[0][2] for l in linhas if _eh_ancora(l)]
            hist_por_ancora: dict[float, list[tuple]] = {}
            consumidas: set = set()
            for k, outra in enumerate(linhas):
                tx = _juntar(outra)
                if _eh_ancora(outra) or not ancoras_y or re.match(r"^TOTAL\b", tx) or tx.startswith("Condom"):
                    continue
                if min(t[0] for t in outra) < 270:
                    continue                       # título de grupo (x≈58-100), não é histórico
                if any(_RE_DINHEIRO.match(t[3]) for t in outra) and any(t[0] < 270 for t in outra):
                    continue
                mais_perto = min(ancoras_y, key=lambda a: abs(a - outra[0][2]))
                if abs(mais_perto - outra[0][2]) <= 30:
                    hist_por_ancora.setdefault(mais_perto, []).append((outra[0][2], [t for t in outra if t[0] >= 270 and not _RE_DINHEIRO.match(t[3]) and not _RE_PCT.match(t[3])]))
                    consumidas.add(k)
            # --- receitas: o histórico do recibo quebra em até 3 linhas (x>=430) acima/abaixo da linha da data
            ancoras_rec = [l[0][2] for l in linhas if _eh_ancora_receita(l)]
            hist_rec: dict[float, list[tuple]] = {}
            if ancoras_rec and not ancoras_y:
                for k, outra in enumerate(linhas):
                    tx = _juntar(outra)
                    if _eh_ancora_receita(outra) or re.match(r"^TOTAL", tx) or tx.startswith("Condom"):
                        continue
                    if min(t[0] for t in outra) < 430 or any(_RE_DINHEIRO.match(t[3]) or _RE_DATA.match(t[3]) for t in outra):
                        continue
                    mais_perto = min(ancoras_rec, key=lambda a: abs(a - outra[0][2]))
                    if abs(mais_perto - outra[0][2]) <= 30:
                        hist_rec.setdefault(mais_perto, []).append((outra[0][2], [t for t in outra if t[0] >= 430]))
                        consumidas.add(k)
            for idx, l in enumerate(linhas):
                texto = _juntar(l)
                if not texto:
                    continue
                if texto.startswith("Condomínio:") or texto.startswith("Condom"):
                    if re.match(r"^Condom[ií]nio:", texto):
                        r = _linha_vazia()
                        r[0] = texto
                        saida.append(r)
                        secao = "novo"
                        continue
                low = texto.lower()
                if secao == "novo":
                    if low.startswith("resumo financeiro"):
                        secao = "resumo"
                    elif low.startswith("demonstra") and "por conta" in low:
                        secao = "contas"
                    elif low.startswith("demonstrativo de despesas"):
                        secao = "despesas"
                    elif low.startswith("demonstrativo de receitas"):
                        secao = "receitas"
                    elif low.startswith("per") and "odo:" in low:
                        pass
                    else:
                        secao = "outro"
                    r = _linha_vazia()
                    r[0] = texto
                    saida.append(r)
                    continue
                if low.startswith("período:") or low.startswith("periodo:"):
                    r = _linha_vazia()
                    r[0] = texto
                    saida.append(r)
                    continue
                if secao in (None,) or low.startswith("consultar") or re.match(r"^(janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+\d{4}", low):
                    continue          # cabeçalho da página impressa (logo, seletor de mês)
                if secao == "resumo":
                    saida.append(_linha_resumo(l))
                elif secao == "contas":
                    saida.append(_linha_contas(l))
                elif secao == "despesas":
                    if idx in consumidas:
                        continue
                    # Total de conta de nome longo: o rótulo, os valores e o resto do nome vêm em três linhas visuais.
                    if (saida and isinstance(saida[-1][4], str) and saida[-1][4].startswith("TOTAL DA CONTA") and saida[-1][7] is None
                            and all(_RE_DINHEIRO.match(t[3]) or _RE_PCT.match(t[3]) for t in l) and all(t[0] >= 560 for t in l)):
                        for t in l:
                            if _RE_DINHEIRO.match(t[3]):
                                saida[-1][7] = _num(t[3])
                            else:
                                saida[-1][9] = t[3]
                        continue
                    # Nome de conta longo quebra em duas linhas ("TOTAL DA CONTA HONORARIOS /" + "ADMINISTRATIVO"): junta.
                    if (saida and isinstance(saida[-1][4], str) and saida[-1][4].startswith("TOTAL DA CONTA")
                            and all(t[0] >= 340 for t in l)
                            and not any(_RE_DINHEIRO.match(t[3]) or _RE_DATA.match(t[3]) or _RE_PCT.match(t[3]) for t in l)
                            and not re.match(r"^TOTAL", texto)):
                        saida[-1][4] = saida[-1][4] + " " + texto
                        continue
                    if _linha_despesa(l, linhas, idx, ancoras_y, hist_por_ancora, consumidas, saida, icones_y):
                        continue
                elif secao == "receitas":
                    if idx in consumidas:
                        continue
                    saida.append(_linha_receita(l, hist_rec.get(l[0][2], [])))
                else:
                    r = _linha_vazia()
                    r[0] = texto
                    saida.append(r)
    finally:
        doc.close()
    if paginas is not None:
        paginas.extend([total_paginas_doc] * (len(saida) - len(paginas)))
    return saida


_ANC_RESUMO = {511: 4, 597: 6, 698: 8, 786: 10}
_COLS_TEXTO_RESUMO = [(351, 4), (515, 6), (602, 8), (703, 10)]
_ANC_CONTAS = {698: 8, 786: 10}
_COLS_TEXTO_CONTAS = [(602, 8), (703, 10)]


def _linha_numerica(l, ancoras: dict, cols_texto: list) -> list:
    """Rótulo (x<300) na coluna A; números pela borda direita; demais textos pela coluna mais próxima (cabeçalhos)."""
    r = _linha_vazia()
    rotulo = []
    for t in l:
        if _RE_DINHEIRO.match(t[3]):
            col = _col_por_borda(t[1], ancoras)
            if col is not None:
                r[col] = _num(t[3])
                continue
        if t[0] < 300:
            rotulo.append(t)
        else:
            col = min(cols_texto, key=lambda c: abs(t[0] - c[0]))[1]
            r[col] = ((r[col] + " ") if r[col] else "") + t[3]
    r[0] = _juntar(rotulo) or None
    return r


def _linha_resumo(l) -> list:
    return _linha_numerica(l, _ANC_RESUMO, _COLS_TEXTO_RESUMO)


def _linha_contas(l) -> list:
    return _linha_numerica(l, _ANC_CONTAS, _COLS_TEXTO_CONTAS)


def _linha_despesa(l, linhas, idx, ancoras_y, hist_por_ancora, consumidas, saida, icones_y=()) -> bool:
    """Acrescenta a(s) linha(s) da planilha para esta linha visual do Demonstrativo de Despesas. True se tratou."""
    y = l[0][2]
    texto = _juntar(l)
    if texto.startswith("Nº Lançto") or texto.startswith("N° Lançto") or re.match(r"^N.{1,2} Lan.to", texto):
        r = _linha_vazia()
        r[0], r[1], r[2], r[3], r[7], r[9] = "Nº Lançto.", "Data", "Anexo", "Histórico", "Valor", "Total"
        saida.append(r)
        return True
    if _eh_ancora(l):
        r = _linha_vazia()
        r[0] = next(t[3] for t in l if t[0] < 70 and t[3].isdigit())
        r[1] = next((t[3] for t in l if 130 <= t[0] <= 146 and _RE_DATA.match(t[3])), None)
        r[2] = "Link" if any(abs(cy - y) <= 14 for cy in icones_y) else None
        proprio = [t for t in l if t[0] >= 270 and not _RE_DINHEIRO.match(t[3]) and not _RE_PCT.match(t[3])]
        meus = list(hist_por_ancora.get(y, []))
        if proprio:
            meus.append((y, proprio))              # layout em que o histórico fica na mesma altura da data/valor
        meus = sorted((m for m in meus if not _juntar(m[1]).startswith("TOTAL DA")), key=lambda m: m[0])
        hist = " ".join(_juntar(m[1]) for m in meus)
        r[3] = hist or None
        for t in l:
            if _RE_DINHEIRO.match(t[3]):
                col = _col_por_borda(t[1], {652: 7, 750: 9})
                if col is not None:
                    r[col] = _num(t[3])
            elif _RE_PCT.match(t[3]):
                r[11] = t[3]
        saida.append(r)
        return True
    if any(t[0] >= 270 for t in l) and not re.match(r"^TOTAL", texto):
        # linha de histórico "solta" (sem âncora de data nesta página): vai para a linha anterior, se houver
        if saida and saida[-1][1] and _RE_DATA.match(str(saida[-1][1])):
            saida[-1][3] = ((saida[-1][3] or "") + " " + _juntar([t for t in l if t[0] >= 270])).strip()
            return True
    if re.match(r"^TOTAL\b", texto):
        r = _linha_vazia()
        r[4] = _juntar([t for t in l if not _RE_DINHEIRO.match(t[3]) and not _RE_PCT.match(t[3])])
        for t in l:
            if _RE_DINHEIRO.match(t[3]):
                col = _col_por_borda(t[1], {652: 7, 750: 9})
                if col is not None:
                    r[col] = _num(t[3])
            elif _RE_PCT.match(t[3]):
                r[9] = t[3]
        saida.append(r)
        return True
    # título de grupo (conta, subconta, rubrica)
    r = _linha_vazia()
    r[0] = texto
    saida.append(r)
    return True


def _linha_receita(l, hist_extra=None) -> list:
    texto = _juntar(l)
    r = _linha_vazia()
    if "Recibo" in texto and "Vencto" in texto:
        r[0], r[1], r[3], r[4], r[5], r[10] = "Data", "Bloco/Unidade", "Recibo", "Vencto", "Histórico", "Valor"
        return r
    nums = [t for t in l if _RE_DINHEIRO.match(t[3]) and t[1] > 600]
    tem_item = any(t[0] >= 270 and re.fullmatch(r"\d{6,}", t[3]) for t in l) or any(340 <= t[0] <= 360 and _RE_DATA.match(t[3]) for t in l)
    if tem_item or (nums and not re.match(r"^TOTAL", texto)):
        esq = [t for t in l if t[0] < 130]
        uni = [t for t in l if 130 <= t[0] < 200]
        r[0] = _juntar(esq) or None
        r[1] = _juntar(uni) or None
        r[2] = _juntar([t for t in l if 200 <= t[0] < 270]) or None
        r[3] = _juntar([t for t in l if 270 <= t[0] < 340]) or None
        r[4] = _juntar([t for t in l if 340 <= t[0] < 430]) or None
        proprio = [t for t in l if 430 <= t[0] < 650 and not _RE_DINHEIRO.match(t[3])]
        partes = sorted(list(hist_extra or []) + ([(l[0][2], proprio)] if proprio else []), key=lambda m: m[0])
        r[5] = " ".join(_juntar(m[1]) for m in partes) or None
        bordas = sorted(nums, key=lambda t: t[1])
        if len(bordas) == 1:
            r[10] = _num(bordas[0][3])
        elif len(bordas) >= 2:
            r[10] = _num(bordas[0][3])
            r[12] = _num(bordas[-1][3])
        return r
    if re.match(r"^TOTAL\b", _juntar([t for t in l if t[0] >= 430]) or texto):
        r[5] = _juntar([t for t in l if not _RE_DINHEIRO.match(t[3])])
        if nums:
            r[10] = _num(nums[-1][3])
        return r
    r[0] = texto
    return r


def _indicadores_das_linhas(linhas: list, mes: str, emissao: dict | None) -> dict | None:
    """Mesma definição da planilha do Cores: previsto/realizado do Resumo de Emissão da ORDINARIA; inadimplência = soma, em todas as
    contas, de "COTAS REC. DE COBRANÇA EM <último dia do mês>" (coluna K); recebidos em atraso = soma da mesma linha do mês anterior."""
    if not emissao:
        return None
    ano, m = int(mes[:4]), int(mes[5:7])
    ant = (12, ano - 1) if m == 1 else (m - 1, ano)
    inad = proc = 0.0
    achou = False
    for r in linhas:
        col0 = r[0] if isinstance(r[0], str) else ""
        mt = re.match(r"^COTAS REC\. DE COBRAN.A\s+EM\s+(\d{2})/(\d{2})/(\d{4})", col0.upper())
        if not mt:
            continue
        mes_l, ano_l = int(mt.group(2)), int(mt.group(3))
        v = r[10] if isinstance(r[10], (int, float)) else 0.0
        if (mes_l, ano_l) == (m, ano):
            inad += v
            achou = True
        elif (mes_l, ano_l) == ant:
            proc += v
    return {"prev": emissao["previsto"], "real": emissao["realizado"], "inad": round(inad, 2) if achou else None, "inadProc": round(proc, 2)}


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def reconhece(self, caminho: Path) -> bool:
        import fitz

        doc = fitz.open(str(caminho))
        try:
            texto = "".join(doc[i].get_text() for i in range(min(len(doc), 3)))
        finally:
            doc.close()
        return "Resumo Financeiro Cont" in texto and ("Consultar" in texto or "Demonstra" in texto) and "Condom" in texto \
            and "Per" in texto and "Emitido em" not in texto

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        from conciliacao.regras_gerais.extratores.habitacional_xlsx import extrair_de_linhas

        caminho = Path(caminho)
        linhas = _ler_documento(caminho)
        dados = extrair_de_linhas(linhas, mes, caminho.name)
        dados.indicadores = _indicadores_das_linhas(linhas, mes, dados.emissao)
        dados.avisos.insert(0, "arquivo em PDF do portal CondoPro (página impressa): linhas reconstruídas pela posição do texto")
        # Recibos de grupos de cobrança (juros, honorários...) cujo título de conta o leitor da planilha toma por uma "conta" nova:
        # o crédito de cada conta já vem completo das linhas da Posição Financeira (ver aviso da conta), então esses recibos
        # duplicariam o valor. Só os NEGATIVOS são mantidos (a regra de receita negativa precisa deles).
        nomes = {c.nome for c in dados.contas}
        fora = [r for r in dados.receitas if r.conta not in nomes]
        if fora:
            dados.receitas = [r for r in dados.receitas if r.conta in nomes or r.valor < -0.011]
            dados.avisos.append(f"{len(fora)} recibos de grupos de cobrança não atribuídos a nenhuma conta do Resumo foram desconsiderados "
                                f"(o crédito de cada conta já está nas linhas da Posição Financeira); mantidos só os de valor negativo")
        return dados
