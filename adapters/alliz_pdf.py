"""
Adapter ALLIZ PDF — Software DataDigitus (formato ALLIZ/Condominios).

Estrutura confirmada (Monte Tabor, 7 paginas):
  Pag 1-2: "5.4 RESUMO FINANCEIRO" por conta (Multas, Juros, Saldo Anterior/Atual)
  Pag 2:   "RESUMO DAS CONTAS DE BALANCETE" — tabela com totais por conta
  Pag 3:   "2.2 DEMONSTRATIVO DE DESPESAS" — categorias da conta ORDINARIA
  Pag 4:   "1.1 RELATORIO DE PENDENCIAS" — inadimplencia total
  Pag 5-7: "1.4 RELATORIO DE ACORDOS" — nao usada na extracao

Condominios: Monte Tabor (0161)
"""
from pathlib import Path
import re
import unicodedata
from adapters.base import AdapterBase, DadosFinanceiros

REPL = "�"


def _normalize(s: str) -> str:
    """Remove replacement chars (U+FFFD), acentos e converte para maiusculas."""
    # U+FFFD = Unicode replacement character (aparece quando pdfplumber
    # nao consegue decodificar bytes do PDF corretamente)
    s = re.sub(u"�", "", s)
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    return s.upper()


def _num(s: str) -> float:
    """Converte string numerica brasileira (1.234,56) para float positivo."""
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


# Mapeamento nome bruto ALLIZ (normalizado) -> nome canonico no BAL
_CONTA_KEYWORDS: list[tuple[str, str]] = [
    ("FUNDO PESSOAL",      "FUNDO PESSOAL PROV."),
    ("FUNDO RESERVA",      "FUNDO DE RESERVA"),
    ("FUNDO RESCIS",       "FUNDO RESCISAO/INDE."),
    ("BENFEITORIAS",       "BENFEITORIAS"),
    ("ELEVADORES",         "ELEVADORES"),
    ("IMPERMEABILIZ",      "IMPERMEABILIZACAO"),
    ("OBRAS",              "OBRAS"),
    ("ORDINARIA",          "ORDINARIA"),
]

# Mapeamento categorias ALLIZ -> nome canonico de despesa no dashboard
_CAT_KEYWORDS: list[tuple[str, str]] = [
    ("DESPESAS PESSOAL",         "PESSOAL"),
    ("ENCARGOS/IMPOSTOS",        "ENCARGOS SOCIAIS"),
    ("ENCARGOS",                 "ENCARGOS SOCIAIS"),
    ("CONSUMOS",                 "CONSUMOS"),
    ("MANUTENCOES/CONTRATOS",    "MANUT/CONSERV. CONTRAT."),
    ("MANUTENCOES EVENTUAIS",    "MANUT/CONSERV. ESPORAD."),
    ("MANUTENCOES",              "MANUT/CONSERV. CONTRAT."),
    ("EVENTUAIS",                "MANUT/CONSERV. ESPORAD."),
    ("ADMINISTRATIVAS",          "ADMINISTRATIVO"),
    ("GERAIS/BANCARIAS",         "DESP. BANCARIAS"),
    ("GERAIS",                   "DESP. BANCARIAS"),
]

# Mapeamento do nome canonico interno -> nome de exibicao no dashboard
_DISPLAY_MAP: dict[str, str] = {
    "PESSOAL":                  "PESSOAL",
    "SERV. TERCEIRIZADOS":      "SERV. TERCEIRIZADOS",
    "ENCARGOS SOCIAIS":         "ENCARGOS SOCIAIS",
    "CONSUMOS":                 "CONSUMOS",
    "MANUT/CONSERV. CONTRAT.":  "MANUT/CONSERV. CONTRAT.",
    "MANUT/CONSERV. ESPORAD.":  "MANUT/CONSERV. ESPORAD.",
    "ADMINISTRATIVO":           "ADMINISTRATIVO",
    "DESP. BANCARIAS":          "DESP. BANCARIAS",
}

# Mapeamento de nome canonico interno de conta -> nome de exibicao no BAL
_CONTA_DISPLAY: dict[str, str] = {
    "ORDINARIA":               "ORDINARIA",
    "FUNDO DE RESERVA":        "FUNDO DE RESERVA",
    "OBRAS":                   "OBRAS",
    "FUNDO PESSOAL PROV.":     "FUNDO PESSOAL PROV.",
    "BENFEITORIAS":            "BENFEITORIAS",
    "ELEVADORES":              "ELEVADORES",
    "FUNDO RESCISAO/INDE.":    "FUNDO RESCISAO/INDE.",
    "IMPERMEABILIZACAO":       "IMPERMEABILIZACAO",
}


def _nome_conta(nome_raw: str) -> str:
    """Mapeia nome bruto (com encoding potencialmente quebrado) para nome canonico."""
    n = _normalize(nome_raw)
    for kw, canonico in _CONTA_KEYWORDS:
        if kw in n:
            return canonico
    return nome_raw.strip()


