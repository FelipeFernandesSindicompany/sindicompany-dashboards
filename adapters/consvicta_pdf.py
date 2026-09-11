"""
Adapter Consvicta PDF — Pasta de Prestação de Contas MM.AAAA.pdf

Formato: software Consvicta (gestão condominial)
Condomínios: Gardens Living Club I
Referência: a partir de Maio/2026 (modelo canônico a ser seguido daqui pra frente)

Estrutura do PDF:
  W020A (pág 2-3):  Demonstrativo de Receitas e Despesas Analítico
                    • Saldo anterior: "Saldo em DD/MM/AAAA: NN,NN"
                    • Taxa de Condomínio → prev
                    • Categorias de receita e despesa
  W016B (pág ~17):  Resumo Financeiro por Conta
                    • Ordinária, Fundo de Reserva, Locações, Medidores de Gás
                    • Formato: Nome | Saldo Ant | Créditos | Débitos | Saldo Final
                    • TOTAL final = tAnt/tCred/tDeb/tAtual
  Inadimplência:    Busca seção específica com total de devedores
"""
from pathlib import Path
import re
from adapters.base import AdapterBase, DadosFinanceiros

_CAT_MAP_DEFAULT: dict[str, str] = {
    "PESSOAL":                "PESSOAL",
    "ENCARGOS":               "ENCARGOS SOCIAIS",
    "SERVIÇOS TERCEIROS":     "SERV. TERCEIRIZADOS",
    "SERV. TERCEIROS":        "SERV. TERCEIRIZADOS",
    "TERCEIRIZADOS":          "SERV. TERCEIRIZADOS",
    "CONSUMO":                "CONSUMOS",
    "CONSUMOS":               "CONSUMOS",
    "ADMINISTRATIVO":         "ADMINISTRATIVO",
    "ADMINISTRATIVAS":        "ADMINISTRATIVO",
    "MANUTENCAO":             "MANUT/CONSERV.",
    "MANUTENÇÃO":             "MANUT/CONSERV.",
    "OBRAS":                  "OBRAS/MELHORIAS",
    "MELHORIAS":              "OBRAS/MELHORIAS",
    "SEGUROS":                "SEGUROS",
    "MATERIAL":               "MATERIAIS",
}

# Contas do W016B e seu mapeamento para banco
_CONTA_CC   = ("ORDINÁRIA", "ORDINARIA")
_CONTA_CDB  = ("FUNDO DE RESERVA",)
_CONTA_PRIV = ("LOCAÇÕES", "LOCACOES", "MEDIDORES DE GÁS", "MEDIDORES DE GAS")


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = str(s).strip()
    s = re.sub(r'\.(?=\d{3})', '', s)
    s = s.replace(',', '.')
    s = re.sub(r'[^\d.\-]', '', s)
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _extract_pages(pdf_path: Path, max_pages: int = 30) -> list[str]:
    try:
        import pdfplumber
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pdfplumber', '-q'])
        import pdfplumber

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages[:max_pages]):
            pages.append(page.extract_text() or '')
    return pages


def _find_w016b(pages: list[str]) -> tuple[list[dict], float, float, float, float]:
    """
    Extrai contas do W016B e o total.
    Retorna: (contas, tAnt, tCred, tDeb, tAtual)
    """
    contas = []
    tAnt = tCred = tDeb = tAtual = 0.0

    # Padrões de contas no W016B Consvicta
    conta_patterns = [
        "Ordinária", "ORDINÁRIA", "Ordinaria",
        "Fundo de Reserva", "FUNDO DE RESERVA",
        "Locações", "LOCAÇÕES", "Locacoes",
        "Medidores de Gás", "MEDIDORES DE GÁS", "Medidores de Gas",
    ]

    # Nomes canônicos
    def normalizar(nome: str) -> str:
        n = nome.lower()
        if 'ordinár' in n or 'ordinaria' in n:
            return 'ORDINÁRIA'
        if 'fundo de reserva' in n:
            return 'FUNDO DE RESERVA'
        if 'locaç' in n or 'locacoes' in n:
            return 'LOCAÇÕES'
        if 'medidor' in n or 'gás' in n or 'gas' in n:
            return 'MEDIDORES DE GÁS'
        return nome.upper()

    for text in pages:
        if 'Resumo Financeiro' not in text and 'W016B' not in text:
            continue

        lines = text.split('\n')
        found_contas = []

        for line in lines:
            matched = False
            for pat in conta_patterns:
                if pat.lower() in line.lower():
                    nums = re.findall(r'-?\d{1,3}(?:\.\d{3})*,\d{2}', line)
                    if len(nums) >= 4:
                        found_contas.append({
                            'n': normalizar(pat),
                            'a': _num(nums[0]),
                            'c': _num(nums[1]),
                            'd': _num(nums[2]),
                            's': _num(nums[3]),
                        })
                        matched = True
                        break

            # TOTAL
            if ('TOTAL' in line.upper() or 'Total' in line) and not matched:
                nums = re.findall(r'-?\d{1,3}(?:\.\d{3})*,\d{2}', line)
                if len(nums) >= 4:
                    tAnt = _num(nums[0])
                    tCred = _num(nums[1])
                    tDeb = _num(nums[2])
                    tAtual = _num(nums[3])

        if found_contas:
            # Deduplicar por nome
            seen = {}
            for c in found_contas:
                if c['n'] not in seen:
                    seen[c['n']] = c
            contas = list(seen.values())

            # Se não achou TOTAL explícito, calcular
            if tAtual == 0.0:
                tAnt = sum(c['a'] for c in contas)
                tCred = sum(c['c'] for c in contas)
                tDeb = sum(c['d'] for c in contas)
                tAtual = sum(c['s'] for c in contas)
            break

    return contas, tAnt, tCred, tDeb, tAtual


