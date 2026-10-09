"""
Extrator das regras gerais — Cores.

O Cores entrega a prestação de contas em TRÊS formatos, todos mantidos:
  .xlsx  → planilha Habitacional (até jul/2026)                      → extratores/habitacional_xlsx.py
  .pdf   → "Demonstrativo de Contas" (ago/2026: "Emitido em...")     → extratores/contasdata.py (+ Resumo de Emissões, abaixo)
  .pdf   → portal CondoPro impresso em PDF (set/2026: logo CondoPro) → extratores/condopro_pdf.py
O PDF é reconhecido pelo conteúdo (o do CondoPro não tem "Emitido em" e traz o seletor de mês "Consultar").
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.modelo import DadosRegras

_RE_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$|^-?\d+,\d{2}$")


def _num(t: str) -> float:
    return float(t.replace(".", "").replace(",", "."))


def _emissao_do_demonstrativo(caminho: Path) -> dict | None:
    """"Resumo de Emissões Colunado" da conta ORDINARIA no PDF "Demonstrativo de Contas": para cada linha, o texto e
    depois Realizado e Previsto (nessa ordem; linha só com um número = só Previsto, ex.: ANTECIPAÇÕES); a linha sem texto
    com dois números é o total. Também lê o crédito "EMISSÃO DO PERÍODO" da Posição Financeira da mesma conta."""
    import fitz

    doc = fitz.open(str(caminho))
    try:
        linhas = [l.strip() for pg in doc for l in pg.get_text().split("\n")]
    finally:
        doc.close()
    ini = next((i for i, l in enumerate(linhas) if l.upper() == "ORDINARIA" and i + 1 < len(linhas)
                and linhas[i + 1].startswith("Resumo de Emiss")), None)
    if ini is None:
        return None
    i = ini + 2
    while i < len(linhas) and linhas[i] in ("Realizado", "Previsto"):
        i += 1
    itens, total, pos = [], None, None
    atual, nums = None, []

    def _fechar():
        nonlocal atual, nums, total
        if atual is not None and len(nums) >= 3 and total is None:
            # a última linha da tabela vem seguida, sem rótulo, dos dois totais (Realizado, Previsto)
            total = (nums[-2], nums[-1])
            nums = nums[:-2]
        if atual is not None and nums:
            real, prev = (nums[0], nums[1]) if len(nums) >= 2 else (0.0, nums[0])
            itens.append({"descricao": atual, "previsto": prev, "realizado": real, "local": "página 1"})
        elif atual is None and len(nums) >= 2 and total is None:
            total = (nums[0], nums[1])          # (realizado, previsto)
        atual, nums = None, []

    while i < len(linhas):
        l = linhas[i]
        if l.startswith("Posi") and "Financeira" in l:
            _fechar()
            break
        if _RE_VALOR.match(l):
            nums.append(_num(l))
        else:
            _fechar()
            if total is not None:
                break          # depois do total vem "COTAS REC. DE COBRANÇA EM <fim do mês>" (devedores)
            atual = l
        i += 1
    # crédito "EMISSÃO DO PERÍODO" da Posição Financeira da ORDINARIA
    for j in range(i, min(i + 80, len(linhas))):
        if linhas[j].upper().startswith("EMISS") and j + 1 < len(linhas) and _RE_VALOR.match(linhas[j + 1]):
            pos = {"valor": _num(linhas[j + 1]), "local": "página 1"}
            break
    if not itens or total is None:
        return None
    return {"conta": "ORDINARIA", "linhas": itens, "previsto": round(total[1], 2), "realizado": round(total[0], 2),
            "posicao_emissao": pos, "local": "página 1", "local_posicao": "página 1"}


def _indicadores_demonstrativo(caminho: Path, mes: str, emissao: dict | None) -> dict | None:
    """Mesma definição da planilha do Cores (adapters/habitacional_xlsx.py): previsto/realizado = totais do Resumo de Emissão da
    ORDINARIA; inadimplência = SOMA, em todas as contas, da linha "COTAS REC. DE COBRANÇA EM <último dia do mês>" (coluna Realizado);
    recebidos em atraso = SOMA da mesma linha com a data do mês anterior. Lido pela posição das palavras (Previsto termina em x≈485 e
    Realizado em x≈563)."""
    import fitz

    ano, m = int(mes[:4]), int(mes[5:7])
    ant = (12, ano - 1) if m == 1 else (m - 1, ano)
    inad = proc = 0.0
    achou = False
    doc = fitz.open(str(caminho))
    try:
        for pg in doc:
            palavras = sorted(pg.get_text("words"), key=lambda t: (round(t[1]), t[0]))
            linhas, ref = [], None
            for t in palavras:
                if ref is None or abs(t[1] - ref) > 3:
                    linhas.append([t])
                    ref = t[1]
                else:
                    linhas[-1].append(t)
            for l in linhas:
                texto = " ".join(t[4] for t in sorted(l, key=lambda t: t[0]))
                mt = re.match(r"^COTAS REC\. DE COBRAN.A\s+EM\s+(\d{2})/(\d{2})/(\d{4})\b", texto)
                if not mt:
                    continue
                mes_l, ano_l = int(mt.group(2)), int(mt.group(3))
                realizado = [_num(t[4]) for t in l if _RE_VALOR.match(t[4]) and t[2] >= 520]
                valor = realizado[0] if realizado else 0.0
                if (mes_l, ano_l) == (m, ano):
                    inad += valor
                    achou = True
                elif (mes_l, ano_l) == ant:
                    proc += valor
    finally:
        doc.close()
    if not emissao:
        return None
    return {"prev": emissao["previsto"], "real": emissao["realizado"], "inad": round(inad, 2) if achou else None, "inadProc": round(proc, 2)}


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        caminho = Path(caminho)
        ext = caminho.suffix.lower()
        if ext in (".xlsx", ".xlsm"):
            from conciliacao.regras_gerais.extratores.habitacional_xlsx import Extrator as ExtratorPlanilha
            return ExtratorPlanilha(self.condo).extrair(caminho, mes)
        if ext == ".pdf":
            from conciliacao.regras_gerais.extratores.condopro_pdf import Extrator as ExtratorCondoPro
            condopro = ExtratorCondoPro(self.condo)
            if condopro.reconhece(caminho):
                return condopro.extrair(caminho, mes)
            from conciliacao.regras_gerais.extratores.contasdata import Extrator as ExtratorContasData
            dados = ExtratorContasData(self.condo).extrair(caminho, mes)
            try:
                dados.emissao = _emissao_do_demonstrativo(caminho)
                dados.indicadores = _indicadores_demonstrativo(caminho, mes, dados.emissao)
            except Exception:
                dados.emissao = None
            return dados
        raise ValueError(f"formato de arquivo não suportado para o Cores: {caminho.suffix or 'sem extensão'}")
