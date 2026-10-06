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
"""
from pathlib import Path

from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        return super().extrair_comprovantes(caminho)
