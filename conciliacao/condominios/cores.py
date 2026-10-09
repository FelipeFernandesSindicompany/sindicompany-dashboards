"""
Conciliador específico — Cores.

Cadastrado como empresa_gestora="habitacional_xlsx" (planilha "prestacao_contas_M_AAAA.xlsx", usada até jul/2026), mas
a administradora passou a entregar o PDF em outros layouts (ago/2026 em diante). O formato é escolhido pelo conteúdo:
  .xlsx/.xlsm/.xls              → leitor de planilha Habitacional (hyperlink "Link" na coluna Anexo)
  PDF do portal CondoPro        → mesma lógica da planilha: o comprovante é o ÍCONE de anexo da linha do lançamento
                                  (linha sem ícone = sem comprovante), lido de conciliacao/regras_gerais/extratores/condopro_pdf.py
  PDF "Demonstrativo de Contas" → leitor ContasData (Lirba); esse PDF só traz o Demonstrativo, sem comprovantes nem ícones
"""
from pathlib import Path

from conciliacao.base import RegistroComprovante
from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF


def _registros_condopro(caminho: Path) -> list:
    """Mesmo resultado do ConciliadorHabitacionalXLSX, a partir das linhas reconstruídas do PDF do CondoPro."""
    from adapters.habitacional_xlsx import _normalizar_categoria
    from conciliacao.regras_gerais.extratores.condopro_pdf import _ler_documento

    paginas_pdf: list = []
    linhas = _ler_documento(Path(caminho), paginas_pdf)
    registros: list = []
    dentro = False
    categoria = None
    for n, r in enumerate(linhas, start=1):
        col0 = r[0]
        if not dentro:
            if isinstance(col0, str) and "Demonstrativo de Despesas" in col0:
                dentro = True
            continue
        total = r[4] if isinstance(r[4], str) and r[4].strip().upper().startswith("TOTAL") else None
        if total:
            if total.upper() == "TOTAL DAS DESPESAS":
                break
            continue
        if isinstance(col0, str) and col0.strip() and all(v in (None, "") for v in r[1:8]) and not col0.strip().upper().startswith(("TOTAL", "Nº", "CONDOM")):
            categoria = _normalizar_categoria(col0.strip())
            continue
        if not (isinstance(col0, str) and col0.strip().isdigit() and r[1]):
            continue            # sem data = rótulo/subtotal (ex.: "Tarifa de Cobrança"), como na planilha
        codigo = str(n) if col0.strip() == "0" else col0.strip()
        registros.append(RegistroComprovante(
            pagina=paginas_pdf[n - 1], tipo_documento="despesa_listada", codigo=codigo,
            descricao=str(r[3])[:200] if r[3] else None, vencimento=str(r[1]),
            valor=float(r[7] or 0.0), categoria_demonstrativo=categoria,
            texto_bruto=" | ".join(str(v) for v in r[:8] if v is not None)))
        if r[2]:
            registros.append(RegistroComprovante(
                pagina=paginas_pdf[n - 1], tipo_documento="comprovante_anexado", codigo=codigo,
                texto_bruto="http://portal.condopro/anexo (ícone de anexo na linha do lançamento)"))
    return registros


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        nome = str(caminho).lower()
        if nome.endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        if nome.endswith(".pdf"):
            from conciliacao.regras_gerais.extratores.condopro_pdf import Extrator as _CondoPro

            if _CondoPro({}).reconhece(Path(caminho)):
                return _registros_condopro(Path(caminho))
        return super().extrair_comprovantes(caminho)
