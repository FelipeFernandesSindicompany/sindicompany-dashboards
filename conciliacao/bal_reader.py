"""
Leitor do bloco `var BAL = {...}` já publicado nos dashboards HTML existentes
(docs/Dashboard_Financeiro_*.html) — mesma fonte de dados que
admin/src/lib/htmlExtractor.ts usa no admin, mas em Python e lendo o mês
inteiro (contas[], desp[], banco{}, fin[]), não só os campos resumidos que o
admin precisa para o preview de injeção.

Não escreve nada — só leitura do HTML já publicado. Usado pela camada de
"Análise Financeira" (conciliacao/analise_financeira.py) para montar a seção
executiva do relatório a partir de dados que já existem no dashboard, sem
reprocessar nenhum PDF/XLSX de novo.
"""
import re
from pathlib import Path

MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez"]
MESES_NUM = {m: i + 1 for i, m in enumerate(MESES_ABREV)}
MESES_TITULO = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def mes_anterior(mes_chave: str) -> str:
    """'jul26' -> 'jun26'; 'jan26' -> 'dez25'."""
    abrev, ano = mes_chave[:3], int(mes_chave[3:])
    idx = MESES_NUM[abrev] - 1
    if idx == 0:
        return f"dez{ano - 1:02d}"
    return f"{MESES_ABREV[idx - 1]}{ano:02d}"


def mes_chave_titulo(mes_chave: str) -> str:
    """'jul26' -> 'Julho/2026'."""
    abrev, ano = mes_chave[:3], int(mes_chave[3:])
    return f"{MESES_TITULO[MESES_NUM[abrev] - 1]}/20{ano:02d}"


def _extrair_bloco_bal(conteudo: str) -> str:
    m = re.search(r"var\s+BAL\s*=\s*\{", conteudo)
    if not m:
        raise ValueError("Bloco 'var BAL = {...}' não encontrado no HTML")
    start = conteudo.index("{", m.start())
    depth = 0
    for i in range(start, len(conteudo)):
        if conteudo[i] == "{":
            depth += 1
        elif conteudo[i] == "}":
            depth -= 1
            if depth == 0:
                return conteudo[start + 1:i]
    raise ValueError("Bloco 'var BAL = {...}' malformado (chaves não fecham)")


def _extrair_entrada_mes(bloco: str, mes_chave: str) -> str:
    """Isola o texto do valor de bloco[mes_chave] (um objeto {...}), por brace-tracking."""
    m = re.search(rf"\b{mes_chave}\s*:\s*\{{", bloco)
    if not m:
        raise KeyError(f"Mês '{mes_chave}' não encontrado no BAL")
    start = bloco.index("{", m.start())
    depth = 0
    for i in range(start, len(bloco)):
        if bloco[i] == "{":
            depth += 1
        elif bloco[i] == "}":
            depth -= 1
            if depth == 0:
                return bloco[start:i + 1]
    raise ValueError(f"Entrada do mês '{mes_chave}' malformada")


def _num(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_objeto_js(texto: str) -> dict:
    """
    Parser mínimo para o subconjunto de JS usado no BAL (objetos/arrays
    literais com chaves sem aspas, strings com aspas simples/duplas, números).
    Não é um parser de JS geral — só o suficiente para este formato conhecido.
    """
    import json
    # Aspas: normaliza para JSON válido.
    # 1) chaves sem aspas -> "chave":
    t = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', texto)
    # 2) strings com aspas simples -> aspas duplas (conteúdo não tem aspas duplas neste formato)
    t = re.sub(r"'([^']*)'", r'"\1"', t)
    return json.loads(t)


def ler_bal_mes(html_dashboard_path: Path, mes_chave: str) -> dict | None:
    """Lê um mês específico do BAL de um dashboard. None se o mês não existir."""
    if not html_dashboard_path.exists():
        return None
    conteudo = html_dashboard_path.read_text(encoding="utf-8", errors="ignore")
    bloco = _extrair_bloco_bal(conteudo)
    try:
        entrada_texto = _extrair_entrada_mes(bloco, mes_chave)
    except KeyError:
        return None
    return _parse_objeto_js(entrada_texto)


def listar_meses_disponiveis(html_dashboard_path: Path) -> list:
    conteudo = html_dashboard_path.read_text(encoding="utf-8", errors="ignore")
    bloco = _extrair_bloco_bal(conteudo)
    return re.findall(r"\b([a-z]{3}\d{2})\s*:\s*\{", bloco)
