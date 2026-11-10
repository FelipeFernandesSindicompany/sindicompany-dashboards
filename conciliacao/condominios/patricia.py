"""
Conciliador específico — Maison Patrícia (Auxiliadora Predial).

Planilha .xls (até ago/2026) -> conciliador Auxiliadora, como sempre.

PDF "Demonstrativo de Contas" (set/2026 em diante): posição por conta, despesas e receitas.
  * set/2026: SEM comprovantes e SEM links -> nenhum registro de comprovante; a validação segue só pelas regras gerais, lidas do próprio PDF,
    e o relatório avisa o escopo.
  * out/2026: cada linha de "Demonstrativo de Despesas" traz um link para o portal "GoControleDocumentos" da Auxiliadora
    (gosoftdoc.auxiliadorapredial.com.br:4443/gocontroledocumentos/AbrirDoctos.aspx?LANCTO=...) — o MESMO protocolo já usado no Upper Itaim,
    Ciudad Real e Central das Artes (conciliacao/gocontroledocumentos.py). Cada linha com link vira `despesa_listada` + `comprovante_anexado`
    (todos os documentos do lançamento lidos por OCR/texto). Linha sem link (tarifas bancárias, gás) fica sem comprovante, como no Upper Itaim.
    O código do registro é o Nº do lançamento (8 dígitos) impresso no PDF.
"""
import json
import re
from pathlib import Path

from conciliacao import gocontroledocumentos, ocr
from conciliacao.auxiliadora_xls import ConciliadorAuxiliadoraXLS
from conciliacao.base import RegistroComprovante
from conciliacao.lirba_pdf import _num
from conciliacao.lirba_pdf import preencher_de_texto as _preencher_via_cadeia_compartilhada

# "04956227 07/10/2026 JOSENILDO BORGES - NF. 53 SERVIÇOS DE ZELADORIA 2.450,00" (+ total do mini-grupo e % quando é a última linha do grupo)
_RE_LINHA = re.compile(r"^(\d{8})\s+(\d{2}/\d{2}/\d{4})\s+(.*?)\s+(-?[\d.]+,\d{2})(?:\s+-?[\d.]+,\d{2})?(?:\s+[\d,]+%)?\s*$")
_RE_TOTAL_CONTA = re.compile(r"^TOTAL\s+DA\s+CONTA\s+(.+?)\s+[\d.]+,\d{2}(?:\s+[\d,]+%)?\s*$", re.IGNORECASE)
_RE_TOTAL_GERAL = re.compile(r"^TOTAL\s+DAS\s+DESPESAS", re.IGNORECASE)
_RE_CONTINUACAO = re.compile(r"^\d{1,2}/\d{2,4}$")        # "12/24", "08/2026": fim da descrição quebrada em duas linhas


def _documento_da_evidencia(caminho: Path) -> dict:
    """{código do lançamento: regex} — qual documento do portal é o print do item quando NÃO é o primeiro (ex.: o e-mail com o valor atualizado, o
    comprovante com o pagador efetivo). Arquivo opcional config/evidencia_documento/<condomínio>/<AAAA-MM>.json; sem ele vale o 1º documento."""
    try:
        mes_dir = Path(caminho).parent.parent.parent                    # .../<condomínio>/conciliacao/<mês>/<versão>/input/<arquivo>
        arq = Path(__file__).resolve().parents[2] / "config" / "evidencia_documento" / mes_dir.parent.parent.name / f"{mes_dir.name}.json"
        return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    except (OSError, ValueError):
        return {}


def _links_de_despesa(caminho: Path) -> bool:
    """True quando alguma página "Demonstrativo de Despesas" do PDF tem link para o portal de documentos."""
    import fitz
    with fitz.open(str(caminho)) as doc:
        for pg in doc:
            if "Demonstrativo de Despesas" in (pg.get_text() or "") and any(l.get("uri") for l in pg.get_links()):
                return True
    return False


