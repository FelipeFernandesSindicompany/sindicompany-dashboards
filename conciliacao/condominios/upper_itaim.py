"""
Conciliador específico — Upper Itaim (administradora Loan Imóveis/Lirba).

Cadastrado como empresa_gestora="lirba_pdf" em condominios.json, mas o
upload usado na validação de balancetes ("Demonstrativo de Contas", 14
páginas) diverge do ContasData padrão (conciliacao/lirba_pdf.py) num ponto
crítico: as linhas de despesa NÃO têm o código de 4 dígitos no fim
(confirmado em dados reais, ago/2026: nenhuma das 54 despesas tem código
impresso) — mesma classe de problema já resolvida em
conciliacao/condominios/central_das_artes.py pro upload parcial dele, mas
aqui o formato inteiro (não só um upload específico) nunca tem código. O
parser genérico (`_RE_ITEM_LINHA`, que EXIGE esse código) nunca casa
nenhuma linha, daí o "0 registros extraídos" real (confirmado: usuário
reportou "0 achados").

Listagem via pdfplumber (mesma técnica comprovada de conciliacao/
lirba_pdf.py — `extract_text_lines()` já reconstrói cada linha visual com
bbox própria, robusto a variação de layout) + link externo de cada linha
via fitz (pdfplumber não expõe anotações de link) — casados por página e
proximidade Y. Uma tentativa inicial só com fitz (`get_text("words")`
agrupado por Y arredondado) quebrava em casos reais onde a mesma linha
visual (ex.: "TOTAL DA CONTA PESSOAL 7.475,99 6,88%") tem palavras com Y
que arredondam pra grupos diferentes — pdfplumber já resolve isso.

Evidência: cada linha de despesa tem um link externo (anotação PDF kind=2/
URI) pro sistema "GoControleDocumentos" (aqui hospedado em
"loanimoveis.dyndns.org:8080/gocontroledocumentos/AbrirDoctos.aspx?...") —
MESMO software/protocolo já confirmado no GK ADM (Ciudad Real) e no
Robotton (Central das Artes), só outro domínio — reaproveita
conciliacao/gocontroledocumentos.py sem duplicar o cliente HTTP. Não há
nenhuma página "Comprovante de Despesa" embutida neste formato (confirmado:
0 páginas com esse marcador) — sempre externo, sem o caminho rápido
kind=4/GOTO do upload completo do Ciudad Real.

Como não existe código de 4 dígitos pra usar como identificador estável,
cada despesa recebe um código SINTÉTICO sequencial (ordem de leitura do
documento, estável entre reprocessamentos do MESMO arquivo) — usado só
internamente pra parear despesa com sua evidência, nunca exibido como se
fosse um código real do sistema de origem.
"""
import re
from pathlib import Path

from conciliacao import gocontroledocumentos, ocr
from conciliacao.base import ConciliadorBase, RegistroComprovante
from conciliacao.lirba_pdf import _num
from conciliacao.lirba_pdf import preencher_de_texto as _preencher_via_cadeia_compartilhada

# Igual a conciliacao/lirba_pdf.py::_RE_ITEM_LINHA, MENOS o código de 4
# dígitos no fim (que este formato nunca tem) — valor individual (sempre o
# primeiro/mais à esquerda) + opcionalmente o total do mini-grupo + opcionalmente
# o percentual, âncora no FIM da linha (evita casar uma leitura de consumo
# no meio da descrição, mesmo motivo do original).
_RE_VALOR_FINAL = re.compile(r"([\d.]+,\d{2})(?:\s+[\d.]+,\d{2})?(?:\s+[\d,]+%)?\s*$")
_RE_TOTAL_LINHA = re.compile(r"^TOTAL\s+DA\s+CONTA\s+(.+?)\s+[\d.]+,\d{2}(?:\s+[\d,]+%)?\s*$", re.IGNORECASE)
_RE_TOTAL_GERAL = re.compile(r"^TOTAL\s+DAS\s+DESPESAS", re.IGNORECASE)
_RE_DATA_INICIO = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.*)")


