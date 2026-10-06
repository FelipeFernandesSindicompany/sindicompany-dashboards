"""
Extrator das regras gerais — Palm Beach (Edifício Palm Beach; administradora HABITAT / GROUP condomínios).

Formato: PDF de 120-230 páginas em que TODO o corpo é imagem raster (só o cabeçalho/rodapé tem texto: "CONDOMINIO EDIFICIO PALM BEACH / Balancete /
GROUP condomínios / Emitido em ... / Pág N/total"). O balancete só pode ser lido por OCR (tesseract, idioma `por`, via conciliacao/ocr.py).

Páginas lidas (sempre as mesmas, em todos os 17 meses abr/2025-ago/2026): a 1ª página cujo texto-camada traz "Demonstrativo de receitas e despesas" (fora
do sumário; pág. 8) e as 2 seguintes (+1 se o "6. Inadimplência" ainda não apareceu). Conteúdo (OCR, 200 dpi, --psm 6):
  1. Receitas        grupos "1.1 Taxa de condomínio 67.508,02" ... (valor por grupo de receita; não há uma linha por unidade nesta tela)
  2. Despesas        "2.1 - Pessoal 42.614,07" (subtotal do grupo) e UMA LINHA POR LANÇAMENTO:
                     "2.1.12 - Empregados Terceirizados - SOUZA LIMA ... - 17/08/2026 13.137,73" + linhas de continuação do histórico
  3. Resumo          Saldo anterior / Total de receitas / Total de despesas / Saldo do mês
  4. Contas bancárias, 5. Contas provisionamento (ORDINÁRIA, FUNDO DE RESERVA, FUNDO DE OBRAS, SALAO DE FESTAS, MANUTENCAO DE PINTURA, ASSISTENCIA JURIDICA):
                     Saldo anterior, Créditos, Débitos, Transferências por conta — são as "contas" das regras.
`categoria` do lançamento = "<código> <subconta>" (ex.: "2.5.6.1 Mão-de-obra em reformas e reparos"); `conta` = "CONSOLIDADO" (o demonstrativo de despesas lista TODAS as
contas juntas e não diz de qual conta cada lançamento saiu; só os Débitos totais de cada conta aparecem no item 5).
Leitura só é aceita se FECHAR: Σ lançamentos == "Total de despesas" (e cada subtotal 2.N), Σ receitas == "Total de receitas". Quando o OCR erra um dígito/sinal e a
soma não fecha, tenta-se corrigir UMA leitura (troca de dígito parecido ou sinal perdido) cuja correção feche a soma; se mesmo assim não fecha, o dado NÃO é aceito
(cobertura False com o motivo). OCR por página fica em cache em disco (pasta temporária), então a 2ª leitura do mesmo arquivo é instantânea.
Receitas -> conta: o item 5 traz os "Créditos" de cada conta; Taxa de condomínio / Fundo de reserva / Fundo de obras / Fundo de pintura / Reserva de espaços têm conta fixa e os
demais grupos (juros, multas, acordos, estorno e, principalmente, o RENDIMENTO 1.8 poupança e 1.9 investimentos) são atribuídos por busca exata contra esses Créditos. Resultado
conferido em todos os 17 meses: o rendimento de investimentos (1.9) foi creditado no FUNDO DE RESERVA, exceto em jun, out e nov/2025, quando foi para a ORDINÁRIA (ver relatório do grupo).
Experimental, desligado por padrão: `condo["parser_config"]["palm_receitas_detalhe"] = true` OCRiza também "Receitas detalhadas por unidade/cliente" (11 pág. rotacionadas, ~8 s cada) e
só o aceita se a soma por classe fechar com o demonstrativo. Testado em ago/2026: NÃO fecha (classe 1.1: 94.154,85 somando as unidades x 67.508,02 no demonstrativo; a base das duas telas é diferente e a causa
não foi investigada), então é descartado com aviso. Não usar para validar nada.
"""
import hashlib
import io
import itertools
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Optional

from conciliacao.regras_gerais.extratores.top_nine import aplicar_config_receitas_negativas
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CENT = 0.011
_DPI = 200
_CONSOLIDADO = "CONSOLIDADO"
_CACHE_DIR = Path(tempfile.gettempdir()) / "sindicompany_ocr_palm_beach"

