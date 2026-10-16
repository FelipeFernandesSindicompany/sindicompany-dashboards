"""Confere se o arquivo de prestação de contas é DO condomínio que está sendo validado (barreira de identidade, SEMPRE ativa).

Casos reais (15-16/10/2026): o balancete de julho do Club Park Butantã estava na pasta do Parque Saint Afonso; o de agosto do Go Liberdade na do
Go Barra Funda; o de agosto de um condomínio "Duo Vila Matilde" (outra administradora) na pasta do Saint Simon. Em todos a validação rodou e
emitiu um relatório com o título de um condomínio e os números de outro.

Regra (estrita): o começo do arquivo TEM de citar o nome do condomínio (o cadastrado, sem sufixo I/II/III, ou um apelido de
`nomes_no_arquivo` na configuração). Se não cita:
  - o arquivo é RECUSADO (erro claro dizendo o que o cabeçalho diz), exceto
  - quando o arquivo não traz nome nenhum que se possa ler (planilha só de números, PDF de texto ilegível): passa com AVISO, porque não
    há como provar de quem é; a conferência de continuidade dos saldos com o mês anterior segue valendo.
"""
import re
import unicodedata
from pathlib import Path

_PALAVRAS_DE_BALANCETE = ("CONDOMINIO", "PRESTACAO", "SALDO", "DESPESAS", "RECEITAS", "FINANCEIRO", "PERIODO", "COMPETENCIA", "DEMONSTRATIVO")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def texto_do_inicio(caminho: Path, limite: int = 40000) -> str:
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
            for ws in wb.worksheets[:3]:
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    partes.append(" ".join(str(c) for c in row if c not in (None, "")))
                    if i > 80:
                        break
            return " ".join(partes)[:limite]
        if suf == ".xls":
            with open(caminho, "rb") as f:
                cab = f.read(300000)
            if cab.lstrip().lower().startswith((b"<html", b"<?xml", b"<!doc")):
                return re.sub(r"<script.*?</script>", " ", cab.decode("utf-8", "replace"), flags=re.S | re.I)[:limite]
            import xlrd
            wb = xlrd.open_workbook(str(caminho))
            partes = []
            for ws in wb.sheets()[:6]:
                for r in range(min(ws.nrows, 80)):
                    partes.append(" ".join(str(c) for c in ws.row_values(r) if str(c).strip()))
            return " ".join(partes)[:limite]
    except Exception:
        return ""
    return ""


def _nomes_aceitos(condo: dict) -> list:
    nome = _norm(condo.get("nome", ""))
    aceitos = {nome, re.sub(r"\s+(I|II|III|IV|V)$", "", nome)}
    aceitos |= {_norm(a) for a in (condo.get("nomes_no_arquivo") or [])}
    return sorted((a for a in aceitos if len(a) >= 3), key=len, reverse=True)


def conferir(caminho: Path, condo: dict, todos: list) -> tuple[bool, str]:
    """(ok, mensagem). ok=False: recusar o arquivo. ok=True com mensagem: passa com AVISO (não deu para provar a identidade)."""
    bruto = texto_do_inicio(caminho)
    texto = _norm(bruto)
    nome = condo.get("nome")
    if not texto or sum(1 for p in _PALAVRAS_DE_BALANCETE if p in texto) < 2:
        return True, (f"AVISO: não foi possível ler um cabeçalho legível em '{Path(caminho).name}' — a identidade do arquivo (se é mesmo de "
                      f"{nome}) NÃO foi confirmada pelo nome. Confira a continuidade dos saldos com o mês anterior.")
    if any(re.search(rf"(?<![A-Z0-9]){re.escape(a)}(?![A-Z0-9])", texto) for a in _nomes_aceitos(condo)):
        return True, ""
    outros = [c for c in todos if c.get("id") != condo.get("id") and len(_norm(c.get("nome", ""))) >= 7
              and re.search(rf"(?<![A-Z0-9]){re.escape(_norm(c['nome']))}(?![A-Z0-9])", texto)]
    if condo.get("identidade_sem_nome") and not outros:
        # formato que NUNCA traz o nome do condomínio (ex.: portal da Auxiliadora, só números): passa, mas fica o aviso
        return True, (f"AVISO: o formato de '{Path(caminho).name}' não traz o nome do condomínio — a identidade do arquivo (se é mesmo de {nome}) "
                      f"não pode ser confirmada pelo nome; confira a continuidade dos saldos com o mês anterior.")
    if outros:
        nomes = ", ".join(c["nome"] for c in outros[:3])
        return False, (f"O arquivo '{Path(caminho).name}' parece ser de outro condomínio ({nomes}), não de {nome}: o cabeçalho cita {nomes} e não "
                       f"cita {nome}. Confira se ele foi salvo na pasta certa.")
    m = re.search(r"(?:COND[A-Z]*|EDIFICIO)\s+[A-Z0-9 ]{4,60}", texto)
    visto = (m.group(0).strip() if m else texto[:80])
    return False, (f"O arquivo '{Path(caminho).name}' não cita o nome de {nome} no cabeçalho (o cabeçalho diz: \"{visto}\"). Pode ser de outro "
                   f"condomínio, ainda não cadastrado. Confira se ele foi salvo na pasta certa; se o nome do condomínio é escrito de outra forma no arquivo, "
                   f"cadastre o apelido em `nomes_no_arquivo` na configuração.")
