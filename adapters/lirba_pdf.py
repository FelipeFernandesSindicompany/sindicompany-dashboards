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
                nums = re.findall(r"-?[\d.,]{1,}[\d]", l)
                nums_f = []
                for n in nums:
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

                # Classifica conta para campos banco_*
                # Usa ASCII-fold para lidar com encoding quebrado nos PDFs
                nome_fold = "".join(
                    c for c in unicodedata.normalize("NFD", nome)
                    if unicodedata.category(c) != "Mn"
                ).upper()
                if "ORDINARI" in nome_fold or "ORDINARIA" in nome_fold:
                    dados.banco_cc += sal
                elif any(kw in nome_fold for kw in (
                    "FUNDO DE RESERVA", "FUNDO RESERVA",
                    "CDB", "APLICA", "INVESTIMENTO",
                )):
                    dados.banco_cdb += sal
                else:
                    dados.banco_priv += sal

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
        #
        # Estratégia: coleta tudo, depois:
        #   - Remove contas que nunca são despesas (_EXCLUIR_SEMPRE)
        #   - Se existem sub-contas (não-fundo além de ORDINÁRIA), exclui ORDINÁRIA
        #   - Se só ORDINÁRIA existe como conta operacional, inclui ela

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
                val_ordinaria = val  # guarda o valor de ORDINÁRIA para comparação
                continue
            operacionais[conta] = val

        # Decide se inclui ORDINÁRIA como categoria:
        # Se a soma das sub-categorias é próxima de ORDINÁRIA → sub-categorias são
        # itens internos de ORDINÁRIA (Blue Sky), não inclui ORDINÁRIA.
        # Se a soma é muito menor que ORDINÁRIA → ORDINÁRIA é independente (Gravura),
        # inclui ORDINÁRIA como categoria adicional.
        if val_ordinaria > 0:
            soma_op = sum(operacionais.values())
            if abs(soma_op - val_ordinaria) / max(val_ordinaria, 1) < 0.05:
                # Sub-categorias somam ≈ ORDINÁRIA → são os detalhes internos
                pass  # não inclui ORDINÁRIA
            else:
                # ORDINÁRIA é uma conta independente → inclui
                operacionais["ORDINÁRIA"] = val_ordinaria

        if not operacionais and val_ordinaria > 0:
            operacionais["ORDINÁRIA"] = val_ordinaria

        for conta, val in operacionais.items():
            cat = conta.title()
            dados.categorias_despesa[cat] = (
                dados.categorias_despesa.get(cat, 0) + val
            )

        # Fallback
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