_RE_DATA = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_RE_FIM_VALOR = re.compile(r"(-?\s?\(?[\d][\d.,“”]*[\d])\)?[\s,\"“”'.|]*$")
_RE_VALOR_SEM_VIRGULA = re.compile(r"^-?\d{3,}$")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", _sem_acento(s).upper())).strip()


def _br(s: str) -> Optional[float]:
    """Número impresso pelo HABITAT lido por OCR: "1.642,00", "34,486,74" (milhar com vírgula), "-0,02", "- 125.237,41", ".02"."""
    if s is None:
        return None
    t = s.strip().replace("“", "").replace("”", "").replace('"', "").replace(" ", "")
    neg = t.startswith("-") or t.startswith("(") or t.endswith("-")
    t = re.sub(r"[^\d,.]", "", t)
    m = re.fullmatch(r"(\d[\d.,]*)?[.,](\d{2})", t) or re.fullmatch(r"()[.,](\d{2})", t)
    if not m:
        if re.fullmatch(r"\d{3,}", t):             # OCR perdeu a vírgula decimal ("72117" = 721,17): os 2 últimos dígitos são os centavos
            v = float(f"{t[:-2]}.{t[-2:]}")
            return -v if neg else v
        return None
    inteiro = re.sub(r"[.,]", "", m.group(1) or "")
    v = float(f"{inteiro or '0'}.{m.group(2)}")
    return -v if neg else v


# ── OCR com cache em disco ────────────────────────────────────────────────────

def _chave_cache(caminho: Path) -> str:
    st = caminho.stat()
    return hashlib.sha1(f"{caminho.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8")).hexdigest()[:20]


