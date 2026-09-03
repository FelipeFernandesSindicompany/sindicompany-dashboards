"""
Adapter para Gardens Living Club — formato Consvicta PDF (48 pgs).

Fonte dos dados:
  • Pág 33 (Receitas x despesas): tCred, tDeb líquidos
  • Pág 34 (Resumo Financeiro): saldos por conta (ant/final)
  • Pág 43 (Dist. Receitas): crédito do Fundo de Reserva
  • Pág 44 (Dist. Despesas): categorias de despesa
  • Págs 35-42 (Inadimplência): inad total = sum(unit totals + accordo pendentes)

Contas:
  cc  = Ordinária saldo final
  cdb = Fundo de Reserva saldo final
  priv = Locações + Medidores de Gás saldo finais
"""
import re
import pdfplumber
from adapters.base import AdapterBase, DadosFinanceiros
from pathlib import Path


_BR_NUM = r'\d{1,3}(?:\.\d{3})*,\d{2}'


def _br(s: str) -> float:
    s = s.strip().lstrip('(').rstrip(')')
    neg = s.startswith('-')
    s = re.sub(r'[^\d,]', '', s).replace(',', '.')
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return 0.0


# Mapeamento código Consvicta → categoria canônica
_CAT_MAP = {
    '2.24.1': 'Serv. Terceirizados',
    '2.24.9': 'Pessoal e Encargos',
    '2.23.2': 'Consumo (Gás/Energia/Água)',
    '2.23.3': 'Consumo (Gás/Energia/Água)',
    '2.25.10': 'Aquisições',
    '2.27.1': 'Manut. Eventual',
    '2.27.4': 'Manut. Eventual',
    '2.26.19': 'Manut. Mensal',
    '2.26.24': 'Manut. Mensal',
    '2.26.20': 'Manut. Mensal',
    '2.28.1': 'Serv. Prestados',
    '2.28.15.6': 'Serv. Prestados',
    '2.30.1': 'Gestão/Admin./Seguro',
    '2.30.2': 'Gestão/Admin./Seguro',
    '2.29': 'Impostos',
}

_ORDER = [
    'Serv. Terceirizados',
    'Aquisições',
    'Consumo (Gás/Energia/Água)',
    'Manut. Eventual',
    'Manut. Mensal',
    'Serv. Prestados',
    'Gestão/Admin./Seguro',
    'Pessoal e Encargos',
    'Impostos',
]


