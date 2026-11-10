"""
Conciliador específico — Cores.

Cadastrado como empresa_gestora="habitacional_xlsx" (planilha "prestacao_contas_M_AAAA.xlsx", usada até jul/2026), mas
a administradora passou a entregar o PDF em outros layouts (ago/2026 em diante). O formato é escolhido pelo conteúdo:
  .xlsx/.xlsm/.xls              → leitor de planilha Habitacional (hyperlink "Link" na coluna Anexo)
  PDF do portal CondoPro        → mesma lógica da planilha: o comprovante é o ÍCONE de anexo da linha do lançamento
                                  (linha sem ícone = sem comprovante), lido de conciliacao/regras_gerais/extratores/condopro_pdf.py
  PDF "Demonstrativo de Contas" → leitor ContasData (Lirba); esse PDF só traz o Demonstrativo, sem comprovantes nem ícones
  PDF "Demonstrativo de Contas" COM LINKS (out/2026 em diante): cada linha do "Demonstrativo de Despesas" traz um link para o portal
                                  GoControleDocumentos (o mesmo protocolo da Patrícia/Elo, conciliacao/gocontroledocumentos.py); cada linha com
                                  link vira `despesa_listada` + `comprovante_anexado` (todos os documentos do lançamento lidos). O código do
                                  registro é o "Nº lancto." de 8 dígitos impresso no PDF.
"""
import re
from pathlib import Path

from conciliacao import gocontroledocumentos, ocr
from conciliacao.base import RegistroComprovante
from conciliacao.condominios.patricia import _documento_da_evidencia, _links_de_despesa, ocultar_cpf
from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF, _num
from conciliacao.lirba_pdf import preencher_de_texto as _preencher_via_cadeia_compartilhada

# "12516983 08/10/2026 Outras Despesas / Beneficios - CONDOMED ASSESSORIA E 475,39 475,39 0,48%" (o 2º valor é o total do grupo, só na última linha dele)
_RE_LINHA_LINKS = re.compile(r"^(\d{8})\s+(\d{2}/\d{2}/\d{4})\s+(.*?)\s+(-?[\d.]+,\d{2})(?:\s+-?[\d.]+,\d{2})?(?:\s+-?[\d,]+%)?\s*$")
_RE_TOTAL_CONTA = re.compile(r"^TOTAL\s+DA\s+CONTA\s+(.+?)\s+-?[\d.]+,\d{2}(?:\s+-?[\d,]+%)?\s*$", re.IGNORECASE)
_RE_TOTAL_GERAL = re.compile(r"^TOTAL\s+DAS\s+DESPESAS", re.IGNORECASE)
_X_MAX_PAGINA = 700                # marcadores do sistema ("ContasData", "Doctos", "Panel53") ficam fora da página


def _registros_condopro(caminho: Path) -> list:
    """Mesmo resultado do ConciliadorHabitacionalXLSX, a partir das linhas reconstruídas do PDF do CondoPro."""
    from adapters.habitacional_xlsx import _normalizar_categoria
    from conciliacao.regras_gerais.extratores.condopro_pdf import _ler_documento

    paginas_pdf: list = []
    linhas = _ler_documento(Path(caminho), paginas_pdf)
    registros: list = []
    dentro = False
    categoria = None
    for n, r in enumerate(linhas, start=1):
        col0 = r[0]
        if not dentro:
            if isinstance(col0, str) and "Demonstrativo de Despesas" in col0:
                dentro = True
            continue
        total = r[4] if isinstance(r[4], str) and r[4].strip().upper().startswith("TOTAL") else None
        if total:
            if total.upper() == "TOTAL DAS DESPESAS":
                break
            continue
        if isinstance(col0, str) and col0.strip() and all(v in (None, "") for v in r[1:8]) and not col0.strip().upper().startswith(("TOTAL", "Nº", "CONDOM")):
            categoria = _normalizar_categoria(col0.strip())
            continue
        if not (isinstance(col0, str) and col0.strip().isdigit() and r[1]):
            continue            # sem data = rótulo/subtotal (ex.: "Tarifa de Cobrança"), como na planilha
        codigo = str(n) if col0.strip() == "0" else col0.strip()
        registros.append(RegistroComprovante(
            pagina=paginas_pdf[n - 1], tipo_documento="despesa_listada", codigo=codigo,
            descricao=str(r[3])[:200] if r[3] else None, vencimento=str(r[1]),
            valor=float(r[7] or 0.0), categoria_demonstrativo=categoria,
            texto_bruto=" | ".join(str(v) for v in r[:8] if v is not None)))
        if r[2]:
            registros.append(RegistroComprovante(
                pagina=paginas_pdf[n - 1], tipo_documento="comprovante_anexado", codigo=codigo,
                texto_bruto="http://portal.condopro/anexo (ícone de anexo na linha do lançamento)"))
    return registros


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        nome = str(caminho).lower()
        if nome.endswith((".xlsx", ".xlsm", ".xls")):
            return ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        if nome.endswith(".pdf"):
            from conciliacao.regras_gerais.extratores.condopro_pdf import Extrator as _CondoPro

            if _CondoPro({}).reconhece(Path(caminho)):
                return _registros_condopro(Path(caminho))
            if _links_de_despesa(Path(caminho)):
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

        # categoria = "TOTAL DA CONTA X" de grupo (recuo ~106) que fecha o bloco; o total da conta-caixa (recuo ~60) não conta
        totais_idx = [(i, m.group(1).strip()) for i, l in enumerate(linhas_globais) if l[4] > 100
                      for m in [_RE_TOTAL_CONTA.match(l[5])] if m]

        def categoria_para(i: int):
            for idx_total, nome in totais_idx:
                if idx_total >= i:
                    return cat_map.get(nome.upper(), nome.upper())
            return None

        idx_total_geral = next((i for i, l in enumerate(linhas_globais) if _RE_TOTAL_GERAL.match(l[5])), len(linhas_globais))

        for i, (pagina, top, bottom, largura, _x0, texto, link_uri, ly1) in enumerate(linhas_globais):
            if i >= idx_total_geral:
                break
            m = _RE_LINHA_LINKS.match(texto)
            if not m:
                continue
            codigo, data, descricao, valor_txt = m.groups()
            valor = _num(valor_txt)
            fim_bloco = bottom
            # descrição quebrada em 2+ linhas: as seguintes caem dentro do retângulo do link da linha
            if ly1 is not None:
                for j in range(i + 1, min(i + 4, len(linhas_globais))):
                    p2, t2, b2, _l2, _x2, tx2, _u2, _y2 = linhas_globais[j]
                    if p2 == pagina and t2 < ly1 - 1 and not _RE_LINHA_LINKS.match(tx2):
                        descricao = f"{descricao} {tx2}"
                        fim_bloco = b2
                    else:
                        break
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
