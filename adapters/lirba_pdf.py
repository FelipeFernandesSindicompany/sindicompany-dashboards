"""
Adapter LIRBA PDF — Prestação de Contas MM.YYYY.PDF (formato LIRBA administradora)

Dois sub-formatos detectados:

──────────────────────────────────────────────────────────────────
SUB-FORMATO A — Lirba (software próprio Lirba)
Exemplos: Gravura Residencial (355 pgs), Blue Sky (344 pgs)

  Pág 2: ÍNDICE — contém nomes de todas as seções (armadilha para
         detecção por keyword); NÃO tem "Período:"

  Pág 4-14 (Gravura) / Pág 18-19 (Blue Sky): "Resumo de Emissões"
    Lirba antigo: "Receita Prevista / Receita Realizada" com total por linha
    Lirba Blue Sky: "Resumo de Emissões Colunado  Previsto  Realizado"

  Pág 15 (Gravura) / Pág 304 (Blue Sky): "Resumo Financeiro Contábil"
    Header: "Resumo Financeiro Contábil Saldo anterior Créditos Débitos Saldo atual"
    Linhas de conta: NOME  saldo_ant  creditos  debitos  saldo_atual
    Linha TOTAL:     TOTAL  saldo_ant  creditos  debitos  saldo_atual
    Após TOTAL (Gravura): "FUNDO DE INVESTIMENTO - ITAU PRIVILEGE RF REF DI  123.328,60"

  Pág 22-24 (Gravura) / Pág 36-38 (Blue Sky): "Demonstrativo de Despesas"
    Fim de cada conta: "TOTAL DA CONTA NOME  valor"
    Contas a excluir das despesas: ORDINARIA, MELHORAMENTOS/BENFEITORIAS,
      FUNDO DE RESERVA, SALAO FESTAS, FUNDO EMERGENCIAL, FUNDO OBRAS, etc.

  Pág 350 (Gravura) / Pág 320 (Blue Sky): "RELAÇÃO DE COTAS EM ABERTO"
    "Total da unidade: 3.342,28" por devedor
    "Total geral: 19.089,92" no final de todos os devedores

  Detecção robusta: páginas com dados reais têm "Período: dd/mm/YYYY"
  O índice (pág 2) tem os nomes das seções mas SEM "Período:" → ignorado

──────────────────────────────────────────────────────────────────
SUB-FORMATO B — Webware (NYC Berrini, software Webware)
Exemplos: NYC Berrini (44 pgs)

  Pág 1: "Demonstrações Por Conta" — Resumo de Emissão (Previsto/Realizado)
    "COTAS EM ATRASO EM 31/03/2026  45.945,98  5.990,84"
    Total previsto / realizado nas linhas de subtotais
    "COTAS EM ATRASO EM 30/04/2026  47.174,43"  ← inadimplência do período

  Pág 4-5: Posição Financeira de cada conta + "Resumo Financeiro Contábil"
    Header: "Conta Saldo Anterior Créditos Débitos Saldo Atual"  ← tem "Conta"
    Linhas: NOME  saldo_ant  creditos  debitos  saldo_atual
    Linha TOTAL: "TOTAL  saldo_ant  creditos  debitos  saldo_atual"
    Conciliação bancária logo abaixo com valores por banco

  Pág 38-44: "Demonstrativo de Despesas" com "TOTAL DA CONTA NOME  valor  pct%"
    Último "TOTAL DA CONTA NOME" fecha a última conta (ORDINARIA)

──────────────────────────────────────────────────────────────────
Condomínios: Gravura Residencial, Gravura Studio, Highlights, Organy Residencial,
             Organy Studio, Padre Carvalho, Praça Saúde, Residencial Napoleão,
             Saint Afonso, Serra da Mantiqueira, Upper Itaim, Vibra Butantã,
             Villa Sardenha, Reserva Verde, Top Nine, Blue Sky, Club Park Butantã,
             I-Gloo, Monte Tabor, Palm Beach, Plano & Mooca,
             Plano Estação Campo Limpo, Plano Rio Bonito, Platinum, Patrícia,
             NYC Berrini (Webware)
"""
from pathlib import Path
import re
import unicodedata
from adapters.base import AdapterBase, DadosFinanceiros

# Contas que são fundos/reservas e NÃO devem entrar como categorias de despesa
# quando existem sub-categorias dentro delas (ex: Blue Sky tem SALÁRIOS dentro de ORDINÁRIA)
_CONTAS_AGREGADO = {
    "ORDINARIA", "ORDINÁRIA",
}

# Contas que são exclusivamente fundos/reservas e nunca entram como despesa operacional
_EXCLUIR_SEMPRE = {
    "FUNDO DE RESERVA", "FUNDO RESERVA",
    "FUNDO EMERGENCIAL",
    "FUNDO DE OBRAS", "FUNDO OBRAS",
    "FUNDO TRABALHISTA",
    "FUNDO 13O SALARIO", "FUNDO 13o SALARIO",
    "LOCACOES", "LOCAÇÕES",
    "INDIVIDUALIZAÇÃO", "INDIVIDUALIZACAO",
}

# Contas que são conta corrente / aplicação / CDB
_CONTAS_CC   = {"ORDINARIA", "ORDINÁRIA"}
_CONTAS_CDB  = {
    "FUNDO DE RESERVA", "FUNDO RESERVA",
    "CDB", "POUPANÇA", "POUPANCA",
    "APLICAÇÃO", "APLICACAO",
    "INVESTIMENTO", "FUNDO DE OBRAS",
    "FUNDO EMERGENCIAL", "FUNDO TRABALHISTA",
}


def _num(s) -> float:
    """Converte string monetária BR (1.234,56) para float, ignorando sinal."""
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return abs(float(s))
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


def _num_signed(s) -> float:
    """Converte string monetária BR (1.234,56 ou -1.234,56) para float, preservando sinal."""
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    negativo = str(s).strip().startswith('-')
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    # remove possível sinal extra após limpeza
    s = s.lstrip('-')
    try:
        v = float(s)
        return -v if negativo else v
    except Exception:
        return 0.0


