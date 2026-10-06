"""
Conciliador específico — Monte Tabor (administradora Alliz).

Reaproveita `ConciliadorAllizPDF` (soma das páginas de comprovante bancário x "Despesas do Período") e corrige
a causa-raiz do único achado antigo: a soma ficava SEMPRE R$ 149,45 abaixo do total declarado em jul/2026
(39.428,72 x 39.578,17) e o relatório acusava "soma não confere". A diferença é exatamente a linha
"BANCARIAS 149,45" do "2.1 Demonstrativo de Despesas" (grupo GERAIS/BANCARIAS): tarifa debitada direto pelo banco,
que por natureza não tem página de comprovante de pagamento — logo nunca entra na soma dos comprovantes, mas
entra no total declarado.

Correção: a linha "BANCARIAS" (e "TARIFAS BANCARIAS") do próprio Demonstrativo de Despesas vira um registro
`despesa_listada` próprio, com o valor impresso — não se inventa valor, e se o Demonstrativo não trouxer a linha
nada é acrescentado (a divergência, se existir, continua aparecendo).
"""
import re
from pathlib import Path

from conciliacao.alliz_pdf import ConciliadorAllizPDF, _num
from conciliacao.base import RegistroComprovante

_RE_LINHA_BANCARIAS = re.compile(r"^\s*(?:TARIFAS\s+)?BANC[AÁ]RIAS\s*\n\s*([\d.]+,\d{2})\s*$", re.IGNORECASE | re.MULTILINE)


def _tarifas_bancarias_do_demonstrativo(caminho: Path):
    """[(pagina, valor)] das linhas BANCARIAS da 1ª ocorrência do Demonstrativo de Despesas (a seção é
    reimpressa mais adiante no arquivo — para na linha "TOTAL GERAL DAS DESPESAS")."""
    import fitz

    achados = []
    with fitz.open(str(caminho)) as doc:
        for i, page in enumerate(doc):
            texto = page.get_text()
            if "DEMONSTRATIVO DE DESPESAS" not in texto.upper():
                continue
            for m in _RE_LINHA_BANCARIAS.finditer(texto):
                achados.append((i + 1, _num(m.group(1))))
            if "TOTAL GERAL DAS DESPESAS" in texto.upper():
                break
    return achados


class Conciliador(ConciliadorAllizPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        registros = super().extrair_comprovantes(caminho)
        if not any(r.tipo_documento == "total_conta_declarado" for r in registros):
            return registros
        try:
            tarifas = _tarifas_bancarias_do_demonstrativo(Path(caminho))
        except Exception:
            tarifas = []
        for n, (pagina, valor) in enumerate(tarifas, start=1):
            if valor <= 0:
                continue
            registros.append(RegistroComprovante(
                pagina=pagina, codigo=f"tarifa{n}", tipo_documento="despesa_listada",
                descricao="BANCARIAS (tarifas debitadas pelo banco — linha do Demonstrativo de Despesas)",
                valor=valor, conta="TOTAL",
                texto_bruto=f"Demonstrativo de Despesas, GERAIS/BANCARIAS: {valor:,.2f} — tarifa debitada direto pelo "
                            f"banco, sem página de comprovante de pagamento própria.",
            ))
        return registros
