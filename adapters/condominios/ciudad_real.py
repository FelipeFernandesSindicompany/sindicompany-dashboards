"""
Adapter específico para Ciudad Real.
Empresa gestora: GK Administração de Bens (a partir de mai/2026).

Estrutura do PDF GK ADM "Prestação de Contas MM.YYYY.PDF" (358 pág típico):

  Pág 8  — Capa "BALANCETE" (sem dados)
  Pág 9  — Resumo Financeiro Bancário
             Conta bancária | Saldo anterior | Créditos | Débitos | Saldo atual
             Linhas: Conta Repasse, Banco Itau C/C, APLIC CDB DI,
                     APLIC PRIVILEGE, ITAUVEST, TOTAL
           Resumo Financeiro Contábil
             ORDINARIA | FUNDO DE RESERVA | SALÃO DE FESTAS/CHURRASQUEIRA |
             FACILITIES | CRÉDITOS A IDENTIFICAR | TOTAL
           ORDINÁRIA — Posição Financeira (Débito | Crédito)
             Débitos: TRANSFERÊNCIAS, APLICAÇÃO / RESGATE,
                      SERVIÇOS TERCEIRIZADOS, TARIFAS CONCESSIONÁRIAS,
                      MANUTENÇÃO - CONTRATOS, EVENTUAIS - EXTRAS,
                      ADMINISTRATIVO, DESPESAS DIVERSAS
  Pág 10 — CRÉDITOS A IDENTIFICAR (fim)
           Resumo de Emissões Geral
             ORDINARIA EMISSÃO DO PERIODO | Previsto | Realizado
           Posição de Devedores
             Conta | Total anterior | Total recebido | Devedores do mês | Total atrasados
             Totais → inad = Total atrasados, inadProc = Total recebido

campos banco{}: cc=Banco Itaú C/C, cdb=APLIC CDB DI, priv=APLIC PRIVILEGE,
                itauvest=ITAUVEST (via banco_extra)
campos prev/real: ORDINÁRIA — Emissão do Período (Previsto / Realizado)
"""
import re
import unicodedata
from pathlib import Path
from adapters.base import AdapterBase, DadosFinanceiros


def _num(s: str) -> float:
    """Converte string numérica brasileira (1.234,56 ou -1.234,56) para float."""
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
    """Remove acentos e converte para uppercase para comparação."""
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s).upper().strip()


# Categorias de despesa ORDINÁRIA → nomes canônicos do dashboard
# Mais específico primeiro para evitar match parcial errado
_DESP_MAP = [
    ('SERVICOS TERCEIRIZADOS',  'Serv. Terceirizados'),
    ('TARIFAS CONCESSIONARIAS', 'Consumo'),
    ('MANUTENCAO - CONTRATOS',  'Manutenção'),
    ('MANUTENCAO',              'Manutenção'),
    ('EVENTUAIS - EXTRAS',      'Eventuais Extras'),
    ('EVENTUAIS',               'Eventuais Extras'),
    ('ADMINISTRATIVO',          'Administrativo'),
    ('DESPESAS DIVERSAS',       'Despesas Diversas'),
    ('APLICACAO / RESGATE',     'Aplicação / Resgate'),
    ('APLICACAO',               'Aplicação / Resgate'),
    ('TRANSFERENCIAS',          'Transferências'),
]

# Nomes canônicos das contas contábeis
_CONTA_MAP = {
    'ORDINARIA':              'ORDINÁRIA',
    'ORDINÁRIA':              'ORDINÁRIA',
    'FUNDO DE RESERVA':       'FUNDO DE RESERVA',
    'SALAO DE FESTAS/CHURRASQUEIRA': 'SALÃO DE FESTAS/CHURRASQ.',
    'SALAO DE FESTAS':        'SALÃO DE FESTAS/CHURRASQ.',
    'FACILITIES':             'FACILITIES',
    'CREDITOS A IDENTIFICAR': 'CRÉDITOS A IDENTIFICAR',
}


