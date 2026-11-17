"""
Adapter específico para Port Saint Tropez.

Empresa gestora migrou de "habitacional_xlsx" (planilha) para PDF ContasData
em algum mês entre a última planilha conhecida e março/2026 — mesma migração
já vista em Baturité (ver adapters/condominios/baturite.py), confirmado em
dados reais: a pasta de conciliação de 2026-03 só tem PDF ("ContasData",
"Comprovante de Despesa", "Resumo Financeiro Contábil").

Diferente de Baturité, porém, a seção "Posição Financeira" da conta
ORDINÁRIA aqui intercala Débito e Crédito na MESMA lista de linhas (sem um
marcador de texto tipo "DESPESAS <valor>" separando os dois lados) —
confirmado em dados reais que a extração de texto simples (extract_text())
non consegue distinguir "PESSOAL 21.129,19" (despesa/débito) de
"ANTECIPAÇÕES 13.626,00" (receita/crédito) só pela ordem das linhas. Por
isso as categorias de despesa são lidas via posição X da palavra
(extract_words(), não extract_text()) — valores à esquerda (x0 < 500, perto
do cabeçalho "Débito") são despesa, à direita (x0 >= 500, perto de
"Crédito") são receita e descartados.

Todos os campos abaixo foram validados batendo exatamente com os dados já
publicados no dashboard (docs/Dashboard_Financeiro_PortSaintTropez.html,
mês mar26): tAnt/tCred/tDeb/tAtual, contas[], prev/real, inad, banco e desp[].
"""
import re
from pathlib import Path

from adapters.base import AdapterBase, DadosFinanceiros

