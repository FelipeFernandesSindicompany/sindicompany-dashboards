"""
Conciliador específico — Plano & Estação Campo Limpo (administradora Foccus, sistema GCONT "W0xx").

Cadastrado como "lirba_pdf", mas o PDF (ex.: 06.2026, 274 páginas) é do mesmo sistema do Club Park Butantã: uma
página "Comprovantes de despesas" (texto nativo, "Parcela <código>", "Pago a:") por pagamento — 40 em jun/2026. O
parser ContasData devolvia 0 registros. Reaproveita o parser GCONT via _gcont_comum.py (o do Club Park, sem
alterá-lo).

Total de fechamento: o "Demonstrativo de Despesas Analítico" termina em "Total de Despesas  VALOR" (R$ 135.393,73 em
jun/2026). Em jun/2026 as 40 capas somam R$ 129.903,80 e a diferença (R$ 5.489,93) é EXATAMENTE a soma de 10
lançamentos listados no demonstrativo que não têm página de comprovante (vale transporte 275,60, vale alimentação
456,26, custas judiciais 38,42 + 46,57 + 46,57 + 35,75, e 159,01 / 280,00 / 169,00 / 990,00 / 2.992,75) — todas as 40
capas têm lançamento de mesmo valor no demonstrativo. Logo o "soma dos comprovantes x total" aponta comprovantes que
faltam de verdade. Vira o registro "total_demonstrativos_declarado" (nome distinto de "total_declarado": o render
compara "total_declarado" com o total do Demonstrativo Resumido e geraria falso achado).
"""
import re
from pathlib import Path

from conciliacao.base import RegistroComprovante
from conciliacao.condominios._gcont_comum import ConciliadorGcontNativo
from conciliacao.condominios.club_park_butanta import _num

_RE_TOTAL_DESPESAS = re.compile(r"^Total de Despesas\s*$\n(?:\s*\n)*\s*([\d.]+,\d{2})\s*$", re.MULTILINE)


def _total_demonstrativo_despesas(caminho: Path):
    """(pagina, valor) do "Total de Despesas" (linha própria, sem sufixo) do Demonstrativo de Despesas Analítico."""
    import fitz

    with fitz.open(str(caminho)) as doc:
        for i, page in enumerate(doc):
            texto = page.get_text()
            if "Comprovantes de despesas" in texto:
                break
            if "Demonstrativo de Despesas" not in texto and i == 0:
                continue
            if "Demonstrativo de Despesas" in texto or "Total de Despesas" in texto:
                m = _RE_TOTAL_DESPESAS.search(texto)
                if m and "Demonstrativo de Despesas Anal" in "".join(
                        doc[j].get_text()[:200] for j in range(max(0, i - 3), i + 1)):
                    return i + 1, _num(m.group(1))
    return None


class Conciliador(ConciliadorGcontNativo):
    def extrair_comprovantes(self, caminho) -> list:
        registros = super().extrair_comprovantes(caminho)
        if not any(r.tipo_documento == "despesa_com_comprovante" for r in registros):
            return registros
        try:
            total = _total_demonstrativo_despesas(Path(caminho))
        except Exception:
            total = None
        if total:
            pagina, valor = total
            registros.append(RegistroComprovante(
                pagina=pagina, tipo_documento="total_demonstrativos_declarado", valor=valor,
                descricao="Total de Despesas (Demonstrativo de Despesas Analítico)",
                texto_bruto=f"Total de Despesas {valor:,.2f}",
            ))
        return registros
