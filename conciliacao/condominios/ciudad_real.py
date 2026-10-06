"""
Conciliador específico — Ciudad Real (administradora GK ADM).

Cadastrado como empresa_gestora="gk_pdf" em condominios.json, que reaproveita
ConciliadorLirbaPDF (ver conciliacao/__init__.py — "mesma estrutura
ContasData do Lirba"). Isso é verdade pro "Demonstrativo de Despesas" — a
listagem de códigos/valores é extraída certa pelo pai via pdfplumber
(confirmado em dados reais: 76/76 despesas em ago/2026, formato parcial;
categoria corretamente atribuída também no arquivo completo de jul/2026).

A EVIDÊNCIA de cada despesa, porém, vem de DOIS mecanismos diferentes,
confirmados em dados reais em arquivos diferentes do MESMO condomínio —
mesma dualidade já vista em conciliacao/condominios/central_das_artes.py:

  a) Upload parcial (ex.: ago/2026, só a "Demonstrativo de Contas" +
     listagem de despesas, 14 páginas) — NENHUMA página "Comprovante de
     Despesa" embutida. Cada linha tem só um link externo (anotação PDF
     kind=2/URI) pro sistema GK ADM ("sistemas.gk.com.br/
     gocontroledocumentos/AbrirDoctos.aspx?LANCTO=...&TIPO=..."), o MESMO
     protocolo de 2 passos (sessão ASP.NET + download) já confirmado no
     sistema Robotton do Central das Artes — ver
     conciliacao/gocontroledocumentos.py (módulo compartilhado, generaliza
     a base URL por domínio em vez de fixar um segmento de caminho como
     "/gocontroledocumentos_condo/", que aqui é só "/gocontroledocumentos/").

  b) Upload completo ("Prestação de Contas MM.YYYY.PDF", 358 páginas
     típico, ex.: jul/2026) — a MESMA linha de despesa tem os DOIS links
     sobrepostos na mesma faixa Y: um interno (kind=4/GOTO, campo "page",
     0-based) pra uma página "Comprovante de Despesa" embutida NO PRÓPRIO
     documento (texto real, sem rede nem OCR — formato de página idêntico
     ao já validado em central_das_artes.py: "Comprovante de Despesa\n
     <código>\n<descrição>\n<valor>\n<data>"), e o MESMO link externo do
     item (a). O link interno é sempre preferido (mais rápido e mais
     confiável) — o externo só é usado quando não há página embutida pra
     aquele código.

O CONTEÚDO do comprovante baixado externamente (texto nativo do PDF
devolvido pelo GK ADM — quase nunca imagem, ao contrário do Robotton) passa
por 2 regras locais, tentadas ANTES da cadeia genérica compartilhada
(conciliacao.lirba_pdf.preencher_de_texto, já usada por todos os outros
formatos ContasData/OCR):

  1. "Espelho de Lançamento" (tela interna do sistema GK, sem comprovante
     bancário real anexado) — o texto sai com valores e rótulos em ordens
     bem diferentes (não é OCR, é a extração nativa mesmo: o layout de
     colunas/formulário vira texto fora de ordem). Confirmado em dados
     reais (7 códigos, ago/2026) que o valor individual do lançamento é
     sempre o SEGUNDO número monetário que aparece no texto depois do
     marcador "Espelho de Lançamento" — o primeiro é sempre um total
     agregado (subtotal da categoria ou "Valor a pagar" do lote).

  2. Fatura de concessionária (SABESP/ENEL/COMGÁS) — o valor cobrado é
     sempre o PRIMEIRO "R$ X,XX" que aparece no texto (mesmo quando
     mascarado com asteriscos antes do valor, ex.: "R$ ****...11.130,46",
     confirmado na fatura Sabesp). Só tentada quando a DESCRIÇÃO da própria
     despesa listada (não o texto do comprovante, que pode vir corrompido —
     ver item 3) já identifica a concessionária, evitando qualquer chance de
     confundir com outro tipo de documento que por acaso tenha um "R$" cedo
     no texto.

  3. Se nenhuma das regras acima OU a cadeia compartilhada encontrar um
     valor, e o documento baixado for um PDF nativo (não já veio via
     Show.aspx como imagem), tenta OCR como último recurso — confirmado em
     dados reais (fatura Claro, código 0019) que ALGUNS PDFs desse sistema
     têm uma tabela de fontes com o ToUnicode CMap quebrado, produzindo
     texto nativo ilegível (não é rotação nem imagem escaneada — é a
     extração de texto em si que sai lixo) mesmo a página tendo conteúdo
     real; renderizar a página e rodar OCR nela contorna esse problema.
"""
import re
from collections import defaultdict
from pathlib import Path

