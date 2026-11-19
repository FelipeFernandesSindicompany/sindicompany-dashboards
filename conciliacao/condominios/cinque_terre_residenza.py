"""
Conciliador específico — Cinque Terre Residenza.

Cadastrado como empresa_gestora="habitacional_xlsx" (planilha "prestacao_contas_M_AAAA.xlsx", com os links dos anexos). Em set/2026 a
administradora enviou um PDF ESCANEADO de 5 páginas (Demonstrativo de Despesas, Posição Financeira, Conciliação Bancária e Resumo Financeiro
Contábil), sem comprovantes: não há o que conferir por comprovante — as regras gerais (extrator por OCR em
regras_gerais/extratores/cinque_terre_residenza.py) é que leem o arquivo, e o relatório traz o aviso de escopo. O formato é escolhido pela extensão.
Em out/2026 o PDF resumido (5 págs, com texto) passou a trazer, em cada lançamento, um link para o portal GoControleDocumentos da Light
(lapp.condominiolight.com.br/gocontroledocumentos/AbrirDoctos.aspx?LANCTO=...) — o MESMO protocolo do Cores/Splendor (conciliacao/gocontroledocumentos.py):
cada linha com link vira `despesa_listada` + `comprovante_anexado` (documentos baixados e lidos). Reaproveita a leitura do Cores (mesmo layout "Nº lancto.").
"""
from pathlib import Path

from conciliacao.condominios.cores import Conciliador as _ConciliadorCores
from conciliacao.condominios.patricia import _links_de_despesa
from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX


class Conciliador(ConciliadorHabitacionalXLSX):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith(".pdf"):
            if _links_de_despesa(Path(caminho)):
                return _ConciliadorCores._extrair_pdf_com_links(self, Path(caminho))
            return []
        return super().extrair_comprovantes(caminho)
