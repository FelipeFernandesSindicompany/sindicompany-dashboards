"""
Adapter para Saint Simon — formato Conviver MRV (1-2 páginas).

Metodologia:
- prev = real = tCred  (garantidora LLZ; todas as cotas sempre realizadas)
- banco{cc=tAtual, cdb=0, priv=0}
- inad = inadProc = fac = 0
- Suporte a 1 ou 2 contas (001-Conta Corrente + 002-Banco Inter Empresas)
- tAnt/tAtual = soma de todos os saldos das contas encontradas
- Categorias brutas → cat_map em condominios.json mapeia para 3 canônicas:
    Mensais, Manutenção, Outras Despesas
"""
import re
import pdfplumber
from adapters.base import AdapterBase, DadosFinanceiros
from pathlib import Path


def _br(s: str) -> float:
    """Converte número em formato BR (possivelmente negativo) para float."""
    s = s.strip()
    neg = s.startswith('-')
    s = re.sub(r'[^\d,]', '', s).replace(',', '.')
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return 0.0


class Adapter(AdapterBase):
    """Adapter para Saint Simon — Conviver MRV PDF."""

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        with pdfplumber.open(str(caminho)) as pdf:
            texto = '\n'.join(pg.extract_text() or '' for pg in pdf.pages)
        return self._extrair(texto, mes_referencia)

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Saint Simon usa PDF Conviver MRV, não XLSX.")

    def _extrair(self, texto: str, mes_referencia: str) -> DadosFinanceiros:
        def find(pattern, t=texto):
            m = re.search(pattern, t)
            return _br(m.group(1)) if m else 0.0

        # Totais globais
        t_cred = find(r'Total Receitas\s*:\s*R\$\s*([\d.,]+)')
        t_deb  = find(r'Total Despesas\s*:\s*R\$\s*([\d.,]+)')

        # Coleta TODAS as contas (suporta saldos negativos com "-" antes de R$)
        # Padrão: "NNN - Nome da Conta  R$ 1.234,56  R$ 7.890,12"
        #          ou "NNN - Nome  -R$ 1.234,56  R$ 7.890,12"
        contas_detalhe = []
        for m in re.finditer(
            r'(\d{3})\s*-\s*([^\n]+?)\s+(-?R\$\s*[\d.,]+)\s+(-?R\$\s*[\d.,]+)',
            texto
        ):
            raw_ant   = re.sub(r'R\$\s*', '', m.group(3))
            raw_atual = re.sub(r'R\$\s*', '', m.group(4))
            v_ant   = _br(raw_ant)
            v_atual = _br(raw_atual)
            nome = m.group(2).strip()
            contas_detalhe.append({
                'nome':       nome,
                'saldo_ant':  v_ant,
                'creditos':   t_cred if 'inter' in nome.lower() else 0.0,
                'debitos':    t_deb  if 'inter' in nome.lower() else abs(v_atual - v_ant) if v_atual != v_ant else 0.0,
                'saldo_atual': v_atual,
            })

        # Calcula totais consolidados
        if contas_detalhe:
            t_ant   = round(sum(c['saldo_ant']   for c in contas_detalhe), 2)
            t_atual = round(sum(c['saldo_atual']  for c in contas_detalhe), 2)
            # Distribui créditos/débitos: conta com 'Inter' recebe os créditos totais
            # Conta Corrente: saldo_ant=0 geralmente, seus débitos = |saldo_atual| se negativo
            _has_inter = any('inter' in c['nome'].lower() for c in contas_detalhe)
            _has_cc    = any('corrente' in c['nome'].lower() for c in contas_detalhe)
            if _has_inter and _has_cc:
                for c in contas_detalhe:
                    if 'inter' in c['nome'].lower():
                        c['creditos'] = round(t_cred, 2)
                        c['debitos']  = round(c['saldo_ant'] + t_cred - c['saldo_atual'], 2)
                    else:
                        c['creditos'] = 0.0
                        c['debitos']  = round(abs(c['saldo_atual'] - c['saldo_ant']), 2)
            elif contas_detalhe:
                # Conta única: todos os fluxos nela
                contas_detalhe[0]['creditos'] = round(t_cred, 2)
                contas_detalhe[0]['debitos']  = round(t_deb, 2)
        else:
            t_ant   = 0.0
            t_atual = 0.0
            contas_detalhe = [{'nome': 'Banco Inter Empresas',
                                'saldo_ant': 0.0, 'creditos': round(t_cred, 2),
                                'debitos': round(t_deb, 2), 'saldo_atual': round(t_cred - t_deb, 2)}]

        # Seção de despesas (após "Total Receitas")
        m_rec = re.search(r'Total Receitas\s*:', texto)
        texto_desp = texto[m_rec.end():] if m_rec else texto

        def find_d(pattern):
            m = re.search(pattern, texto_desp)
            return _br(m.group(1)) if m else 0.0

        mensais    = find_d(r'Total Mensais\s*:\s*R\$\s*([\d.,]+)')
        manutencao = find_d(r'Total Manutenção\s*:\s*R\$\s*([\d.,]+)')
        serv_terc  = find_d(r'Serviços Terceirizados\s+R\$\s*([\d.,]+)')
        sindico    = find_d(r'Síndico\(a\) Profissional\s+R\$\s*([\d.,]+)')
        if sindico == 0.0:
            sindico = find_d(r'Ajuda de custos\s*-\s*Síndico\(a\)\s+R\$\s*([\d.,]+)')
        escritorio = find_d(r'Escritório Jurídico\s+R\$\s*([\d.,]+)')
        diversas = round(t_deb - mensais - manutencao - serv_terc - sindico - escritorio, 2)
        if diversas < 0:
            diversas = 0.0

        cats: dict = {}
        if mensais:    cats['Mensais']               = round(mensais, 2)
        if manutencao: cats['Manutenção']             = round(manutencao, 2)
        if serv_terc:  cats['Serv. Terceirizados']    = round(serv_terc, 2)
        if sindico:    cats['Síndico(a) Profissional']= round(sindico, 2)
        if escritorio: cats['Escritório Jurídico']    = round(escritorio, 2)
        if diversas > 0: cats['Diversas']             = diversas

        return DadosFinanceiros(
            condominio_id='saint_simon',
            mes_referencia=mes_referencia,
            receita_prevista=round(t_cred, 2),
            receita_realizada=round(t_cred, 2),
            despesa_total=round(t_deb, 2),
            saldo_anterior=round(t_ant, 2),
            saldo_atual=round(t_atual, 2),
            inadimplencia_valor=0.0,
            inadimplencia_recebida=0.0,
            banco_cc=round(t_atual, 2),
            banco_cdb=0.0,
            banco_priv=0.0,
            categorias_despesa=cats,
            contas_detalhe=contas_detalhe,
        )