from conciliacao import gocontroledocumentos, ocr
from conciliacao.base import RegistroComprovante
from conciliacao.condominios.central_das_artes import _ler_comprovante_embutido
from conciliacao.lirba_pdf import _RE_ITEM_LINHA, ConciliadorLirbaPDF, _num
from conciliacao.lirba_pdf import preencher_de_texto as _preencher_via_cadeia_compartilhada

_RE_DATA_INICIO = re.compile(r"^(?:\d+\s+)?\d{2}/\d{2}/\d{4}\s")

_RE_ESPELHO_MARCADOR = re.compile(r"Espelho de Lan\S*amento", re.IGNORECASE)
_RE_VALOR_GENERICO = re.compile(r"([\d.]+,\d{2})")
_RE_VALOR_RS_TOLERANTE = re.compile(r"R\$\s*\**([\d.]+,\d{2})")
_MARCADORES_CONCESSIONARIA = ("SABESP", "ENEL", "COMGAS", "COMGÁS")


def _valor_espelho_lancamento(texto: str) -> float | None:
    m_marcador = _RE_ESPELHO_MARCADOR.search(texto)
    if not m_marcador:
        return None
    valores = _RE_VALOR_GENERICO.findall(texto[m_marcador.end():])
    return _num(valores[1]) if len(valores) >= 2 else None


def _valor_fatura_concessionaria(texto: str) -> float | None:
    m = _RE_VALOR_RS_TOLERANTE.search(texto)
    return _num(m.group(1)) if m else None


