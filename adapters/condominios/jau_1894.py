"""
Adapter específico para Jaú 1894.
Empresa gestora: Lello Condomínios — PDF "Balancete Mensal" (2 páginas).

Estrutura do PDF:
  Pág 1:
    COMPOSIÇÃO DE ARRECADAÇÃO
      CONDOMINOS EM ATRASO | COTAS CONDOMINIAIS | BENFEITORIAS DIVERSAS | ... | TOTAL
    RESUMO DE ACORDOS
    COMPOSIÇÃO RECEITAS ORDINÁRIAS
      CONDOMINOS EM ATRASO | COTAS CONDOMINIAIS | ... | TOTAL
    COMPOSIÇÃO DESPESAS ORDINÁRIA
      DESPESAS COM PESSOAL | ENCARGOS SOCIAIS | MANUTENCAO CONSERV.* | ... | TOTAL
  Pág 2:
    RECEBIMENTO DE CONTAS EXTRAORDINÁRIAS (TOTAL)
    DESPESAS DE CONTAS EXTRAORDINÁRIAS (TOTAL)
    RESUMO DE INADIMPLÊNCIA
      TOTAL DEVEDORES CONTA CONDOMÍNIO | TOTAL DEVEDORES FUNDO DE RESERVA | TOTAL GERAL
    RESUMO FINANCEIRO (CONTA CONDOMÍNIO | FUNDO DE RESERVA | SALDO FINAL)
      Colunas: saldo_ant | créditos | débitos | saldo_final

Campos extraídos:
  tAnt/tCred/tDeb/tAtual = SALDO FINAL do RESUMO FINANCEIRO
  real  = créditos da CONTA CONDOMÍNIO
  prev  = COTAS CONDOMINIAIS (COMPOSIÇÃO RECEITAS ORDINÁRIAS) — melhor aproximação disponível
  banco = cc: saldo_final CONTA CONDOMÍNIO; cdb: saldo_final FUNDO DE RESERVA
  inad  = TOTAL GERAL DE DEVEDORES (RESUMO DE INADIMPLÊNCIA)
  inadProc = CONDOMINOS EM ATRASO (COMPOSIÇÃO DE ARRECADAÇÃO) — valor recebido de devedores
  desp  = COMPOSIÇÃO DESPESAS ORDINÁRIA → nomes canônicos
"""
import re
import unicodedata
from pathlib import Path
from adapters.base import AdapterBase, DadosFinanceiros


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = str(s).strip()
    neg = s.startswith('-')
    s = re.sub(r'[^\d,.]', '', s)
    s = s.replace('.', '').replace(',', '.')
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return 0.0


def _norm(s: str) -> str:
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s).upper().strip()


# Mapeamento COMPOSIÇÃO DESPESAS ORDINÁRIA → nomes canônicos do dashboard
_DESP_MAP = [
    ('DESPESAS COM PESSOAL',            'Pessoal'),
    ('ENCARGOS SOCIAIS',                'Encargos Sociais'),
    ('MANUTENCAO CONSERV.PREVENTIVA',    'Manut/Conserv. Preventiva'),
    ('MANUTENCAO CONSERV. CORRETIVA',   'Manut/Conserv. Corretiva'),
    ('SERVICOS ADVOCATICIOS',           'Serv. Advocatícios'),
    ('CONCESSAO DE SERVICOS',           'Concessão de Serv.'),
    ('MATERIAIS P/CONSERV.',            'Materiais'),
    ('ADMINISTRATIVO',                  'Administrativo'),
    ('DESPESAS GERAIS',                 'Desp. Gerais'),
    ('DESPESAS OPERACIONAIS',           'Desp. Operacionais'),
    ('SEGUROS',                         'Seguros'),
    ('BENS/ACESSORIOS E EQUIPAMENTOS',  'Bens/Equipamentos'),
    ('SINDICO PROFISSIONAL',            'Síndico Profissional'),
    ('CAIXA LOCAL',                     'Caixa Local'),
]


