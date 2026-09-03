"""
Adapter para Saint Simon — formato Conviver MRV (1-2 páginas).
Receitas: "Total Receitas : R$ X"
Despesas por grupo: "Total Mensais : R$ X", "Total Manutenção : R$ X"
Itens diretos: "Serviços Terceirizados R$ X", "Síndico(a) ..."
Saldos: "NNN - Conta R$ ant R$ atual"
"""
import re
import pdfplumber
from adapters.base import AdapterBase, DadosFinanceiros
from pathlib import Path
from typing import Optional


def _br(s: str) -> float:
    """Converte número em formato BR para float."""
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
        t_deb = find(r'Total Despesas\s*:\s*R\$\s*([\d.,]+)')

        # Saldo da conta com saldo real (não-zero)
        t_ant = 0.0
        t_atual = 0.0
        conta_nome = 'Banco Inter Empresas'
        for m in re.finditer(
            r'\d{3}\s+-\s+([^\n]+?)\s+R\$\s*([\d.,]+)\s+R\$\s*([\d.,]+)',
            texto
        ):
            v_ant = _br(m.group(2))
            v_atual = _br(m.group(3))
            if v_ant != 0.0 or v_atual != 0.0:
                conta_nome = m.group(1).strip()
                t_ant = v_ant
                t_atual = v_atual
                break

        # Seção de despesas (após "Total Receitas")
        m_rec = re.search(r'Total Receitas\s*:', texto)
        texto_desp = texto[m_rec.end():] if m_rec else texto

        def find_d(pattern):
            m = re.search(pattern, texto_desp)
            return _br(m.group(1)) if m else 0.0

        mensais = find_d(r'Total Mensais\s*:\s*R\$\s*([\d.,]+)')
        manutencao = find_d(r'Total Manutenção\s*:\s*R\$\s*([\d.,]+)')

        # Serviços Terceirizados: linha direta (não é "Total ...")
        serv_terc = find_d(r'Serviços Terceirizados\s+R\$\s*([\d.,]+)')

        # Síndico — múltiplos padrões possíveis
        sindico = find_d(r'Síndico\(a\) Profissional\s+R\$\s*([\d.,]+)')
        if sindico == 0.0:
            sindico = find_d(r'Ajuda de custos\s*-\s*Síndico\(a\)\s+R\$\s*([\d.,]+)')

        escritorio = find_d(r'Escritório Jurídico\s+R\$\s*([\d.,]+)')

        diversas = round(
            t_deb - mensais - manutencao - serv_terc - sindico - escritorio, 2
        )
        if diversas < 0:
            diversas = 0.0

        cats: dict = {}
        if mensais: cats['Mensais'] = round(mensais, 2)
        if manutencao: cats['Manutenção'] = round(manutencao, 2)
        if serv_terc: cats['Serv. Terceirizados'] = round(serv_terc, 2)
        if sindico: cats['Síndico(a) Profissional'] = round(sindico, 2)
        if escritorio: cats['Escritório Jurídico'] = round(escritorio, 2)
        if diversas > 0: cats['Diversas'] = diversas

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
            contas_detalhe=[{
                'nome': conta_nome,
                'saldo_ant': round(t_ant, 2),
                'creditos': round(t_cred, 2),
                'debitos': round(t_deb, 2),
                'saldo_atual': round(t_atual, 2),
            }],
        )