def _find_period(pages: list[str]) -> tuple[str, str]:
    """Encontra período do balancete."""
    import calendar

    for text in pages:
        # Padrão: "01/07/2026 a 31/07/2026" ou similar
        m = re.search(r'(\d{2}/\d{2}/\d{4})\s+(?:a|à|A)\s+(\d{2}/\d{2}/\d{4})', text)
        if m:
            return m.group(1), m.group(2)

        # Padrão: "Período: MM/AAAA"
        m = re.search(r'(?:Período|PERÍODO)[:\s]+(\d{2}/\d{4})', text)
        if m:
            mes, ano = m.group(1).split('/')
            mes, ano = int(mes), int(ano)
            ultimo = calendar.monthrange(ano, mes)[1]
            return f"01/{mes:02d}/{ano}", f"{ultimo}/{mes:02d}/{ano}"

    return '', ''


def _find_inad(pages: list[str]) -> tuple[float, float]:
    """Extrai inadimplência total e recuperada."""
    inad = inadProc = 0.0

    for text in pages:
        # Total inadimplência
        for pattern in [
            r'(?:Total\s+(?:de\s+)?[Ii]nadimplência|TOTAL\s+INADIMPLÊNCIA)[^\n\d]*(\d{1,3}(?:\.\d{3})*,\d{2})',
            r'(?:Cotas?\s+em\s+[Aa]traso|COTAS EM ATRASO)[^\n\d]*(\d{1,3}(?:\.\d{3})*,\d{2})',
            r'Total\s+[Ii]nadimpl[êe]ntes[^\n\d]*(\d{1,3}(?:\.\d{3})*,\d{2})',
        ]:
            m = re.search(pattern, text)
            if m:
                inad = _num(m.group(1))
                break

        # Recuperado em atraso
        for pattern in [
            r'(?:Recebido|RECEBIDO)\s+(?:em\s+)?[Aa]traso[^\n\d]*(\d{1,3}(?:\.\d{3})*,\d{2})',
            r'(?:Cotas?\s+em\s+[Aa]traso\s+[Rr]ecebidas?|COTAS EM ATRASO RECEBIDAS?)[^\n\d]*(\d{1,3}(?:\.\d{3})*,\d{2})',
            r'(?:Recuperado|RECUPERADO)[^\n\d]*(\d{1,3}(?:\.\d{3})*,\d{2})',
        ]:
            m = re.search(pattern, text)
            if m:
                inadProc = _num(m.group(1))
                break

    return inad, inadProc


def _find_desp(pages: list[str], cat_map: dict) -> dict:
    """Extrai categorias de despesa."""
    merged_map = {**_CAT_MAP_DEFAULT, **cat_map}
    cats: dict[str, float] = {}

    for text in pages:
        lines = text.split('\n')
        for line in lines:
            lu = line.upper()
            for raw, canonical in merged_map.items():
                if raw.upper() in lu:
                    nums = re.findall(r'\d{1,3}(?:\.\d{3})*,\d{2}', line)
                    if nums:
                        val = _num(nums[-1])
                        if val > 0:
                            if canonical not in cats:
                                cats[canonical] = val

    return cats


class AdapterConsvictaPDF(AdapterBase):
    """Adapter para PDFs no formato Consvicta (W020A + W016B)."""

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        cat_map = self.parser_config.get('cat_map', {})
        pages = _extract_pages(caminho, max_pages=30)

        # Contas W016B
        contas, tAnt, tCred, tDeb, tAtual = _find_w016b(pages)

        # Período
        d_ini, d_fim = _find_period(pages)

        # prev e real da conta Ordinária
        prev = real = tDesp = 0.0
        for c in contas:
            if 'ORDINÁR' in c['n'] or 'ORDINARIA' in c['n'].upper():
                real = c['c']    # créditos da Ordinária = receita realizada
                tDesp = c['d']   # débitos da Ordinária = despesas pagas
                prev = real      # sem previsão separada: usar realizado como base
                break

        # Inadimplência
        inad, inadProc = _find_inad(pages)

        # Banco: ordinária=cc, reserva=cdb, demais=priv
        cc = cdb = priv = 0.0
        for c in contas:
            n = c['n'].upper()
            if 'ORDINÁR' in n or 'ORDINARIA' in n:
                cc = c['s']
            elif 'FUNDO DE RESERVA' in n:
                cdb = c['s']
            else:
                priv += c['s']

        # Despesas por categoria
        cats = _find_desp(pages, cat_map)

        # Contas para contas_detalhe
        contas_detalhe = [
            {
                'nome': c['n'],
                'saldo_ant': c['a'],
                'creditos': c['c'],
                'debitos': c['d'],
                'saldo_atual': c['s'],
            }
            for c in contas
        ]

        return DadosFinanceiros(
            condominio_id='',
            mes_referencia=mes_referencia,
            receita_prevista=prev,
            receita_realizada=real,
            despesa_total=tDesp,
            saldo_anterior=tAnt,
            saldo_atual=tAtual,
            inadimplencia_valor=inad,
            inadimplencia_recebida=inadProc,
            categorias_despesa=cats,
            contas_detalhe=contas_detalhe,
            banco_cc=cc,
            banco_cdb=cdb,
            banco_priv=priv,
            observacoes=f"Período: {d_ini} a {d_fim}" if d_ini else '',
        )

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Consvicta usa PDF, não XLSX")