def _ocr_pagina(doc, caminho: Path, i: int, chave: str, rotacionar: bool = False) -> str:
    """OCR da página i (0-based). Cache em disco por (arquivo, página, dpi, modo). Devolve "" se o OCR não estiver disponível."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    arq = _CACHE_DIR / f"{chave}_p{i + 1}_d{_DPI}{'_rot' if rotacionar else ''}.txt"
    if arq.exists():
        return arq.read_text(encoding="utf-8")
    from conciliacao import ocr as _ocr

    if not _ocr.tesseract_disponivel():
        return ""
    try:
        import pytesseract
        from PIL import Image

        pix = doc[i].get_pixmap(dpi=_DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        if rotacionar:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                img.save(tmp.name)
                ang = _ocr._angulo_correcao(tmp.name)
            Path(tmp.name).unlink(missing_ok=True)
            if ang:
                img = img.rotate(-ang, expand=True)
        txt = pytesseract.image_to_string(img, lang="por", config="--psm 6")
    except Exception as exc:                     # nunca derruba a validação por causa do OCR
        print(f"[AVISO] OCR falhou na pág. {i + 1} de {caminho.name}: {exc}")
        return ""
    if txt.strip():
        arq.write_text(txt, encoding="utf-8")
    return txt


# ── parser do texto OCR do demonstrativo ──────────────────────────────────────

_RUIDO = re.compile(r"^(CONDOMINIO EDIFICIO PALM BEACH|GROUP condom|Emitido em|P[áa]g\s*\d|I?\s*Demonstrativo de receitas|Balancete$|Classe de conta|"
                    r"=== pdf p)", re.IGNORECASE)


def _parse_demonstrativo(texto: str) -> dict:
    """Devolve {receitas:[(cod,nome,valor,linha)], despesas:[dict], sub2:{cod:valor}, sub3:{cod:valor}, total_receitas, total_despesas, saldo_anterior,
    saldo_mes, contas:[{nome,saldo_atual,saldo_anterior,creditos,debitos,deb_ilegivel}], saldo_total}."""
    out = {"receitas": [], "despesas": [], "sub2": {}, "sub3": {}, "contas": [], "total_receitas": None, "total_despesas": None,
           "saldo_anterior": None, "saldo_mes": None, "saldo_total": None, "inadimplencia": None}
    secao = None
    cur = None
    conta = None
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or _RUIDO.match(linha):
            continue
        ln = linha.replace("‘", "").replace("’", "")
        if re.match(r"^1\.\s*Receitas", ln):
            secao, cur = "receitas", None
            continue
        if re.match(r"^2\.\s*Despesas", ln):
            secao, cur = "despesas", None
            continue
        if re.match(r"^3\.\s*Resumo", ln):
            secao, cur = "resumo", None
            continue
        if re.match(r"^4[.,]\s*Contas banc", ln):
            secao, cur = "bancarias", None
            continue
        if re.match(r"^5[.,]\s*Contas provision", ln):
            secao, cur = "provisao", None
            continue
        if re.match(r"^6[.,]\s*Inadimpl", ln):
            secao, cur = "inad", None
            continue
        if re.match(r"^7[.,]\s*Acordos", ln) or ln.startswith("* As contas de provisionamento"):
            secao, cur = None, None
            continue
        if secao == "receitas":
            m = re.match(r"^(1\.\d+)\s+(.+?)\s+(-?\(?[\d.,“”]+\)?)\s*$", ln)
            if m and _br(m.group(3)) is not None:
                out["receitas"].append((m.group(1), m.group(2).strip(), _br(m.group(3)), ln))
            m2 = re.match(r"^Total de receitas\s+(.+)$", ln, re.I)
            if m2:
                out["total_receitas"] = _br(m2.group(1))
            continue
        if secao == "despesas":
            mc = re.match(r"^(2[.,]\d+(?:[.,]\d+)*)\s*[-–—]?\s+(.*)$", ln) or re.match(r"^(2[.,]\d+(?:[.,]\d+)*)\s*-\s*(.*)$", ln)
            if mc:
                cod = mc.group(1).replace(",", ".")
                resto = mc.group(2).strip(" -")
                niveis = cod.count(".")
                md = _RE_DATA.search(resto)
                mv = _RE_FIM_VALOR.search(resto)
                if md and mv and mv.start() > md.start():          # lançamento: ... DD/MM/AAAA VALOR
                    valor = _br(mv.group(1))
                    corpo = resto[:md.start()].strip(" -")
                    cur = {"cod": cod, "corpo": corpo, "data": md.group(1), "valor": valor, "bruto": ln, "cont": [], "valor_txt": mv.group(1)}
                    out["despesas"].append(cur)
                    continue
                if mv and not md:                                   # subtotal "2.1 - Pessoal 42.614,07" / "2.5.6 - Reformas e reparos 32.647,80"
                    v = _br(mv.group(1))
                    if v is not None:
                        (out["sub2"] if niveis == 1 else out["sub3"])[cod] = v
                    cur = None
                    continue
                if niveis <= 2 and not md:                         # subtotal de grupo/subgrupo ilegível (ex.: "2.3 - Tarifas ETA"): sem data, não é lançamento
                    cur = None
                    continue
                # linha de código sem valor/data (início de um lançamento cuja data/valor veio na linha de baixo)
                cur = {"cod": cod, "corpo": resto, "data": None, "valor": None, "bruto": ln, "cont": [], "valor_txt": None}
                out["despesas"].append(cur)
                continue
            if cur is not None:
                if cur["valor"] is None:
                    md = _RE_DATA.search(ln)
                    mv = _RE_FIM_VALOR.search(ln)
                    if md and mv and mv.start() > md.start():
                        cur["data"], cur["valor"], cur["valor_txt"] = md.group(1), _br(mv.group(1)), mv.group(1)
                        cur["corpo"] = (cur["corpo"] + " " + ln[:md.start()]).strip(" -")
                        continue
                cur["cont"].append(ln)
            continue
        if secao == "resumo":
            for rot, chave in (("Saldo anterior", "saldo_anterior"), ("Total de receitas", "total_receitas"), ("Total de despesas", "total_despesas"),
                               ("Saldo do m", "saldo_mes")):
                if ln.lower().startswith(rot.lower()):
                    mm = re.search(r"(-?\s?\(?[\d][\d.,“”]*[\d])\)?\s*$", ln)
                    if mm:
                        out[chave] = _br(mm.group(1))
            continue
        if secao in ("bancarias", "provisao"):
            ml = ln.lower()
            if ml.startswith("saldo total"):
                mm = re.search(r"(-?\s?\(?[\d][\d.,“”]*[\d])\)?\s*$", ln)
                out["saldo_total"] = _br(mm.group(1)) if mm else None
                continue
            if ml.startswith("contas valor") or ml.startswith("contas  valor"):
                continue
            if conta is not None and ml.startswith(("saldo anterior", "créditos", "creditos", "débitos", "debitos", "transfer")):
                if secao == "provisao" or secao == "bancarias":
                    rest = re.sub(r"^[^\d\-–]*", "", ln.split(" ", 1)[1] if " " in ln else "")
                    mm = re.search(r"(-\s?)?\(?([\d][\d.,]*[\d])\)?\s*$", ln)
                    val = _br(("-" if (mm and mm.group(1)) else "") + mm.group(2)) if mm else None
                    if ml.startswith("saldo anterior"):
                        conta["saldo_anterior"] = val
                    elif ml.startswith(("créditos", "creditos")):
                        conta["creditos"] = val or 0.0
                    elif ml.startswith(("débitos", "debitos")):
                        conta["debitos"] = abs(val) if val is not None else None
                        conta["deb_txt"] = ln
                    elif ml.startswith("transfer"):
                        conta.setdefault("transf", []).append((ln, val))
                continue
            mn = re.match(r"^([A-ZÀ-Ý][A-ZÀ-Ý .\-/Ç]+?)\s+(-?\(?[\d][\d.,]*[\d]\)?)\s*$", ln)
            if mn and _br(mn.group(2)) is not None:
                conta = {"nome": mn.group(1).strip(), "saldo_atual": _br(mn.group(2)), "secao": secao}
                out["contas"].append(conta)
            continue
    return out


def _tipo_receita(nome: str) -> str:
    n = _norm(nome)
    if "RENDIMENTO" in n:
        return "rendimento"
    if "JURO" in n or "MULTA" in n:
        return "multa_juros"
    if "TAXA DE CONDOMINIO" in n or "FUNDO" in n:
        return "cota"
    return "outra"


# Conta de provisionamento onde cada grupo de receita é creditado. Taxa de condomínio, fundos e reserva de espaços têm conta fixa (confirmado nos 17 meses);
# juros, multas, acordos, estorno e principalmente RENDIMENTO (1.8 poupança / 1.9 investimentos) mudam de conta de um mês para o outro (jun/2025: o rendimento
# do CDB foi para a ORDINÁRIA; ago/2026: para o FUNDO DE RESERVA) — por isso a conta é resolvida contra os "Créditos" de cada conta do item 5.
_CONTA_FIXA = [("TAXA DE CONDOMINIO", "ORDINARIA"), ("FUNDO DE RESERVA", "FUNDO DE RESERVA"), ("FUNDO DE OBRAS", "FUNDO DE OBRAS"),
               ("FUNDO DE PINTURA", "MANUTENCAO DE PINTURA"), ("RESERVA DE ESPACO", "SALAO DE FESTAS")]
_CONTA_PADRAO = "ORDINARIA"


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        caminho = Path(caminho)
        dados = DadosRegras(mes=mes, arquivo=caminho.name)
        motivo = ("este PDF só traz o balancete como imagem (sem texto): leitura por OCR indisponível nesta máquina "
                  "(tesseract/idioma 'por') ou página do demonstrativo não localizada")
        doc = fitz.open(str(caminho))
        try:
            ini = self._pagina_demonstrativo(doc)
            if ini is None:
                dados.motivos_nao_cobertos = {k: motivo for k in ("receitas", "rendimentos", "lancamentos")}
                return dados
            chave = _chave_cache(caminho)
            texto, i = "", ini
            while i < min(len(doc), ini + 5):
                texto += f"\n=== pdf p{i + 1}\n" + _ocr_pagina(doc, caminho, i, chave)
                if re.search(r"^6[.,]\s*Inadimpl", texto, re.M) or (i - ini >= 2 and "Síndico" in texto[-600:]):
                    break
                i += 1
            if len(texto.strip()) < 200:
                dados.motivos_nao_cobertos = {k: motivo for k in ("receitas", "rendimentos", "lancamentos")}
                return dados
            p = _parse_demonstrativo(texto)
            pag_demo = ini + 1
            self._montar(dados, p, pag_demo, doc, caminho, chave)
        finally:
            doc.close()
        aplicar_config_receitas_negativas(dados, self.condo)
        return dados

    @staticmethod
    def _pagina_demonstrativo(doc) -> Optional[int]:
        for i in range(2, min(len(doc), 40)):
            t = doc[i].get_text()
            if "Demonstrativo de receitas e despesas" in t and "Sumário" not in t:
                return i
        return None

    # ── monta o DadosRegras e confere as somas ────────────────────────────────
    def _montar(self, dados, p, pag, doc, caminho, chave):
        avisos = dados.avisos
        despesas = [d for d in p["despesas"] if d["valor"] is not None]
        incompletas = [d for d in p["despesas"] if d["valor"] is None]
        if incompletas:
            avisos.append(f"{len(incompletas)} linha(s) de despesa sem data/valor legível pelo OCR: {'; '.join(d['bruto'][:60] for d in incompletas[:3])}")
        total_desp = abs(p["total_despesas"]) if p["total_despesas"] is not None else None
        total_rec = p["total_receitas"]

        # 1) conferência + reparo de UMA leitura de OCR
        corrigidos = self._fechar_somas(despesas, p, total_desp, avisos)
        soma_desp = round(sum(d["valor"] for d in despesas), 2)
        fecha_desp = total_desp is not None and abs(soma_desp - total_desp) <= _CENT and not incompletas
        # subtotais por grupo
        for cod2, v in p["sub2"].items():
            s = round(sum(d["valor"] for d in despesas if d["cod"] == cod2 or d["cod"].startswith(cod2 + ".")), 2)
            if abs(s - v) > _CENT:
                avisos.append(f"grupo {cod2}: lançamentos lidos somam {s:,.2f}, subtotal impresso {v:,.2f}")
                fecha_desp = False

        receitas = [(c, n, v) for c, n, v, _ in p["receitas"]]
        soma_rec = round(sum(v for _, _, v in receitas), 2)
        fecha_rec = total_rec is not None and abs(soma_rec - total_rec) <= _CENT
        if not fecha_rec:
            fix = self._sinal_perdido(receitas, total_rec)
            if fix is not None:
                avisos.append(f"o sinal '-' da receita '{receitas[fix][1]}' foi perdido no OCR; restaurado porque a soma só fecha assim")
                c, n, v = receitas[fix]
                receitas[fix] = (c, n, -v)
                soma_rec = round(sum(v for _, _, v in receitas), 2)
                fecha_rec = abs(soma_rec - total_rec) <= _CENT
        if not fecha_rec:
            avisos.append(f"Σ receitas lidas ({soma_rec:,.2f}) não fecha com 'Total de receitas' ({total_rec if total_rec is None else f'{total_rec:,.2f}'})")

        # 2) contas de provisionamento
        contas = self._contas(p, avisos)
        dados.contas = contas

        # 3) lançamentos
        if fecha_desp:
            for d in despesas:
                dados.lancamentos.append(self._lancamento(d, pag))
        else:
            dados.motivos_nao_cobertos["lancamentos"] = (
                f"o OCR do demonstrativo não fechou com o total declarado (Σ lido {soma_desp:,.2f} x 'Total de despesas' "
                f"{total_desp if total_desp is None else f'{total_desp:,.2f}'}): lançamentos NÃO aceitos para não validar valores incertos")
        # 4) receitas
        mapa_ok = False
        if fecha_rec:
            atrib, status = self._atribuir_contas(receitas, contas)
            if status:
                avisos.append(status)
            mapa_ok = status is None
            for k, (cod, nome, v) in enumerate(receitas):
                dados.receitas.append(LinhaReceita(conta=atrib[k], descricao=f"{cod} {nome}", valor=v, tipo=_tipo_receita(nome), pagina=pag))
            detalhe = (self.condo.get("parser_config") or {}).get("palm_receitas_detalhe")
            if detalhe:
                self._receitas_detalhe(doc, caminho, chave, dados, receitas, avisos)
        else:
            dados.motivos_nao_cobertos["receitas"] = (
                f"o OCR do demonstrativo não fechou com 'Total de receitas' (Σ lido {soma_rec:,.2f}): receitas NÃO aceitas")
        # rendimento por conta
        for r in dados.receitas:
            if r.tipo == "rendimento":
                for c in contas:
                    if _norm(c.nome) == _norm(r.conta):
                        c.rendimento = round(c.rendimento + r.valor, 2)
        com_rend = [c for c in contas if abs(c.rendimento) > _CENT]
        # Palm Beach: o rendimento MUDA de conta de um mês para o outro, então basta uma conta com rendimento para a regra ter o que comparar
        # (ela marca conta que tinha rendimento no mês anterior e ficou sem). Só vale se a atribuição por conta fechou com os Créditos.
        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": mapa_ok and bool(com_rend), "lancamentos": bool(dados.lancamentos)}
        if not dados.cobertura["rendimentos"]:
            dados.motivos_nao_cobertos["rendimentos"] = (
                "receitas não aceitas (OCR não fechou)" if not dados.receitas else
                "não foi possível atribuir os rendimentos às contas de provisionamento: nenhuma combinação fecha com os Créditos do item 5 "
                "(provável erro de OCR em algum valor do item 5)" if not mapa_ok else "nenhum rendimento (1.8/1.9) neste mês")
        if corrigidos:
            avisos.extend(corrigidos)

    # tenta corrigir UMA leitura (troca de dígito parecido) que feche a soma com o total declarado
    _PARECIDOS = {"0": "896", "1": "74", "3": "85", "5": "63", "6": "58", "8": "03", "9": "04", "7": "1", "4": "19", "2": "7"}

    def _fechar_somas(self, despesas, p, total, avisos):
        """Primeiro por grupo com subtotal impresso (isola onde o OCR errou), depois pelo total geral."""
        msgs = []
        for cod2, v in p["sub2"].items():
            grupo = [d for d in despesas if d["cod"] == cod2 or d["cod"].startswith(cod2 + ".")]
            delta = round(v - sum(d["valor"] for d in grupo), 2)
            if grupo and abs(delta) > _CENT:
                msgs += self._corrigir_um(grupo, delta, avisos, f"grupo {cod2}")
        if total is not None and despesas:
            delta = round(total - sum(d["valor"] for d in despesas), 2)
            if abs(delta) > _CENT:
                msgs += self._corrigir_um(despesas, delta, avisos, "total geral")
        return msgs

    def _corrigir_um(self, lista, delta, avisos, onde):
        """UMA correção de OCR (dígito parecido trocado, dígito a mais, sinal '-' perdido) que feche `delta`; só se for a única possível."""
        candidatos = []
        for d in lista:
            digs = re.sub(r"[^\d]", "", d.get("valor_txt") or "")
            for pos, ch in enumerate(digs):
                for alt in list(self._PARECIDOS.get(ch, "")) + ([""] if len(digs) > 3 else []):
                    novo = digs[:pos] + alt + digs[pos + 1:]
                    try:
                        v = float(novo[:-2] + "." + novo[-2:])
                    except ValueError:
                        continue
                    if abs((v - d["valor"]) - delta) <= _CENT and (d, v) not in [(c[0], c[1]) for c in candidatos]:
                        candidatos.append((d, v, ch, alt or "(removido)"))
        if not candidatos:
            for d in lista:
                if d["valor"] > 0 and abs(-2 * d["valor"] - delta) <= _CENT:
                    d["valor"] = -d["valor"]
                    return [f"OCR ({onde}): sinal '-' perdido em '{d['corpo'][:50]}'; restaurado porque a soma só fecha assim"]
            return []
        if len(candidatos) == 1:
            d, v, ch, alt = candidatos[0]
            msg = f"OCR ({onde}): valor {d['valor']:,.2f} de '{d['corpo'][:50]}' corrigido para {v:,.2f} (dígito {ch}->{alt}) — única correção que fecha a soma"
            d["valor"] = v
            return [msg]
        avisos.append(f"OCR ({onde}): {len(candidatos)} correções possíveis para fechar a diferença de {delta:,.2f}; nenhuma aplicada")
        return []

    @staticmethod
    def _sinal_perdido(receitas, total):
        if total is None:
            return None
        delta = round(total - sum(v for _, _, v in receitas), 2)
        for k, (_, _, v) in enumerate(receitas):
            if v > 0 and abs(-2 * v - delta) <= _CENT:
                return k
        return None

    def _lancamento(self, d, pag) -> LancamentoDespesa:
        corpo = re.sub(r"\s+", " ", d["corpo"]).strip(" -")
        partes = [x.strip() for x in re.split(r"\s+[-–]\s+", corpo) if x.strip()]
        subconta = partes[0] if partes else ""
        fornecedor = partes[1] if len(partes) >= 3 else None
        # Retenções/encargos pagos ao fisco (RECEITA FEDERAL, Previdência Social, Município de São Paulo) são lançados na subconta do serviço a que
        # se referem (que muda de mês a mês); o "fornecedor" do imposto não identifica a despesa — a regra de subcontas passa a usar o histórico.
        if fornecedor and re.match(r"^(RECEITA FEDERAL|PREVIDENCIA SOCIAL|MUNICIPIO DE SAO PAULO|PREFEITURA|SECRETARIA DA RECEITA)", _norm(fornecedor)):
            fornecedor = None
        resto = " - ".join(partes[1:]) if len(partes) > 1 else ""
        cont = " ".join(d["cont"]).strip()
        desc = re.sub(r"\s+", " ", f"{resto} {cont}").strip(" -")
        if not desc:
            desc = subconta
        desc = re.sub(r"\bPARCELA\s*(\d{1,2})\s*/\s*(\d{1,2})\b", r"PARCELA \1/\2", desc)
        return LancamentoDespesa(descricao=desc, valor=d["valor"], categoria=f"{d['cod']} {subconta}".strip(), conta=_CONSOLIDADO,
                                 data=d["data"], fornecedor=fornecedor, pagina=pag)

    def _contas(self, p, avisos) -> list:
        contas = []
        for c in p["contas"]:
            if c.get("secao") != "provisao":
                continue
            ant, cred = c.get("saldo_anterior"), c.get("creditos") or 0.0
            deb = c.get("debitos")
            atual = c["saldo_atual"]
            if ant is None:
                continue
            esperado = round(ant + cred - (deb or 0.0), 2)
            if deb is not None and atual > 0 and abs(esperado + atual) <= _CENT:
                atual = -atual          # o OCR perdeu o '-' do saldo atual no título da conta (saldo negativo da ORDINÁRIA)
                avisos.append(f"conta {c['nome']}: sinal '-' do saldo atual perdido no OCR; restaurado (saldo anterior + créditos - débitos = {esperado:,.2f})")
            if deb is None or abs(esperado - atual) > _CENT:
                # Débitos ilegível ('z', 'é', ...) ou OCR de outro campo: o saldo atual (impresso no título da conta) manda
                deb_der = round(ant + cred - atual, 2)
                if deb_der >= -_CENT:
                    if deb is not None and abs(deb_der - deb) > _CENT:
                        avisos.append(f"conta {c['nome']}: Débitos lidos ({deb:,.2f}) não batem com saldo anterior+créditos-saldo atual ({deb_der:,.2f}); usado o derivado")
                    deb = max(deb_der, 0.0)
                else:
                    avisos.append(f"conta {c['nome']}: saldo anterior {ant:,.2f} + créditos {cred:,.2f} - débitos != saldo atual {atual:,.2f} (provável erro de OCR)")
                    deb = deb or 0.0
            contas.append(ContaMes(nome=c["nome"], saldo_anterior=ant, saldo_atual=atual, creditos=cred, debitos=deb or 0.0))
        tot = p.get("saldo_total")
        if tot is not None and contas and abs(sum(c.saldo_atual for c in contas) - tot) > _CENT:
            avisos.append(f"Σ saldo das contas de provisionamento ({sum(c.saldo_atual for c in contas):,.2f}) difere de 'Saldo total' ({tot:,.2f})")
        return contas

    @staticmethod
    def _nome_conta(destino: str, contas) -> str:
        return next((c.nome for c in contas if _norm(c.nome) == _norm(destino)), destino)

    def _atribuir_contas(self, receitas, contas):
        """Conta de cada grupo de receita, por busca exata contra os Créditos de cada conta (item 5).
        Devolve (lista de contas na ordem de `receitas`, aviso|None). Sem solução: padrão ORDINÁRIA + aviso (e o rendimento não é cobrido)."""
        if not contas:
            return [_CONSOLIDADO] * len(receitas), "contas de provisionamento (item 5) não lidas: receitas sem conta"
        fixa = []
        for _, nome, _ in receitas:
            n = _norm(nome)
            fixa.append(next((self._nome_conta(c, contas) for chave, c in _CONTA_FIXA if chave in n), None))
        livres = [k for k, f in enumerate(fixa) if f is None]
        alvo = {c.nome: round(c.creditos, 2) for c in contas}
        base = {c.nome: 0.0 for c in contas}
        padrao = self._nome_conta(_CONTA_PADRAO, contas)
        for k, f in enumerate(fixa):
            if f is not None:
                if f not in base:
                    return [x or padrao for x in fixa], f"conta '{f}' não existe no item 5; receitas atribuídas por padrão"
                base[f] = round(base[f] + receitas[k][2], 2)
        destinos = [c.nome for c in contas if alvo[c.nome] > _CENT or base[c.nome] > _CENT]
        solucoes = []
        for combo in itertools.product(destinos, repeat=len(livres)):
            soma = dict(base)
            for k, dest in zip(livres, combo):
                soma[dest] = round(soma[dest] + receitas[k][2], 2)
            if all(abs(soma[c] - alvo[c]) <= _CENT for c in soma):
                solucoes.append(combo)
            if len(solucoes) > 50:
                break
        if not solucoes:
            return [f or padrao for f in fixa], "a atribuição dos grupos de receita às contas não fecha com os Créditos do item 5 (OCR ou lançamento atípico)"
        desvios = lambda cb: sum(1 for d in cb if d != padrao)
        escolhida = min(solucoes, key=desvios)                         # a mais próxima do padrão
        empate = [cb for cb in solucoes if desvios(cb) == desvios(escolhida)]
        atrib = list(fixa)
        for k, dest in zip(livres, escolhida):
            atrib[k] = dest
        if len(empate) > 1:
            return atrib, f"{len(empate)} atribuições de receita a contas fecham igualmente com os Créditos; usada a primeira, mais próxima do padrão"
        return atrib, None

    # ── (opcional) receitas por unidade ──────────────────────────────────────
    def _receitas_detalhe(self, doc, caminho, chave, dados, grupos, avisos):
        # localiza o intervalo pelo sumário não é possível (sumário é imagem): procura páginas com o título no texto-camada
        # o título só está no texto-camada da 1ª página da seção; a seção vai até o título "Inadimplências consolidadas"
        ini = next((i for i in range(len(doc)) if "Receitas detalhadas por unidade" in doc[i].get_text()[:400]), None)
        paginas = []
        if ini is not None:
            fim = next((i for i in range(ini + 1, min(len(doc), ini + 40)) if "Inadimplências consolidadas" in doc[i].get_text()[:400]), ini + 12)
            paginas = [i for i in range(ini, fim) if doc[i].get_text().strip()]
        if not paginas:
            avisos.append("páginas 'Receitas detalhadas por unidade/cliente' não localizadas; detalhe não lido")
            return
        linhas = []
        for i in paginas:
            texto = _ocr_pagina(doc, caminho, i, chave, rotacionar=True)
            for ln in texto.splitlines():
                m = re.match(r"^\s*(1\.\d+)\s*[-–]\s*(.+?)\s+(-?\(?[\d][\d.,]*\)?|-|é)\s+(-?\(?[\d][\d.,]*\)?|-)\s*$", ln)
                if m:
                    vr = _br(m.group(4)) if m.group(4) != "-" else 0.0
                    linhas.append((m.group(1), m.group(2).strip(), vr, i + 1, ln.strip()))
        soma_por_classe: dict[str, float] = {}
        for cod, nome, v, pg, ln in linhas:
            if v is not None:
                soma_por_classe[cod] = round(soma_por_classe.get(cod, 0.0) + v, 2)
        grupos_d = {c: v for c, _, v in grupos}
        bate = [c for c in grupos_d if abs(soma_por_classe.get(c, 0.0) - grupos_d[c]) <= _CENT]
        if len(bate) == len(grupos_d) and linhas:
            dados.receitas = [r for r in dados.receitas if False]
            for cod, nome, v, pg, ln in linhas:
                if v is not None:
                    dados.receitas.append(LinhaReceita(conta=self._nome_conta(_CONTA_PADRAO, dados.contas), descricao=f"{cod} {nome} ({ln[:40]})",
                                                       valor=v, tipo=_tipo_receita(nome), pagina=pg))
            avisos.append(f"receitas lidas por unidade (OCR de {len(paginas)} páginas): {len(linhas)} linhas, soma por classe fecha com o demonstrativo")
        else:
            faltam = [c for c in grupos_d if c not in bate]
            avisos.append("detalhe de receitas por unidade descartado: a soma por classe não fecha com o demonstrativo em "
                          + ", ".join(f"{c} ({soma_por_classe.get(c, 0.0):,.2f} x {grupos_d[c]:,.2f})" for c in faltam[:4]))
