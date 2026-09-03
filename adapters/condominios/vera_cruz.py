"""
Adapter para Vera Cruz — formato Convivium PDF.

Página 5 — Demonstrativo de Contas:
  • Resumo Financeiro Contábil (TOTAL): tAnt, tCred, tDeb, tAtual
  • Resumo de Emissões (CONDÔMINIOS EM ATRASO): inad / inadProc

Páginas 8+:
  • "TOTAL DA CONTA X value%" → categorias de despesa
  • Merge: ENCARGOS SOCIAIS→PESSOAL TERCEIRIZADO, EQUIPAM.→SERVIÇOS EVENTUAIS,
           DESPESAS BANCÁRIAS→DIVERSOS E IMPREVISTOS, IMPOSTOS E TAXAS→HONORÁRIOS
"""
import re
from datetime import datetime
import pdfplumber
from adapters.base import AdapterBase, DadosFinanceiros
from pathlib import Path


def _br(s: str) -> float:
    s = s.strip()
    neg = s.startswith('-')
    s = re.sub(r'[^\d,]', '', s).replace(',', '.')
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return 0.0


_MERGE = {
    'ENCARGOS SOCIAIS': 'PESSOAL TERCEIRIZADO',
    'EQUIPAM. E FERRAMENTAS': 'SERVIÇOS EVENTUAIS/AVULSOS',
    'DESPESAS BANCÁRIAS': 'DIVERSOS E IMPREVISTOS',
    'IMPOSTOS E TAXAS': 'HONORÁRIOS E EXPEDIENTE',
}

_ORDER = [
    'PESSOAL TERCEIRIZADO',
    'CONTRATOS/MANUT. MENSAIS',
    'CONCES.SERV.PÚBLICOS',
    'MATERIAIS DE CONSUMO',
    'SEGUROS',
    'SERVIÇOS EVENTUAIS/AVULSOS',
    'HONORÁRIOS E EXPEDIENTE',
    'DIVERSOS E IMPREVISTOS',
]


class Adapter(AdapterBase):
    """Adapter para Vera Cruz — Convivium PDF."""

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        with pdfplumber.open(str(caminho)) as pdf:
            pages = [pg.extract_text() or '' for pg in pdf.pages]
        return self._extrair(pages, mes_referencia)

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Vera Cruz usa PDF Convivium, não XLSX.")

    def _extrair(self, pages: list, mes_referencia: str) -> DadosFinanceiros:
        # Página 5 (índice 4): dados financeiros principais
        p5 = pages[4] if len(pages) > 4 else ''

        # Resumo Financeiro Contábil — linha TOTAL
        m = re.search(
            r'TOTAL\s+(-?[\d.]+,\d{2})\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s+(-?[\d.]+,\d{2})',
            p5
        )
        if m:
            t_ant  = _br(m.group(1))
            t_cred = _br(m.group(2))
            t_deb  = _br(m.group(3))
            t_atual = _br(m.group(4))
        else:
            t_ant = t_cred = t_deb = t_atual = 0.0

        # CONDÔMINIOS EM ATRASO — inad e inadProc
        inad = 0.0
        inadProc = 0.0
        atraso_hits = re.findall(
            r'CONDÔMINIOS?\s+EM\s+ATRASO\s+EM\s+(\d{2}/\d{2}/\d{4})\s+'
            r'([\d.,]+)(?:\s+([\d.,]+))?',
            p5, re.IGNORECASE
        )
        if atraso_hits:
            dated = []
            for ds, v1, v2 in atraso_hits:
                try:
                    dt = datetime.strptime(ds, '%d/%m/%Y')
                except ValueError:
                    continue
                dated.append((dt, _br(v1), _br(v2) if v2 else 0.0))
            if dated:
                dated.sort(key=lambda x: x[0])
                inad = dated[-1][1]             # último mês = inad atual
                if len(dated) >= 2:
                    inadProc = dated[-2][2]     # coluna Realizado do mês anterior

        # Despesas: "TOTAL DA CONTA X value" em páginas 8+
        raw_cats: dict = {}
        for pg in pages[7:]:
            for m2 in re.finditer(
                r'TOTAL\s+DA\s+CONTA\s+(.+?)\s+([\d.]+,\d{2})(?:\s+[\d.,]+%)?',
                pg, re.IGNORECASE
            ):
                nome = m2.group(1).strip().upper()
                # Pular linha de total geral
                if nome in ('ORDINÁRIA',) or 'TOTAL' in nome:
                    continue
                val = _br(m2.group(2))
                canonical = _MERGE.get(nome, nome)
                raw_cats[canonical] = round(raw_cats.get(canonical, 0.0) + val, 2)

        # Ordenar pelas categorias canônicas
        cats: dict = {}
        for cat in _ORDER:
            if cat in raw_cats:
                cats[cat] = raw_cats[cat]
        for cat, val in raw_cats.items():
            if cat not in cats:
                cats[cat] = val

        return DadosFinanceiros(
            condominio_id='vera_cruz',
            mes_referencia=mes_referencia,
            receita_prevista=round(t_cred, 2),
            receita_realizada=round(t_cred, 2),
            despesa_total=round(t_deb, 2),
            saldo_anterior=round(t_ant, 2),
            saldo_atual=round(t_atual, 2),
            inadimplencia_valor=round(inad, 2),
            inadimplencia_recebida=round(inadProc, 2),
            banco_cc=round(t_atual, 2),
            banco_cdb=0.0,
            banco_priv=0.0,
            categorias_despesa=cats,
            contas_detalhe=[{
                'nome': 'ORDINÁRIA',
                'saldo_ant': round(t_ant, 2),
                'creditos': round(t_cred, 2),
                'debitos': round(t_deb, 2),
                'saldo_atual': round(t_atual, 2),
            }],
        )
