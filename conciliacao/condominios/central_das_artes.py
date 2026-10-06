"""
Conciliador específico — Central das Artes.

Cadastrado como empresa_gestora="lirba_pdf" em condominios.json, mas o
formato real da "Demonstrativo de Despesas" (administradora Hausy/Robotton)
diverge do ContasData padrão em dois pontos, confirmados em dados reais:

  1. As linhas de despesa NÃO têm o código de 4 dígitos no fim (formato
     "total_da_conta", já usado pelo adapter de injeção mensal — ver
     adapters/lirba_pdf.py, parser_config.extract_cats). O parser genérico
     de conciliação (conciliacao/lirba_pdf.py::_RE_ITEM_LINHA, que EXIGE
     esse código) nunca casa uma linha sequer neste formato, daí o "0
     registros extraídos" reportado pelo usuário.

  2. A evidência de cada despesa é alcançada por DOIS mecanismos diferentes,
     confirmados em dados reais em arquivos diferentes do MESMO condomínio:

       a) Um link interno do PDF (anotação kind=4/GOTO, "page": N) pra uma
          página "Comprovante de Despesa" embutida NO PRÓPRIO documento
          (confirmado em julho/2026, pacote completo de 261 páginas — essa
          página já tem código, descrição, valor e data em texto puro,
          sem precisar de rede nem OCR). Esse é o caminho RÁPIDO e
          preferido quando existe.

       b) Quando não há página embutida (confirmado em agosto/2026, um
          upload de só 3 páginas — só a listagem, sem nenhum "Comprovante
          de Despesa" embutido), a MESMA linha tem um link externo (kind=2/
          URI) pro sistema Robotton ("sistemas.imoveis.robotton.com.br/
          gocontroledocumentos_condo/AbrirDoctos.aspx?LANCTO=...&TIPO=..."),
          publicamente acessível sem login, que devolve uma imagem JPEG (ou,
          pra documentos que já eram PDF nativo, um PDF de verdade) do
          comprovante — usado como fallback via rede + OCR.

     Confirmado em dados reais: quando as duas anotações existem na mesma
     linha, elas ficam na MESMA faixa Y (sobrepostas) — a ordem que
     page.get_links() devolve NÃO é garantida, então nunca dá pra pegar "a
     primeira" sem checar explicitamente qual tem o quê.
"""
import re
from collections import defaultdict
from pathlib import Path

from conciliacao import gocontroledocumentos, ocr
from conciliacao.base import ConciliadorBase, RegistroComprovante

_RE_DATA_INICIO = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.*)")
_RE_VALOR = re.compile(r"([\d.]+,\d{2})")
_RE_TOTAL_DA_CONTA = re.compile(r"^TOTAL\s+DA\s+CONTA\s+(.+?)\s+[\d.]+,\d{2}\s*$", re.IGNORECASE)
# Confirmado em dados reais (julho/2026, pacote completo): AO CONTRÁRIO do
# upload parcial de agosto (só a listagem, sem código nenhum no fim da
# linha), o pacote completo TEM o código de 4 dígitos no fim de cada linha
# de despesa — mesma convenção "$valor individual [$valor subtotal] código"
# do formato ContasData padrão (ver _RE_ITEM_LINHA em conciliacao/
# lirba_pdf.py, cuja âncora no FIM da linha é reaproveitada aqui de
# propósito). É esse código, não um contador inventado por nós nem o código
# lido de uma página embutida "parecida", que é a fonte confiável pra parear
# despesa com comprovante — usar qualquer outra coisa (contador sequencial,
# ou o código da 1ª página que um link aponta) já gerou pareamentos errados
# confirmados em dados reais (valores trocados entre despesas vizinhas).
# A âncora no fim (vs. "primeiro valor da linha") também é necessária pelo
# mesmo motivo do _RE_ITEM_LINHA original: uma leitura de consumo no meio da
# descrição (ex.: "50,000KWH", "4.680,000KWH") bate o padrão "X,XX" de forma
# FALSA (vira "50,00") se a busca não for ancorada — confirmado em dados
# reais que isso gerava divergência de valor em despesas de energia elétrica.
_RE_VALOR_E_CODIGO_FINAL = re.compile(r"([\d.]+,\d{2})(?:\s+[\d.]+,\d{2})?\s+(\d{4})\s*$")

