"""
Conciliador Auxiliadora XLS — Patrícia.

Arquivo ".xls" binário de verdade (Excel 97-2003, não HTML como o Lello) —
usa xlrd, não openpyxl. A aba "Demonstrativo de Despesas" é pequena e só
cobre a conta extraordinária em andamento (confirmado em 4 meses reais:
"DESP. REFORMA ELEVADORES", parcelas de modernização de elevadores) — as
despesas ordinárias recorrentes do condomínio não aparecem itemizadas
nessa aba, só em agregado em outras abas do mesmo arquivo.

Estrutura (por conta, pode haver mais de uma seção no arquivo):
  linha 0: "Demonstrativo de Despesas" (título, só na 1ª linha do arquivo)
  linha 1: "<NOME DA CONTA>" | "Valor" | "Total" | "Percentual"  (cabeçalho)
  linhas seguintes: "<histórico>" | <valor> | <total acumulado> | "<pct>%"
  linha de fechamento: "" | "" | "Total da conta:" | <valor>
  linha final: "TOTAL DE DESPESAS:" | "R$ <valor>" | "" | ""

Sem comprovante escaneado nem link anexado — reaproveita
gerar_achados_datadigitus() (duplicidade + soma x total declarado), mesmo
padrão do DataDigitus/Consvicta/LFC/Lello/Alliz.
"""
from pathlib import Path
import re

from conciliacao.base import ConciliadorBase, RegistroComprovante


def _num(valor) -> float:
    if isinstance(valor, (int, float)):
        return abs(float(valor))
    s = re.sub(r"[^\d,.\-]", "", str(valor or "").strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


class ConciliadorAuxiliadoraXLS(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import xlrd

        wb = xlrd.open_workbook(str(caminho))
        try:
            ws = wb.sheet_by_name("Demonstrativo de Despesas")
        except Exception:
            return []

        registros: list[RegistroComprovante] = []
        conta_atual: str | None = None
        indice = 0

        for r in range(ws.nrows):
            row = [ws.cell_value(r, c) if c < ws.ncols else "" for c in range(4)]
            col0 = str(row[0]).strip()

            if not col0:
                continue
            if col0 == "Demonstrativo de Despesas":
                continue
            if col0.upper().startswith("TOTAL DE DESPESAS"):
                indice += 1
                registros.append(RegistroComprovante(
                    pagina=r + 1,
                    codigo=str(indice),
                    tipo_documento="total_conta_declarado",
                    conta="TOTAL",
                    descricao="TOTAL",
                    valor=_num(row[1]),
                    texto_bruto=" | ".join(str(v) for v in row),
                ))
                continue
            if str(row[2]).strip() == "Total da conta:":
                continue  # fecha a conta corrente — não é lançamento

            # Cabeçalho de nova conta: col0 preenchido, col1 literalmente "Valor".
            if str(row[1]).strip() == "Valor":
                conta_atual = col0
                continue

            # Lançamento: col0 = histórico, col1 = valor numérico.
            if isinstance(row[1], (int, float)) and conta_atual:
                indice += 1
                registros.append(RegistroComprovante(
                    pagina=r + 1,
                    codigo=str(indice),
                    tipo_documento="despesa_listada",
                    descricao=col0[:200],
                    valor=_num(row[1]),
                    categoria_demonstrativo=conta_atual,
                    conta="TOTAL",
                    texto_bruto=" | ".join(str(v) for v in row),
                ))

        return registros
