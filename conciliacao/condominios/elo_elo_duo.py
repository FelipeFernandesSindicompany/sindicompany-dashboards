"""
Conciliador específico — Elo & Elo Duo Caminhos da Lapa.

Planilha .xlsx (Habitacional, com hyperlink "Link" por lançamento) -> conciliador Habitacional, como sempre.
PDF "Pasta Digital" completo (ContasData, "Voltar ao índice", ~545 págs com o Demonstrativo e os comprovantes — jul/2026) -> leitor ContasData
(Lirba), igual ao Onze 22/Baturité/Port Saint Tropez.
PDF resumido (4 págs, só Resumo Financeiro + Demonstrativo de Despesas, ago/2026) -> não traz comprovantes: nenhum registro de comprovante; a
validação segue só pelas regras gerais (lidas do próprio PDF) e o relatório avisa o escopo.
PDF resumido COM LINKS (6 págs, ago/set/2026 reemitido em 10/11/2026): cada linha do "Demonstrativo de Despesas" traz um link para o portal
"GoControleDocumentos" da Graiche (sistemas.graiche.com.br/gocontroledocumentos/AbrirDoctos.aspx?LANCTO=...) — o MESMO protocolo já usado na Patrícia,
Upper Itaim, Ciudad Real e Central das Artes (conciliacao/gocontroledocumentos.py). Cada linha com link vira `despesa_listada` + `comprovante_anexado`
(todos os documentos do lançamento lidos por OCR/texto). O PDF não traz o Nº do lançamento: o código do registro é sequencial (L001, L002...).
"""
import re
from pathlib import Path

from conciliacao import gocontroledocumentos, ocr
from conciliacao.base import RegistroComprovante
from conciliacao.condominios.patricia import _documento_da_evidencia, _links_de_despesa, ocultar_cpf
from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF, _num
from conciliacao.lirba_pdf import preencher_de_texto as _preencher_via_cadeia_compartilhada

_PAGINAS_PASTA_DIGITAL = 30        # acima disso o PDF é a Pasta Digital com comprovantes; o resumo mensal tem 4-6 páginas

# "21/09/2026 CONDOMED ASSESSORIA - NF. 211757 - GESTAO DE 335,63 352,00" (o 2º valor é o total da subconta, só na última linha do grupo)
_RE_LINHA = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.*?)\s+(-?[\d.]+,\d{2})(?:\s+-?[\d.]+,\d{2})?\s*$")
_RE_TOTAL_CONTA = re.compile(r"^TOTAL\s+DA\s+CONTA\s+(.+?)\s+[\d.]+,\d{2}\s*$", re.IGNORECASE)
_RE_TOTAL_GERAL = re.compile(r"^TOTAL\s+DAS\s+DESPESAS", re.IGNORECASE)
_X_MAX_PAGINA = 700                # marcadores do sistema ("ContasData", "Doctos", "Panel53") ficam fora da página


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        import fitz
        with fitz.open(str(caminho)) as doc:
            paginas = len(doc)
        if paginas <= _PAGINAS_PASTA_DIGITAL:
            if _links_de_despesa(Path(caminho)):
                return self._extrair_pdf_com_links(Path(caminho))
            return []
        return super().extrair_comprovantes(caminho)

    def _extrair_pdf_com_links(self, caminho: Path) -> list:
        import fitz
        import pdfplumber

        cat_map = self.parser_config.get("cat_map", {})
        registros: list[RegistroComprovante] = []
        doc_da_evidencia = _documento_da_evidencia(caminho)

        # (pagina_1based, top, bottom, largura, x0, texto, link_uri, link_y0, link_y1)
        linhas_globais = []
        with pdfplumber.open(str(caminho)) as pdf, fitz.open(str(caminho)) as fdoc:
            for i, page in enumerate(pdf.pages):
                if "Demonstrativo de Despesas" not in (page.extract_text() or ""):
                    continue
                links = [l for l in fdoc[i].get_links() if l.get("uri")]
                for linha in page.extract_text_lines():
                    if linha["top"] > 3000 or linha["x0"] > _X_MAX_PAGINA:
                        continue
                    texto = linha["text"].replace("ContasData", " ").strip()
                    cand = next((l for l in links if abs(l["from"].y0 - linha["top"]) < 4), None)
                    linhas_globais.append((i + 1, linha["top"], linha["bottom"], page.width, linha["x0"], texto,
                                           cand.get("uri") if cand else None,
                                           cand["from"].y0 if cand else None, cand["from"].y1 if cand else None))

        # categoria = nome do "TOTAL DA CONTA X" de subconta (recuo 106) que fecha o bloco; o total da conta-caixa (recuo 60) não conta
        totais_idx = [(i, m.group(1).strip()) for i, l in enumerate(linhas_globais) if l[4] > 100
                      for m in [_RE_TOTAL_CONTA.match(l[5])] if m]

        def categoria_para(i: int):
            for idx_total, nome in totais_idx:
                if idx_total >= i:
                    return cat_map.get(nome.upper(), nome.upper())
            return None

        idx_total_geral = next((i for i, l in enumerate(linhas_globais) if _RE_TOTAL_GERAL.match(l[5])), len(linhas_globais))

        seq = 0
        for i, (pagina, top, bottom, largura, _x0, texto, link_uri, ly0, ly1) in enumerate(linhas_globais):
            if i >= idx_total_geral:
                break
            m = _RE_LINHA.match(texto)
            if not m:
                continue
            data, descricao, valor_txt = m.groups()
            valor = _num(valor_txt)
            fim_bloco = bottom
            # descrição quebrada em 2+ linhas: as seguintes caem dentro do retângulo do link da linha
            if ly1 is not None:
                for j in range(i + 1, min(i + 4, len(linhas_globais))):
                    p2, t2, b2, _l2, _x2, tx2, _u2, _a2, _b2 = linhas_globais[j]
                    if p2 == pagina and t2 < ly1 - 1 and not _RE_LINHA.match(tx2):
                        descricao = f"{descricao} {tx2}"
                        fim_bloco = b2
                    else:
                        break
            seq += 1
            codigo = f"L{seq:03d}"
            margem = 2.0
            registros.append(RegistroComprovante(
                pagina=pagina, tipo_documento="despesa_listada", codigo=codigo, descricao=descricao[:200], vencimento=data, valor=valor,
                categoria_demonstrativo=categoria_para(i), texto_bruto=texto, fornecedor=descricao[:200], conta="TOTAL",
                bbox_crop=(0.0, top - margem, largura, fim_bloco + margem),
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
                comp.cnpj_cpf, comp.autenticacao = melhor.cnpj_cpf, melhor.autenticacao
            if textos_docs:
                comp.texto_bruto = "\n\n---\n\n".join(textos_docs)
            marcador = doc_da_evidencia.get(codigo)
            if marcador:                                     # print de outro documento do lançamento que não o primeiro
                idx_ev = next((k for k, t in enumerate(textos_docs) if re.search(marcador, t, re.IGNORECASE)), None)
                if idx_ev is not None:
                    dados_evidencia, tipo_evidencia = documentos[idx_ev]
            comp.fornecedor = None            # o fornecedor está na listagem; o campo do OCR de NF/boleto não é confiável
            if dados_evidencia is not None and tipo_evidencia == "pdf":
                dados_evidencia = ocultar_cpf(dados_evidencia)
            if dados_evidencia is not None:
                comp.arquivo_evidencia_externa = gocontroledocumentos.salvar_evidencia_externa(caminho, codigo, dados_evidencia, tipo_evidencia)
            registros.append(comp)
        return registros
