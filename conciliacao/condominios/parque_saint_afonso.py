"""
Conciliador específico — Parque Saint Afonso (administradora GCONT).

Cadastrado como empresa_gestora="lirba_pdf" em condominios.json, mas o PDF de
"Prestação de Contas" (ex.: 06.2026, 325 páginas) é do MESMO sistema do Club
Park Butantã (GCONT): cada pagamento tem a sua página "Comprovantes de
despesas" ("Parcela <código>", "Pago a:", "Destina-se a:", "Valor Emitido")
em TEXTO NATIVO, e o relatório "Despesas por categoria" (Livro Caixa) fecha
com "N itens VALOR_TOTAL" (ex.: 67 itens / R$ 99.290,41 em jun/2026, igual à
soma das 67 páginas-capa). O parser genérico do Lirba/ContasData procura
"Comprovante de Despesa" + código de 4 dígitos e por isso devolvia 0
registros (a varredura de out/2026 mostrou 0 comprovantes verificados).

O formato é idêntico ao já validado em conciliacao/condominios/club_park_butanta.py
(que NÃO é alterado): reaproveita a classe dele via _gcont_comum.py (que ainda
repara fornecedor com nome em duas linhas). As regras de matching são as de
`matching.gerar_achados_gcont` (duplicidade, soma x Livro Caixa, atraso, NF
ausente, subconta atípica).

Meses antigos (jun-ago/2025, out-dez/2025) vêm em outro formato (PDF escaneado
sem texto): nenhuma página "Comprovantes de despesas" é achada e o conciliador
devolve [] (mesmo comportamento anterior, sem inventar leitura).
"""
import re

from conciliacao.condominios._gcont_comum import ConciliadorGcontNativo


class Conciliador(ConciliadorGcontNativo):
    def extrair_comprovantes(self, caminho) -> list:
        registros = super().extrair_comprovantes(caminho)
        if any(r.tipo_documento in ("despesa_com_comprovante", "despesa_listada") for r in registros):
            return registros
        # out/2026: prestação RESUMIDA (4 páginas, só o W020A "Demonstrativo de Receitas e Despesas Analítico"): sem as páginas de comprovante, mas cada
        # lançamento traz o link público do portal da GCONT (Superlógica, "...areadocondomino/publico/arquivos?...idParcela=") com os documentos do
        # pagamento — mesmo caminho da variante reduzida do I-Gloo (cada lançamento vira `despesa_listada` e o comprovante é baixado do portal)
        try:
            from pathlib import Path

            from conciliacao.condominios.club_park_butanta import _anexar_comprovantes_do_portal
            from conciliacao.condominios.i_gloo_alphaville import _registros_demonstrativo_analitico
            from conciliacao.regras_gerais.extratores.parque_saint_afonso import Extrator

            regs, linhas = _registros_demonstrativo_analitico(Path(caminho), self.config, Extrator)
            registros = registros + regs
            if any(l["uri"] for l in linhas):
                _anexar_comprovantes_do_portal(Path(caminho), None, registros, linhas=linhas)
                if any(r.tipo_documento == "comprovante_anexado" for r in registros):
                    # tarifa debitada pelo banco / tarifa da garantidora não têm documento no portal
                    registros[:] = [r for r in registros if not (r.tipo_documento == "despesa_listada" and re.match(
                        r"(?i)\s*(banco |despesas banc|tar[ -]|tarifa)", (r.fornecedor or "")))]
        except Exception as exc:
            print(f"[AVISO] não foi possível ler o Demonstrativo Analítico/links do portal: {exc}")
        return registros
