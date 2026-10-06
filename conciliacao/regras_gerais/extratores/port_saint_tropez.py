"""
Extrator das regras gerais — Port Saint Tropez.

O condomínio migrou da planilha Habitacional (XLSX "prestacao_contas_M_AAAA") para o PDF "Prestação de Contas"
(Verti/ContasData, Stimulsoft, com índice) em algum mês até mar/2026. Na pasta do projeto convivem os dois:
planilhas de abr/2025 a jul/2026 na raiz e PDFs de jan a jul/2026 em "Pasta de Prestação de Contas". Como o
arquivo enviado ao Admin pode ser de qualquer um dos dois formatos, este módulo despacha pela EXTENSÃO:

  .xlsx/.xlsm -> extratores/habitacional_xlsx.py   (planilha; conferido nos 16 meses da pasta)
  .pdf        -> extratores/contasdata.py          (importado só aqui dentro; se não existir/falhar o import,
                                                    devolve cobertura False com o motivo, nunca derruba a Validação)

Os dois formatos imprimem os mesmos blocos do mesmo sistema (Resumo Financeiro Contábil, Posição Financeira,
Demonstrativos), mas os nomes de conta e categoria podem diferir de um formato para o outro (xlsx 'ORDINÁRIA'
x PDF 'ORDINÁRIA', categorias com asteriscos etc.); a comparação mês a mês (subcontas, rendimento) só é confiável
entre arquivos do mesmo formato — mês anterior em planilha e mês atual em PDF pode gerar achados de nome.
"""
from pathlib import Path

from conciliacao.regras_gerais.modelo import DadosRegras

_MOTIVO_PDF_INDISPONIVEL = "o extrator de PDF ContasData não está disponível nesta instalação ({erro})"


class ExtratorPlanilhaOuContasData:
    """Despacha pela extensão: planilha Habitacional ou PDF ContasData."""

    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        caminho = Path(caminho)
        ext = caminho.suffix.lower()
        if ext in (".xlsx", ".xlsm"):
            from conciliacao.regras_gerais.extratores.habitacional_xlsx import Extrator as ExtratorPlanilha
            return ExtratorPlanilha(self.condo).extrair(caminho, mes)
        if ext == ".pdf":
            try:
                from conciliacao.regras_gerais.extratores.contasdata import Extrator as ExtratorPdf
            except ImportError as exc:
                return self._sem_leitura(caminho, mes, _MOTIVO_PDF_INDISPONIVEL.format(erro=exc))
            return ExtratorPdf(self.condo).extrair(caminho, mes)
        return self._sem_leitura(caminho, mes, f"formato de arquivo '{ext or 'sem extensão'}' não suportado (esperado XLSX ou PDF)")

    @staticmethod
    def _sem_leitura(caminho: Path, mes: str, motivo: str) -> DadosRegras:
        dados = DadosRegras(mes=mes, arquivo=caminho.name)
        dados.cobertura = {"receitas": False, "rendimentos": False, "lancamentos": False}
        dados.motivos_nao_cobertos = {k: motivo for k in dados.cobertura}
        dados.avisos.append(motivo)
        return dados


class Extrator(ExtratorPlanilhaOuContasData):
    pass
