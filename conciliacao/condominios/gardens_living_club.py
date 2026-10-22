"""
Conciliador específico — Gardens Living Club I (Consvicta / GCONT).

O PDF do mês (~500 páginas) traz o "Demonstrativo de Receitas e Despesas Analítico" (texto) e, depois, ~400 páginas de "Comprovantes de
despesas — Credt. em <mês>; Parcela NNNNN", que são IMAGENS escaneadas. O código "Parcela" agrupa as páginas de um mesmo pagamento
(comprovante bancário + nota fiscal/boleto), mas NÃO aparece na listagem — não há vínculo textual entre uma despesa e o seu comprovante.

Por isso o pareamento é feito pelo CONTEÚDO: as páginas de comprovante são lidas por OCR (cache em disco, ver conciliacao/ocr.py), agrupadas por
"Parcela", e cada despesa da listagem procura o grupo que traz o seu VALOR e/ou o número da NOTA FISCAL e/ou o nome do fornecedor. O grupo
encontrado vira o conjunto de páginas daquele "código" e daí em diante vale TODA a cadeia do formato Lirba/ContasData (valor lido na imagem,
releituras em 300 dpi, marcador de Nota Fiscal, conta de concessionária, etc.): `ConciliadorLirbaPDF.extrair_comprovantes`.
Despesa sem nenhum grupo = "sem comprovante" (as isenções — tarifa bancária, retenção paga em guia — ficam por conta do matching).
"""
import re
import unicodedata
from pathlib import Path

from conciliacao import ocr
from conciliacao.base import RegistroComprovante
from conciliacao.consvicta_pdf import ConciliadorConsvictaPDF
from conciliacao.lirba_pdf import ConciliadorLirbaPDF

_RE_PARCELA = re.compile(r"Parcela\s+(\d+)", re.IGNORECASE)
_PALAVRAS_GENERICAS = {"LTDA", "EIRELI", "COMERCIO", "SERVICOS", "SERVICO", "INDUSTRIA", "BRASIL", "SOCIEDADE", "ADVOGADOS", "ADVOCACIA",
                       "MANUTENCAO", "CONSERVADORA", "EQUIPAMENTOS", "SISTEMAS", "TECNOLOGIA", "EMPRESARIAIS", "COMERCIAL", "MATERIAL",
                       "MATERIAIS", "CONSTRUCAO", "ADMINISTRADORA", "BENEFICIOS", "CONDOMINIO", "INSTALACAO", "PAGAMENTO", "REEMBOLSO"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def _br(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Conciliador(ConciliadorLirbaPDF):
    def _extrair_despesas_listadas(self, caminho: Path):
        registros = ConciliadorConsvictaPDF(self.config).extrair_comprovantes(caminho)
        # código ÚNICO no arquivo (a listagem original numera por página): é ele que liga a despesa às páginas do comprovante
        for i, r in enumerate(registros, start=1):
            r.codigo = f"{i:04d}"
        despesas = [r for r in registros if r.tipo_documento == "despesa_listada"]

        grupos = self._grupos_de_comprovantes(caminho)                 # {parcela: [páginas 1-based]}
        textos = {}
        if grupos:
            todas = sorted({p for ps in grupos.values() for p in ps})
            lidos = ocr.ocr_paginas(caminho, [p - 1 for p in todas])    # {índice 0-based: texto}, 150 dpi
            textos = {p: lidos.get(p - 1, "") or "" for p in todas}
        texto_do_grupo = {g: "\n".join(textos.get(p, "") for p in ps) for g, ps in grupos.items()}
        digitos_do_grupo = {g: re.sub(r"\D", "", t) for g, t in texto_do_grupo.items()}
        norm_do_grupo = {g: _norm(t) for g, t in texto_do_grupo.items()}

        # várias linhas da listagem podem citar o MESMO documento (ex.: 3 linhas da fatura Claro 367800690): o comprovante traz o total da fatura
        total_do_documento: dict[str, float] = {}
        linhas_do_documento: dict[str, int] = {}
        for d in despesas:
            if d.autenticacao:
                total_do_documento[d.autenticacao] = round(total_do_documento.get(d.autenticacao, 0.0) + d.valor, 2)
                linhas_do_documento[d.autenticacao] = linhas_do_documento.get(d.autenticacao, 0) + 1

        paginas_por_codigo: dict[str, list[int]] = {}
        primeira: dict[str, int] = {}
        for d in despesas:
            nome = _norm(d.descricao or "")
            # tarifa do banco (sem documento) e retenção de imposto paga em guia consolidada não têm comprovante individual: não se pareia
            # (valores pequenos "casariam" por acaso com qualquer página e distorceriam a soma de pagamentos agrupados)
            if (nome.startswith("BANCO ") and not d.autenticacao) or nome.startswith(("MINISTERIO DA ", "RECEITA FEDERAL")):
                continue
            soma_doc = total_do_documento[d.autenticacao] if d.autenticacao and linhas_do_documento.get(d.autenticacao, 0) > 1 else None
            g = self._melhor_grupo(d, texto_do_grupo, digitos_do_grupo, norm_do_grupo, soma_doc)
            if g is not None:
                paginas_por_codigo[d.codigo] = list(grupos[g])
                primeira[d.codigo] = grupos[g][0]
        self._paginas_por_codigo = paginas_por_codigo
        return registros, primeira

    @staticmethod
    def _grupos_de_comprovantes(caminho: Path) -> dict:
        """{nº da Parcela: [páginas]} das páginas "Comprovantes de despesas" (cabeçalho em texto nativo, o resto é imagem)."""
        import fitz
        grupos: dict[str, list[int]] = {}
        doc = fitz.open(str(caminho))
        try:
            for i in range(len(doc)):
                cab = doc[i].get_text()[:400]
                if "Comprovantes de despesas" not in cab:
                    continue
                m = _RE_PARCELA.search(cab)
                grupos.setdefault(m.group(1) if m else f"p{i + 1}", []).append(i + 1)
        finally:
            doc.close()
        return grupos

    @staticmethod
    def _melhor_grupo(d: RegistroComprovante, texto: dict, digitos: dict, norm: dict, soma_doc: float | None = None):
        """Grupo de páginas cujo conteúdo traz o valor da despesa (ou o total do documento que ela compartilha com outras linhas) e/ou o nº da NF
        e/ou o fornecedor. Exige valor OU NF OU o nome do fornecedor com ao menos 2 palavras distintivas (uma palavra só não basta)."""
        valor = _br(d.valor)
        valor_doc = _br(soma_doc) if soma_doc else None
        nfs = [n for n in re.findall(r"\d{3,}", d.autenticacao or "")]
        fornecedor = (d.descricao or "").split(" - ")[0]
        tokens = [w for w in _norm(fornecedor).split() if len(w) >= 4 and w not in _PALAVRAS_GENERICAS][:3]
        melhor, melhor_pts = None, 0
        melhor_nome, melhor_nome_pts = None, 0
        for g, t in texto.items():
            pts = 0
            if valor in t or (valor_doc and valor_doc in t):
                pts += 3
            if any(re.search(rf"(?<!\d){re.escape(n)}(?!\d)", t) for n in nfs):
                pts += 3
            acertos = sum(1 for w in tokens if w in norm[g])
            if pts == 0:
                if acertos >= 2 and acertos > melhor_nome_pts:
                    melhor_nome, melhor_nome_pts = g, acertos
                continue
            pts += min(2, acertos)
            if pts > melhor_pts:
                melhor, melhor_pts = g, pts
        return melhor if melhor is not None else melhor_nome
