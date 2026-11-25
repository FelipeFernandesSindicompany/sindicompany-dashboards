"""
Conciliador específico — Cap D'Antibes (Administradora Angélica, DataDigitus).

PDF com datas nos lançamentos (abr a ago/2026) -> conciliador DataDigitus de sempre. Layout matricial novo COM texto (out/2026: 1.1 Relatório de Pendências,
2.1 Demonstrativo de Despesas e 5.4 Resumo Financeiro, sem data nos lançamentos, sem 4.1 e sem comprovantes) -> os lançamentos e os totais por conta vêm do
extrator das regras gerais (`extratores/cap_d_antibes.py`), que já os lê e os confere pelas somas do próprio arquivo.
"""
from pathlib import Path

from conciliacao.base import RegistroComprovante
from conciliacao.datadigitus_pdf import ConciliadorDatadigitusPDF


class Conciliador(ConciliadorDatadigitusPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        from conciliacao.regras_gerais.extratores.cap_d_antibes import Extrator

        ext = Extrator(self.config)
        if not ext.eh_layout_resumo(Path(caminho)):
            return super().extrair_comprovantes(caminho)
        dados = ext.extrair(Path(caminho), "")
        registros: list = []
        por_pagina: dict = {}

        def _cod(pag: int) -> str:
            por_pagina[pag] = por_pagina.get(pag, 0) + 1
            return str(por_pagina[pag])

        for l in dados.lancamentos:
            registros.append(RegistroComprovante(
                pagina=l.pagina, codigo=_cod(l.pagina), tipo_documento="despesa_listada", descricao=(l.descricao or "")[:200] or None, valor=l.valor,
                categoria_demonstrativo=l.categoria, conta=l.conta, texto_bruto=l.descricao, bbox_crop=l.bbox))
        pag_total = max((l.pagina or 0) for l in dados.lancamentos) if dados.lancamentos else 1
        for conta, valor in ext.totais_despesas.items():
            if conta == "geral":
                continue
            registros.append(RegistroComprovante(pagina=pag_total, codigo=_cod(pag_total), tipo_documento="total_conta_declarado", descricao=conta, valor=valor,
                                                 texto_bruto=f"TOTAL DA CONTA {valor}"))
        return registros