# OCR do comprovante Robotton sai limpo o bastante pra reaproveitar o mesmo
# rótulo "Valor do lancto"/"Valor pagto" já usado pelos outros formatos
# ContasData (ver conciliacao/lirba_pdf.py) — mas com fallback pro segundo
# rótulo ("Valor pagto"), confirmado como sempre presente e idêntico ao
# "Valor do lancto" nos documentos reais testados.
# "[^\dR]*" (em vez de "\s*") entre o rótulo e o valor — confirmado em dados
# reais que o OCR às vezes solta um caractere de ruído isolado ali (ex.:
# "Vvalorpagto: � R$ 12,00") que não é espaço e travava a extração.
_RE_VALOR_LANCTO = re.compile(r"[VW]+alor\s*(?:do\s*)?lan\S*to:?[^\dR]*(?:R\$)?\s*([\d.]+,\d{2})", re.IGNORECASE)
_RE_VALOR_PAGTO = re.compile(r"[VW]+alor\s*pagto:?[^\dR]*(?:R\$)?\s*([\d.]+,\d{2})", re.IGNORECASE)
_RE_VENCIMENTO = re.compile(r"Vencimento:?\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_RE_PAGO_EM = re.compile(r"Pago em:?\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_RE_FAVORECIDO = re.compile(r"Favorecido:?\s*(.+)", re.IGNORECASE)
# Fatura de cartão de crédito (ex.: "Cartão Itaú Empresas") — fecha com
# "Total desta fatura R$ X,XX", confirmado em dados reais.
_RE_TOTAL_FATURA = re.compile(r"Total desta fatura:?\s*(?:R\$)?\s*([\d.]+,\d{2})", re.IGNORECASE)
# "DEMONSTRATIVO DE PAGAMENTO" — documento gerado pelo próprio sistema
# Robotton quando o ORIGINAL (nota/conta) não foi enviado pra administradora
# até o fechamento da pasta (confirmado em dados reais: o próprio texto do
# documento diz isso — "não foi enviado para a Administradora"). Mesmo sem
# o documento original, o valor E a data aparecem no final do texto, na
# mesma ordem "<descrição> <valor>,XX <data>" — às vezes com um dígito
# solto colado depois do ano (ruído da extração), daí o "\d?" tolerante.
_RE_VALOR_DATA_FINAL = re.compile(r"([\d.]+,\d{2})\s*(\d{2}/\d{2}/\d{4})\d?\s*$")

# Página "Comprovante de Despesa" embutida no PDF (ver item 2a da docstring
# do módulo) — texto puro, direto, sem OCR: código, descrição (pode ter
# quebras de linha no meio, daí o DOTALL não-guloso), valor e data de
# pagamento nessa ordem fixa.
_RE_COMPROVANTE_PAGINA = re.compile(
    r"Comprovante de Despesa\s*\n(\d{4})\n(.+?)\n([\d.]+,\d{2})\s*\n(\d{2}/\d{2}/\d{4})",
    re.DOTALL,
)


def _ler_comprovante_embutido(doc, pagina_0based: int) -> dict | None:
    """Lê a página "Comprovante de Despesa" embutida diretamente (texto
    real do PDF, nunca imagem) — None se a página não existir ou não seguir
    o padrão esperado (degrada pra "conteúdo não confirmável", não confirma
    um valor às cegas)."""
    if not (0 <= pagina_0based < len(doc)):
        return None
    texto = doc[pagina_0based].get_text()
    m = _RE_COMPROVANTE_PAGINA.search(texto)
    if not m:
        return None
    codigo, descricao, valor, data = m.groups()
    return {
        "codigo": codigo,
        "descricao": descricao.strip(),
        "valor": _num(valor),
        "data": data,
        "texto_bruto": texto,
    }


def _num(s) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


_RE_INDICE_DEMONSTRATIVO = re.compile(r"Demonstrativo de Despesas\s*\n(\d+)")
_RE_PROXIMA_PAGINA = re.compile(r"\n(\d+)\b")


def _intervalo_demonstrativo_despesas(doc) -> tuple[int, int]:
    """
    O PDF completo de "Prestação de Contas" (confirmado em dados reais,
    julho/2026: 261 páginas) traz VÁRIAS seções diferentes (Relatório de
    Lançamentos, Extratos bancários, Folha Analítica, Demonstrativo de
    Receitas...) — processar o documento inteiro linha a linha conta datas e
    valores de seções que não são despesas (gerou 484 "despesas" fantasmas
    numa tentativa real). O Índice (sempre nas 2 primeiras páginas) lista
    cada seção com seu número de página inicial em sequência — usa isso pra
    achar onde "Demonstrativo de Despesas" começa e onde a seção seguinte
    começa (limite exclusivo). Se o Índice não bater nesse padrão exato
    (ex.: mês em que a administradora mudou a ordem/nome das seções), cai
    pro documento inteiro — mais lento e sujeito a ruído, mas nunca perde
    despesas reais por causa de um Índice que não bateu.
    """
    texto_indice = ""
    for i in range(min(3, len(doc))):
        texto_indice += doc[i].get_text()
    m_inicio = _RE_INDICE_DEMONSTRATIVO.search(texto_indice)
    if not m_inicio:
        return 1, len(doc) + 1
    inicio = int(m_inicio.group(1))
    m_fim = _RE_PROXIMA_PAGINA.search(texto_indice, m_inicio.end())
    fim = int(m_fim.group(1)) if m_fim else len(doc) + 1
    return inicio, fim


class Conciliador(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import fitz

        cat_map = self.parser_config.get("cat_map", {})
        registros: list[RegistroComprovante] = []

        doc = fitz.open(str(caminho))
        try:
            pagina_inicio, pagina_fim = _intervalo_demonstrativo_despesas(doc)

            # ── 1. Junta todas as linhas das páginas do Demonstrativo de
            #      Despesas, em ordem, com página + os 2 tipos de link
            #      possíveis na mesma faixa Y (ver docstring do módulo) ────
            # Páginas "Comprovante de Despesa" embutidas (a evidência em si,
            # ver item 2a da docstring do módulo) ficam DENTRO do mesmo
            # intervalo 25-255 que as páginas de listagem real — confirmado
            # em dados reais que elas TAMBÉM têm uma linha "data + descrição
            # + valor" no seu próprio resumo, que o parser de listagem
            # reconhecia como se fosse mais uma despesa da tabela (código
            # fantasma, sequencial, colidindo com os códigos reais das
            # despesas de verdade — foi isso que causou os pareamentos
            # errados). Só processa como listagem as páginas que NÃO são elas
            # mesmas uma página de comprovante.
            linhas_globais = []  # (pagina_1based, y, texto, pagina_embutida_0based, link_uri)
            for pidx in range(pagina_inicio - 1, min(pagina_fim - 1, len(doc))):
                page = doc[pidx]
                if "Comprovante de Despesa" in page.get_text():
                    continue
                links = page.get_links()
                palavras = page.get_text("words")
                por_y = defaultdict(list)
                for w in palavras:
                    por_y[round(w[1])].append(w)
                for y in sorted(por_y):
                    ws = sorted(por_y[y], key=lambda w: w[0])
                    texto = " ".join(w[4] for w in ws)
                    candidatos = [l for l in links if abs(l["from"].y0 - y) < 3]
                    link_interno = next((l for l in candidatos if l.get("kind") == 4 and "page" in l), None)
                    link_uri = next((l for l in candidatos if l.get("uri")), None)
                    pagina_embutida = int(link_interno["page"]) if link_interno else None
                    linhas_globais.append((
                        pidx + 1, y, texto, pagina_embutida,
                        link_uri.get("uri") if link_uri else None,
                    ))

            # ── 2. Categoria de cada linha = nome da PRÓXIMA "TOTAL DA CONTA
            #      X" à frente (a seção fecha com o total, não abre com um
            #      cabeçalho confiável de distinguir de sub-categoria) ─────
            totais_idx = [
                (i, m.group(1).strip())
                for i, (_, _, texto, _, _) in enumerate(linhas_globais)
                for m in [_RE_TOTAL_DA_CONTA.match(texto)] if m
            ]

            def categoria_para(i: int) -> str | None:
                for idx_total, nome in totais_idx:
                    if idx_total >= i:
                        bruta = nome.upper()
                        return cat_map.get(bruta, nome)
                return None

            # ── 3. Cada linha começando com data + tendo valor vira uma
            #      despesa_listada. Código: se a PRÓPRIA linha termina com um
            #      código de 4 dígitos (pacote completo, confirmado em dados
            #      reais — julho/2026), usa ele, a mesma convenção "$valor
            #      [$subtotal] código" do ContasData padrão. Sem código
            #      impresso na linha (upload parcial, só a listagem, sem
            #      nenhum código — confirmado em agosto/2026), cai pra um
            #      contador sequencial próprio. Tentativas anteriores de usar
            #      um contador sequencial SEMPRE, ou de confiar cegamente no
            #      código lido de qualquer página que um link apontasse,
            #      geraram pareamentos errados confirmados em dados reais
            #      (valores de despesas vizinhas trocados entre si) — o
            #      código da própria linha é a única fonte que não erra.
            contador = 0
            for i, (pagina, _y, texto, pagina_embutida, link_uri) in enumerate(linhas_globais):
                m = _RE_DATA_INICIO.match(texto)
                if not m:
                    continue
                data, resto = m.groups()

                m_final = _RE_VALOR_E_CODIGO_FINAL.search(resto)
                if m_final:
                    valor = _num(m_final.group(1))
                    codigo = m_final.group(2)
                    descricao = resto[:m_final.start()].strip(" -")
                else:
                    valores = _RE_VALOR.findall(resto)
                    if not valores:
                        continue
                    valor = _num(valores[0])
                    contador += 1
                    codigo = f"{contador:04d}"
                    descricao = resto.split(valores[0])[0].strip(" -")

                lido = _ler_comprovante_embutido(doc, pagina_embutida) if pagina_embutida is not None else None

                registros.append(RegistroComprovante(
                    pagina=pagina,
                    tipo_documento="despesa_listada",
                    codigo=codigo,
                    descricao=descricao[:200],
                    valor=valor,
                    vencimento=data,
                    categoria_demonstrativo=categoria_para(i),
                    texto_bruto=texto,
                ))

                # Trava de segurança: se a página embutida existe mas o
                # código impresso NELA não bate com o código da própria
                # linha de despesa, o link não aponta pro comprovante certo
                # (ou a leitura da página embutida falhou de forma sutil) —
                # descarta em vez de arriscar um pareamento errado.
                if lido and lido["codigo"] != codigo:
                    lido = None

                if not lido and not link_uri:
                    continue  # sem nenhuma evidência → sem_comprovante (ou isenção, ex. tarifa bancária) via matching.py

                # "lido" já foi calculado acima (mesma chamada, reaproveitada
                # aqui) — caminho RÁPIDO: página "Comprovante de Despesa"
                # embutida no próprio PDF, texto puro, sem rede nem OCR (ver
                # item 2a da docstring do módulo). Usa a página REAL (1-based)
                # como evidência — é uma página de verdade do PDF de origem,
                # então o recorte vetorial padrão (conciliacao/render.py::
                # preparar_evidencia_vetorial) funciona sem nada especial.
                # Nunca colide com a chave página+código da despesa_listada
                # porque essa página nunca é uma página de LISTAGEM (ver
                # exclusão de páginas "Comprovante de Despesa" no passo 1).
                if lido:
                    comp = RegistroComprovante(
                        pagina=pagina_embutida + 1,
                        tipo_documento="comprovante_anexado",
                        codigo=codigo,
                        texto_bruto=lido["texto_bruto"],
                        valor=lido["valor"],
                        pagamento=lido["data"],
                        descricao=lido["descricao"][:200],
                    )
                elif link_uri:
                    # Fallback: sem página embutida (ex.: upload parcial só
                    # com a listagem) — busca via link externo Robotton +
                    # OCR (ver item 2b da docstring do módulo). Página
                    # sintética (fora do range real do PDF) — a evidência não
                    # é uma página deste PDF; usa arquivo_evidencia_externa
                    # em vez do recorte vetorial padrão (ver
                    # _salvar_evidencia_externa e conciliacao/render.py).
                    comp = RegistroComprovante(
                        pagina=1000 + i,
                        tipo_documento="comprovante_anexado",
                        codigo=codigo,
                    )
                    # Um lançamento pode ter MAIS DE UM documento anexado
                    # (ex.: comprovante bancário + Nota Fiscal — confirmado
                    # em dados reais, mesmo sistema usado no Ciudad Real e
                    # Upper Itaim) — busca todos, não só o primeiro (ver
                    # conciliacao/gocontroledocumentos.py::baixar_todos_
                    # comprovantes). Junta o texto de TODOS num só
                    # `texto_bruto` e tenta as regras de valor em CADA
                    # documento até uma confirmar.
                    documentos = gocontroledocumentos.baixar_todos_comprovantes(link_uri)
                    textos_docs = []
                    dados_evidencia = tipo_evidencia = None
                    for idx_doc, (dados_bin, tipo_arquivo) in enumerate(documentos):
                        if idx_doc == 0:
                            dados_evidencia, tipo_evidencia = dados_bin, tipo_arquivo
                        if tipo_arquivo == "jpeg":
                            texto_doc = ocr.ocr_imagem_bytes(dados_bin)
                        else:
                            # PDF nativo (ex.: fatura de concessionária
                            # anexada como PDF, não como imagem, ou a Nota
                            # Fiscal) — tenta texto extraível primeiro; só
                            # recorre a OCR se a página vier vazia
                            # (PDF-imagem, mesmo problema dos outros formatos
                            # ContasData, ver conciliacao/lirba_pdf.py).
                            texto_doc, pagina_ok = gocontroledocumentos.texto_de_pdf_baixado(dados_bin)
                            if len(texto_doc.strip()) < 30 and pagina_ok:
                                texto_doc = gocontroledocumentos.ocr_primeira_pagina(dados_bin)
                        textos_docs.append(texto_doc)

                        if comp.valor == 0.0:
                            m_valor = (
                                _RE_VALOR_LANCTO.search(texto_doc)
                                or _RE_VALOR_PAGTO.search(texto_doc)
                                or _RE_TOTAL_FATURA.search(texto_doc)
                                or _RE_VALOR_DATA_FINAL.search(texto_doc)
                            )
                            if m_valor:
                                comp.valor = _num(m_valor.group(1))
                            m_venc = _RE_VENCIMENTO.search(texto_doc)
                            if m_venc:
                                comp.vencimento = m_venc.group(1)
                            m_pago = _RE_PAGO_EM.search(texto_doc)
                            if m_pago:
                                comp.pagamento = m_pago.group(1)
                            elif m_valor is not None and m_valor.re is _RE_VALOR_DATA_FINAL:
                                comp.pagamento = m_valor.group(2)
                            m_fav = _RE_FAVORECIDO.search(texto_doc)
                            if m_fav:
                                comp.fornecedor = m_fav.group(1).strip()[:200]
                    if textos_docs:
                        comp.texto_bruto = "\n\n---\n\n".join(textos_docs)
                    if dados_evidencia is not None:
                        comp.arquivo_evidencia_externa = gocontroledocumentos.salvar_evidencia_externa(
                            caminho, codigo, dados_evidencia, tipo_evidencia
                        )
                else:
                    continue
                registros.append(comp)
        finally:
            doc.close()

        return registros
