"""Confere se o arquivo de prestação de contas é DO condomínio que está sendo validado.

Caso real (15/10/2026): o balancete de julho do Club Park Butantã (341 MB) estava salvo na pasta do Parque Saint Afonso com o nome
"Prestação de Contas 07.2026.pdf"; a validação rodou e emitiu um relatório com o título do Saint Afonso e os números do Club Park.

Regra (conservadora, para não barrar arquivos legítimos cujo cabeçalho usa outro apelido): só recusa quando o início do arquivo
cita o nome de OUTRO condomínio cadastrado e não cita o deste.
"""
import re
import unicodedata
from pathlib import Path


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def texto_do_inicio(caminho: Path, limite: int = 12000) -> str:
    """Texto do começo do arquivo (primeiras páginas/linhas); '' se não conseguir ler."""
    try:
        suf = Path(caminho).suffix.lower()
        if suf == ".pdf":
            import fitz
            doc = fitz.open(str(caminho))
            return "".join(doc[i].get_text() for i in range(min(3, len(doc))))[:limite]
        if suf in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(str(caminho), read_only=True, data_only=True)
            partes = []
            for ws in wb.worksheets[:2]:
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    partes.append(" ".join(str(c) for c in row if c not in (None, "")))
                    if i > 40:
                        break
            return " ".join(partes)[:limite]
        if suf == ".xls":
            with open(caminho, "rb") as f:
                cab = f.read(limite)
            if cab.lstrip().lower().startswith((b"<html", b"<?xml", b"<!doc")):
                return cab.decode("utf-8", "replace")
            import xlrd
            wb = xlrd.open_workbook(str(caminho))
            partes = []
            for ws in wb.sheets()[:3]:
                for r in range(min(ws.nrows, 40)):
                    partes.append(" ".join(str(c) for c in ws.row_values(r) if str(c).strip()))
            return " ".join(partes)[:limite]
    except Exception:
        return ""
    return ""


def conferir(caminho: Path, condo: dict, todos: list) -> tuple[bool, str]:
    """(ok, mensagem). ok=False só quando o arquivo cita outro condomínio cadastrado e não cita este."""
    texto = _norm(texto_do_inicio(caminho))
    if not texto:
        return True, ""
    meu = _norm(condo.get("nome", ""))
    aliases = [_norm(a) for a in (condo.get("nomes_no_arquivo") or [])]
    if any(a and a in texto for a in [meu, *aliases] if len(a) >= 4) or any(tok in texto for tok in [meu] if len(tok) >= 4):
        return True, ""
    # nenhum nome deste condomínio apareceu: há nome de outro?
    outros = [c for c in todos if c.get("id") != condo.get("id") and len(_norm(c.get("nome", ""))) >= 7
              and re.search(rf"(?<![A-Z0-9]){re.escape(_norm(c['nome']))}(?![A-Z0-9])", texto)]
    if outros:
        nomes = ", ".join(c["nome"] for c in outros[:3])
        return False, (f"O arquivo '{Path(caminho).name}' parece ser de outro condomínio ({nomes}), não de {condo.get('nome')}: "
                       f"o cabeçalho cita {nomes} e não cita {condo.get('nome')}. Confira se ele foi salvo na pasta certa.")
    return True, ""