class Adapter(AdapterBase):
    """
    Adapter para Jaú 1894 — PDF "Balancete Mensal" Lello Condomínios (2 páginas).
    """

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get('id', 'jau_1894'),
            mes_referencia=mes_referencia,
        )

        with pdfplumber.open(str(caminho)) as pdf:
            textos = [p.extract_text() or '' for p in pdf.pages]

        linhas = [l.strip() for l in '\n'.join(textos).split('\n') if l.strip()]

        self._extrair_resumo_financeiro(linhas, dados)
        self._extrair_inad(linhas, dados)
        self._extrair_desp(linhas, dados)
        self._extrair_inadproc_e_prev(linhas, dados)

        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        return self.ler_pdf(caminho, mes_referencia)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _extrair_resumo_financeiro(self, linhas: list, dados: DadosFinanceiros):
        """
        Extrai do RESUMO FINANCEIRO (Page 2):
          CONTA CONDOMÍNIO — colunas: saldo_ant | créditos | débitos | saldo_final
          FUNDO DE RESERVA — idem
          SALDO FINAL — totais consolidados
        """
        em_secao = False
        for linha in linhas:
            ln = _norm(linha)
            if 'RESUMO FINANCEIRO' in ln:
                em_secao = True
                continue
            if not em_secao:
                continue

            nums = re.findall(r'-?[\d.]+,\d{2}', linha)
            if len(nums) < 4:
                continue

            if 'CONTA CONDOMINIO' in ln or 'CONTA COND' in ln:
                dados.contas_detalhe.append({
                    'nome': 'CONTA CONDOMÍNIO', 'nome_curto': 'CONTA CONDOMÍNIO',
                    'saldo_ant': _num(nums[0]),
                    'creditos':  _num(nums[1]),
                    'debitos':   abs(_num(nums[2])),
                    'saldo_atual': _num(nums[3]),
                })
                dados.receita_cotas = _num(nums[1])   # créditos CONTA CONDOMÍNIO → real
                dados.banco_cc = _num(nums[3])

            elif 'FUNDO DE RESERVA' in ln:
                dados.contas_detalhe.append({
                    'nome': 'FUNDO DE RESERVA', 'nome_curto': 'FUNDO DE RESERVA',
                    'saldo_ant': _num(nums[0]),
                    'creditos':  _num(nums[1]),
                    'debitos':   abs(_num(nums[2])),
                    'saldo_atual': _num(nums[3]),
                })
                dados.banco_cdb = _num(nums[3])

            elif 'SALDO FINAL' in ln:
                # Totais consolidados
                dados.saldo_anterior    = _num(nums[0])
                dados.receita_realizada = _num(nums[1])  # total créditos → tCred
                dados.despesa_total     = abs(_num(nums[2]))
                dados.saldo_atual       = _num(nums[3])
                break

    def _extrair_inad(self, linhas: list, dados: DadosFinanceiros):
        """TOTAL GERAL DE DEVEDORES do RESUMO DE INADIMPLÊNCIA → inad."""
        em_secao = False
        for linha in linhas:
            ln = _norm(linha)
            if 'RESUMO DE INADIMPL' in ln:
                em_secao = True
                continue
            if not em_secao:
                continue
            if 'RESUMO FINANCEIRO' in ln:
                break
            if 'TOTAL GERAL' in ln:
                nums = re.findall(r'[\d.]+,\d{2}', linha)
                if nums:
                    dados.inadimplencia_valor = _num(nums[-1])
                break

    def _extrair_desp(self, linhas: list, dados: DadosFinanceiros):
        """COMPOSIÇÃO DESPESAS ORDINÁRIA → categorias canônicas."""
        em_secao = False
        cats: dict = {}
        for linha in linhas:
            ln = _norm(linha)
            if 'COMPOSICAO DESPESAS ORDINARIA' in ln or 'COMPOSIÇÃO DESPESAS ORDINÁRIA' in ln:
                em_secao = True
                continue
            if not em_secao:
                continue
            # Fim de seção
            if ln.startswith('TOTAL') or 'RECEBIMENTO DE CONTAS' in ln or 'RESUMO DE ACORDOS' in ln:
                break
            nums = re.findall(r'-?[\d.]+,\d{2}', linha)
            if not nums:
                continue
            for cat_norm, cat_canon in _DESP_MAP:
                if ln.startswith(cat_norm):
                    val = abs(_num(nums[0]))
                    if val > 0:
                        cats[cat_canon] = cats.get(cat_canon, 0.0) + val
                    break
        dados.categorias_despesa = cats

    def _extrair_inadproc_e_prev(self, linhas: list, dados: DadosFinanceiros):
        """
        COMPOSIÇÃO RECEITAS ORDINÁRIAS:
          CONDOMINOS EM ATRASO → inadProc
          COTAS CONDOMINIAIS   → prev (melhor aproximação disponível no PDF)
        """
        em_secao = False
        for linha in linhas:
            ln = _norm(linha)
            if 'COMPOSICAO RECEITAS ORDINARIAS' in ln or 'COMPOSIÇÃO RECEITAS ORDINÁRIAS' in ln:
                em_secao = True
                continue
            if not em_secao:
                continue
            if ln.startswith('TOTAL') or 'COMPOSICAO DESPESAS' in ln or 'COMPOSIÇÃO DESPESAS' in ln:
                break

            nums = re.findall(r'[\d.]+,\d{2}', linha)
            if not nums:
                continue

            if 'CONDOMINOS EM ATRASO' in ln:
                dados.inadimplencia_recebida = _num(nums[0])
            elif 'COTAS CONDOMINIAIS' in ln:
                dados.receita_prevista = _num(nums[0])
