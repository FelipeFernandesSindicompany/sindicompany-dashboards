"""
Extrator das regras gerais — 730 Padre Carvalho (Loan Gestão Imobiliária, ContasData).

Em set/2026 a administradora enviou só o Demonstrativo de Despesas e o Resumo Financeiro Contábil (3 páginas, exportação
Stimulsoft). O arquivo não traz as marcas que o extrator ContasData usa para se reconhecer ("Voltar ao índice", "ContasData",
"Nº lancto.", "Emitido em"), embora tenha exatamente os blocos que ele lê. Aqui o reconhecimento aceita também o arquivo que
tem, juntos, o cabeçalho "Condomínio: NNNN - ...", o "Demonstrativo de Despesas", os "TOTAL DA CONTA" e o "Resumo Financeiro
Contábil" — a leitura em si é a do ContasData, sem nenhuma mudança.
"""
import re

from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ExtratorContasData


class Extrator(_ExtratorContasData):
    def _reconhecer(self, paginas: list) -> bool:
        try:
            return super()._reconhecer(paginas)
        except ValueError:
            todo = "\n".join(p.texto for p in paginas[:40])
            if (re.search(r"Condom[ií]nio:\s*\d+\s*-", todo) and re.search(r"Demonstrativo de Despesas", todo)
                    and re.search(r"TOTAL DA CONTA", todo, re.I) and re.search(r"Resumo Financeiro Cont[áa]bil", todo, re.I)):
                return any(p.tipo == "despesas" for p in paginas)
            raise
