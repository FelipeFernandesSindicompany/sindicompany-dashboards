"""
Conciliador específico — Port Saint Tropez.

Cadastrado como empresa_gestora="habitacional_xlsx" em condominios.json, mas
a administradora (Verti) mudou pra PDF ContasData em algum mês entre a
última planilha conhecida e março/2026 (confirmado em dados reais: o
arquivo de março/2026 é um PDF de 238 páginas com "Comprovante de Despesa",
"TOTAL DA CONTA" e a marca-d'água "ContasData" — mesmo padrão de migração
já visto em Baturité, ver conciliacao/condominios/baturite.py) — o
conciliador genérico associado a "habitacional_xlsx" (openpyxl) quebrava
com InvalidFileException ao tentar abrir o PDF como planilha.

O inverso também quebrava: a pasta do condomínio ainda guarda as planilhas de 2025/jan-mar 2026
(`prestacao_contas_M_AAAA.xlsx`, inclusive uma de jul/2026) e o conciliador só de PDF falhava com
"No /Root object! Is this really a PDF?" (varredura de out/2026) ao receber uma planilha. Agora o formato é
escolhido pela extensão do arquivo recebido: .xlsx/.xls → leitor de planilha Habitacional; PDF → ContasData.

PDF resumido COM LINKS (6 págs, out/2026 em diante, sem a Pasta Digital): cada linha do "Demonstrativo de Despesas" traz o Nº do lançamento (8 dígitos) e um
link para o portal GoControleDocumentos (mesmo protocolo do Cores/Elo/Patrícia, conciliacao/gocontroledocumentos.py): cada linha com link vira
`despesa_listada` + `comprovante_anexado`. Reaproveita a leitura do Cores (mesmo layout "Relatórios Financeiros" da BBZ/GK, com "N° lancto." e %).
"""
from pathlib import Path

from conciliacao.condominios.cores import Conciliador as _ConciliadorCores
from conciliacao.condominios.patricia import _links_de_despesa
from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF

_PAGINAS_PASTA_DIGITAL = 30        # acima disso é a Pasta Digital completa (com comprovantes embutidos); o resumo mensal tem ~6 páginas


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        import fitz
        with fitz.open(str(caminho)) as doc:
            paginas = len(doc)
        if paginas <= _PAGINAS_PASTA_DIGITAL and _links_de_despesa(Path(caminho)):
            return _ConciliadorCores._extrair_pdf_com_links(self, Path(caminho))
        return super().extrair_comprovantes(caminho)