class Adapter(AdapterBase):
    """Adapter para Gardens Living Club — Consvicta PDF."""

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        with pdfplumber.open(str(caminho)) as pdf:
            pages = [pg.extract_text() or '' for pg in pdf.pages]
        return self._extrair(pages, mes_referencia)

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Gardens Living Club usa PDF Consvicta, não XLSX.")

    def _extrair(self, pages: list, mes_referencia: str) -> DadosFinanceiros:
        # ── Página 33: Receitas x Despesas (valores líquidos, sem transferências) ──
        p33 = self._find_page(pages, 'Receitas x despesas')
        t_cred, t_deb = self._parse_p33(p33)

        # ── Página 34: Resumo Financeiro (saldos por conta) ──
        p34 = self._find_page(pages, 'Resumo Financeiro')
        contas_data = self._parse_p34(p34)

        t_ant  = round(sum(c['saldo_ant']   for c in contas_data.values()), 2)
        t_atual = round(sum(c['saldo_final'] for c in contas_data.values()), 2)

        # ── Página 43: Distribuição das Receitas (FR crédito canônico) ──
        p43 = self._find_page(pages, 'Distribuição das Receitas')
        fr_creditos = self._parse_fr_creditos(p43)

        # ── Reconstruir créditos/débitos por conta ──
        # Medidores de Gás: c=saldo_final, d=saldo_ant (conta pass-through)
        contas_detalhe = self._build_contas(contas_data, t_cred, t_deb, fr_creditos)

        # ── Página 44: Distribuição das Despesas (categorias) ──
        p44 = self._find_page(pages, 'Distribuição das Despesas')
        cats = self._parse_desp(p44)

        # ── Páginas 35-42: Inadimplência por unidade ──
        inad = self._parse_inad(pages)

        # Saldos bancários
        ord_final = contas_data.get('Ordinária', {}).get('saldo_final', 0.0)
        fr_final  = contas_data.get('Fundo de Reserva', {}).get('saldo_final', 0.0)
        loc_final = contas_data.get('Locações', {}).get('saldo_final', 0.0)
        med_final = contas_data.get('Medidores de Gás', {}).get('saldo_final', 0.0)

        return DadosFinanceiros(
            condominio_id='gardens_living_club',
            mes_referencia=mes_referencia,
            receita_prevista=round(t_cred, 2),
            receita_realizada=round(t_cred, 2),
            despesa_total=round(t_deb, 2),
            saldo_anterior=round(t_ant, 2),
            saldo_atual=round(t_atual, 2),
            inadimplencia_valor=round(inad, 2),
            inadimplencia_recebida=0.0,
            banco_cc=round(ord_final, 2),
            banco_cdb=round(fr_final, 2),
            banco_priv=round(loc_final + med_final, 2),
            categorias_despesa=cats,
            contas_detalhe=contas_detalhe,
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _find_page(self, pages: list, keyword: str) -> str:
        """Retorna texto da primeira página que contém keyword."""
        for pg in pages:
            if keyword in pg:
                return pg
        return ''

    def _parse_p33(self, text: str):
        """Extrai receitas e despesas líquidas da tabela Receitas x Despesas."""
        # Linha do mês atual (última linha com Receitas/Despesas/Resultado)
        rows = re.findall(
            r'(Jan|Fev|Mar|Abr|Mai|Jun|Jul|Ago|Set|Out|Nov|Dez)/\d{4}\s+'
            r'([\d.]+,\d{2})\s+([\d.]+,\d{2})\s+[-\d.,]+\s+[-\d.,]+%',
            text, re.IGNORECASE
        )
        if rows:
            last = rows[-1]
            return _br(last[1]), _br(last[2])
        # Fallback: procura "Total" da tabela
        m = re.search(
            r'Total\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})',
            text
        )
        if m:
            return _br(m.group(1)), _br(m.group(2))
        return 0.0, 0.0

    def _parse_p34(self, text: str) -> dict:
        """Extrai saldos por conta do Resumo Financeiro."""
        contas = {}
        # Padrão: "Nome Conta  valor  valor  valor  valor"
        pat = re.compile(
            r'^(Ordinária|Fundo de Reserva|Locações|Medidores de Gás)\s+'
            r'(' + _BR_NUM + r')\s+(' + _BR_NUM + r')\s+(' + _BR_NUM + r')\s+(' + _BR_NUM + r')',
            re.MULTILINE
        )
        for m in pat.finditer(text):
            nome = m.group(1)
            contas[nome] = {
                'saldo_ant':   _br(m.group(2)),
                'creditos_raw': _br(m.group(3)),
                'debitos_raw':  _br(m.group(4)),
                'saldo_final': _br(m.group(5)),
            }
        return contas

    def _parse_fr_creditos(self, text: str) -> float:
        """Extrai crédito canônico do Fundo de Reserva da pág 43."""
        m = re.search(r'(?:1\.22|Fundo de Reserva)\s+(' + _BR_NUM + r')', text)
        if m:
            return _br(m.group(1))
        return 0.0

    def _build_contas(self, contas_data: dict, t_cred: float, t_deb: float,
                      fr_creditos: float) -> list:
        """Constrói contas_detalhe com créditos/débitos ajustados."""
        result = []
        c_ord = contas_data.get('Ordinária')
        c_fr  = contas_data.get('Fundo de Reserva')
        c_loc = contas_data.get('Locações')
        c_med = contas_data.get('Medidores de Gás')

        # Créditos/débitos per conta
        fr_c  = fr_creditos if fr_creditos else (c_fr['creditos_raw'] if c_fr else 0.0)
        loc_c = c_loc['creditos_raw'] if c_loc else 0.0
        med_c = c_med['saldo_final']  if c_med else 0.0   # pass-through
        ord_c = round(t_cred - fr_c - loc_c - med_c, 2)

        med_d = c_med['saldo_ant']   if c_med else 0.0    # pass-through
        fr_d  = round((c_fr['saldo_ant'] + fr_c - c_fr['saldo_final']), 2) if c_fr else 0.0
        loc_d = c_loc['debitos_raw'] if c_loc else 0.0
        ord_d = round(t_deb - fr_d - loc_d - med_d, 2)

        contas_map = [
            ('ORDINÁRIA',        c_ord, ord_c, ord_d),
            ('FUNDO DE RESERVA', c_fr,  fr_c,  fr_d),
            ('LOCAÇÕES',         c_loc, loc_c, loc_d),
            ('MEDIDORES DE GÁS', c_med, med_c, med_d),
        ]
        for nome, data, cred, deb in contas_map:
            if data:
                result.append({
                    'nome': nome,
                    'saldo_ant':  round(data['saldo_ant'], 2),
                    'creditos':   round(cred, 2),
                    'debitos':    round(deb, 2),
                    'saldo_atual': round(data['saldo_final'], 2),
                })
        return result

    def _parse_desp(self, text: str) -> dict:
        """Extrai categorias de despesa da pág 44 (Distribuição das Despesas)."""
        raw: dict = {}

        # Linhas com código: "2.24.1 Serviços Terceirizados 121.860,43 31,17"
        for m in re.finditer(
            r'^([\d.]+)\s+(.+?)\s+(' + _BR_NUM + r')\s+[\d.,]+\s*$',
            text, re.MULTILINE
        ):
            code = m.group(1).strip()
            val  = _br(m.group(3))
            canonical = _CAT_MAP.get(code)
            if canonical:
                raw[canonical] = round(raw.get(canonical, 0.0) + val, 2)
            # Códigos não mapeados → ignorar (contribuem para "Outros" implicitamente)

        # Linha "Outros value %"
        m_out = re.search(r'^Outros\s+(' + _BR_NUM + r')', text, re.MULTILINE)
        if m_out:
            raw['Aquisições'] = round(
                raw.get('Aquisições', 0.0) + _br(m_out.group(1)), 2
            )

        cats: dict = {}
        for cat in _ORDER:
            if cat in raw:
                cats[cat] = raw[cat]
        for cat, val in raw.items():
            if cat not in cats:
                cats[cat] = val
        return cats

    def _parse_inad(self, pages: list) -> float:
        """Soma total de inadimplência: unit totals + accordo pendentes."""
        # Identificar seção de inadimplência
        inad_start = -1
        inad_end   = len(pages)
        for i, pg in enumerate(pages):
            if 'Inadimplência, acordos e cobranças judiciais por unidade' in pg:
                if inad_start < 0:
                    inad_start = i
            if inad_start >= 0 and (
                'Distribuição das Receitas' in pg or 'Distribuição das Despesas' in pg
            ):
                inad_end = i
                break

        if inad_start < 0:
            return 0.0

        texto_inad = '\n'.join(pages[inad_start:inad_end])

        total = 0.0

        # 1) Total das unidades inadimplentes: "Total n n n n n UNIT_TOTAL"
        pat_inad = re.compile(
            r'^Total\s+(?:' + _BR_NUM + r'\s+){5}(' + _BR_NUM + r')\s*$',
            re.MULTILINE
        )
        for m in pat_inad.finditer(texto_inad):
            total += _br(m.group(1))

        # 2) Pendente de acordos: linha de totalizacao com exatamente 5 numeros BR
        # "D1 D2 D3 ATRASO PENDENTE" — o 5º valor é o pendente ainda a vencer
        pat_acc = re.compile(
            r'^(' + _BR_NUM + r')\s+(' + _BR_NUM + r')\s+(' + _BR_NUM + r')\s+'
            r'(' + _BR_NUM + r')\s+(' + _BR_NUM + r')\s*$',
            re.MULTILINE
        )
        for m in pat_acc.finditer(texto_inad):
            total += _br(m.group(5))

        return round(total, 2)
