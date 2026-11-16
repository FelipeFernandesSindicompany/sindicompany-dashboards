"""
Conciliador específico — Baturité.

Empresa gestora mudou de "habitacional_xlsx" (planilha) para o sistema
ContasData (PDF) a partir de 2026 — confirmado em dados reais: a pasta de
projeto só tem arquivos ".xlsx" até 2025 e só ".pdf" a partir de 2026 (ver
também adapters/condominios/baturite.py, mesmo motivo). A estrutura do
"Demonstrativo de Despesas" é a mesma família ContasData/Lirba, só sem
coluna de data por lançamento — já suportado por
conciliacao/lirba_pdf.py::ConciliadorLirbaPDF após tornar o cabeçalho
"Data Histórico Valor Total" tolerante à ausência de "Data".

Os meses em planilha (até 2025) continuam existindo na pasta: o formato é escolhido pela extensão do arquivo
(.xlsx/.xls → leitor de planilha Habitacional; PDF → ContasData), para não quebrar com "No /Root object!"
ao receber uma planilha (mesmo caso de port_saint_tropez.py).

PDF resumido COM LINKS (6 págs, out/2026 em diante, sem a Pasta Digital): o "Demonstrativo de Despesas" não traz data nem Nº de lançamento — só o
histórico, o valor e, em cada linha, um link para o portal GoControleDocumentos (mesmo protocolo do Cores/Elo/Patrícia, conciliacao/
gocontroledocumentos.py). Cada linha com link vira `despesa_listada` + `comprovante_anexado` (código sequencial L001, L002...). Linhas sem link
(transferência para a aplicação e tarifas bancárias) não são lançamentos a comprovar e ficam de fora.
"""
import re
from pathlib import Path

from conciliacao import gocontroledocumentos, ocr
from conciliacao.base import RegistroComprovante
from conciliacao.condominios.patricia import _documento_da_evidencia, _links_de_despesa, ocultar_cpf
from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF, _num
from conciliacao.lirba_pdf import preencher_de_texto as _preencher_via_cadeia_compartilhada

_PAGINAS_PASTA_DIGITAL = 30        # acima disso é a Pasta Digital completa; o resumo mensal tem ~6 páginas
# "SALARIO LIQUIDO SETEMBRO/2026 - REGINALDO MACHADO DE SOUSA 1.391,00" (o 2º valor é o total do grupo, só na última linha dele)
_RE_LINHA_LINKS = re.compile(r"^(.*?)\s+(-?[\d.]+,\d{2})(?:\s+-?[\d.]+,\d{2})?\s*$")
_RE_TOTAL_GERAL = re.compile(r"^TOTAL\s+DAS\s+DESPESAS", re.IGNORECASE)
_X_MAX_PAGINA = 700


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        import fitz
        with fitz.open(str(caminho)) as doc:
            paginas = len(doc)
        if paginas <= _PAGINAS_PASTA_DIGITAL and _links_de_despesa(Path(caminho)):
            return self._extrair_pdf_com_links(Path(caminho))
        return super().extrair_comprovantes(caminho)

    def _extrair_pdf_com_links(self, caminho: Path) -> list:
        import fitz
        import pdfplumber

        cat_map = self.parser_config.get("cat_map", {})
        registros: list[RegistroComprovante] = []
        doc_da_evidencia = _documento_da_evidencia(caminho)

        # (pagina_1based, top, bottom, largura, x0, texto, link_uri, link_y1)
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
                    cand = next((l for l in links if abs(l["from"].y0 - linha["top"]) < 5), None)
                    linhas_globais.append((i + 1, linha["top"], linha["bottom"], page.width, linha["x0"], texto,
                                           cand.get("uri") if cand else None, cand["from"].y1 if cand else None))

        idx_total_geral = next((i for i, l in enumerate(linhas_globais) if _RE_TOTAL_GERAL.match(l[5])), len(linhas_globais))
        categoria = None
        seq = 0
        for i, (pagina, top, bottom, largura, x0, texto, link_uri, ly1) in enumerate(linhas_globais):
            if i >= idx_total_geral:
                break
            m = _RE_LINHA_LINKS.match(texto)
            if not link_uri or not m:
                # cabeçalho de grupo (recuo ~82, sem valor): define a categoria das linhas seguintes
                if not m and x0 < 95 and not texto.upper().startswith(("TOTAL", "DEMONSTRATIVO", "CONDOMINIO", "PERÍODO", "PÁGINA")):
                    categoria = cat_map.get(texto.upper(), texto.upper())
                continue
            descricao, valor_txt = m.group(1).strip(), m.group(2)
            valor = _num(valor_txt)
            fim_bloco = bottom
            # descrição quebrada em 2+ linhas: as seguintes caem dentro do retângulo do link da linha
            if ly1 is not None:
                for j in range(i + 1, min(i + 4, len(linhas_globais))):
                    p2, t2, b2, _l2, _x2, tx2, u2, _y2 = linhas_globais[j]
                    if p2 == pagina and t2 < ly1 - 1 and not u2:
                        descricao = f"{descricao} {tx2}"
                        fim_bloco = b2
                    else:
                        break
            seq += 1
            codigo = f"L{seq:03d}"
            margem = 2.0
            registros.append(RegistroComprovante(
                pagina=pagina, tipo_documento="despesa_listada", codigo=codigo, descricao=descricao[:200], valor=valor,
                categoria_demonstrativo=categoria, texto_bruto=texto, fornecedor=descricao[:200], conta="TOTAL",
                bbox_crop=(0.0, top - margem, largura, fim_bloco + margem),
            ))

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
