"""
Adapter DataDigitus PDF — Software DataDigitus

Estrutura confirmada (Cap D'Antibes, 6 páginas):

  Pág 1 — "Resumo Financeiro Contábil"
    Header: CONTA | Saldo Anterior | Créditos | Débitos | Saldo Atual
    Linhas de conta: "CONTA ORDINÁRIA - ..." saldo_ant creditos debitos saldo_atual
    Última linha: "TOTAL GERAL" com os totais consolidados

  Pág 1–3 — "Demonstrativo de Despesas"
    Por conta (ex: "001 - CONTA ORDINÁRIA...")
    Dentro de cada conta, categorias em MAIÚSCULAS aparecem como cabeçalhos de grupo.
    Cada grupo tem entradas "DD/MM/YYYY histórico valor" e termina com uma linha
    contendo apenas o subtotal da categoria (número isolado, ex: "22.322,00").
    Fim da conta: "TOTAL DA CONTA X  valor"
    Fim do demonstrativo: "TOTAL GERAL DAS DESPESAS  valor"

  Pág 3–6 — "Demonstrativo Financeiro por Conta"
    Para cada conta com emissão de cotas:
      "Receita Prevista e Realizada  Previsto  Realizado"
      "Devedores meses anteriores  V1  V2"
      "Emissão do Período  V3  V4"
      ["Antecipações meses anteriores  -Vx"]
      "TOTAL_PREVISTO  TOTAL_REALIZADO"   ← linha com dois números isolados
      "Condôminos em atraso  VALOR_INAD"  ← inadimplência daquela conta
    Não confundir com "De condôminos em atraso" (é receita recebida de inadimplentes)

Categorias padrão reconhecidas (evita falsos positivos de descrições multi-linha):
  SALARIOS E ORDENADOS, ENCARGOS TRABALHISTAS, ENCARGOS SOCIAIS,
  MANUT/CONSERV/REPOSIÇÃO, MANUTENÇÃO, TARIFAS PÚBLICAS,
  SEGUROS CONTRATADOS, MATERIAIS DE CONSUMO, SERVIÇOS PRESTADOS,
  IMPOSTOS E TAXAS, COMPRAS E AQUISIÇÕES, HONORARIOS E EXPEDIENTE,
  TERCEIRIZAÇÃO, SERVIÇOS TERCEIRIZADOS

Condomínios: Cap D'Antibes
"""
from pathlib import Path
import re
import unicodedata
from adapters.base import AdapterBase, DadosFinanceiros