def _e_pagina_dados(txt: str) -> bool:
    """Retorna True se a página tem dados reais (não é o índice)."""
    return bool(re.search(r"Per[íi]odo:\s*\d{2}/\d{2}/\d{4}", txt))


def _e_webware(textos: list) -> bool:
    """Detecta sub-formato Webware (NYC Berrini) pela presença do URL Webware."""
    for t in textos[:3]:
        if "webware.com.br" in t or "Webware" in t:
            return True
    return False


class AdapterLirbaPDF(AdapterBase):
    """
    Adapter para PDFs da administradora LIRBA (dois sub-formatos:
    Lirba e Webware). Implementa ler_pdf(); ler_xlsx() redireciona
    para ler_pdf() ao encontrar um PDF correspondente.
    """

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
            total_unidades=self.config.get("unidades", 0),
        )

        with pdfplumber.open(str(caminho)) as pdf:
            textos = [p.extract_text() or "" for p in pdf.pages]

        texto_completo = "\n".join(textos)

        if _e_webware(textos):
            self._parsear_webware(textos, texto_completo, dados)
        else:
            self._parsear_lirba(textos, texto_completo, dados)

        # Calcula inadimplência percentual
        if dados.receita_realizada > 0 and dados.inadimplencia_valor > 0:
            dados.inadimplencia_percentual = round(
                dados.inadimplencia_valor / dados.receita_realizada * 100, 2
            )

        return dados

    # ──────────────────────────────────────────────────────────────────────────
    # SUB-FORMATO A — Lirba
    # ──────────────────────────────────────────────────────────────────────────

    def _parsear_lirba(self, textos: list, texto_completo: str, dados: DadosFinanceiros):
        """Extrai dados do formato Lirba (Gravura, Blue Sky, etc.)."""

        # ── 1. Resumo Financeiro Contábil ──────────────────────────────────────
        # A página real tem "Período:" (o índice na pág 2 não tem)
        for txt in textos:
            if "Resumo Financeiro" not in txt:
                continue
            if not _e_pagina_dados(txt):
                continue  # Índice — ignora

            # Extrai cada linha de conta: "NOME  num  num  num  num"
            # A linha TOTAL termina o bloco
            linhas = txt.split("\n")
            in_resumo = False
            for linha in linhas:
                l = linha.strip()
                if "Resumo Financeiro" in l and "Saldo" in l:
                    in_resumo = True
                    continue
                if not in_resumo:
                    continue

                # Busca 4 números consecutivos na linha (podem ter sinal negativo)
                nums_raw = re.findall(r"-?[\d.,]{1,}[\d]", l)
                nums_f = []
                for n in nums_raw:
                    try:
                        v = _num(n)
                        nums_f.append(v)
                    except Exception:
                        pass

                if len(nums_f) < 4:
                    continue

                nome = re.sub(r"[\s\d.,\-]+$", "", l).strip().upper()
                if not nome:
                    continue

                # Saldo atual preserva sinal (conta corrente pode ser negativa)
                sa, cr, db = nums_f[0], nums_f[1], nums_f[2]
                sal = _num_signed(nums_raw[3]) if len(nums_raw) >= 4 else nums_f[3]

                if nome.startswith("TOTAL"):
                    dados.saldo_anterior    = sa
                    dados.receita_realizada = cr
                    dados.despesa_total     = db
                    dados.saldo_atual       = abs(sal)  # total sempre positivo
                    in_resumo = False
                    break

                dados.contas_detalhe.append({
                    "nome":       nome,
                    "saldo_ant":  sa,
                    "creditos":   cr,
                    "debitos":    db,
                    "saldo_atual": sal,  # com sinal: conta corrente pode ser negativa
                })

            # CDB externo: linha como "FUNDO DE INVESTIMENTO - ITAU ... 123.328,60"
            for linha in linhas:
                if re.search(r"(APLICA[ÇC][AÃ]O|INVESTIMENTO|PRIVILEGE|FUNDO.+INV)",
                             linha, re.IGNORECASE):
                    nums = re.findall(r"[\d.,]{6,}", linha)
                    if nums:
                        val = _num(nums[-1])
                        if val > 0 and dados.banco_cdb == 0:
                            dados.banco_cdb = val
            break  # Lirba: só há uma página de Resumo Financeiro real

        # ── Banco: tenta "Conta Bancária" primeiro, fallback no Resumo Contábil ──
        conta_banc = self._extrair_conta_bancaria(textos)
        if conta_banc:
            # "Conta Bancária" é a fonte mais precisa — saldos reais de banco
            account_list = list(conta_banc.items())
            if len(account_list) == 1:
                saldo = account_list[0][1]
                dados.banco_cc   = saldo if saldo > 0 else 0.0
                dados.banco_cdb  = 0.0
                dados.banco_priv = 0.0
            elif len(account_list) >= 2:
                dados.banco_cc   = account_list[0][1]
                dados.banco_cdb  = account_list[1][1]
                dados.banco_priv = round(
                    sum(v for _, v in account_list[2:]), 2
                ) if len(account_list) > 2 else 0.0
        else:
            # Fallback: classifica a partir do Resumo Financeiro Contábil
            # (inclui contas negativas na soma de banco_priv para não inflar)
            dados.banco_cc = dados.banco_cdb = dados.banco_priv = 0.0
            positivos_priv: list = []
            negativos_priv: list = []
            for conta in dados.contas_detalhe:
                nome_fold = "".join(
                    c for c in unicodedata.normalize("NFD", conta["nome"])
                    if unicodedata.category(c) != "Mn"
                ).upper()
                sal_real = conta["saldo_atual"]  # mantém sinal
                if "ORDINARI" in nome_fold:
                    dados.banco_cc = sal_real
                elif any(kw in nome_fold for kw in (
                    "FUNDO DE RESERVA", "FUNDO RESERVA",
                    "CDB", "APLICA", "INVESTIMENTO",
                )):
                    dados.banco_cdb += sal_real
                else:
                    if sal_real < 0:
                        negativos_priv.append(sal_real)
                    else:
                        positivos_priv.append(sal_real)
            dados.banco_priv = round(
                sum(positivos_priv) + sum(negativos_priv), 2
            )

        # ── 2. Receita Prevista ─────────────────────────────────────────────────
        # Lirba antigo (Gravura): seção "Receita Prevista" por conta com:
        #   "RECEBIMENTO DO PERIODO  previsto  total_previsto_com_atrasos"
        #   A soma dos "total_previsto_com_atrasos" de todas as contas = receita prevista
        #
        # Lirba novo (Blue Sky): "Resumo de Emissões Colunado  Previsto  Realizado"
        #   Linha de sub-total: "CONDOMINIO  previsto  realizado"
        #   Linha de total:     "valor_previsto_total  valor_realizado_total"  (dois nums)
        #
        # Estratégia: coleta o "RECEBIMENTO DO PERIODO X Y" da seção Receita Prevista,
        # onde Y é o total previsto (inclui atrasos). Soma de todos = receita_prevista.
        # Se não encontrar, usa a linha de total "X Y" dentro da seção.
        previsto_total = 0.0

        # Tenta padrão Lirba antigo: "RECEBIMENTO DO PERIODO  X  Y" em seção Receita Prevista
        in_prev = False
        for linha in texto_completo.split("\n"):
            l = linha.strip()
            if re.match(r"Receita Prevista$", l, re.IGNORECASE):
                in_prev = True
                continue
            if re.match(r"Receita Realizada", l, re.IGNORECASE):
                in_prev = False
                continue
            if not in_prev:
                continue
            # "RECEBIMENTO DO PERIODO  X  Y" ou "RECEBIMENTO CONSUMO - AGUA  X  Y"
            m = re.match(r"^RECEBIMENTO.+?\s+([\d.,]+)\s+([\d.,]+)\s*$", l, re.IGNORECASE)
            if m:
                v2 = _num(m.group(2))
                if v2 > 0:
                    previsto_total += v2
                    in_prev = False

        # Tenta padrão Blue Sky: linha de total "X Y" dentro de seção de emissão colunada
        # A primeira ocorrência de dois números grandes sozinhos em seção colunada
        if previsto_total == 0.0:
            in_col = False
            for linha in texto_completo.split("\n"):
                l = linha.strip()
                if re.search(r"Resumo de Emiss[oõ]es Colunado", l, re.IGNORECASE):
                    in_col = True
                    continue
                if not in_col:
                    continue
                m = re.match(r"^([\d.,]+)\s+([\d.,]+)$", l)
                if m:
                    v1 = _num(m.group(1))
                    if v1 > 1000:
                        previsto_total += v1
                    in_col = False
                # Reset se sair da seção
                if re.match(r"(Posi[çc][ãa]o Financeira|SALDO ANTERIOR)", l, re.IGNORECASE):
                    in_col = False

        if previsto_total > 0:
            dados.receita_prevista = previsto_total
        else:
            dados.receita_prevista = dados.receita_realizada  # último fallback

        # ── 3. Despesas por categoria ───────────────────────────────────────────
        # "TOTAL DA CONTA NOME  valor"
        # Lirba antigo (Gravura): as contas de nível alto são as categorias
        #   (MELHORAMENTOS, BENFEITORIAS, CONSUMO etc.)
        # Lirba novo (Blue Sky): há sub-contas DENTRO de ORDINÁRIA
        #   (SALÁRIOS, SERVIÇOS TERCEIRIZADOS etc.) e ORDINÁRIA é o agregado
        # Lirba Vibra/padrão novo: sub-categorias estão na POSIÇÃO FINANCEIRA de
        #   ORDINÁRIA (linhas após MULTAS e antes de TOTAIS), não no Demonstrativo
        #
        # Estratégia:
        #   1. Tenta "Posição Financeira ORDINÁRIA" — extrai sub-categorias direto do
        #      resumo da conta (mais confiável, valores corretos)
        #   2. Coleta "TOTAL DA CONTA" para contas de nível alto (CONSUMO, IPTU etc.)
        #   3. Fallback clássico: se nenhuma sub-categoria da Posição Financeira,
        #      usa extração por "TOTAL DA CONTA" (Blue Sky, Gravura etc.)

        # ── 3a. Posição Financeira ORDINÁRIA → sub-categorias de despesa ──────────
        posicao_cats = self._extrair_subcats_posicao_financeira(textos)

        # ── 3b. TOTAL DA CONTA → contas de nível alto (CONSUMO, IPTU, etc.) ───────
        todos_totais = {}  # conta_upper -> valor
        for m in re.finditer(
            r"TOTAL DA CONTA\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ /\-\.0-9]+?)\s+([\d.,]+)(?:\s|$)",
            texto_completo, re.IGNORECASE
        ):
            conta = m.group(1).strip().upper()
            val   = _num(m.group(2))
            if val > 0:
                todos_totais[conta] = todos_totais.get(conta, 0) + val

        # Separa: excluídas sempre, agregados (ORDINÁRIA), operacionais
        operacionais = {}
        val_ordinaria = 0.0
        for conta, val in todos_totais.items():
            if any(ex in conta for ex in _EXCLUIR_SEMPRE):
                continue
            if any(ag == conta for ag in _CONTAS_AGREGADO):
                val_ordinaria = val
                continue
            operacionais[conta] = val

        # ── 3c. Combina fontes ────────────────────────────────────────────────────
        if posicao_cats:
            # Sub-categorias da Posição Financeira + contas de nível alto
            # (CONSUMO, IPTU) que não são sub-categorias de ORDINÁRIA
            # Mapeamento canônico para contas de nível alto
            _conta_canonical = {
                "CONSUMO": "Consumos", "CONSUMOS": "Consumos",
                "I.P.T.U.": "IPTU", "IPTU": "IPTU",
                "I P T U": "IPTU",
                "MELHORAMENTOS": "Melhoramentos",
                "BENFEITORIAS": "Benfeitorias",
                "MATERIAL IMPLANTACAO": "Mat. Implantação",
                "MATERIAL IMPLANTAÇÃO": "Mat. Implantação",
            }
            for conta_upper, val in operacionais.items():
                # Adiciona apenas contas que NÃO são já cobertas pela Posição Financeira
                cat_title = _conta_canonical.get(conta_upper.upper(), conta_upper.title())
                if cat_title not in posicao_cats:
                    posicao_cats[cat_title] = val
            for cat, val in posicao_cats.items():
                dados.categorias_despesa[cat] = (
                    dados.categorias_despesa.get(cat, 0) + val
                )
        else:
            # Fallback clássico: usa TOTAL DA CONTA (Blue Sky, Gravura, etc.)
            if val_ordinaria > 0:
                soma_op = sum(operacionais.values())
                if abs(soma_op - val_ordinaria) / max(val_ordinaria, 1) < 0.05:
                    pass  # sub-categorias ≈ ORDINÁRIA → são detalhes internos
                else:
                    operacionais["ORDINÁRIA"] = val_ordinaria

            if not operacionais and val_ordinaria > 0:
                operacionais["ORDINÁRIA"] = val_ordinaria

            # Fallback Vibra: extrai sub-categorias do Demonstrativo se ainda poucas
            if val_ordinaria > 0 and len(operacionais) <= 3:
                sub_cats = self._extrair_subcategorias_demonstrativo(texto_completo)
                if len(sub_cats) > len(operacionais):
                    operacionais = {k: v for k, v in operacionais.items()
                                    if k not in _CONTAS_AGREGADO}
                    operacionais.update(sub_cats)

            for conta, val in operacionais.items():
                cat = conta.title()
                dados.categorias_despesa[cat] = (
                    dados.categorias_despesa.get(cat, 0) + val
                )

        # Fallback final
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        # ── 4. Inadimplência ────────────────────────────────────────────────────
        # "Total geral: 19.089,92" na seção "RELAÇÃO DE COTAS EM ABERTO"
        m_inad = re.search(r"Total geral:\s*([\d.,]+)", texto_completo, re.IGNORECASE)
        if m_inad:
            dados.inadimplencia_valor = _num(m_inad.group(1))
        else:
            # Fallback: soma de "Total da unidade: X" (cada devedor)
            total_u = sum(
                _num(m.group(1))
                for m in re.finditer(
                    r"Total da unidade:\s*([\d.,]+)", texto_completo
                )
            )
            if total_u > 0:
                dados.inadimplencia_valor = total_u

        # ── 5. FAC (Faturas Anteriores Cobradas = juros + multas recebidos) ────
        dados.fac = self._extrair_fac(textos)

    # ──────────────────────────────────────────────────────────────────────────
    # SUB-FORMATO B — Webware (NYC Berrini)
    # ──────────────────────────────────────────────────────────────────────────

    def _parsear_webware(self, textos: list, texto_completo: str, dados: DadosFinanceiros):
        """Extrai dados do formato Webware (NYC Berrini)."""

        # ── 1. Resumo Financeiro Contábil ──────────────────────────────────────
        # Aparece como seção "Resumo Financeiro Contábil" com header
        # "Conta Saldo Anterior Créditos Débitos Saldo Atual" (diferente do Lirba)
        # Estratégia: usa o padrão de linha "NOME  num  num  num  num" depois do header
        for txt in textos:
            if "Resumo Financeiro" not in txt:
                continue

            linhas = txt.split("\n")
            in_resumo = False
            for linha in linhas:
                l = linha.strip()
                if "Resumo Financeiro" in l:
                    in_resumo = True
                    continue
                if not in_resumo:
                    continue
                # Pula linhas de cabeçalho e linhas de navegação
                if re.match(r"^(Conta\b|Per[íi]odo|Condom[íi]nio|https?://)", l,
                             re.IGNORECASE):
                    continue
                # Para se chegou à Conciliação ou fim da seção
                if re.match(r"^(Concilia[çc][aã]o|Demonstrativo de Receitas)", l,
                             re.IGNORECASE):
                    in_resumo = False
                    break

                # Extrai números: podem ser negativos (conta corrente negativa)
                # Padrão: "NOME -saldo_ant creditos debitos saldo_atual"
                nums = re.findall(r"-?[\d.]+,\d{2}", l)
                nums_f = [_num(n) for n in nums]
                if len(nums_f) < 4:
                    continue

                # Nome = parte antes dos números (remove todos os números do final)
                nome = re.sub(r"[\s\-]*-?[\d.,]+(?:\s+-?[\d.,]+)+\s*$", "", l).strip().upper()
                if not nome or re.search(r"\d", nome):
                    continue  # ainda tem número no nome → linha mal parseada

                sa, cr, db, sal = nums_f[0], nums_f[1], nums_f[2], nums_f[3]

                if nome.startswith("TOTAL"):
                    dados.saldo_anterior    = sa
                    dados.receita_realizada = cr
                    dados.despesa_total     = db
                    dados.saldo_atual       = sal
                    in_resumo = False
                    break

                dados.contas_detalhe.append({
                    "nome":       nome,
                    "saldo_ant":  sa,
                    "creditos":   cr,
                    "debitos":    db,
                    "saldo_atual": sal,
                })

                nome_up = nome.upper()
                if "ORDINARI" in nome_up:
                    dados.banco_cc += sal
                elif any(kw in nome_up for kw in (
                    "FUNDO DE RESERVA", "FUNDO RESERVA",
                    "CDB", "APLICA", "INVESTIMENTO", "INVEST",
                )):
                    dados.banco_cdb += sal
                else:
                    dados.banco_priv += sal
            break

        # Webware: "Conciliação Bancaria" lista saldos reais por banco (mais preciso)
        # "Saldo Conta Corrente Banco X  1,00"
        # "Saldo Aplicação Bco. Y - Invest facil  5.180,53"
        # "Valor total  5.181,53"  ← corresponde ao saldo_atual
        banco_cc_concil  = 0.0
        banco_cdb_concil = 0.0
        for linha in texto_completo.split("\n"):
            l = linha.strip()
            m = re.match(r"Saldo\s+(.+?)\s+([\d.,]+)\s*$", l, re.IGNORECASE)
            if not m:
                continue
            desc = m.group(1).upper()
            val  = _num(m.group(2))
            if "APLICA" in desc or "INVEST" in desc or "CDB" in desc or "POUPAN" in desc:
                banco_cdb_concil += val
            elif "CORRENTE" in desc or "C/C" in desc or "CONTA" in desc:
                banco_cc_concil += val

        # Usa dados de Conciliação se disponíveis (mais precisos)
        if banco_cc_concil > 0 or banco_cdb_concil > 0:
            dados.banco_cc  = banco_cc_concil
            dados.banco_cdb = banco_cdb_concil

        # ── 2. Receita Prevista ─────────────────────────────────────────────────
        # Pág 1: "Resumo de Emissão  Previsto  Realizado"
        # As linhas seguintes têm "ITEM  previsto  realizado"
        # A linha de subtotais "215.227,27  168.052,84" (dois núms sem texto) é o total
        previsto = 0.0
        in_emissao = False
        for linha in texto_completo.split("\n"):
            l = linha.strip()
            if re.match(r"Resumo de Emiss[aã]o\b", l, re.IGNORECASE):
                in_emissao = True
                continue
            if not in_emissao:
                continue
            # Linha de subtotal: apenas dois números
            m = re.match(r"^([\d.,]+)\s+([\d.,]+)$", l)
            if m:
                v1, v2 = _num(m.group(1)), _num(m.group(2))
                if v1 > 1000:
                    previsto += v1
                in_emissao = False
            # "Devedores e Acordos" indica fim da seção de emissão
            if re.match(r"Devedores", l, re.IGNORECASE):
                in_emissao = False

        if previsto > 0:
            dados.receita_prevista = previsto
        else:
            dados.receita_prevista = dados.receita_realizada

        # ── 3. Despesas por categoria ───────────────────────────────────────────
        # "TOTAL DA CONTA NOME  valor  pct%" (Webware inclui percentual no final)
        # Em NYC: as sub-categorias (PESSOAL, CONSUMO, CONTRATOS, MANUTENCAO, etc.)
        # são o que queremos; ORDINARIA é o agregado de tudo.
        todos_totais_w = {}
        for m in re.finditer(
            r"TOTAL DA CONTA\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ /\-\.0-9]+?)\s+([\d.,]+)"
            r"(?:\s+[\d.,]+%?)?(?:\s|$)",
            texto_completo, re.IGNORECASE
        ):
            conta = m.group(1).strip().upper()
            val   = _num(m.group(2))
            if val > 0:
                todos_totais_w[conta] = todos_totais_w.get(conta, 0) + val

        for conta, val in todos_totais_w.items():
            if any(ex in conta for ex in _EXCLUIR_SEMPRE):
                continue
            if conta in _CONTAS_AGREGADO:
                continue  # ORDINARIA é o agregado
            if "TOTAL DAS DESPESAS" in conta or "TOTAL DESPESAS" in conta:
                continue
            cat = conta.title()
            dados.categorias_despesa[cat] = (
                dados.categorias_despesa.get(cat, 0) + val
            )

        # Fallback
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        # ── 4. Inadimplência ────────────────────────────────────────────────────
        # Webware: "COTAS EM ATRASO EM dd/mm/yyyy  valor" no Resumo de Emissão
        # A linha com data do final do período (mês corrente) é a inadimplência
        # Ex: "COTAS EM ATRASO EM 30/04/2026  47.174,43"
        # Extrai todas as ocorrências e pega a maior (última = saldo atual)
        inad_values = []
        for m in re.finditer(
            r"COTAS EM ATRASO EM\s+\d{2}/\d{2}/\d{4}\s+([\d.,]+)",
            texto_completo, re.IGNORECASE
        ):
            inad_values.append(_num(m.group(1)))

        if inad_values:
            dados.inadimplencia_valor = max(inad_values)
        else:
            # Fallback: soma "Total da unidade:"
            total_u = sum(
                _num(m.group(1))
                for m in re.finditer(
                    r"Total da unidade:\s*([\d.,]+)", texto_completo
                )
            )
            if total_u > 0:
                dados.inadimplencia_valor = total_u

    # ──────────────────────────────────────────────────────────────────────────
    # Métodos auxiliares compartilhados (Lirba + Webware)
    # ──────────────────────────────────────────────────────────────────────────

    # Linhas que aparecem na Posição Financeira mas NÃO são despesas
    _POS_NAO_DESPESA = {
        "SALDO ANTERIOR CREDOR", "SALDO ANTERIOR DEVEDOR", "SALDO ANTERIOR",
        "CONDOMINOS EM ATRASO", "CONDOMÍNOS EM ATRASO",
        "RECEBIMENTO DO PERIODO", "RECEBIMENTO DO PERÍODO",
        "OUTRAS PREVISOES", "OUTRAS PREVISÕES",
        "OUTRAS RECEITAS",
        "REEMBOLSO CUSTAS PROCESSUAIS",
        "RENDIMENTOS APLICACAO", "RENDIMENTOS APLICAÇÃO",
        "RENDIMENTOS DE APLICACAO", "RENDIMENTOS DE APLICAÇÃO",
        "JUROS", "MULTAS",
        "ATUALIZACAO MONETARIA", "ATUALIZAÇÃO MONETÁRIA",
        "TOTAIS",
        "SALDO ATUAL CREDOR", "SALDO ATUAL DEVEDOR", "SALDO ATUAL",
        "CONTASDATA", "CONTAS",
        "DÉBITO/CRÉDITO NÃO IDENTIFICAD", "DEBITO/CREDITO NAO IDENTIFICAD",
    }

    # Mapeamento nome_upper → canonical para categorias de despesa na Posição Financeira
    _POS_CAT_MAP = {
        "NR'S NORMAS REGULAMENTADORAS":  "Normas Reg.",
        "NRS NORMAS REGULAMENTADORAS":   "Normas Reg.",
        "NORMAS REGULAMENTADORAS":       "Normas Reg.",
        "TERCEIRIZACAO":                 "Terceirização",
        "TERCEIRIZAÇÃO":                 "Terceirização",
        "MANUTENCAO":                    "Manutenção",
        "MANUTENÇÃO":                    "Manutenção",
        "CONSERVACAO PREDIAL":           "Conserv. Predial",
        "CONSERVAÇÃO PREDIAL":           "Conserv. Predial",
        "MATERIAL DE CONSUMO":           "Mat. de Consumo",
        "ADMINISTRATIVO":                "Administrativo",
        "DESPESAS OPERACIONAIS":         "Desp. Operacionais",
        "SEGURANCA":                     "Segurança",
        "SEGURANÇA":                     "Segurança",
        "OUTRAS DESPESAS":               "Outras Desp.",
        "MAT. IMPLANTACAO":              "Mat. Implantação",
        "MAT. IMPLANTAÇÃO":              "Mat. Implantação",
        "MATERIAL DE IMPLANTACAO":       "Mat. Implantação",
        "MATERIAL DE IMPLANTAÇÃO":       "Mat. Implantação",
        "MATERIAL IMPLANTACAO":          "Mat. Implantação",
        "MATERIAL IMPLANTAÇÃO":          "Mat. Implantação",
        "SALARIOS":                      "Salários",
        "SALÁRIOS":                      "Salários",
        "SERVICOS TERCEIRIZADOS":        "Serv. Terceirizados",
        "SERVIÇOS TERCEIRIZADOS":        "Serv. Terceirizados",
        "UTILIDADES":                    "Utilidades",
        "AGUA":                          "Água",
        "ÁGUA":                          "Água",
        "ENERGIA ELETRICA":              "Energia Elétrica",
        "ENERGIA ELÉTRICA":              "Energia Elétrica",
        "GAS":                           "Gás",
        "GÁS":                           "Gás",
        "LIMPEZA":                       "Limpeza",
        "VIGILANCIA":                    "Vigilância",
        "VIGILÂNCIA":                    "Vigilância",
    }

    def _extrair_subcats_posicao_financeira(self, pages_text: list) -> dict:
        """
        Extrai sub-categorias de despesa da seção 'Posição Financeira' da conta ORDINÁRIA.

        A Posição Financeira de ORDINÁRIA tem o layout:
          Posição Financeira Débito Crédito
          SALDO ANTERIOR CREDOR dd/mm/YYYY  value
          CONDOMINOS EM ATRASO  value            ← créditos (não despesas)
          RECEBIMENTO DO PERIODO  value
          ContasData
          OUTRAS PREVISOES  value
          ...
          JUROS  value
          ATUALIZACAO MONETARIA  value
          MULTAS  value
          NR'S NORMAS REGULAMENTADORAS  value    ← ← ← despesas começam aqui
          TERCEIRIZAÇÃO  value
          MANUTENÇÃO  value
          ...
          DÉBITO/CRÉDITO NÃO IDENTIFICAD  value  ← crédito de ajuste (excluir)
          TOTAIS  total_deb  total_cred

        Retorna dict {canonical_name: valor} das categorias encontradas.
        Retorna {} se a seção não for encontrada ou não houver categorias.
        """
        import unicodedata

        def _norm(s: str) -> str:
            s = unicodedata.normalize("NFD", s)
            return "".join(c for c in s if unicodedata.category(c) != "Mn").upper().strip()

        BR_NUM = re.compile(r"^([\d]{1,3}(?:\.[\d]{3})*,[\d]{2})\s*$")
        SINGLE_VAL = re.compile(r"^(.+?)\s+([\d]{1,3}(?:\.[\d]{3})*,[\d]{2})\s*$")

        # Linhas a ignorar (não são despesas)
        not_desp_norm = {_norm(k) for k in self._POS_NAO_DESPESA}
        # Prefixos de linhas de crédito/data
        not_desp_prefixes = {
            "SALDO", "CONDOMINO", "RECEBIMENTO", "OUTRAS", "REEMBOLSO",
            "RENDIMENTO", "JUROS", "MULTAS", "ATUALIZACAO", "ATUALIZAÇÃO",
            "TOTAIS", "CONTAS", "PERIOD", "PERÍODO",
        }

        # Marcadores para entrar na zona de despesas
        MULTAS_NORM = "MULTAS"
        ATUALIZACAO_NORM = "ATUALIZACAO MONETARIA"

        results: dict = {}

        for pg_idx, text in enumerate(pages_text):
            if "Posição Financeira" not in text and "Posicao Financeira" not in text:
                continue
            if "Resumo Financeiro" in text:
                # Página diferente (contém Resumo Financeiro, não Posição Financeira de conta)
                continue

            lines = [l.strip() for l in text.split("\n") if l.strip()]

            in_pos = False
            past_multas = False
            found_cats = {}

            for line in lines:
                ll_norm = _norm(line)

                # Inicia quando encontra "Posição Financeira"
                if not in_pos:
                    if re.match(r"Posi[çc][aã]o Financeira", line, re.IGNORECASE):
                        in_pos = True
                    continue

                # Para ao encontrar "TOTAIS" ou nova seção
                if ll_norm.startswith("TOTAIS"):
                    break

                # Detecta passagem por MULTAS/ATUALIZACAO → próximas linhas são despesas
                if ll_norm in (MULTAS_NORM, ATUALIZACAO_NORM) or ll_norm.startswith("MULTAS"):
                    past_multas = True
                    continue

                if not past_multas:
                    continue

                # Pula linhas de ajuste conhecidas
                if any(ll_norm.startswith(p) for p in not_desp_prefixes):
                    continue
                if ll_norm in not_desp_norm:
                    continue

                # Pula DÉBITO/CRÉDITO NÃO IDENTIFICAD (ajuste de conta, não despesa)
                if "NÃO IDENTIFICAD" in ll_norm or "NAO IDENTIFICAD" in ll_norm:
                    continue

                # Linha de categoria: "NOME_CATEGORIA  valor"
                m = SINGLE_VAL.match(line)
                if m:
                    name_raw = m.group(1).strip().upper()
                    val = _num(m.group(2))
                    if val > 0:
                        # Mapeia para nome canônico
                        name_norm = _norm(name_raw)
                        canonical = self._POS_CAT_MAP.get(name_raw) or \
                                    self._POS_CAT_MAP.get(name_norm)
                        if canonical is None:
                            # Usa title-case como fallback para nomes não mapeados
                            canonical = name_raw.title()
                        found_cats[canonical] = found_cats.get(canonical, 0.0) + val

            if found_cats:
                results = found_cats
                break  # Usa apenas a primeira Posição Financeira (ORDINÁRIA)

        return results

    # Mapeamento de cabeçalhos de seção → nome canônico (usado no Demonstrativo
    # de PDFs Vibra/Lirba que não têm "TOTAL DA CONTA" por sub-seção).
    # Chaves em maiúsculas sem acentos (normalizado) para match robusto.
    _DEMO_SECTION_MAP = {
        # Normalizado (sem acento) : canônico
        "NR'S NORMAS REGULAMENTADORAS": "Normas Reg.",
        "NRS NORMAS REGULAMENTADORAS":  "Normas Reg.",
        "NORMAS REGULAMENTADORAS":      "Normas Reg.",
        "TERCEIRIZACAO":                "Terceirização",
        "TERCEIRIZAÇÃO":                "Terceirização",
        "MANUTENCAO":                   "Manutenção",
        "MANUTENÇÃO":                   "Manutenção",
        "MANUTENÇÃO.":                  "Manutenção",    # com ponto no PDF
        "CONSERVACAO PREDIAL":          "Conserv. Predial",
        "CONSERVAÇÃO PREDIAL":          "Conserv. Predial",
        "MATERIAL DE CONSUMO":          "Mat. de Consumo",
        "ADMINISTRATIVO":               "Administrativo",
        "DESPESAS OPERACIONAIS":        "Desp. Operacionais",
        "SEGURANCA":                    "Segurança",
        "SEGURANÇA":                    "Segurança",
        "OUTRAS DESPESAS":              "Outras Desp.",
        "MAT. IMPLANTACAO":             "Mat. Implantação",
        "MAT. IMPLANTAÇÃO":             "Mat. Implantação",
        "MATERIAL DE IMPLANTACAO":      "Mat. Implantação",
        "MATERIAL DE IMPLANTAÇÃO":      "Mat. Implantação",
        # Contas de nível alto que podem aparecer sem sub-seções:
        "I.P.T.U.":                     "IPTU",
        "IPTU":                         "IPTU",
        "CONSUMO":                      "Consumos",
        "CONSUMOS":                     "Consumos",
        # Excluir (retorna None):
        "DEBITO/CREDITO NAO IDENTIFICAD":  None,
        "DÉBITO/CRÉDITO NÃO IDENTIFICAD":  None,
        "ORDINARIA":                       None,
        "ORDINÁRIA":                       None,
    }

    def _extrair_subcategorias_demonstrativo(self, texto_completo: str) -> dict:
        """
        Extrai sub-categorias do Demonstrativo de Despesas quando os PDFs Lirba
        não possuem 'TOTAL DA CONTA' individual para cada sub-seção dentro de ORDINÁRIA.

        Algoritmo:
        - Localiza a seção "Demonstrativo de Despesas" no texto
        - Rastreia cabeçalhos de seção (linhas ALL-CAPS sem números, match em _DEMO_SECTION_MAP)
        - O ÚLTIMO número acumulado antes do próximo cabeçalho (ou fim) é o total da seção
        - Retorna dict {nome_upper: valor} a ser mesclado em operacionais

        Valores de "TOTAL DA CONTA X" explícitos são sempre preferidos; este método
        é chamado apenas como fallback quando há poucas categorias extraídas.
        """
        # Encontra início do Demonstrativo de Despesas
        demo_start = texto_completo.lower().find("demonstrativo de despesas")
        if demo_start < 0:
            return {}

        texto_demo = texto_completo[demo_start:]

        # Cabeçalhos conhecidos (norm key → canonical)
        smap = self._DEMO_SECTION_MAP

        # Padrão para linha de cabeçalho de seção:
        # linha ALL-CAPS, sem dígitos no meio, comprimento razoável
        # Pega o nome normalizado para match
        def _normalize(s: str) -> str:
            import unicodedata
            s = unicodedata.normalize("NFD", s)
            s = "".join(c for c in s if unicodedata.category(c) != "Mn")
            return s.upper().strip()

        # Padrão de número monetário com separador de milhar + 2 casas decimais
        # Formato BR: 86.087,03  ou 1.234,56  ou 42.875,97
        NUM_RE = re.compile(r"\b(\d{1,3}(?:\.\d{3})*,\d{2})\b")
        # Linha de transação geralmente termina com: valor_acum  num_lancamento
        TRANSAC_RE = re.compile(
            r"(\d{1,3}(?:\.\d{3})*,\d{2})\s+(\d{4})\s*$"
        )
        # "TOTAL DA CONTA" e "TOTAL DAS DESPESAS" — parar ao encontrar esses
        TOTAL_RE = re.compile(r"TOTAL\s+D[AO]S?\s+(CONTA|DESPESAS)", re.IGNORECASE)

        results: dict = {}           # canonical_name -> valor
        current_section: str = None  # chave em smap (str upper)
        last_cumul: float = 0.0      # último valor acumulado visto na seção

        skip_lines = {
            "demonstrativo de despesas", "página:", "periodo:", "condominio:",
            "nº lancto.", "voltar ao índice", "contasdata", "relatdemon", "panel",
        }

        for raw_line in texto_demo.split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            # Pula cabeçalhos de página
            ll = line.lower()
            if any(sk in ll for sk in skip_lines):
                continue
            if re.match(r"^(página|periodo|condominio|nº lancto)", ll, re.IGNORECASE):
                continue

            # Se encontra TOTAL DA CONTA ou TOTAL DAS DESPESAS, encerra seção atual
            if TOTAL_RE.search(line):
                if current_section and last_cumul > 0:
                    canonical = smap.get(current_section)
                    if canonical is not None:
                        results[canonical] = results.get(canonical, 0.0) + last_cumul
                current_section = None
                last_cumul = 0.0
                continue

            # Tenta match de cabeçalho de seção
            line_norm = _normalize(line)
            # Só considera cabeçalho se:
            # 1. Está no mapa de seções
            # 2. Linha não contém dígitos (além do ponto e vírgula monetários)
            candidate = line_norm.rstrip(".")
            is_header = candidate in smap or line_norm in smap
            if is_header:
                norm_key = line_norm if line_norm in smap else candidate
                # Fecha seção anterior
                if current_section and last_cumul > 0:
                    canonical = smap.get(current_section)
                    if canonical is not None:
                        results[canonical] = results.get(canonical, 0.0) + last_cumul
                current_section = norm_key
                last_cumul = 0.0
                continue

            # Dentro de uma seção: captura valor acumulado em linha de transação
            if current_section:
                m_t = TRANSAC_RE.search(line)
                if m_t:
                    val = _num(m_t.group(1))
                    if val > 0:
                        last_cumul = val
                else:
                    # Tenta qualquer número isolado ao final da linha
                    nums = NUM_RE.findall(line)
                    if nums:
                        v = _num(nums[-1])
                        if v > 0:
                            last_cumul = v

        # Fecha última seção
        if current_section and last_cumul > 0:
            canonical = smap.get(current_section)
            if canonical is not None:
                results[canonical] = results.get(canonical, 0.0) + last_cumul

        # Retorna como {UPPER_KEY: valor} para mesclagem no operacionais
        return {k.upper(): v for k, v in results.items() if v > 0}

    def _extrair_conta_bancaria(self, pages_text: list) -> dict:
        """
        Extrai saldos reais da seção 'Conta bancária' do PDF.
        Retorna {nome_conta: saldo_atual} com sinal (podem ser negativos).
        Retorna {} se a seção não existir no PDF.
        """
        BR_NUM = re.compile(r'-?[\d]{1,3}(?:[.,][\d]{3})*,[\d]{2}')

        def br_to_float(s: str) -> float:
            return float(s.strip().replace('.', '').replace(',', '.'))

        for text in pages_text:
            if 'conta banc' not in text.lower():
                continue
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            for i, line in enumerate(lines):
                if 'conta banc' not in line.lower():
                    continue
                # Cabeçalho pode estar na MESMA linha ("Conta bancária Saldo anterior...")
                # OU na linha seguinte ("Conta bancária\nSaldo anterior Créditos...")
                header_same_line  = 'saldo' in line.lower()
                header_next_line  = (i + 1 < len(lines) and
                                     'saldo' in lines[i + 1].lower())
                if not header_same_line and not header_next_line:
                    continue
                # Se o cabeçalho está na linha seguinte, pula ela antes de parsear
                parse_start = i + 1 if header_same_line else i + 2
                # Parse das linhas de conta
                contas: dict = {}
                for j in range(parse_start, min(i + 30, len(lines))):
                    ln = lines[j]
                    if ln.upper().startswith('TOTAL'):
                        break
                    # Ignora linhas de cabeçalho ou de outras seções
                    if any(kw in ln.lower() for kw in [
                        'saldo anterior', 'resumo', 'posicao', 'posição',
                        'ordinaria', 'ordinária', 'demonstrativo', 'creditos',
                        'débitos', 'debitos',
                    ]):
                        continue
                    nums = BR_NUM.findall(ln)
                    if len(nums) >= 4:
                        name = BR_NUM.sub('', ln).strip()
                        # Remove caracteres residuais de separação
                        name = re.sub(r'\s{2,}', ' ', name).strip()
                        saldo_atual = br_to_float(nums[-1])
                        if name:
                            contas[name] = saldo_atual
                if contas:
                    return contas
        return {}

    def _extrair_fac(self, pages_text: list) -> float:
        """
        Extrai total de JUROS + MULTAS recebidos (FAC = Faturas Anteriores Cobradas).
        Soma todas as linhas 'JUROS X' e 'MULTAS X' nos detalhes de movimentação.
        """
        BR_NUM = re.compile(r'[\d]{1,3}(?:[.,][\d]{3})*,[\d]{2}')

        def br_to_float(s: str) -> float:
            return float(s.strip().replace('.', '').replace(',', '.'))

        total = 0.0
        for text in pages_text:
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            for line in lines:
                upper = line.upper()
                # Linhas como "JUROS 28,24" ou "MULTAS 55,07"
                # Exclui linhas que são totais ou apenas cabeçalhos
                if (upper.startswith('JUROS ') or upper.startswith('MULTAS ')) \
                        and 'TOTAL' not in upper:
                    nums = BR_NUM.findall(line)
                    if len(nums) == 1:
                        total += br_to_float(nums[0])
                    elif len(nums) >= 2:
                        # Pega o primeiro número (valor individual, não acumulado)
                        total += br_to_float(nums[0])
        return round(total, 2)

    # ──────────────────────────────────────────────────────────────────────────
    # ler_xlsx — redireciona para ler_pdf
    # ──────────────────────────────────────────────────────────────────────────

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """Redireciona para ler_pdf — LIRBA usa PDF, não XLSX."""
        # Tenta trocar extensão
        for ext in [".pdf", ".PDF"]:
            p = caminho.parent / (caminho.stem + ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        # Busca qualquer PDF na pasta
        pdfs = sorted(
            list(caminho.parent.glob("*.pdf")) +
            list(caminho.parent.glob("*.PDF")),
            key=lambda x: x.stat().st_mtime, reverse=True
        )
        if pdfs:
            return self.ler_pdf(pdfs[0], mes_referencia)
        raise FileNotFoundError(f"Nenhum PDF Lirba encontrado em {caminho.parent}")