class Conciliador(ConciliadorAuxiliadoraXLS):
    def extrair_comprovantes(self, caminho: Path) -> list:
        caminho = Path(caminho)
        if caminho.suffix.lower() != ".pdf":
            return super().extrair_comprovantes(caminho)
        if not _links_de_despesa(caminho):
            return []
        return self._extrair_pdf_com_links(caminho)

    def _extrair_pdf_com_links(self, caminho: Path) -> list:
        import fitz
        import pdfplumber

        cat_map = self.parser_config.get("cat_map", {})
        registros: list[RegistroComprovante] = []
        doc_da_evidencia = _documento_da_evidencia(caminho)

        linhas_globais = []          # (pagina_1based, top, bottom, largura, texto, link_uri)
        with pdfplumber.open(str(caminho)) as pdf, fitz.open(str(caminho)) as fdoc:
            for i, page in enumerate(pdf.pages):
                if "Demonstrativo de Despesas" not in (page.extract_text() or ""):
                    continue
                links = [l for l in fdoc[i].get_links() if l.get("uri")]
                for linha in page.extract_text_lines():
                    texto = linha["text"].replace("ContasData", " ").strip()
                    if linha["top"] > 3000:         # texto fora da página (marcadores do sistema: "Doctos", "Panel53"...)
                        continue
                    candidato = next((l for l in links if abs(l["from"].y0 - linha["top"]) < 4), None)
                    linhas_globais.append((i + 1, linha["top"], linha["bottom"], page.width, texto, candidato.get("uri") if candidato else None))

        totais_idx = [(i, m.group(1).strip()) for i, l in enumerate(linhas_globais) for m in [_RE_TOTAL_CONTA.match(l[4])] if m]

        def categoria_para(i: int):
            for idx_total, nome in totais_idx:
                if idx_total >= i:
                    return cat_map.get(nome.upper(), nome.upper())
            return None

        idx_total_geral = next((i for i, l in enumerate(linhas_globais) if _RE_TOTAL_GERAL.match(l[4])), len(linhas_globais))

        for i, (pagina, top, bottom, largura, texto, link_uri) in enumerate(linhas_globais):
            if i >= idx_total_geral:
                break
            m = _RE_LINHA.match(texto)
            if not m:
                continue
            codigo, data, descricao, valor_txt = m.groups()
            valor = _num(valor_txt)
            # descrição quebrada: a linha seguinte é só o fim ("12/24")
            if i + 1 < len(linhas_globais) and _RE_CONTINUACAO.match(linhas_globais[i + 1][4]):
                descricao = f"{descricao} {linhas_globais[i + 1][4]}"
            margem = 2.0
            registros.append(RegistroComprovante(
                pagina=pagina, tipo_documento="despesa_listada", codigo=codigo, descricao=descricao[:200], vencimento=data, valor=valor,
                categoria_demonstrativo=categoria_para(i), texto_bruto=texto, fornecedor=descricao[:200], conta="TOTAL",
                bbox_crop=(0.0, top - margem, largura, bottom + margem),
            ))
            if not link_uri:
                continue                                     # sem link -> "sem comprovante" via matching.py

            comp = RegistroComprovante(pagina=1000 + i, tipo_documento="comprovante_anexado", codigo=codigo)
            documentos = gocontroledocumentos.baixar_todos_comprovantes(link_uri)
            textos_docs: list[str] = []
            candidatos = []
            dados_evidencia = tipo_evidencia = None
            for idx_doc, (dados_bin, tipo_arquivo) in enumerate(documentos):
                if idx_doc == 0:
                    dados_evidencia, tipo_evidencia = dados_bin, tipo_arquivo
                if tipo_arquivo == "jpeg":
                    texto_doc = ocr.ocr_imagem_bytes(dados_bin)
                else:
                    texto_doc, pagina_ok = gocontroledocumentos.texto_de_pdf_baixado(dados_bin)
                    if len(texto_doc.strip()) < 30 and pagina_ok:
                        texto_doc = gocontroledocumentos.ocr_primeira_pagina(dados_bin)
                    texto_doc = (texto_doc + "\n" + gocontroledocumentos.textos_das_demais_paginas(dados_bin)).strip()
                textos_docs.append(texto_doc)
                cand = RegistroComprovante(pagina=comp.pagina, tipo_documento="comprovante_anexado", codigo=codigo)
                _preencher_via_cadeia_compartilhada(cand, texto_doc)
                candidatos.append(cand)

            # prefere o documento cujo valor bate com o da listagem (o 1º pode ser guia consolidada de vários lançamentos)
            melhor = next((c for c in candidatos if c.valor != 0.0 and abs(c.valor - valor) <= 0.01),
                          next((c for c in candidatos if c.valor != 0.0), None))
            if melhor is not None:
                comp.valor, comp.vencimento, comp.pagamento = melhor.valor, melhor.vencimento, melhor.pagamento
                comp.fornecedor, comp.cnpj_cpf, comp.autenticacao = melhor.fornecedor, melhor.cnpj_cpf, melhor.autenticacao
            if textos_docs:
                comp.texto_bruto = "\n\n---\n\n".join(textos_docs)
            marcador = doc_da_evidencia.get(codigo)
            if marcador:                                     # print de outro documento do lançamento que não o primeiro
                idx_ev = next((k for k, t in enumerate(textos_docs) if re.search(marcador, t, re.IGNORECASE)), None)
                if idx_ev is not None:
                    dados_evidencia, tipo_evidencia = documentos[idx_ev]
            comp.fornecedor = None            # o campo vinha de OCR de NF/boleto ("Número da Nota Código de Verificação"); o fornecedor está na listagem
            if dados_evidencia is not None:
                comp.arquivo_evidencia_externa = gocontroledocumentos.salvar_evidencia_externa(caminho, codigo, dados_evidencia, tipo_evidencia)
            registros.append(comp)
        return registros