def _normalize(s: str) -> str:
    """
    Normaliza string para comparação: remove replacement chars (U+FFFD),
    remove acentos e converte para maiúsculas.
    Mantém letras, dígitos, / e espaço.
    """
    # Remove replacement chars e chars de controle
    s = re.sub(r"[�\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    # Remove acentos de letras latinas
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    return s.upper()


# Mapeamento de prefixos → nome canônico de exibição.
# Chaves em maiúsculas sem acentos (pdfplumber pode retornar encoding quebrado
# em PDFs gerados por browser). Mais específicos primeiro para evitar ambiguidade.
_CAT_MAP: list[tuple[str, str]] = [
    # prefixo (upper, sem acento)      → nome canônico de exibição
    ("SALARIOS E ORDENADOS",           "Salários e Ordenados"),
    ("ENCARGOS TRABALHISTAS",          "Encargos Trabalhistas"),
    ("ENCARGOS SOCIAIS",               "Encargos Sociais"),
    ("MANUT/CONSERV",                  "Manutenção/Conservação"),  # MANUT/CONSERV/REPOSIÇÃO
    ("MANUTENCAO",                     "Manutenção/Conservação"),
    ("TARIFAS PUBLICAS",               "Tarifas Públicas"),
    ("TARIFAS P",                      "Tarifas Públicas"),        # encoding quebrado
    ("SEGUROS CONTRATADOS",            "Seguros Contratados"),
    ("MATERIAIS DE CONSUMO",           "Materiais de Consumo"),
    ("SERVICOS PRESTADOS",             "Serviços Prestados"),
    ("SERVIOS PRESTADOS",             "Serviços Prestados"),   # Ç → vazio (encoding quebrado)
    ("SERVICOS TERCEIRIZADOS",         "Serviços Terceirizados"),
    ("SERVIOS TERCEIRIZADOS",          "Serviços Terceirizados"),
    ("TERCEIRIZACAO",                  "Terceirização"),
    ("IMPOSTOS E TAXAS",               "Impostos e Taxas"),
    ("COMPRAS E AQUISICOES",           "Compras e Aquisições"),
    ("COMPRAS E AQUISI",               "Compras e Aquisições"),    # encoding quebrado
    ("HONORARIOS E EXPEDIENTE",        "Honorários e Expediente"),
]


def _num(s: str) -> float:
    """Converte string numérica brasileira (1.234,56) para float."""
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


def _e_categoria(linha: str) -> str | None:
    """
    Retorna o nome canônico da categoria se a linha for um cabeçalho de
    categoria reconhecida; caso contrário, retorna None.
    Usa _normalize() para lidar com encoding quebrado em PDFs gerados pelo
    browser (caracteres como Ç/Ã/Õ podem aparecer como U+FFFD).
    """
    l_norm = _normalize(linha.strip())
    for prefix, canonical in _CAT_MAP:
        p_norm = _normalize(prefix)
        if l_norm.startswith(p_norm):
            return canonical
    return None


class AdapterDatadigitusPDF(AdapterBase):
    """
    Adapter para PDFs gerados pelo software DataDigitus (balancetes condominiais).
    Implementa apenas ler_pdf(); ler_xlsx() redireciona para ler_pdf().
    """

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        with pdfplumber.open(str(caminho)) as pdf:
            textos = [p.extract_text() or "" for p in pdf.pages]

        texto_total = "\n".join(textos)
        linhas = texto_total.split("\n")

        # ── 1. Resumo Financeiro Contábil — TOTAL GERAL ─────────────────────
        # Linha: "TOTAL GERAL  saldo_ant  creditos  debitos  saldo_atual"
        # Os débitos podem ser precedidos de "-" no texto; _num() aplica abs()
        m_total = re.search(
            r"TOTAL\s+GERAL\s+([\d.,]+)\s+([\d.,]+)\s+-?([\d.,]+)\s+([\d.,]+)",
            texto_total, re.IGNORECASE
        )
        if m_total:
            dados.saldo_anterior    = _num(m_total.group(1))
            dados.receita_realizada = _num(m_total.group(2))   # créditos totais
            dados.despesa_total     = _num(m_total.group(3))   # débitos totais
            dados.saldo_atual       = _num(m_total.group(4))

        # ── 2. Contas individuais do Resumo Financeiro ───────────────────────
        # "CONTA NOME...  saldo_ant  creditos  debitos  saldo_atual"
        for m in re.finditer(
            r"^(CONTA\s+[^\n]+?)\s+([\d.,]+)\s+([\d.,]+)\s+-?([\d.,]+)\s+([\d.,]+)",
            texto_total, re.MULTILINE
        ):
            nome_conta = m.group(1).strip()
            # Normaliza nome (DataDigitus pode quebrar encoding)
            nome_curto = re.sub(r"\s*-\s*.*", "", nome_conta)  # remove sufixo do banco
            dados.contas_detalhe.append({
                "nome":       nome_conta,
                "nome_curto": nome_curto,
                "saldo_ant":  _num(m.group(2)),
                "creditos":   _num(m.group(3)),
                "debitos":    _num(m.group(4)),
                "saldo_atual": _num(m.group(5)),
            })

        # Classifica contas para banco_cc / banco_cdb / banco_priv
        for conta in dados.contas_detalhe:
            n = conta["nome"].upper()
            sa = conta["saldo_atual"]
            if "APLICA" in n or "CDB" in n or "INVESTIMENTO" in n:
                dados.banco_cdb += sa
            elif "ORDINARIA" in n or "ORDINÁRIA" in n or "CORRENTE" in n:
                dados.banco_cc = sa          # usa saldo da conta ordinária principal
            else:
                dados.banco_priv += sa

        # ── 3. Receita Prevista ──────────────────────────────────────────────
        # Busca seções "Receita Prevista e Realizada" e, dentro de cada uma,
        # captura a linha de totais (dois números isolados logo após os sub-itens).
        # Isso evita capturar pares de números de outras tabelas do PDF.
        previsto_total = 0.0
        in_prev_section = False
        for linha in linhas:
            l = linha.strip()
            if re.search(r"Receita Prevista e Realizada", l, re.IGNORECASE):
                in_prev_section = True
                continue
            if in_prev_section:
                # Linha de total: exatamente dois números BR isolados
                m = re.match(r"^([\d.]+,\d{2})\s+([\d.]+,\d{2})$", l)
                if m:
                    previsto_total += _num(m.group(1))
                    in_prev_section = False  # consumiu o total, aguarda próxima seção
                    continue
                # Linha com label+valor (sub-item): continua na seção
                # Linha de nova seção (sem números): encerra seção sem total
                if l and not re.search(r"[\d.,]", l):
                    in_prev_section = False
        if previsto_total > 0:
            dados.receita_prevista = previsto_total
        elif dados.receita_realizada > 0:
            dados.receita_prevista = dados.receita_realizada  # fallback

        # ── 4. Categorias de Despesa ─────────────────────────────────────────
        # Percorre linhas do Demonstrativo de Despesas:
        #   - Linha com prefixo reconhecido → abre nova categoria
        #   - Linha com apenas número → subtotal da categoria corrente
        #   - "TOTAL DA CONTA" → fecha bloco da conta (reseta categoria)
        cat_atual = None
        for linha in linhas:
            l = linha.strip()
            if not l:
                continue

            # Fecha categoria no "TOTAL DA CONTA"
            if re.match(r"^TOTAL DA CONTA\b", l, re.IGNORECASE):
                cat_atual = None
                continue

            # Detecta novo cabeçalho de categoria
            nome_cat = _e_categoria(l)
            if nome_cat:
                cat_atual = nome_cat
                continue

            # Linha com apenas número isolado = subtotal da categoria corrente
            if cat_atual and re.match(r"^[\d.]+,\d{2}$", l):
                val = _num(l)
                # Sanity: subtotal deve ser menor que o total de despesas (com margem)
                max_val = (dados.despesa_total or 1_000_000) * 1.1
                if 0 < val < max_val:
                    dados.categorias_despesa[cat_atual] = (
                        dados.categorias_despesa.get(cat_atual, 0) + val
                    )
                    cat_atual = None  # subtotal consumido, aguarda próxima categoria

        # Fallback: se nenhuma categoria encontrada, usa total como "Despesas Gerais"
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        # ── 5. Inadimplência ─────────────────────────────────────────────────
        # "Condôminos em atraso  VALOR" aparece uma vez por conta na seção de
        # Receita Prevista e Realizada.
        # NÃO confundir com "De condôminos em atraso" (receita recebida).
        total_inad = 0.0
        for m in re.finditer(
            # Linha começa com "Condôminos em atraso" (não "De condôminos...")
            r"(?<!\bDe\s)(?<!\bde\s)Cond[oô]m[ie]nos em atraso\s+([\d.,]+)",
            texto_total, re.IGNORECASE
        ):
            total_inad += _num(m.group(1))

        # Alternativa mais robusta: buscar apenas linhas que comecem com "Condôminos"
        if total_inad == 0.0:
            for l in linhas:
                m = re.match(
                    r"^Cond[oô]m[ie]nos em atraso\s+([\d.,]+)", l.strip(), re.IGNORECASE
                )
                if m:
                    total_inad += _num(m.group(1))

        dados.inadimplencia_valor = total_inad
        dados.total_unidades = self.config.get("unidades", 0)

        if dados.receita_realizada > 0 and total_inad > 0:
            dados.inadimplencia_percentual = round(
                total_inad / dados.receita_realizada * 100, 2
            )

        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        """Redireciona para ler_pdf — DataDigitus usa PDF, não XLSX."""
        for ext in [".pdf", ".PDF"]:
            p = caminho.parent / (caminho.stem + ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        raise FileNotFoundError(
            f"Nenhum PDF DataDigitus encontrado em {caminho.parent}"
        )
