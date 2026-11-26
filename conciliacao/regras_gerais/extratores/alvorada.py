"""
Extrator das regras gerais — Alvorada.

Cadastrado como habitacional_xlsx (planilha "prestacao_contas_M_AAAA.xlsx", até jul/2026), mas a administradora também entrega a
"Pasta Digital" em PDF (ContasData, "Voltar ao índice", ~30 MB com o Demonstrativo e os comprovantes; jun-ago/2026) — mesma
migração do Onze 22, Baturité e Port Saint Tropez. Despacha pela EXTENSÃO: .xlsx → extratores/habitacional_xlsx.py;
.pdf → extratores/contasdata.py.

PDF RESUMIDO (set/2026 em diante: 9 páginas, "Demonstração de Contas" + "Resumo Contábil" + Demonstrativo de Despesas com Nº do lançamento e link do portal
GoControleDocumentos) → o mesmo leitor do Highlights Dr. Nelson Moretti (GK ADM): ver extratores/highlights_dr_nelson_moretti.py.
"""
from pathlib import Path

from conciliacao.regras_gerais.extratores.port_saint_tropez import ExtratorPlanilhaOuContasData


class Extrator(ExtratorPlanilhaOuContasData):
    def extrair(self, caminho: Path, mes: str):
        caminho = Path(caminho)
        if caminho.suffix.lower() == ".pdf":
            import fitz
            with fitz.open(str(caminho)) as doc:
                resumido = len(doc) <= 30
            if resumido:
                from conciliacao.regras_gerais.extratores.highlights_dr_nelson_moretti import Extrator as _Resumido
                return _Resumido(self.condo).extrair(caminho, mes)
        return super().extrair(caminho, mes)