class Adapter(AdapterBase):
    """
    Adapter para Ciudad Real — administradora GK Administração de Bens.
    Lê PDF mensal "Prestação de Contas MM.YYYY.PDF".
    Implementa ler_pdf(); ler_xlsx() redireciona para ler_pdf().
    """

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get('id', 'ciudad_real'),
            mes_referencia=mes_referencia,
        )

        # Lê páginas 8-12 (índices 7-11 zero-based) que contêm todos os dados.
        # Margem extra caso a paginação varie ±1 entre meses.
        with pdfplumber.open(str(caminho)) as pdf:
            total = len(pdf.pages)
            inicio = min(7, total - 1)
            fim    = min(12, total)
            textos = [pdf.pages[i].extract_text() or '' for i in range(inicio, fim)]

        texto = '\n'.join(textos)
        linhas = [l.strip() for l in texto.split('\n') if l.strip()]

        self._extrair_totais_banco(linhas, dados)
        self._extrair_banco(linhas, dados)
        self._extrair_contas(linhas, dados)
        self._extrair_desp(linhas, dados)
        self._extrair_emissoes(linhas, dados)
        self._extrair_inad(linhas, dados)

        return dados

    # ── helpers de extração ────────────────────────────────────────────────────

    def _extrair_totais_banco(self, linhas: list, dados: DadosFinanceiros):
        """Extrai totais gerais do TOTAL do Resumo Financeiro Bancário/Contábil."""
        # Busca a primeira linha "TOTAL ..." com 4 números — são os totais gerais
        for linha in linhas:
            ln = _norm(linha)
            if not ln.startswith('TOTAL'):
                continue
            nums = re.findall(r'-?[\d.]+,\d{2}', linha)
            if len(nums) >= 4:
                dados.saldo_anterior    = _num(nums[0])
                dados.receita_realizada = _num(nums[1])
                dados.despesa_total     = _num(nums[2])
                dados.saldo_atual       = _num(nums[3])
                return

    def _extrair_banco(self, linhas: list, dados: DadosFinanceiros):
        """
        Extrai saldos bancários físicos do Resumo Financeiro Bancário.
        Cada linha tem: descrição | saldo_ant | créditos | débitos | saldo_atual
        """
        for linha in linhas:
            ln = _norm(linha)
            nums = re.findall(r'[\d.]+,\d{2}', linha)
            if len(nums) < 4:
                continue

            saldo_atual = _num(nums[3])

            if 'BANCO ITAU' in ln or 'ITAU AG' in ln or 'C/C' in ln:
                dados.banco_cc = saldo_atual
            elif ('APLIC CDB' in ln or 'CDB DI' in ln) and 'PRIVILEGE' not in ln:
                dados.banco_cdb = saldo_atual
            elif 'PRIVILEGE' in ln:
                dados.banco_priv = saldo_atual
            elif 'ITAUVEST' in ln:
                dados.banco_extra['itauvest'] = saldo_atual

    def _extrair_contas(self, linhas: list, dados: DadosFinanceiros):
        """
        Extrai contas do Resumo Financeiro Contábil.
        Possível crédito negativo em CRÉDITOS A IDENTIFICAR.
        """
        contas_order = [
            'ORDINARIA', 'FUNDO DE RESERVA', 'SALAO DE FESTAS',
            'FACILITIES', 'CREDITOS A IDENTIFICAR',
        ]
        encontradas = set()

        for linha in linhas:
            ln = _norm(linha)

            # Pula linhas de TOTAL e de cabeçalho
            if ln.startswith('TOTAL') or ln in ('SALDO ANTERIOR', 'CREDITOS', 'DEBITOS'):
                continue

            for chave in contas_order:
                if chave not in ln:
                    continue
                if chave in encontradas:
                    continue

                # Captura números, incluindo possível negativo nos créditos
                nums_pos = re.findall(r'[\d.]+,\d{2}', linha)
                if len(nums_pos) < 3:
                    break

                a = _num(nums_pos[0])
                c = _num(nums_pos[1])
                d = _num(nums_pos[2])
                s = _num(nums_pos[3]) if len(nums_pos) >= 4 else round(a + c - d, 2)

                # CRÉDITOS A IDENTIFICAR pode ter crédito negativo
                neg_m = re.search(r'-([\d.]+,\d{2})', linha)
                if 'CREDITOS A IDENTIFICAR' in ln and neg_m:
                    c = -_num(neg_m.group(1))
                    s = round(a + c, 2)

                # Nome canônico
                nome_canon = _CONTA_MAP.get(chave, chave)
                # Para SALÃO: tenta mapear mais específico
                for k, v in _CONTA_MAP.items():
                    if k in ln and k != 'ORDINARIA':
                        nome_canon = v
                        break

                dados.contas_detalhe.append({
                    'nome':       nome_canon,
                    'nome_curto': nome_canon,
                    'saldo_ant':  round(a, 2),
                    'creditos':   round(c, 2),
                    'debitos':    round(d, 2),
                    'saldo_atual': round(s, 2),
                })
                encontradas.add(chave)
                break

    def _extrair_desp(self, linhas: list, dados: DadosFinanceiros):
        """
        Extrai categorias de despesa da Posição Financeira da ORDINÁRIA.
        Detecta seção ORDINÁRIA via marcador e encerra ao entrar em outra conta.
        """
        em_ordinaria = False
        cats: dict = {}
        marcadores_fim = {
            'FUNDO DE RESERVA', 'SALAO DE FESTAS', 'FACILITIES',
            'CREDITOS A IDENTIFICAR', 'RESUMO DE EMISSOES', 'POSICAO DE DEVEDORES',
        }

        for linha in linhas:
            ln = _norm(linha)

            # Detecta início da seção ORDINÁRIA (Posição Financeira)
            if not em_ordinaria:
                if ln in ('ORDINARIA', 'ORDINÁRIA') or ln == 'ORDINARIA':
                    em_ordinaria = True
                continue

            # Detecta fim da seção
            for fim in marcadores_fim:
                if ln.startswith(fim):
                    em_ordinaria = False
                    break
            if not em_ordinaria:
                continue

            # Tenta casar com uma categoria de despesa
            nums = re.findall(r'[\d.]+,\d{2}', linha)
            if not nums:
                continue

            for cat_norm, cat_canon in _DESP_MAP:
                if ln.startswith(cat_norm):
                    val = _num(nums[0])
                    if val > 0:
                        # Evita duplicata (mesmo item pode aparecer nas duas colunas)
                        cats[cat_canon] = max(cats.get(cat_canon, 0.0), val)
                    break

        # Fallback: se não extraiu nada, tenta busca global pelas categorias conhecidas
        if not cats:
            for linha in linhas:
                ln = _norm(linha)
                nums = re.findall(r'[\d.]+,\d{2}', linha)
                if not nums:
                    continue
                for cat_norm, cat_canon in _DESP_MAP:
                    if ln.startswith(cat_norm) and cat_canon not in cats:
                        val = _num(nums[0])
                        if val > 0:
                            cats[cat_canon] = val
                        break

        dados.categorias_despesa = cats

    def _extrair_emissoes(self, linhas: list, dados: DadosFinanceiros):
        """
        Extrai prev e real do TOTAL do Resumo de Emissões Geral (todas as contas).
        O total aparece como a última linha com 2 números antes de
        "COTAS EM ABERTO EM DD/MM/AAAA" (inad do período atual).
        Exemplo: "211.354,66  117.719,67" — sem label de conta.
        """
        em_secao = False
        ultimo_par: tuple | None = None  # (previsto, realizado)

        for linha in linhas:
            ln = _norm(linha)
            if 'RESUMO DE EMISSOES' in ln or 'RESUMO DE EMISSAO' in ln:
                em_secao = True
                continue
            if not em_secao:
                continue

            # Fim da seção — COTAS EM ABERTO no mês de referência atual (ex: 31/07/2026)
            if re.search(r'COTAS EM ABERTO EM \d{2}/\d{2}/\d{4}', ln) and not re.search(r'30/\d{2}/\d{4}', ln):
                break
            if 'POSICAO DE DEVEDORES' in ln or 'RELACAO DE COTAS' in ln:
                break

            # Qualquer linha com 2 ou mais números = candidata ao total
            nums = re.findall(r'[\d.]+,\d{2}', linha)
            if len(nums) >= 2:
                v1 = _num(nums[0])
                v2 = _num(nums[1])
                # Guarda o par mais recente (a última linha com 2 nums = linha de total)
                if v1 > 0 and v2 > 0:
                    ultimo_par = (v1, v2)

        if ultimo_par:
            dados.receita_prevista = ultimo_par[0]
            dados.receita_cotas    = ultimo_par[1]
            return

        # Fallback: usa ORDINÁRIA EMISSÃO DO PERIODO se não encontrar total
        for linha in linhas:
            ln = _norm(linha)
            if 'EMISSAO DO PERIODO' in ln and 'ORDINARIA' in ln:
                nums = re.findall(r'[\d.]+,\d{2}', linha)
                if len(nums) >= 2:
                    dados.receita_prevista = _num(nums[0])
                    dados.receita_cotas    = _num(nums[1])
                    return

    def _extrair_inad(self, linhas: list, dados: DadosFinanceiros):
        """
        Extrai inad e inadProc da Posição de Devedores.
        Linha "Totais": Total anterior | Total recebido | Devedores mês | Total atrasados
        inad     = Total atrasados  (4ª coluna)
        inadProc = Total recebido   (2ª coluna)
        """
        em_secao = False
        for linha in linhas:
            ln = _norm(linha)
            if 'POSICAO DE DEVEDORES' in ln:
                em_secao = True
                continue
            if not em_secao:
                continue

            if ln.startswith('TOTAIS') or ln.startswith('TOTAL'):
                nums = re.findall(r'[\d.]+,\d{2}', linha)
                if len(nums) >= 4:
                    dados.inadimplencia_recebida = _num(nums[1])   # inadProc
                    dados.inadimplencia_valor    = _num(nums[3])   # inad
                    return
            # Encerra seção
            if 'RELACAO DE COTAS' in ln or 'PARCELAS DE PROCESSO' in ln:
                break

        # Fallback: procura "Totais" com 4 números em qualquer linha
        if dados.inadimplencia_valor == 0:
            for linha in linhas:
                ln = _norm(linha)
                if ln.startswith('TOTAIS'):
                    nums = re.findall(r'[\d.]+,\d{2}', linha)
                    if len(nums) >= 4:
                        dados.inadimplencia_recebida = _num(nums[1])
                        dados.inadimplencia_valor    = _num(nums[3])
                        return

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """Redireciona para ler_pdf — GK ADM usa somente PDF."""
        # Testa extensões comuns de PDF
        for ext in ['.pdf', '.PDF']:
            p = caminho.parent / (caminho.stem + ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        # Se o próprio caminho já for um PDF
        if caminho.suffix.lower() == '.pdf' and caminho.exists():
            return self.ler_pdf(caminho, mes_referencia)
        raise FileNotFoundError(
            f"PDF GK ADM não encontrado em {caminho.parent} para {caminho.stem}"
        )
