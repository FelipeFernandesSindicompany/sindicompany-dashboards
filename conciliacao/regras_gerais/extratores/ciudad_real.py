"""
Extrator das regras gerais — Ciudad Real (GK Administração de Bens, `gk_pdf`).

O condomínio é enviado ao Admin em DOIS formatos (ver `conciliacao/condominios/ciudad_real.py`), ambos com as mesmas
seções e a mesma geometria de tabela do software da GK (o mesmo desenho do ContasData):

  * COMPLETO — "Prestação de Contas MM.AAAA.PDF" (~358 págs, 27-40 MB): índice "Prestação de Contas", Resumo Financeiro
    Contábil, Posição Financeira, Demonstrativos de Receitas e Despesas, e centenas de páginas "Comprovante de Despesa"
    embutidas (nunca lidas aqui);
  * PARCIAL — export "Demonstrativo de Contas" (~14 págs, 0,2 MB; nome do upload `sc_conciliacao_*.pdf`): as mesmas
    seções SEM índice, SEM comprovantes e SEM a marca "Voltar ao índice"; cada linha de despesa só tem link externo
    para o GoControleDocumentos (links não importam para as regras gerais).

Os dois são lidos por `contasdata.Extrator` (a geometria vem do cabeçalho de cada página). O que muda aqui é só o
RECONHECIMENTO do formato: o parcial não tem as marcas que o ContasData usa para se identificar.

Pontos específicos do Ciudad Real (conferidos nos arquivos reais de mai, jun, jul/2026 e no parcial de ago/2026):
  * contas: ORDINARIA, FUNDO DE RESERVA, SALÃO DE FESTAS/CHURRASQUEIRA, FACILITIES, CRÉDITOS A IDENTIFICAR (+ AUDITORIA
    só no Resumo de Emissões). A ORDINARIA reúne a c/c Itaú, o PRIVILEGE e o ITAUVEST; o FUNDO DE RESERVA, o CDB DI;
  * a seção "Transferências" (fim do Demonstrativo de Despesas = coluna Débito; fim do de Receitas = coluna Crédito)
    traz UMA coluna só: "REPASSE KARPAT", "APLICAÇÃO ITAUVEST", "RESGATE ITAUVEST", "APLICAÇÃO CDB-DI". Ela entra como
    lançamento `TRANSFERÊNCIA ENTRE CONTAS` (débito) e como receita `tipo=transferencia` (crédito) — por isso o débito de
    149.603,81 da ORDINARIA em jul/2026 fecha ao centavo com despesas + R$ 13.246,68 de transferências;
  * o Demonstrativo de Receitas completo é seguido, depois de "TOTAL GERAL RECEITAS", da "Relação de cotas em aberto"
    (mesmo cabeçalho de colunas): NÃO é receita e é cortada aqui (o leitor genérico a somava em CRÉDITOS A IDENTIFICAR);
  * CRÉDITOS A IDENTIFICAR recebe "DEPÓSITOS NÃO IDENTIFICADOS": jul/2026 uma baixa de recibos de −1.835,02 (receita
    negativa real, créditos do Resumo negativos);
  * rendimento: "REND PAGO APLIC AUT MAIS" (c/c) + "RENDIMENTO APLICAÇÃO PRIVILEGE/ITAUVEST" na ORDINARIA e "RENDIMENTO
    APLICAÇÃO CDB-DI" no FUNDO DE RESERVA, mais linhas "IR APLICAÇÃO ..." e correções negativas (mai/2026: PRIVILEGE
    −1.132,22), todas dentro do Demonstrativo de Receitas, uma por linha, com data;
  * no PARCIAL (sem recibos com histórico) as receitas vêm do "Resumo de Recebimentos" por categoria (uma linha por
    categoria e conta, soma fecha com os créditos do Resumo) e só as linhas negativas dos recibos/"OUTROS RECEBIMENTOS"
    são lidas individualmente; despesas, transferências e contas são idênticas às do completo;
  * arquivos escaneados da administradora anterior (Verticce, nov/2025 a fev/2026: 2-3 páginas, só imagem, só totais por
    categoria, sem lançamentos) NÃO são lidos: cobertura False com o motivo (nunca valores de OCR).
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.extratores.contasdata import Extrator as _ContasData, _norm, _sem_acento
from conciliacao.regras_gerais.modelo import DadosRegras


class Extrator(_ContasData):
    NIVEL_CATEGORIA = "subconta"

    def _reconhecer(self, paginas: list) -> bool:
        inicio = "\n".join(p.texto for p in paginas[:40])
        tem_condominio = re.search(r"Condom[ií]nio:\s*\d+\s*-", inicio)
        completo = re.search(r"Presta[çc][ãa]o de Contas", inicio) and re.search(r"Voltar ao [íi]ndice|ContasData|N[ºo°] lancto", inicio, re.I)
        parcial = re.search(r"^Demonstrativo de Contas\s*$", inicio, re.M) and re.search(r"N[ºo°] lancto|Posi[çc][ãa]o Financeira", inicio)
        if not (tem_condominio and (completo or parcial)):
            raise ValueError("formato não reconhecido como GK ADM (Prestação de Contas / Demonstrativo de Contas)")
        todo = "\n".join(p.texto for p in paginas if p.tipo != "outro")
        resumo = re.search(r"Resumo Financeiro Cont[áa]bil", todo, re.I)
        total_conta = re.search(r"TOTAL DA CONTA", todo, re.I)
        despesas = any(p.tipo == "despesas" for p in paginas)
        return bool(resumo and total_conta and despesas)

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        dados = super().extrair(caminho, mes)
        if not any(dados.cobertura.values()) and dados.avisos and "só imagem" in dados.avisos[0]:
            motivo = ("o PDF é uma digitalização (scanner) do relatório da administradora anterior, sem camada de texto e só com "
                      "totais por categoria (sem lançamentos individuais nem recibos): a leitura exigiria OCR e não é confiável")
            dados.avisos = [motivo]
            dados.motivos_nao_cobertos = {k: motivo for k in ("receitas", "rendimentos", "lancamentos")}
        return dados

    # -- Demonstrativo de Receitas: só até "TOTAL GERAL RECEITAS" --------------------------------------------------
    def _receitas_recibos(self, paginas: list, contas: dict) -> list:
        """Depois do 'TOTAL GERAL RECEITAS' (e da seção Transferências) o completo ainda imprime a 'Relação de cotas em
        aberto' / 'Relação de Devedores' em páginas com o mesmo cabeçalho de colunas (Unidade, Recibo, Vencto., Histórico,
        Valor): são cotas devidas, NÃO receitas — o leitor genérico as somava na última conta (CRÉDITOS A IDENTIFICAR)."""
        fim = None
        for p in paginas:
            if p.tipo == "receitas" and re.search(r"TOTAL GERAL RECEITAS", p.texto):
                fim = p.n
                break
        if fim is not None:
            paginas = [p for p in paginas if p.n <= fim]
        return super()._receitas_recibos(paginas, contas)

    def _ler_transferencias(self, paginas: list) -> dict:
        """Igual ao genérico, mas o corte do cabeçalho da página é y<90 (no GK a linha de colunas 'Data Histórico Débito'
        da seção fica em y≈109 e o genérico a descartava por y<110, deixando a seção sem lado de coluna)."""
        st = self._novo_estado_transf()
        for p in paginas:
            if "Comprovante de Despesa" in p.texto[:260] or re.search(r"^\s*[ÍI]ndice\s*$", p.texto[:400], re.M):
                continue
            if not st["ativo"] and not re.search(r"^Transfer[êe]ncias\s*$", p.texto, re.M):
                continue
            for l in p.linhas:
                if self._rodape(l) or l.y < 90:
                    continue
                self._linha_transferencia(l, _sem_acento(l.texto).upper(), st)
        vistos: dict = {}
        unicas = []
        for e in st["entradas"]:
            k = (e["lado"], _norm(e["conta"]), e["data"], round(e["valor"], 2))
            if k not in vistos or vistos[k] == e["pg"]:
                vistos.setdefault(k, e["pg"])
                unicas.append(e)
        st["entradas"] = unicas
        return st

    # -- seção "Transferências": coluna única (Débito no demonstrativo de despesas, Crédito no de receitas) --------
    def _linha_transferencia(self, l, up: str, st: dict) -> bool:
        """Na GK a seção Transferências vem com UMA coluna de valor: 'Débito' (fim do Demonstrativo de Despesas, também
        no export parcial, que traz o Nº lancto.) ou 'Crédito' (fim do Demonstrativo de Receitas). O leitor genérico exige
        as duas colunas e então a seção nunca era lida (as transferências entravam só pela Posição Financeira, sem data nem
        histórico). Aqui o lado vem do cabeçalho."""
        if st["ativo"]:
            nomes = {w[4].lower(): w for w in l.pal}
            tem_deb, tem_cred = "débito" in nomes, "crédito" in nomes
            if tem_deb != tem_cred:
                w = nomes["débito" if tem_deb else "crédito"]
                st["lado_unico"] = "deb" if tem_deb else "cred"
                st["deb"] = w[2] if tem_deb else -1e5
                st["cred"] = w[2] if tem_cred else -1e5
                return True
        n = len(st["entradas"])
        res = super()._linha_transferencia(l, up, st)
        if res and len(st["entradas"]) > n and st.get("lado_unico"):
            st["entradas"][-1]["lado"] = st["lado_unico"]
        if res and not st["ativo"]:
            st.pop("lado_unico", None)
        return res

    def _tipo_receita(self, categoria: str, historico: str) -> str:
        h = _norm(historico)
        if re.match(r"^(RESGATE|APLICACAO)", h) or h.startswith("APLICACAO RESGATE"):
            return "transferencia"
        return super()._tipo_receita(categoria, historico)