def _categoria_alliz(linha: str) -> str | None:
    """Retorna nome canonico da categoria ALLIZ se linha for cabecalho.

    Usa checagem por palavras-chave porque encoding quebrado do PDF faz
    'MANUTENÇÕES' perder as letras C/O (U+FFFD remove bytes do multibyte char).
    Ex: 'MANUTENÇÕES EVENTUAIS' normaliza para 'MANUTENES EVENTUAIS'.
    Por isso checamos 'EVENTUAIS' com 'in' em vez de startswith.
    """
    n = _normalize(linha.strip())
    # Filtra datas e numeros isolados
    if re.search(r"\d{2}/\d{2}/\d{2}", n):
        return None
    if re.search(r"^\d+[.,]\d{2}", n):
        return None
    # Mais especifico primeiro
    if "EVENTUAIS" in n:
        return "MANUT/CONSERV. ESPORAD."
    if n.startswith("DESPESAS PESSOAL") or "DESPESAS PESSOAL" in n:
        return "PESSOAL"
    if "ENCARGOS/IMPOSTOS" in n or n.startswith("ENCARGOS"):
        return "ENCARGOS SOCIAIS"
    if n.startswith("CONSUMOS"):
        return "CONSUMOS"
    if ("CONTRATOS" in n or "CONTRATOS" in n) and "MANUTEN" in n:
        return "MANUT/CONSERV. CONTRAT."
    if "MANUTENCOES/CONTRATOS" in n:
        return "MANUT/CONSERV. CONTRAT."
    if n.startswith("ADMINISTRATIVAS") or n.startswith("ADMINISTRATIVO"):
        return "ADMINISTRATIVO"
    if "GERAIS/BANCARIAS" in n or n.startswith("GERAIS"):
        return "DESP. BANCARIAS"
    return None


