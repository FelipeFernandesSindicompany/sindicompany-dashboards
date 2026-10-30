"""
Extrator das regras gerais — Cap D'Antibes (Administradora Angélica, `datadigitus_pdf`).

Dois formatos do mesmo balancete, os dois da Angélica:

  * PDF com camada de texto ("Balancete consolidado", abr a ago/2026): lido pelo extrator DataDigitus (módulo `datadigitus`);
  * PDF ESCANEADO do balancete impresso (set/2026: capa, termo de verificação, tabelas anuais giradas, relatórios em fonte matricial
    e, em seguida, extratos bancários e os comprovantes/notas fiscais — 143 páginas, nenhuma com texto): lido aqui por OCR POSICIONAL
    (tesseract, 300 dpi) só nas páginas do relatório matricial, que o OCR lê limpo:

      5.4 Resumo Financeiro            saldo anterior / receitas / transferências / despesas / saldo atual de cada conta (conferência)
      4.1 Demonstrativo Financeiro     "Posição Financeira" por conta — fonte das receitas, das contas (ContaMes) e dos saldos
      2.1 Demonstrativo de Despesas    "001 - CONTA ..." > grupo (SALARIOS E ORDENADOS...) > histórico + valor (sem data) > subtotal com "%"

    O OCR NÃO é aceito às cegas (ver o aviso do datadigitus sobre vírgulas e somas em R$): cada número lido é conferido pelas somas que
    o próprio arquivo declara — itens do grupo = subtotal do grupo, grupos = "TOTAL DA CONTA", contas = "TOTAL GERAL DAS DESPESAS" e
    despesa da conta = "Despesas do Período" da Posição Financeira; saldo anterior + créditos - despesas - transferências enviadas =
    saldo atual. Valor que não fecha é relido em resolução maior; se ainda assim a soma não fecha, a página/conta entra em `avisos`
    (e `verificar_extracao` repete a conferência) — nunca se finge ter lido.

    Também grava ao lado do cache do OCR um PDF "pesquisável" (camada de texto invisível sobre as páginas lidas) que o render usa para
    localizar as linhas dos prints de evidência (`render._pdf_para_busca`): o original continua sendo a imagem mostrada.

Particularidades:
  * as contas têm nome fixo por código (001 ORDINÁRIA ... 054 I.P.T.U.), os mesmos do formato com texto — a continuidade de saldos e as
    regras comparam os meses pelo nome; o OCR lê "13o." como "130.";
  * a Posição Financeira traz a transferência entre contas pelo valor LÍQUIDO (ORDINÁRIA -> CDB 55.773,42 = 60.000,00 - 4.226,58 do Resumo),
    como o formato com texto; o rendimento das contas de aplicação é "JUROS APLICAÇÃO" + "DEDUÇÃO FUNDOS /IR" (líquido, uma linha);
  * o demonstrativo de despesas deste layout NÃO traz data nem nº de lançamento (o formato com texto trazia a data).
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path

from conciliacao.regras_gerais.extratores import datadigitus as _dd
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

from conciliacao.regras_gerais.extratores._ocr_posicional import (DPI, DPI_TRIAGEM, DPIS_VOTO, _RE_VALOR, _aplicar_votos, _linhas, _norm,  # noqa: F401
                                                                  _ocr_palavras, _tem_pct, _valor, _valor_da_linha, _vl)
from conciliacao.regras_gerais.extratores._ocr_posicional import gravar_pesquisavel as _gravar_pesquisavel
MAX_PAGINAS_RELATORIO = 30          # o relatório matricial fica no começo do arquivo; o resto são extratos e comprovantes
_CONTAS = {                          # código -> nome como no formato com texto
    "001": "CONTA ORDINÁRIA - ITAÚ AG.0237-C/C.41.025-3",
    "002": "CONTA OBRAS",
    "003": "CONTA FUNDO DE RESERVA",
    "009": "CONTA RESTAURAÇÃO FACHADA",
    "013": "CONTA PROVISÃO P/ 13o. SALÁRIO",
    "025": "CONTA REFORMA ELEVADOR",
    "038": "CONTA APLICAÇÃO /CDB ORDINÁRIA",
    "039": "CONTA APLICAÇÃO /ITAU VEST - FUNDO DE RESERVA",
    "054": "CONTA I.P.T.U.",
}
_RE_CONTA_HDR = re.compile(r"^\W*(\d{3})\s*[-—–]+\s*(CONTA.*?)\s*\|?\s*$", re.IGNORECASE)

class Extrator(_dd.Extrator):
    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        doc = fitz.open(str(caminho))
        try:
            com_texto = sum(len(doc[i].get_text().strip()) for i in range(min(len(doc), 12))) > 200
            n = len(doc)
        finally:
            doc.close()
        if com_texto:
            return super().extrair(caminho, mes)
        return self._extrair_ocr(Path(caminho), mes, n)

    # ── leitura do balancete escaneado ───────────────────────────────────────────────────────────────────────
    def _extrair_ocr(self, caminho: Path, mes: str, n_paginas: int) -> DadosRegras:
        dados = DadosRegras(mes=mes, arquivo=caminho.name)
        indices = list(range(min(n_paginas, MAX_PAGINAS_RELATORIO)))
        triagem = _ocr_palavras(caminho, indices, DPI_TRIAGEM)          # leitura rápida só para achar as páginas do relatório
        if not triagem:
            dados.motivos_nao_cobertos = {k: "OCR indisponível nesta máquina (tesseract/idioma 'por') — o PDF é uma impressão em imagem"
                                          for k in ("receitas", "rendimentos", "lancamentos")}
            return dados
        relatorio = []
        for i in indices:
            topo = " ".join(l["texto"] for l in _linhas(triagem.get(i, []))[:14])
            if re.search(r"COND\.?\s*EDIF\s*\.?\s*CAP", topo, re.IGNORECASE) and re.search(r"GARANTIA|FOLHA|/\s*20\d\d", topo):
                relatorio.append(i)
        paginas = []                                   # (pagina_1based, largura, linhas) só das páginas do relatório matricial
        if relatorio:
            import fitz
            principal = _ocr_palavras(caminho, relatorio, DPI)
            outras = [_ocr_palavras(caminho, relatorio, d) for d in (DPI_TRIAGEM,) + DPIS_VOTO]
            d_ = fitz.open(str(caminho))
            try:
                larguras = {i: float(d_[i].rect.width) for i in relatorio}
            finally:
                d_.close()
            for i in relatorio:
                ls = _linhas(principal.get(i, []))
                _aplicar_votos(ls, [_linhas(o.get(i, [])) for o in outras], larguras[i])
                paginas.append((i + 1, larguras[i], ls))
        if not paginas:
            dados.motivos_nao_cobertos = {k: "o PDF é uma impressão em imagem e não reconheci nele as páginas do relatório da Angélica (Resumo Financeiro, "
                                             "Demonstrativo Financeiro, Demonstrativo de Despesas)" for k in ("receitas", "rendimentos", "lancamentos")}
            return dados
        dados.variante = None
        resumo = self._ler_resumo(paginas)
        achou_pos = self._ler_posicao(dados, paginas)
        totais = {}
        achou_desp = self._ler_despesas(dados, paginas, caminho, totais)
        self._conferir(dados, resumo, totais, achou_pos, achou_desp, caminho)
        dados.cobertura = {"receitas": achou_pos, "rendimentos": achou_pos and bool(dados.contas), "lancamentos": achou_desp and bool(dados.lancamentos)}
        if not achou_pos:
            dados.motivos_nao_cobertos["receitas"] = dados.motivos_nao_cobertos["rendimentos"] = "não li o Demonstrativo Financeiro (Posição Financeira por conta) no PDF escaneado"
        if not dados.cobertura["lancamentos"]:
            dados.motivos_nao_cobertos["lancamentos"] = "não li o Demonstrativo de Despesas no PDF escaneado"
        dados.avisos.insert(0, "PDF escaneado (impressão em imagem): números lidos por OCR e conferidos pelas somas do próprio arquivo; "
                               "o demonstrativo de despesas deste layout não traz data dos lançamentos")
        self._gravar_pesquisavel(caminho, paginas)
        return dados

    def _nome_conta(self, cod: str, ocr_nome: str) -> str:
        return _CONTAS.get(cod) or re.sub(r"\s+", " ", ocr_nome).strip()

    # 5.4 Resumo Financeiro: {nome_conta: {"anterior", "atual"}} para conferir a Posição Financeira
    def _ler_resumo(self, paginas) -> dict:
        res: dict = {}
        em = False
        conta = None
        for pag, W, ls in paginas:
            for l in ls:
                tn = _norm(l["texto"])
                if "RESUMO FINANCEIRO" in tn and re.match(r"^\d\.\d", l["texto"].strip()):
                    em = True
                    continue
                if em and ("DEMONSTRATIVO" in tn or "RESUMO DAS CONTAS" in tn):
                    return res
                if not em:
                    continue
                m = _RE_CONTA_HDR.match(l["texto"].strip())
                if m:
                    conta = self._nome_conta(m.group(1), m.group(2))
                    res.setdefault(conta, {})
                    continue
                if conta is None:
                    continue
                v, _, _ = _vl(l, W, 0.55)
                if v is None:
                    continue
                if tn.startswith("SALDO ANTERIOR"):
                    res[conta]["anterior"] = v
                elif tn.startswith("SALDO ATUAL"):
                    res[conta]["atual"] = v
        return res

    # 4.1 Demonstrativo Financeiro: Posição Financeira por conta -> ContaMes + receitas
    def _ler_posicao(self, dados: DadosRegras, paginas) -> bool:
        em_sec = False
        conta = None
        em_pos = False
        achou = False
        pend = ""
        outras: dict[str, list] = {}           # conta -> linhas de "Outras Receitas" (juros, dedução de IR)
        inad: dict[str, float] = {}
        inad_proc: dict[str, float] = {}
        for pag, W, ls in paginas:
            for l in ls:
                t = l["texto"].strip()
                tn = _norm(t)
                if re.match(r"^\d\.\d\s+DEMONSTRATIVO FINANCEIRO", tn) or tn.startswith("4 1 DEMONSTRATIVO FINANCEIRO"):
                    em_sec = True
                    continue
                if tn.startswith("RESUMO DAS CONTAS"):
                    em_sec = False
                if not em_sec:
                    # a seção começa na página sem o título impresso (a 1ª folha traz só os cabeçalhos das contas): entra quando aparece
                    # "RECEITA PREVISTA" ou "POSICAO FINANCEIRA" numa página que já tem conta
                    if tn.startswith(("RECEITA PREVISTA", "POSICAO FINANCEIRA")):
                        em_sec = True
                    else:
                        continue
                m = _RE_CONTA_HDR.match(t)
                if m and _vl(l, W, 0.55)[0] is None:
                    cod, conta = m.group(1), self._nome_conta(m.group(1), m.group(2))
                    em_pos, pend = False, ""
                    continue
                if tn.startswith("POSICAO FINANCEIRA"):
                    em_pos, pend = True, ""
                    if conta and not any(c.nome == conta for c in dados.contas):
                        dados.contas.append(ContaMes(nome=conta, pagina=pag))
                    continue
                if not em_pos and conta is not None:
                    # bloco "RECEITA PREVISTA": inadimplência do mês (Condôminos em atraso) e dos meses anteriores recebida (Devedores meses anteriores -> Realizado)
                    vv = _vl(l, W, 0.55)[0]
                    if vv is not None and re.match(r"^COND\w*NOS EM ATRASO", tn):
                        inad[conta] = abs(vv)
                    elif vv is not None and tn.startswith("DEVEDORES MESES ANTERIORES"):
                        inad_proc[conta] = abs(vv)
                if not em_pos or conta is None:
                    continue
                c = next(x for x in dados.contas if x.nome == conta)
                v, bb, _ = _vl(l, W, 0.55)
                if v is None:
                    if not re.match(r"^(RECEITA REALIZADA|OUTRAS RECEITAS|RECEITA PREVISTA)$", tn):
                        pend = (pend + " " + t).strip() if tn.startswith(("TRANSFERIDO", "DE RESERVA")) or pend else pend or (t if tn.startswith("TRANSFERIDO") else "")
                    continue
                rotulo = " ".join(w["t"] for w in l["w"] if w["x0"] < 0.55 * W).strip()
                rotulo = (pend + " " + rotulo).strip() if pend else rotulo
                pend = ""
                rn = _norm(rotulo)
                achou = True
                if rn.startswith("SALDO ANTERIOR"):
                    c.saldo_anterior = v
                elif rn.startswith("SALDO ATUAL"):
                    c.saldo_atual = v
                    c.pagina = pag
                    em_pos = False
                elif rn.startswith("DESPESAS DO PERIODO"):
                    c.debitos = abs(v)
                elif rn.startswith("TRANSFERIDO PARA"):
                    c._saidas = getattr(c, "_saidas", 0.0) + abs(v)
                elif rn.startswith("TRANSFERIDO DA"):
                    c.creditos += v
                    dados.receitas.append(LinhaReceita(conta=conta, descricao=rotulo, valor=v, tipo="transferencia", pagina=pag,
                                                       bbox=tuple(round(x, 1) for x in (l["x0"], l["top"], l["x1"], l["bottom"]))))
                elif rn.startswith(("JUROS APLICACAO", "DEDUCAO FUNDOS", "OUTRAS RECEITAS")) or (rn.startswith("JUROS") and "APLICA" in rn):
                    outras.setdefault(conta, []).append((rotulo, v, pag, l))
                else:
                    if rn.startswith(("DA EMISSAO", "DE CONDOMINOS", "ANTECIPACO")):
                        tipo = "cota"
                    elif re.match(r"^(MULTAS?|JUROS)", rn):
                        tipo = "multa_juros"
                    else:
                        tipo = "outra"
                    c.creditos += v
                    dados.receitas.append(LinhaReceita(conta=conta, descricao=rotulo, valor=v, tipo=tipo, pagina=pag,
                                                       bbox=tuple(round(x, 1) for x in (l["x0"], l["top"], l["x1"], l["bottom"]))))
        # "Outras Receitas" (juros de aplicação, dedução de fundos/IR): UMA linha líquida por conta, como no formato com texto
        for conta, linhas in outras.items():
            c = next(x for x in dados.contas if x.nome == conta)
            liquido = round(sum(v for _, v, _, _ in linhas), 2)
            pag = linhas[0][2]
            detalhe = "; ".join(f"{r} {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") for r, v, _, _ in linhas)
            tipo = "rendimento" if "APLICA" in _norm(conta) else "outra"
            top = min(l["top"] for *_, l in linhas)
            bot = max(l["bottom"] for *_, l in linhas)
            x0 = min(l["x0"] for *_, l in linhas)
            x1 = max(l["x1"] for *_, l in linhas)
            dados.receitas.append(LinhaReceita(conta=conta, descricao=f"Outras Receitas ({detalhe})", valor=liquido, tipo=tipo, pagina=pag,
                                               bbox=(round(x0, 1), round(top, 1), round(x1, 1), round(bot, 1))))
            c.creditos += liquido
            if tipo == "rendimento":
                c.rendimento += liquido
        for c in dados.contas:
            c.creditos = round(c.creditos, 2)
            c.debitos = round(c.debitos, 2)
        if inad:
            tot_inad, tot_proc = round(sum(inad.values()), 2), round(sum(inad_proc.values()), 2)
            # conferência: o Relatório de Pendências imprime o total dos condôminos em atraso
            pend = next((_vl(l, W, 0.55)[0] for pag, W, ls in paginas for l in ls if _norm(l["texto"]).startswith("TOTAL DAS PENDENCIAS")), None)
            if pend is not None and abs(pend - tot_inad) > 0.011:
                dados.avisos.append(f"OCR: condôminos em atraso das contas somam {tot_inad:,.2f}, mas o total do Relatório de Pendências é {pend:,.2f}"
                                    .replace(",", "X").replace(".", ",").replace("X", "."))
            # previsto x realizado: não calculado — o 'Realizado' impresso mistura o que é recebimento de meses anteriores; só a inadimplência é lida
            dados.indicadores = {"prev": 0.0, "real": 0.0, "inad": tot_inad, "inadProc": tot_proc}
        return achou

    # 2.1 Demonstrativo de Despesas
    def _ler_despesas(self, dados: DadosRegras, paginas, caminho: Path, totais: dict) -> bool:
        em = False
        conta = None
        grupo = None
        espera_grupo = False
        pend: list = []
        itens: list = []                         # entradas do grupo corrente
        achou = False
        grupos: dict = {}                        # (conta, grupo) -> {"itens": [...], "total": v, "pagina": pag}
        for pag, W, ls in paginas:
            for l in ls:
                t = l["texto"].strip()
                tn = _norm(t)
                if re.match(r"^\d\.\d\s+DEMONSTRATIVO DE DESPESAS", tn) or tn.startswith("2 1 DEMONSTRATIVO DE DESPESAS"):
                    if not em:                          # o título se repete no topo de cada folha: a conta/grupo em curso continuam
                        conta, grupo, espera_grupo, pend = None, None, False, []
                    em, achou = True, True
                    continue
                if not em:
                    continue
                if re.match(r"^\d\.\d\s", t) and "DESPESAS" not in tn:
                    em = False
                    continue
                if tn.startswith("TOTAL GERAL DAS DESPESAS"):
                    totais["geral"] = _vl(l, W, 0.55)[0]
                    em = False
                    continue
                m = _RE_CONTA_HDR.match(t)
                if m and _vl(l, W, 0.55)[0] is None:
                    nova = self._nome_conta(m.group(1), m.group(2))
                    if nova != conta:               # mudou de conta; se repete a da página anterior, a categoria continua
                        conta, grupo, espera_grupo = nova, None, True
                    pend = []
                    continue
                if tn.startswith("TOTAL DA CONTA"):
                    totais[conta] = _vl(l, W, 0.55)[0]
                    grupo, espera_grupo, pend = None, True, []
                    continue
                v, bb, vx = _vl(l, W, 0.55)
                if _tem_pct(l):                     # "28,95%   21.190,00": subtotal do grupo
                    if grupo is not None and v is not None:
                        grupos.setdefault((conta, grupo), {"itens": [], "pagina": pag})["total"] = v
                    grupo, espera_grupo, pend = None, True, []
                    continue
                if conta is None:
                    continue
                if v is None:
                    if espera_grupo and not pend and tn.upper() == tn.upper() and not re.search(r"\d", tn):
                        grupo, espera_grupo = t, False
                        grupos.setdefault((conta, grupo), {"itens": [], "pagina": pag})
                    else:
                        pend.append(l)
                    continue
                if grupo is None:                   # valor sem grupo aberto (cabeçalho do grupo não lido): não inventa categoria
                    grupo = "SEM GRUPO"
                    grupos.setdefault((conta, grupo), {"itens": [], "pagina": pag})
                    espera_grupo = False
                desc_ls = pend + [l]
                desc = " ".join(" ".join(w["t"] for w in x["w"] if not (x is l and w["x0"] >= vx - 0.5)) for x in desc_ls).strip()
                desc = re.sub(r"\s+", " ", desc.replace("—", "-").replace("–", "-"))
                desc = re.sub(r"\s*-\s*-\s*", " - ", desc)
                bbox = (min(x["x0"] for x in desc_ls), min(x["top"] for x in desc_ls), max(x["x1"] for x in desc_ls), max(x["bottom"] for x in desc_ls))
                grupos[(conta, grupo)]["itens"].append({"desc": desc, "valor": v, "pag": pag, "bbox": bbox, "vbb": bb, "linha": l})
                pend = []
        self._grupos = grupos
        self._reparar(caminho, grupos)
        for (cta, grp), g in grupos.items():
            for it in g["itens"]:
                dados.lancamentos.append(LancamentoDespesa(
                    descricao=it["desc"], valor=it["valor"], categoria=grp, conta=cta, pagina=it["pag"],
                    local=f"OCR, página {it['pag']}", bbox=tuple(round(x, 1) for x in it["bbox"])))
        return achou

    def _reparar(self, caminho: Path, grupos: dict):
        """Subtotal do grupo != soma dos itens: relê cada valor do grupo em resolução maior e aceita a combinação que fecha."""
        for (cta, grp), g in grupos.items():
            tot = g.get("total")
            if tot is None or abs(sum(i["valor"] for i in g["itens"]) - tot) <= 0.011:
                continue
            alternativas = []
            for it in g["itens"]:
                alt = [it["valor"]]
                for dpi in (450, 600):
                    r = self._reler_valor(caminho, it, dpi)
                    if r is not None and r not in alt:
                        alt.append(r)
                alternativas.append(alt)
            if sum(len(a) > 1 for a in alternativas) > 8 or not any(len(a) > 1 for a in alternativas):
                continue
            for comb in product(*alternativas):
                if abs(sum(comb) - tot) <= 0.011:
                    for it, v in zip(g["itens"], comb):
                        it["valor"] = v
                    break

    def _reler_valor(self, caminho: Path, it: dict, dpi: int):
        try:
            import fitz
            import pytesseract
            from PIL import Image

            doc = fitz.open(str(caminho))
            try:
                x0, top, x1, bot = it["vbb"]
                clip = fitz.Rect(x0 - 6, top - 3, x1 + 6, bot + 3)
                pix = doc[it["pag"] - 1].get_pixmap(dpi=dpi, clip=clip)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            finally:
                doc.close()
            txt = pytesseract.image_to_string(img, lang="por", config="--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789.,-")
            return _valor(txt)
        except Exception:
            return None

    # conferências cruzadas
    def _conferir(self, dados: DadosRegras, resumo: dict, totais: dict, achou_pos: bool, achou_desp: bool, caminho: Path):
        for c in dados.contas:
            saidas = round(getattr(c, "_saidas", 0.0), 2)
            esperado = round(c.saldo_anterior + c.creditos - c.debitos - saidas, 2)
            if achou_pos and abs(esperado - c.saldo_atual) > 0.011:
                dados.avisos.append(f"OCR: na conta {c.nome} o saldo anterior + créditos - despesas - transferências enviadas ({esperado:,.2f}) não fecha com o "
                                    f"saldo atual lido ({c.saldo_atual:,.2f}) — algum número desta conta pode estar lido errado".replace(",", "X").replace(".", ",").replace("X", "."))
            r = resumo.get(c.nome) or {}
            for k, atr in (("anterior", c.saldo_anterior), ("atual", c.saldo_atual)):
                if k in r and abs(r[k] - atr) > 0.011:
                    dados.avisos.append(f"OCR: saldo {k} da conta {c.nome} lido no Resumo Financeiro ({r[k]:,.2f}) difere do lido no Demonstrativo Financeiro ({atr:,.2f})"
                                        .replace(",", "X").replace(".", ",").replace("X", "."))
            # a transferência enviada fica no débito do Resumo; aqui o débito é só a despesa (como o formato com texto)
        if not achou_desp:
            return
        por_conta: dict[str, float] = {}
        for (cta, grp), g in self._grupos.items():
            s = round(sum(i["valor"] for i in g["itens"]), 2)
            por_conta[cta] = round(por_conta.get(cta, 0.0) + s, 2)
            if g.get("total") is not None and abs(s - g["total"]) > 0.011:
                dados.avisos.append(f"OCR: itens do grupo {grp} ({cta}) somam {s:,.2f}, mas o subtotal impresso é {g['total']:,.2f} (página {g['pagina']}) — "
                                    f"não consegui reconciliar a leitura".replace(",", "X").replace(".", ",").replace("X", "."))
        for cta, s in por_conta.items():
            t = totais.get(cta)
            if t is not None and abs(s - t) > 0.011:
                dados.avisos.append(f"OCR: despesas da conta {cta} somam {s:,.2f}, mas o TOTAL DA CONTA impresso é {t:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        if totais.get("geral") is not None and abs(round(sum(por_conta.values()), 2) - totais["geral"]) > 0.011:
            dados.avisos.append(f"OCR: despesas lidas somam {sum(por_conta.values()):,.2f}, mas o TOTAL GERAL DAS DESPESAS impresso é {totais['geral']:,.2f}"
                                .replace(",", "X").replace(".", ",").replace("X", "."))

    # ── PDF pesquisável para os prints de evidência ──────────────────────────────────────────────────────────
    def _gravar_pesquisavel(self, caminho: Path, paginas):
        _gravar_pesquisavel(caminho, paginas)
