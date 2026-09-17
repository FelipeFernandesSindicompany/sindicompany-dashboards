"""
Conciliador Habitacional XLSX — extrai RegistroComprovante[] do mesmo
arquivo prestacao_contas_N_YYYY.xlsx que adapters/habitacional_xlsx.py já lê
para o demonstrativo consolidado.

Formato bem diferente de Addomus/Lirba (PDF com imagem escaneada por
comprovante): aqui a "evidência" é um HYPERLINK do Excel (coluna "Anexo",
texto "Link") apontando para um sistema externo (Webware) onde o documento
fica hospedado. Não há página física pra recortar — o achado "sem
comprovante" aqui significa "linha do Demonstrativo de Despesas sem
hyperlink na coluna Anexo", não "sem página no PDF".

Estrutura da aba única (confirmada em Alvorada, jul/2026):
  "Demonstrativo de Despesas" (linha marcador) até "TOTAL DAS DESPESAS":
    col A = Nº Lançto. (número) OU nome de categoria (linha só com col A) OU
            vazio (linha "TOTAL DA CONTA X")
    col B = Data (vazia em linhas de subtotal tipo "0 | | | DESPESAS BANCARIAS | 320,25" —
            usada aqui para distinguir lançamento real de rótulo de subcategoria)
    col C = Anexo ("Link", com hyperlink real quando o comprovante existe)
    col D = Histórico
    col E = só preenchida em linhas "TOTAL DA CONTA X" / "TOTAL DAS DESPESAS"
    col H (índice 7) = Valor (do lançamento OU do subtotal da categoria)
"""
from pathlib import Path

from conciliacao.base import ConciliadorBase, RegistroComprovante

# Reaproveita a normalização de categoria e o parser de valor BR já
# validados em adapters/habitacional_xlsx.py — não duplica a lógica.
from adapters.habitacional_xlsx import _normalizar_categoria, _f


def _linha_total(row) -> str | None:
    v4 = row[4].value if len(row) > 4 else None
    if v4 and str(v4).strip().upper().startswith("TOTAL"):
        return str(v4).strip()
    return None


def _linha_categoria_header(row) -> str | None:
    v0 = row[0].value
    if v0 is None or not str(v0).strip():
        return None
    resto = [c.value for c in row[1:8]]
    if all(v is None for v in resto) and not str(v0).strip().upper().startswith("TOTAL"):
        return str(v0).strip()
    return None


def _linha_transacao(row):
    """(codigo, data) se a linha é um lançamento real, None se for cabeçalho,
    rótulo ou subtotal (ex.: código "0" sem data, usado só pra exibir o nome
    de uma subcategoria sem detalhar cada lançamento individual)."""
    v0 = row[0].value
    v1 = row[1].value
    if v0 is None or not str(v0).strip():
        return None
    if str(v0).strip().lower().startswith("n") and "lan" in str(v0).strip().lower():
        return None  # linha de cabeçalho "Nº Lançto. | Data | Anexo | ..."
    if not v1 or not str(v1).strip():
        return None
    return str(v0).strip(), str(v1).strip()


class ConciliadorHabitacionalXLSX(ConciliadorBase):
    """Extrai despesas listadas (Demonstrativo de Despesas) e a presença ou
    não de hyperlink de comprovante (coluna Anexo) do XLSX Habitacional."""

    def extrair_comprovantes(self, caminho: Path) -> list:
        try:
            import openpyxl
        except ImportError:
            raise ImportError("Instale openpyxl: pip install openpyxl")

        wb = openpyxl.load_workbook(str(caminho), data_only=True)
        ws = wb.active

        registros: list[RegistroComprovante] = []
        dentro_demonstrativo = False
        categoria_atual: str | None = None

        for row in ws.iter_rows(min_row=1):
            col0 = row[0].value

            if not dentro_demonstrativo:
                if col0 and "Demonstrativo de Despesas" in str(col0):
                    dentro_demonstrativo = True
                continue

            total_label = _linha_total(row)
            if total_label:
                if total_label.upper() == "TOTAL DAS DESPESAS":
                    break
                continue  # "TOTAL DA CONTA X" — só usado como limite, não guardado

            cat_header = _linha_categoria_header(row)
            if cat_header:
                categoria_atual = _normalizar_categoria(cat_header)
                continue

            transacao = _linha_transacao(row)
            if not transacao:
                continue
            codigo, data = transacao

            anexo_cell = row[2]
            historico = row[3].value
            valor = _f(row[7].value if len(row) > 7 else None)
            texto_linha = " | ".join(str(c.value) for c in row[:8] if c.value is not None)

            registros.append(RegistroComprovante(
                pagina=row[0].row,
                tipo_documento="despesa_listada",
                codigo=codigo,
                descricao=str(historico)[:200] if historico else None,
                vencimento=data,
                valor=valor,
                categoria_demonstrativo=categoria_atual,
                texto_bruto=texto_linha,
            ))

            if anexo_cell.hyperlink is not None:
                registros.append(RegistroComprovante(
                    pagina=row[0].row,
                    tipo_documento="comprovante_anexado",
                    codigo=codigo,
                    texto_bruto=anexo_cell.hyperlink.target or "",
                ))

        return registros