class AdapterAllizPDF(AdapterBase):
    """Adapter para PDFs gerados pelo software DataDigitus no formato ALLIZ."""

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        with pdfplumber.open(str(caminho)) as pdf:
            textos = [p.extract_text() or "" for p in pdf.pages]

        texto_total = "\n".join(textos)
        linhas = texto_total.split("\n")

        # ── 1. RESUMO DAS CONTAS DE BALANCETE ─────────────────────────────────
        in_resumo = False
        contas_bal: list[dict] = []

        for linha in linhas:
            l = linha.strip()
            if not l:
                continue

            if "RESUMO DAS CONTAS DE BALANCETE" in l.upper():
                in_resumo = True
                continue

            if not in_resumo:
                continue

            # Cabecalho (ex: "Saldo Anterior Creditos Debitos Saldo Atual")
            if re.search(r"Saldo Anterior", l, re.IGNORECASE) and re.search(r"bitos", l):
                continue

            # Linha "Total Geral  v1  v2  v3  v4"
            if re.match(r"Total\s+Geral", l, re.IGNORECASE):
                nums = re.findall(r"-?[\d.]+,\d{2}", l)
                if len(nums) >= 4:
                    dados.saldo_anterior    = _num(nums[0])
                    dados.receita_realizada = _num(nums[1])
                    dados.despesa_total     = _num(nums[2])
                    dados.saldo_atual       = _num(nums[3])
                in_resumo = False
                continue

            # Linha de conta: extrai 4 numeros no final
            nums = re.findall(r"-?[\d.]+,\d{2}", l)
            if len(nums) == 4:
                # Nome da conta = tudo antes do primeiro numero
                pos = l.index(re.search(r"-?[\d.]+,\d{2}", l).group())
                nome_raw = l[:pos].strip()
                if not nome_raw:
                    continue
                saldo_ant_v  = float(re.sub(r"\.", "", nums[0]).replace(",", "."))
                creditos_v   = float(re.sub(r"\.", "", nums[1]).replace(",", "."))
                debitos_v    = float(re.sub(r"\.", "", nums[2]).replace(",", "."))
                saldo_at_v   = float(re.sub(r"\.", "", nums[3]).replace(",", "."))

                nome_can = _nome_conta(nome_raw)
                contas_bal.append({
                    "nome":        nome_can,
                    "saldo_ant":   round(saldo_ant_v, 2),
                    "creditos":    round(creditos_v, 2),
                    "debitos":     round(debitos_v, 2),
                    "saldo_atual": round(saldo_at_v, 2),
                })

                # Classifica conta bancaria
                n_norm = _normalize(nome_raw)
                if "ORDINARIA" in n_norm:
                    dados.banco_cc      = round(saldo_at_v, 2)
                    dados.receita_cotas = round(creditos_v, 2)
                else:
                    dados.banco_cdb += round(saldo_at_v, 2)
                continue

            # Saida da secao: linha com datas ou titulos de secao
            if re.match(r"\d{2}/\d{2}/\d{2}", l):
                in_resumo = False

        dados.contas_detalhe = [
            {
                "nome":       c["nome"],
                "nome_curto": c["nome"],
                "saldo_ant":  c["saldo_ant"],
                "creditos":   c["creditos"],
                "debitos":    abs(c["debitos"]),
                "saldo_atual": c["saldo_atual"],
            }
            for c in contas_bal
        ]

        # ── 2. FAC: Multas + Juros do 5.4 RESUMO FINANCEIRO ──────────────────
        fac_total = 0.0
        for m in re.finditer(
            r"(?:Multas|Juros e Corre[^\n]{0,20}?)\s+([\d.]+,\d{2})\s*$",
            texto_total, re.MULTILINE
        ):
            fac_total += _num(m.group(1))
        dados.fac = round(fac_total, 2)

        # ── 3. Categorias de Despesa — DEMONSTRATIVO (apenas conta ORDINARIA) ─
        in_demo      = False
        in_ordinaria = False
        cat_atual: str | None = None
        portaria_remota   = 0.0
        cat_pessoal_total = 0.0

        for linha in linhas:
            l = linha.strip()
            if not l:
                continue

            if re.search(r"2\.2\s+DEMONSTRATIVO DE DESPESAS", l, re.IGNORECASE):
                in_demo = True
                continue

            if not in_demo:
                continue

            # Detecta conta ORDINARIA: linha "001 - ORDINARIA"
            m_conta_num = re.match(r"^(\d{3})\s*[-]\s*(\w.*)", l)
            if m_conta_num:
                num_conta = m_conta_num.group(1)
                nome_conta_l = _normalize(m_conta_num.group(2))
                if num_conta == "001" and "ORDINARIA" in nome_conta_l:
                    in_ordinaria = True
                    cat_atual = None
                    portaria_remota = 0.0
                    cat_pessoal_total = 0.0
                elif in_ordinaria:
                    # Encontrou proxima conta, sai da ORDINARIA
                    in_ordinaria = False
                continue

            if not in_ordinaria:
                continue

            # Fecha ao encontrar "TOTAL DA CONTA"
            if re.match(r"TOTAL\s+DA\s+CONTA", _normalize(l)):
                in_ordinaria = False
                cat_atual = None
                continue

            # Detecta linha de despesa "PORTARIA REMOTA ..." (deve INICIAR com isso)
            # Nao capturar linhas de INSS/PIS/ISS que mencionam portaria no sufixo
            if _normalize(l).startswith("PORTARIA REMOTA"):
                m_pr = re.search(r"([\d.]+,\d{2})\s*$", l)
                if m_pr:
                    portaria_remota = _num(m_pr.group(1))
                continue

            # Detecta cabecalho de categoria
            cat = _categoria_alliz(l)
            if cat:
                cat_atual = cat
                continue

            # Subtotal: "XX,XX% VALOR"
            m_sub = re.match(r"[\d,]+%\s+([\d.]+,\d{2})\s*$", l)
            if m_sub and cat_atual:
                val = _num(m_sub.group(1))
                if cat_atual == "PESSOAL":
                    cat_pessoal_total = val
                else:
                    dados.categorias_despesa[cat_atual] = (
                        dados.categorias_despesa.get(cat_atual, 0.0) + val
                    )
                cat_atual = None
                continue

        # Divide PESSOAL em PESSOAL liquido + SERV. TERCEIRIZADOS (portaria)
        if cat_pessoal_total > 0:
            dados.categorias_despesa["PESSOAL"] = round(
                cat_pessoal_total - portaria_remota, 2
            )
            if portaria_remota > 0:
                dados.categorias_despesa["SERV. TERCEIRIZADOS"] = round(portaria_remota, 2)

        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        # ── 4. Inadimplencia: "TOTAL DAS PENDENCIAS" ──────────────────────────
        m_inad = re.search(
            r"TOTAL\s+DAS\s+PEND[^\n]{0,30}\s+([\d.]+,\d{2})\s*$",
            texto_total, re.MULTILINE | re.IGNORECASE
        )
        if m_inad:
            dados.inadimplencia_valor = _num(m_inad.group(1))

        ref_rec = dados.receita_cotas or dados.receita_realizada
        if ref_rec > 0 and dados.inadimplencia_valor > 0:
            dados.inadimplencia_percentual = round(
                dados.inadimplencia_valor / ref_rec * 100, 2
            )

        dados.total_unidades = self.config.get("unidades", 0)
        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """Redireciona para ler_pdf — ALLIZ usa PDF."""
        for ext in [".pdf", ".PDF"]:
            p = caminho.parent / (caminho.stem + ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        raise FileNotFoundError(f"Nenhum PDF ALLIZ encontrado em {caminho.parent}")