_RE_LINHA_RESUMO = re.compile(
    r'^(.+?)\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})\s*$'
)
_RE_EMISSOES_TOTAL = re.compile(r'^([\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$')
_RE_ATRASO = re.compile(r'^CONDOMINOS EM ATRASO EM\s+(\d{2}/\d{2}/\d{4})\s+([\d.]+,\d{2})\s*$', re.IGNORECASE)
_RE_VALOR_BRUTO = re.compile(r'[\d.]+,\d{2}')
# Débito fica em torno de x0≈449–465, Crédito em x0≈524–543 (confirmado nas
# coordenadas reais da tabela "Posição Financeira" da ORDINÁRIA) — qualquer
# limiar entre os dois grupos serve; usa 500 por estar bem no meio.
_LIMITE_X_DEBITO = 500.0


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

            # ── 1. Resumo Financeiro Contábil — uma linha por conta + TOTAL ──
            dentro_resumo = False
            for linha in linhas:
                l = linha.strip()
                if re.match(r'^Resumo Financeiro Cont\S*bil\s+Saldo\b', l, re.IGNORECASE):
                    dentro_resumo = True
                    continue
                if not dentro_resumo:
                    continue
                if l.upper().startswith("DEMONSTRATIVO CONCILIA"):
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

            # ── 2. Demonstrativo Conciliação Bancária — saldo bancário real ──
            # (confirmado em dados reais: cc=Conta Corrente, priv=Aplicação
            # Privilege; não há linha de CDB/Fundo de Reserva nesta seção —
            # fica em 0, igual ao já publicado no dashboard).
            # A conta corrente vem seguida do número da conta (ex.: "0452/50.013-5")
            # ANTES do saldo — ".*?" não-guloso pula esse número (que não
            # forma um "X,XX" válido) e pega o primeiro valor que forma.
            m_cc = re.search(r'SALDO BANCO ITA\S*\s*-\s*CONTA CORRENTE.*?([\d.]+,\d{2})', texto_total, re.IGNORECASE)
            if m_cc:
                dados.banco_cc = _num(m_cc.group(1))
            m_priv = re.search(r'SALDO BANCO ITA\S*\s*-\s*APLICA\S*O PRIVILEGE.*?([\d.]+,\d{2})', texto_total, re.IGNORECASE)
            if m_priv:
                dados.banco_priv = _num(m_priv.group(1))

            # ── 3. Previsto/Realizado + Inadimplência — só a conta ORDINÁRIA ──
            # (confirmado em dados reais: os dois batem com o total da seção
            # "Resumo de Emissões Colunado" e a última "CONDOMINOS EM ATRASO
            # EM <fim do mês>" da ORDINÁRIA, não a soma de todas as contas).
            dentro_ordinaria = False
            atraso_visto = 0
            for linha in linhas:
                l = linha.strip()
                if l.upper() in ("ORDINÁRIA", "ORDINARIA"):
                    dentro_ordinaria = True
                    atraso_visto = 0
                    continue
                if not dentro_ordinaria:
                    continue
                if l.upper().startswith("POSIÇÃO FINANCEIRA") or l.upper().startswith("POSICAO FINANCEIRA"):
                    dentro_ordinaria = False
                    continue
                m_emissao = _RE_EMISSOES_TOTAL.match(l)
                if m_emissao:
                    dados.receita_prevista = _num(m_emissao.group(1))
                    dados.receita_cotas = _num(m_emissao.group(2))
                    # real = Realizado da ORDINÁRIA (não o TOTAL GERAL de todas as contas)
                    dados.receita_realizada = _num(m_emissao.group(2))
                    continue
                m_atraso = _RE_ATRASO.match(l)
                if m_atraso:
                    # A 1ª ocorrência é o saldo de ABERTURA (mês anterior) —
                    # só a partir da 2ª (fechamento deste mês) é que atualiza.
                    atraso_visto += 1
                    if atraso_visto >= 2:
                        dados.inadimplencia_valor = _num(m_atraso.group(2))

        # ── 4. Despesas por categoria — só o lado Débito da Posição
        #      Financeira da ORDINÁRIA, via posição X da palavra (não dá pra
        #      confiar na ordem do texto puro — ver docstring do módulo) ──
        self._extrair_despesas_ordinaria(paginas_pdf=caminho, dados=dados)

        # tDesp = soma dos débitos da ORDINÁRIA (não o TOTAL DAS DESPESAS de todas as contas)
        if dados.categorias_despesa:
            dados.despesa_total = sum(dados.categorias_despesa.values())

        dados.total_unidades = self.config.get("unidades", 0)
        return dados

    def _extrair_despesas_ordinaria(self, paginas_pdf: Path, dados: DadosFinanceiros) -> None:
        import pdfplumber

        with pdfplumber.open(str(paginas_pdf)) as pdf:
            for page in pdf.pages:
                palavras = page.extract_words()
                if not palavras:
                    continue
                # Localiza o cabeçalho "ORDINÁRIA" (nome de conta sozinho na
                # linha) seguido de "Posição Financeira ... Débito Crédito"
                # e "TOTAIS" nesta MESMA página — delimita a tabela a extrair.
                top_ordinaria = None
                top_posicao = None
                top_totais = None
                for w in palavras:
                    texto = w["text"]
                    if texto.upper() in ("ORDINÁRIA", "ORDINARIA") and top_ordinaria is None:
                        top_ordinaria = w["top"]
                    elif texto in ("Posição", "Posicao") and top_ordinaria is not None and top_posicao is None:
                        top_posicao = w["top"]
                    elif texto.upper() == "TOTAIS" and top_posicao is not None and top_totais is None:
                        top_totais = w["top"]
                if top_posicao is None or top_totais is None:
                    continue

                from collections import defaultdict
                por_linha = defaultdict(list)
                for w in palavras:
                    if top_posicao < w["top"] < top_totais:
                        por_linha[round(w["top"])].append(w)

                for top in sorted(por_linha):
                    ws = sorted(por_linha[top], key=lambda w: w["x0"])
                    rotulo_partes = []
                    valor_debito = None
                    for w in ws:
                        if _RE_VALOR_BRUTO.fullmatch(w["text"]):
                            if w["x0"] < _LIMITE_X_DEBITO:
                                valor_debito = w["text"]
                            break
                        rotulo_partes.append(w["text"])
                    if valor_debito is None:
                        continue
                    categoria = " ".join(rotulo_partes).strip()
                    if not categoria or categoria.upper().startswith("SALDO"):
                        continue
                    dados.categorias_despesa[categoria] = (
                        dados.categorias_despesa.get(categoria, 0.0) + _num(valor_debito)
                    )
                return  # achou e processou a página da ORDINÁRIA — encerra

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """Mantém compatibilidade com meses antigos (.xlsx), de antes da
        migração pra PDF — redireciona pro adapter genérico usado até então."""
        from adapters.habitacional_xlsx import AdapterHabitacionalXLSX
        return AdapterHabitacionalXLSX(self.config).ler_xlsx(caminho, mes_referencia)