def _tem_comprovantes_embutidos(caminho: Path) -> bool:
    """True quando o PDF é o upload COMPLETO ("Prestação de Contas MM.AAAA", ~190 páginas): traz
    páginas "Comprovante de Despesa" embutidas (cabeçalho + código de 4 dígitos), igual ao ContasData
    padrão. O upload PARCIAL (14 páginas, "Demonstrativo de Contas") não tem nenhuma."""
    import fitz

    with fitz.open(str(caminho)) as doc:
        for page in doc:
            if "Comprovante de Despesa" in page.get_text()[:200]:
                return True
    return False


class Conciliador(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        # Upload completo = formato ContasData padrão (listagem COM código + páginas de comprovante
        # embutidas): o parser genérico já cobre. Antes deste desvio o conciliador específico (feito só
        # para o upload parcial, sem código) devolvia 0 registros em todo upload completo (ex.: 06.2026).
        if _tem_comprovantes_embutidos(Path(caminho)):
            from conciliacao.lirba_pdf import ConciliadorLirbaPDF

            return ConciliadorLirbaPDF(self.config).extrair_comprovantes(caminho)

        import fitz
        import pdfplumber

        cat_map = self.parser_config.get("cat_map", {})
        registros: list[RegistroComprovante] = []

        with pdfplumber.open(str(caminho)) as pdf, fitz.open(str(caminho)) as fdoc:
            # ── 1. Junta todas as linhas das páginas "Demonstrativo de
            #      Despesas", em ordem, com o link externo (se houver) na
            #      mesma faixa Y — não existe página embutida neste formato.
            linhas_globais = []  # (pagina_1based, top, bottom, largura_pagina, texto, link_uri)
            for i, page in enumerate(pdf.pages):
                texto_pagina = page.extract_text() or ""
                if "Demonstrativo de Despesas" not in texto_pagina:
                    continue
                links = [l for l in fdoc[i].get_links() if l.get("uri")]
                for linha in page.extract_text_lines():
                    # "ContasData" é a marca-d'água do sistema (rodapé) e às
                    # vezes cola na mesma linha de uma despesa (ex.: "...
                    # 0,07% ContasData"), empurrando o valor pra fora do fim
                    # de linha que _RE_VALOR_FINAL espera — mesmo bug já
                    # resolvido em conciliacao/lirba_pdf.py.
                    texto = linha["text"].replace("ContasData", " ").rstrip()
                    candidato = next((l for l in links if abs(l["from"].y0 - linha["top"]) < 4), None)
                    linhas_globais.append((
                        i + 1, linha["top"], linha["bottom"], page.width, texto,
                        candidato.get("uri") if candidato else None,
                    ))

            # ── 2. Categoria de cada linha = nome da PRÓXIMA "TOTAL DA CONTA
            #      X" à frente (mesma técnica de central_das_artes.py/
            #      ciudad_real.py — a seção fecha com o total, os
            #      subcabeçalhos internos como "SALÁRIOS"/"ADIANTAMENTOS"
            #      dentro de "PESSOAL" não têm total próprio, então são
            #      ignorados automaticamente por não casarem essa âncora) ──
            totais_idx = [
                (i, m.group(1).strip())
                for i, (_, _, _, _, texto, _) in enumerate(linhas_globais)
                for m in [_RE_TOTAL_LINHA.match(texto.strip())] if m
            ]

            def categoria_para(i: int) -> str | None:
                for idx_total, nome in totais_idx:
                    if idx_total >= i:
                        bruta = nome.upper()
                        return cat_map.get(bruta, nome.title())
                return None

            # A última página de "Demonstrativo de Despesas" repete, DEPOIS
            # de "TOTAL DAS DESPESAS", um resumo "Resumo Financeiro Contábil"
            # (mesma tabela da capa "Demonstrativo de Contas") — confirmado
            # em dados reais. Tudo a partir daí não é mais despesa, mesmo
            # que alguma linha termine em número (ex.: "ORDINÁRIA -119.081,23
            # 227.880,88 108.688,15 111,50").
            idx_total_geral = next(
                (i for i, (_, _, _, _, texto, _) in enumerate(linhas_globais)
                 if _RE_TOTAL_GERAL.match(texto.strip())),
                len(linhas_globais),
            )

            # ── 3. Cada linha com valor no fim (data no início é OPCIONAL —
            #      confirmado em dados reais que tarifas recorrentes de
            #      conta única na categoria, ex.: "TARIFA BOLETO BANCARIO",
            #      não têm data de lançamento própria) vira despesa_listada,
            #      com código sintético sequencial (ver docstring). Linhas
            #      "TOTAL DA CONTA X"/"TOTAL DAS DESPESAS" NUNCA são
            #      despesas em si, mesmo terminando em valor. ─────────────
            contador = 0
            for i, (pagina, top, bottom, largura, texto, link_uri) in enumerate(linhas_globais):
                if i >= idx_total_geral:
                    continue
                texto_norm = texto.strip()
                if _RE_TOTAL_LINHA.match(texto_norm):
                    continue
                m_data = _RE_DATA_INICIO.match(texto)
                data, resto = m_data.groups() if m_data else (None, texto)
                m_valor = _RE_VALOR_FINAL.search(resto)
                if not m_valor:
                    continue
                valor = _num(m_valor.group(1))
                descricao = resto[:m_valor.start()].strip(" -")
                contador += 1
                codigo = f"{contador:04d}"
                margem = 2.0

                registros.append(RegistroComprovante(
                    pagina=pagina,
                    tipo_documento="despesa_listada",
                    codigo=codigo,
                    descricao=descricao[:200],
                    vencimento=data,
                    valor=valor,
                    categoria_demonstrativo=categoria_para(i),
                    texto_bruto=texto,
                    fornecedor=descricao[:200],
                    bbox_crop=(0.0, top - margem, largura, bottom + margem),
                ))

                if not link_uri:
                    continue  # sem link → sem_comprovante via matching.py

                comp = RegistroComprovante(
                    pagina=1000 + i,
                    tipo_documento="comprovante_anexado",
                    codigo=codigo,
                )
                # Um lançamento pode ter MAIS DE UM documento anexado (ex.:
                # comprovante bancário + Nota Fiscal — confirmado em dados
                # reais, código 0004) — busca todos, não só o primeiro (ver
                # conciliacao/gocontroledocumentos.py::baixar_todos_
                # comprovantes). Junta o texto de TODOS num só `texto_bruto`
                # (pra achado_nota_fiscal_ausente conseguir achar um
                # marcador de NF em QUALQUER um dos documentos).
                #
                # NÃO usa o primeiro documento com QUALQUER valor não-zero
                # como se fosse o certo — confirmado em dados reais (Ciudad
                # Real, mesmo sistema) que o PRIMEIRO documento da lista às
                # vezes é uma guia de tributo CONSOLIDADA (mesmo documento
                # compartilhado por várias despesas diferentes, ver
                # _RE_TOTAL_DO_DOCUMENTO em conciliacao/lirba_pdf.py) — só o
                # SEGUNDO documento (o comprovante bancário individual) tem
                # o valor certo desse lançamento específico. Tenta todos os
                # documentos e prefere o candidato cujo valor bate com o da
                # própria listagem; sem nenhum batendo exato, cai pro
                # primeiro candidato com QUALQUER valor (mantém o
                # comportamento de consolidação já existente em
                # conciliacao/matching.py::gerar_achados_lirba).
                documentos = gocontroledocumentos.baixar_todos_comprovantes(link_uri)
                textos_docs = []
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
                    textos_docs.append(texto_doc)
                    candidato = RegistroComprovante(pagina=comp.pagina, tipo_documento="comprovante_anexado", codigo=codigo)
                    _preencher_via_cadeia_compartilhada(candidato, texto_doc)
                    candidatos.append(candidato)

                melhor = next(
                    (c for c in candidatos if c.valor != 0.0 and abs(c.valor - valor) <= 0.01),
                    next((c for c in candidatos if c.valor != 0.0), None),
                )
                if melhor is not None:
                    comp.valor = melhor.valor
                    comp.vencimento = melhor.vencimento
                    comp.pagamento = melhor.pagamento
                    comp.fornecedor = melhor.fornecedor
                    comp.cnpj_cpf = melhor.cnpj_cpf
                    comp.autenticacao = melhor.autenticacao
                if textos_docs:
                    comp.texto_bruto = "\n\n---\n\n".join(textos_docs)
                if dados_evidencia is not None:
                    comp.arquivo_evidencia_externa = gocontroledocumentos.salvar_evidencia_externa(
                        caminho, codigo, dados_evidencia, tipo_evidencia
                    )
                registros.append(comp)

        return registros
