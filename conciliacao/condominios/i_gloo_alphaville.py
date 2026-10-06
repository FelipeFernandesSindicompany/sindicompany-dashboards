"""
Conciliador específico — I-Gloo Alphaville (administradora HSA Condomínios,
sistema GCONT/"W061A").

Cadastrado como "lirba_pdf", mas o PDF é do mesmo sistema do Club Park
Butantã: uma página "Comprovantes de despesas" (texto nativo, "Parcela
<código>", "Pago a:", "Destina-se a:") por pagamento. O parser ContasData
devolvia 0 registros. Reaproveita o parser GCONT via _gcont_comum.py.

Diferença para o Club Park/Saint Afonso: o HSA NÃO traz o Livro Caixa
"N itens VALOR". O fechamento independente vem dos "Demonstrativo Analítico"
de cada conta ("Ordinária", "Gás", "Água", ...), cada um terminando em
"Total de DESPESAS ... VALOR". Confirmado em jul/2026: 137.055,62 (Ordinária)
+ 26.763,57 (Gás) + 14.948,94 (Água) = 178.768,13 = soma das 73 capas.
Esse total vira um registro "total_demonstrativos_declarado" (nome distinto
de "total_declarado" de propósito: o render compara "total_declarado" com o
total do Demonstrativo Resumido e geraria falso achado aqui). Se nenhum total
for lido, não é emitido (não inventa).
"""
import re
from pathlib import Path

from conciliacao.base import RegistroComprovante
from conciliacao.condominios._gcont_comum import ConciliadorGcontNativo
from conciliacao.condominios.club_park_butanta import _num

_RE_SECAO = re.compile(r'Demonstrativo Anal[ií]tico\s+"([^"]+)"')
_RE_TOTAL_DESP = re.compile(r"Total de DESPESAS\s*\n(.{0,80})", re.DOTALL)
_RE_VALOR = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})*,\d{2})(?![\d%])")


def _totais_demonstrativos(caminho: Path) -> list[tuple[int, str, float]]:
    """[(pagina, conta, total_despesas)] dos Demonstrativos Analíticos."""
    import fitz

    out = []
    with fitz.open(str(caminho)) as doc:
        secao = None
        for i, page in enumerate(doc):
            t = page.get_text()
            if "Comprovantes de despesas" in t:
                break  # a parte financeira termina antes das capas
            m = _RE_SECAO.search(t)
            if m:
                secao = m.group(1)
            if secao is None:
                continue
            for mt in _RE_TOTAL_DESP.finditer(t):
                v = _RE_VALOR.search(mt.group(1))
                if v:
                    out.append((i + 1, secao, _num(v.group(1))))
                    break  # um total de despesas por seção
            # Cada Demonstrativo Analítico fecha com "Mov. Líquido(Receitas-Despesas) ... Saldo em dd/mm". Depois
            # disso, qualquer "Total de DESPESAS" é de OUTRA tabela (ex.: o Comparativo mês x mês, que em 11/2025
            # trazia o total do mês anterior e foi lido como se fosse da seção Benfeitorias).
            if "Mov. Líquido" in t:
                secao = None
    return out


class Conciliador(ConciliadorGcontNativo):
    def extrair_comprovantes(self, caminho) -> list:
        registros = super().extrair_comprovantes(caminho)
        if not any(r.tipo_documento == "despesa_com_comprovante" for r in registros):
            return registros
        if any(r.tipo_documento == "total_declarado" for r in registros):
            return registros
        try:
            totais = _totais_demonstrativos(Path(caminho))
        except Exception:
            totais = []
        if totais:
            partes = "; ".join(f"{c}: {v:,.2f}" for _, c, v in totais)
            registros.append(RegistroComprovante(
                pagina=totais[0][0],
                tipo_documento="total_demonstrativos_declarado",
                valor=round(sum(v for _, _, v in totais), 2),
                descricao=f"Total de DESPESAS dos Demonstrativos Analíticos ({partes})",
                texto_bruto=partes,
            ))
        return registros