def _mapear_codigo_para_evidencia(caminho: Path) -> dict[str, dict]:
    """Segunda passada (fitz) só pra achar a evidência de CADA código de
    despesa — a listagem em si já foi extraída certa pelo pai (pdfplumber).
    Agrupa palavras por linha (mesma faixa Y, mesma técnica de
    conciliacao/condominios/central_das_artes.py), acha o código de 4
    dígitos no fim de cada linha via _RE_ITEM_LINHA (mesma âncora já
    validada pro Ciudad Real: 76/76 despesas no formato parcial) e associa
    os 2 tipos de link possíveis na mesma faixa Y — confirmado em dados
    reais que o upload COMPLETO ("Prestação de Contas", 358 pág.) tem os
    DOIS sobrepostos na mesma linha (interno kind=4/GOTO pra página
    embutida + externo kind=2/URI), igual ao formato do Central das Artes;
    o upload PARCIAL (ago/2026, 14 pág.) só tem o externo. Pula páginas que
    já SÃO elas mesmas "Comprovante de Despesa" embutido — teriam sua
    própria linha "código+descrição+valor+data" que o parser de listagem
    reconheceria como uma despesa fantasma (mesmo bug já resolvido em
    central_das_artes.py).

    Também grava, pra CADA linha reconhecida (com ou sem link), o "bbox"
    (x0, top, x1, bottom em pontos, mesmo formato de RegistroComprovante.
    bbox_crop) — só a faixa Y dessa linha, largura da página inteira. Sem
    isso, um lançamento "sem_comprovante" (nenhum link, nem embutido nem
    externo — ex.: tarifa bancária, fatura sem link cadastrado) mostra a
    PÁGINA INTEIRA da listagem como evidência (dezenas de outras despesas
    junto) — o pedido é mostrar só a linha do lançamento em si."""
    import fitz

    mapa: dict[str, dict] = {}
    doc = fitz.open(str(caminho))
    try:
        for page in doc:
            texto_pagina = page.get_text()
            if "Demonstrativo de Despesas" not in texto_pagina:
                continue
            if "Comprovante de Despesa" in texto_pagina:
                continue
            links = page.get_links()
            palavras = page.get_text("words")
            por_y = defaultdict(list)
            for w in palavras:
                por_y[round(w[1])].append(w)
            for y in sorted(por_y):
                ws = sorted(por_y[y], key=lambda w: w[0])
                texto = " ".join(w[4] for w in ws)
                m_data = _RE_DATA_INICIO.match(texto)
                if not m_data:
                    continue
                m_item = _RE_ITEM_LINHA.search(texto)
                if not m_item:
                    continue
                codigo = m_item.group(2).zfill(4)
                candidatos = [l for l in links if abs(l["from"].y0 - y) < 3]
                link_interno = next((l for l in candidatos if l.get("kind") == 4 and "page" in l), None)
                link_uri = next((l for l in candidatos if l.get("uri")), None)
                margem = 2.0
                bbox = (
                    0.0,
                    min(w[1] for w in ws) - margem,
                    page.rect.width,
                    max(w[3] for w in ws) + margem,
                )
                # "Histórico" (texto livre entre a data e o valor/código no
                # fim da linha, ex.: "VIVO 8999 5547 4144 AGO/2026") — usado
                # como `fornecedor` do lançamento (ver extrair_comprovantes),
                # pra achado "sem_comprovante" citar QUEM é o lançamento, não
                # só a categoria genérica (ex.: "TARIFAS CONCESSIONÁRIAS").
                historico = texto[m_data.end():m_item.start()].strip()
                mapa[codigo] = {
                    "pagina_embutida": int(link_interno["page"]) if link_interno else None,
                    "link_uri": link_uri.get("uri") if link_uri else None,
                    "bbox": bbox,
                    "historico": historico,
                }
    finally:
        doc.close()
    return mapa


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        # Usa só a listagem do pai (pdfplumber, já validada), SEM o OCR que
        # ConciliadorLirbaPDF.extrair_comprovantes() rodaria em seguida pras
        # páginas "Comprovante de Despesa" — aqui o upload completo tem TEXTO
        # REAL nessas páginas (ver _ler_comprovante_embutido abaixo), então
        # rodar OCR nelas só pra descartar o resultado depois seria ~70
        # chamadas de OCR (renderização + tesseract) inteiramente perdidas.
        registros, _ = self._extrair_despesas_listadas(caminho)
        despesa_por_codigo = {r.codigo: r for r in registros}

        mapa_evidencia = _mapear_codigo_para_evidencia(caminho)
        import fitz
        doc = fitz.open(str(caminho))
        try:
            for i, (codigo, info) in enumerate(sorted(mapa_evidencia.items())):
                # Sempre grava o recorte da PRÓPRIA linha na despesa listada
                # (mesmo quando ela tem comprovante) — é o que
                # scripts/gerar_relatorio_conciliacao.py usa como evidência
                # de um achado "sem_comprovante" (a despesa é o único
                # registro relacionado nesse caso, ver conciliacao/matching.py
                # ::gerar_achados_lirba) — sem isso, a evidência cai pra
                # página inteira da listagem em vez de só o lançamento.
                despesa = despesa_por_codigo.get(codigo)
                if despesa is not None:
                    despesa.bbox_crop = info["bbox"]
                    if info["historico"]:
                        despesa.fornecedor = info["historico"][:200]

                pagina_embutida = info["pagina_embutida"]
                lido = _ler_comprovante_embutido(doc, pagina_embutida) if pagina_embutida is not None else None
                # Trava de segurança: só confia na página embutida se o
                # código impresso NELA bater com o código da própria linha
                # de despesa (mesmo cuidado de central_das_artes.py) — evita
                # pareamento errado se o link apontar pro lugar errado.
                if lido and lido["codigo"] != codigo:
                    lido = None

                if lido:
                    registros.append(RegistroComprovante(
                        pagina=pagina_embutida + 1,
                        tipo_documento="comprovante_anexado",
                        codigo=codigo,
                        texto_bruto=lido["texto_bruto"],
                        valor=lido["valor"],
                        pagamento=lido["data"],
                        descricao=lido["descricao"][:200],
                    ))
                    continue

                if not info["link_uri"]:
                    continue
                registros.append(self._comprovante_externo(caminho, codigo, info["link_uri"], despesa_por_codigo, i))
        finally:
            doc.close()
        return registros

    def _comprovante_externo(self, caminho: Path, codigo: str, uri: str,
                              despesa_por_codigo: dict, i: int) -> RegistroComprovante:
        comp = RegistroComprovante(
            pagina=1000 + i,
            tipo_documento="comprovante_anexado",
            codigo=codigo,
        )
        despesa = despesa_por_codigo.get(codigo)
        descricao = (despesa.descricao if despesa else "") or ""

        def _valor_do_texto(texto_doc: str) -> RegistroComprovante:
            """Roda as 3 regras de valor nessa ordem (Espelho > concessionária
            > cadeia compartilhada) contra um registro TEMPORÁRIO — nunca
            mexe direto no `comp` real, porque precisamos comparar os
            candidatos de TODOS os documentos antes de decidir qual usar
            (ver comentário abaixo sobre guia consolidada)."""
            candidato = RegistroComprovante(pagina=comp.pagina, tipo_documento="comprovante_anexado", codigo=codigo)
            valor = _valor_espelho_lancamento(texto_doc)
            if valor is None and any(m in descricao.upper() for m in _MARCADORES_CONCESSIONARIA):
                valor = _valor_fatura_concessionaria(texto_doc)
            if valor is not None:
                candidato.valor = valor
            else:
                _preencher_via_cadeia_compartilhada(candidato, texto_doc)
            return candidato

        # Um lançamento pode ter MAIS DE UM documento anexado (ex.:
        # comprovante bancário + Nota Fiscal — confirmado em dados reais,
        # Upper Itaim e Ciudad Real: a maioria dos lançamentos amostrados
        # tem 2 ou 3 documentos) — busca todos, não só o primeiro (ver
        # conciliacao/gocontroledocumentos.py::baixar_todos_comprovantes).
        documentos = gocontroledocumentos.baixar_todos_comprovantes(uri)
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
            candidato = _valor_do_texto(texto_doc)
            # Nenhuma regra reconheceu o conteúdo nativo — última tentativa
            # via OCR antes de desistir desse documento. Não filtra por
            # tamanho do texto nativo: confirmado em dados reais (fatura
            # Claro, código 0019) que o ToUnicode CMap quebrado desse PDF
            # específico produz texto nativo LONGO mas ilegível (lixo, não
            # texto curto) — só o próprio fracasso das regras de valor é
            # sinal confiável de que vale a pena tentar OCR.
            if candidato.valor == 0.0 and tipo_arquivo == "pdf":
                texto_ocr = gocontroledocumentos.ocr_primeira_pagina(dados_bin)
                if texto_ocr and texto_ocr != texto_doc:
                    texto_doc = texto_ocr
                    candidato = _valor_do_texto(texto_ocr)
            textos_docs.append(texto_doc)
            candidatos.append(candidato)

        # Escolhe o MELHOR candidato, não o primeiro que confirmou ALGUM
        # valor — confirmado em dados reais (Ciudad Real) que um lançamento
        # pode ter, como PRIMEIRO documento da lista, uma guia DARF/GPS
        # CONSOLIDADA (mesmo documento compartilhado por várias despesas
        # diferentes, ver _RE_TOTAL_DO_DOCUMENTO em conciliacao/lirba_pdf.py)
        # e, como segundo, o comprovante bancário individual com o valor
        # certo — parar no primeiro candidato não-zero pegava sempre o
        # valor AGREGADO errado. Prioridade: candidato cujo valor bate com o
        # da própria listagem > primeiro candidato com QUALQUER valor (ex.:
        # nenhum documento bate exato, mas um deles é uma guia consolidada —
        # mantém o comportamento de consolidação já existente em
        # conciliacao/matching.py::gerar_achados_lirba).
        valor_esperado = despesa.valor if despesa else None
        melhor = next(
            (c for c in candidatos if c.valor != 0.0 and valor_esperado is not None and abs(c.valor - valor_esperado) <= 0.01),
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
        return comp
