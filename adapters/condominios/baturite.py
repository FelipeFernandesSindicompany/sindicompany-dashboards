"""
Adapter específico para Baturité.

Empresa gestora mudou de "habitacional_xlsx" (planilha) para "lirba_pdf"
(ContasData) a partir de 2026 — confirmado em dados reais: a pasta de
projeto só tem arquivos ".xlsx" até 2025 e só ".pdf" a partir de 2026. O
adapter genérico adapters/lirba_pdf.py não reconhece a estrutura exata
deste condomínio (testado contra dados reais: retorna tudo zerado), então
este override lê diretamente a seção "RESUMO FINANCEIRO CONTABIL" (tabela
limpa com saldo anterior/créditos/débitos/saldo atual por conta + linha
TOTAL) e a "Posição Financeira" da conta ORDINÁRIA (para as categorias de
despesa) — confirmado que os números batem exatamente com jul/2026 já
publicado no dashboard.
"""
import re
from pathlib import Path

from adapters.base import AdapterBase, DadosFinanceiros

_RE_LINHA_RESUMO = re.compile(
    r'^(.+?)\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})\s*$'
)
_RE_EMISSOES_TOTAL = re.compile(r'^([\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$')


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = str(s).strip()
    negativo = s.startswith("-")
    s = re.sub(r"[^\d,.]", "", s)
    s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except Exception:
        return 0.0
    return -v if negativo else v


class Adapter(AdapterBase):
    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        import pdfplumber

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        with pdfplumber.open(str(caminho)) as pdf:
            textos = [p.extract_text() or "" for p in pdf.pages]
        texto_total = "\n".join(textos)
        linhas = texto_total.split("\n")

        # ── 1. RESUMO FINANCEIRO CONTABIL — uma linha por conta + TOTAL ──────
        dentro_resumo = False
        for linha in linhas:
            l = linha.strip()
            # A mesma frase aparece no Índice (com só o nº da página depois,
            # ex.: "RESUMO FINANCEIRO CONTABIL 6") — só considera o início
            # de verdade quando vem seguida do cabeçalho da tabela.
            if re.match(r'^RESUMO FINANCEIRO CONTABIL\s+Saldo\b', l, re.IGNORECASE):
                dentro_resumo = True
                continue
            if not dentro_resumo:
                continue
            if l.upper().startswith("VOLTAR AO"):
                # A tabela às vezes quebra no meio, entre páginas — o
                # cabeçalho se repete na página seguinte (ver regex acima),
                # então só pausa aqui, não encerra de vez.
                dentro_resumo = False
                continue
            m = _RE_LINHA_RESUMO.match(l)
            if not m:
                continue
            nome, saldo_ant, creditos, debitos, saldo_atual = m.groups()
            if nome.strip().upper() == "TOTAL":
                dados.saldo_anterior = _num(saldo_ant)
                dados.receita_realizada = _num(creditos)
                dados.despesa_total = _num(debitos)
                dados.saldo_atual = _num(saldo_atual)
                dentro_resumo = False
                continue
            dados.contas_detalhe.append({
                "nome": nome.strip(),
                "nome_curto": nome.strip(),
                "saldo_ant": _num(saldo_ant),
                "creditos": _num(creditos),
                "debitos": _num(debitos),
                "saldo_atual": _num(saldo_atual),
            })

        # ── 2. Classificação bancária ─────────────────────────────────────
        # cc = ORDINÁRIA, cdb = FUNDO DE RESERVA, priv = todas as demais
        # contas (Obras/Melhorias + Aplicações) — mesma convenção usada em
        # outros condomínios ContasData (ex.: Padre Carvalho).
        for conta in dados.contas_detalhe:
            n = conta["nome"].upper()
            sa = conta["saldo_atual"]
            if "ORDIN" in n:
                dados.banco_cc = sa
            elif "FUNDO DE RESERVA" in n:
                dados.banco_cdb = sa
            else:
                dados.banco_priv += sa

        # ── 3. Previsto/Realizado — "Resumo de Emissões Colunado" da ORDINÁRIA ──
        # Primeira linha só com 2 números isolados logo após o cabeçalho da
        # conta ORDINÁRIA é o total (previsto realizado) daquela seção.
        dentro_ordinaria = False
        aguardando_total_emissao = False
        for linha in linhas:
            l = linha.strip()
            if l.upper() == "ORDINÁRIA" or l.upper() == "ORDINARIA":
                dentro_ordinaria = True
                continue
            if not dentro_ordinaria:
                continue
            if re.search(r"Resumo de Emissões Colunado", l, re.IGNORECASE):
                aguardando_total_emissao = True
                continue
            if aguardando_total_emissao:
                m = _RE_EMISSOES_TOTAL.match(l)
                if m:
                    dados.receita_prevista = _num(m.group(1))
                    # "realizado" da própria emissão da ORDINÁRIA (não o
                    # crédito total da conta, que inclui receitas diversas/
                    # antecipações de outros meses) — mesmo campo "real" que
                    # o dashboard já usava antes da mudança de formato.
                    dados.receita_cotas = _num(m.group(2))
                    aguardando_total_emissao = False
                continue
            if l.upper().startswith("POSIÇÃO FINANCEIRA") or l.upper().startswith("POSICAO FINANCEIRA"):
                break

        # ── 4. Despesas por categoria — Posição Financeira (lado Crédito) da ORDINÁRIA ──
        # Da linha "DESPESAS <valor>" (marca o início do detalhamento) até
        # "TOTAIS <débito> <crédito>" (fecha a seção).
        dentro_ordinaria = False
        dentro_despesas_detalhe = False
        for linha in linhas:
            l = linha.strip()
            if l.upper() in ("ORDINÁRIA", "ORDINARIA"):
                dentro_ordinaria = True
                continue
            if not dentro_ordinaria:
                continue
            if l.upper().startswith("TOTAIS"):
                break
            if re.match(r'^DESPESAS\s+[\d.]+,\d{2}$', l, re.IGNORECASE):
                dentro_despesas_detalhe = True
                continue
            if not dentro_despesas_detalhe:
                continue
            m = re.match(r'^(.+?)\s+([\d.]+,\d{2})$', l)
            if m and m.group(1).strip().upper() != "CONTASDATA":
                categoria = m.group(1).strip()
                if categoria.upper() == "CONTASDATA":
                    continue
                dados.categorias_despesa[categoria] = (
                    dados.categorias_despesa.get(categoria, 0.0) + _num(m.group(2))
                )

        # ── 5. Inadimplência — "RELATORIO DE COTAS EM ABERTO" ────────────────
        if "NÃO HÁ DEVEDORES" in texto_total.upper() or "NAO HA DEVEDORES" in texto_total.upper():
            dados.inadimplencia_valor = 0.0
        else:
            m_total_geral = re.search(r"Total geral:\s*([\d.]+,\d{2})", texto_total, re.IGNORECASE)
            if m_total_geral:
                dados.inadimplencia_valor = _num(m_total_geral.group(1))

        dados.total_unidades = self.config.get("unidades", 0)
        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """A partir de 2026 a pasta de Baturité só vem em PDF — mantém
        compatibilidade com meses antigos (.xlsx) redirecionando pro
        adapter genérico usado até então."""
        from adapters.habitacional_xlsx import AdapterHabitacionalXLSX
        return AdapterHabitacionalXLSX(self.config).ler_xlsx(caminho, mes_referencia)
