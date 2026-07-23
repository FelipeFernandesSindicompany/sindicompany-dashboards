"""
Adapter Iello PDF — Iello Condomínios (Balancete Mensal)

Estrutura confirmada (Giardino D'Itália, Vita Parque):
  Pág 1: COMPOSIÇÃO DESPESAS ORDINÁRIA
    DESPESAS COM PESSOAL -44.961,17
    ENCARGOS SOCIAIS -14.623,17
    ...
    TOTAL -137.981,25

  Pág 2-3: RESUMO FINANCEIRO
    DESCRIÇÃO | SALDO ANT. | CREDITOS | DÉBITOS | SALDO FINAL
    CONTA CONDOMINIO 46.109,32 139.841,36 -137.981,25 47.969,43
    ...
    SALDO FINAL 159.676,75 158.703,32 -153.331,25 165.048,82

  Inadimplência:
    TOTAL GERAL DE DEVEDORES 550.123,31
"""
from pathlib import Path
import re
from adapters.base import AdapterBase, DadosFinanceiros


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except:
        return 0.0


class AdapterIelloPDF(AdapterBase):

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
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)

        linhas = texto.split("\n")

        # ── Resumo Financeiro: cada linha é uma conta com 4 números (ant/cred/deb/atual) ──
        # Escopa ao bloco RESUMO FINANCEIRO para evitar capturar linhas de outras seções.
        # "CONTA CONDOMINIO" = ordinária (banco_cc)
        # "FUNDO DE RESERVA" / "FUNDO INVESTIMENTO" = banco_cdb (somados)
        # Demais contas (SALAO DE FESTAS, BENFEITORIA, LOCACAO, etc.) = banco_priv
        # "SALDO FINAL" = totais consolidados
        _CC_KEYS  = ("CONTA CONDOMINIO", "ORDINARI", "CORRENTE")
        _CDB_KEYS = ("FUNDO", "RESERVA", "CDB", "APLICA", "INVESTIMENTO")
        conta_condominio_c = None
        in_resumo = False
        for linha in linhas:
            l = linha.strip()
            l_up = l.upper()

            if "RESUMO FINANCEIRO" in l_up:
                in_resumo = True
                continue

            if l_up.startswith("SALDO FINAL"):
                nums = re.findall(r"-?[\d.,]+", l.replace("SALDO FINAL", ""))
                nums_f = [_num(n) for n in nums if re.search(r"\d", n)]
                if len(nums_f) >= 4:
                    dados.saldo_anterior    = nums_f[0]
                    dados.receita_realizada = conta_condominio_c if conta_condominio_c else nums_f[1]
                    dados.despesa_total     = nums_f[2]
                    dados.saldo_atual       = nums_f[3]
                    dados.receita_prevista  = 0.0
                in_resumo = False
                continue

            if not in_resumo:
                continue

            nums = re.findall(r"-?[\d.,]+", l)
            nums_f = [_num(n) for n in nums if re.search(r"\d", n)]
            if len(nums_f) < 4:
                continue

            # Nome da conta = texto antes do primeiro número; filtra paginação (minúsculas)
            nome_conta = re.sub(r'\s+-?[\d.,]+.*', '', l).strip()
            if not nome_conta or nome_conta != nome_conta.upper():
                continue

            saldo_conta = nums_f[3]
            conta_entry = {
                "nome":       nome_conta,
                "saldo_ant":  nums_f[0],
                "creditos":   nums_f[1],
                "debitos":    nums_f[2],
                "saldo_atual": saldo_conta,
            }
            if any(k in l_up for k in _CC_KEYS):
                conta_condominio_c = nums_f[1]
                dados.banco_cc = saldo_conta
            elif any(k in l_up for k in _CDB_KEYS):
                dados.banco_cdb = round(dados.banco_cdb + saldo_conta, 2)
            else:
                dados.banco_priv = round(dados.banco_priv + saldo_conta, 2)
            dados.contas_detalhe.append(conta_entry)

        # Fallback: PDF sem RESUMO FINANCEIRO reconhecível
        if dados.saldo_atual and not dados.contas_detalhe:
            dados.contas_detalhe = [{"nome": "ORDINÁRIA",
                                      "saldo_ant":  dados.saldo_anterior,
                                      "creditos":   dados.receita_realizada,
                                      "debitos":    dados.despesa_total,
                                      "saldo_atual": dados.saldo_atual}]

        # ── Despesas por categoria ──
        # Seção "COMPOSIÇÃO DESPESAS ORDINÁRIA" — encerra em "RECEBIMENTO DE CONTAS"
        # Atenção: a linha "TOTAL" aparece no meio da seção (subtotal parcial da pág.);
        # categorias como CAIXA LOCAL, ADMINISTRATIVO, DESPESAS GERAIS e DESPESAS
        # OPERACIONAIS surgem DEPOIS do "TOTAL" e devem ser capturadas.
        in_desp = False
        for linha in linhas:
            l = linha.strip()
            l_up = l.upper()
            if re.search(r"COMPOSI[ÇC][ÃA]O DESPESAS ORDIN", l, re.IGNORECASE):
                in_desp = True
                continue
            if not in_desp:
                continue
            # Encerra a seção na próxima seção do PDF
            if re.match(r"^(RECEBIMENTO DE CONTAS|RESUMO DE INAD|MULTAS E CORRE|RESUMO FINANCEIRO)", l_up):
                in_desp = False
                continue
            # Ignora a linha de total acumulado e cabeçalhos de página
            if re.match(r"^TOTAL\b", l, re.IGNORECASE):
                continue
            if not l or re.match(r"^(Per[ií]odo|P[aá]g\.|Balancete|COMPOSI)", l, re.IGNORECASE):
                continue
            # Linha de categoria: "TEXTO -valor" ou "TEXTO  valor"
            m = re.match(r"^(.+?)\s+-?([\d.,]{4,})\s*$", l)
            if m:
                cat = m.group(1).strip()
                val = _num(m.group(2))
                # Filtra totalizadores e linhas de outras seções
                if val > 0 and len(cat) > 3 and not re.match(
                    r"^(TOTAL|RECEBIMENTO|RESUMO|SALDO|ACORDOS|CANCELAMENTO|"
                    r"ANTECIPA|COTAS|CONDÔMINO|ARRECADA|MULTAS|CONSUMO|FUNDO|SALÃO)",
                    cat, re.IGNORECASE
                ):
                    dados.categorias_despesa[cat] = (
                        dados.categorias_despesa.get(cat, 0) + val
                    )

        # ── Acordos recebidos (faturas em atraso cobradas no período) ──
        m_acordos = re.search(r"ACORDOS RECEBIDOS\s+([\d.,]+)", texto, re.IGNORECASE)
        if m_acordos:
            dados.inadimplencia_recebida = _num(m_acordos.group(1))

        # ── Inadimplência ──
        m_inad = re.search(
            r"TOTAL GERAL DE DEVEDORES\s+([\d.,]+)", texto, re.IGNORECASE
        )
        if m_inad:
            dados.inadimplencia_valor = _num(m_inad.group(1))
        else:
            # Fallback: soma todos os "TOTAL DEVEDORES"
            total_inad = 0.0
            for m in re.finditer(r"TOTAL DEVEDORES[^\n]+?([\d.,]+)", texto, re.IGNORECASE):
                total_inad += _num(m.group(1))
            if total_inad > 0:
                dados.inadimplencia_valor = total_inad

        # Fallback despesas
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        dados.total_unidades = self.config.get("unidades", 0)
        if dados.receita_realizada > 0 and dados.inadimplencia_valor > 0:
            dados.inadimplencia_percentual = round(
                dados.inadimplencia_valor / dados.receita_realizada * 100, 2
            )
        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        for ext in [".pdf", ".PDF"]:
            p = caminho.with_suffix(ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        pdfs = list(caminho.parent.glob("*.pdf")) + list(caminho.parent.glob("*.PDF"))
        if pdfs:
            return self.ler_pdf(pdfs[0], mes_referencia)
        raise FileNotFoundError(f"Nenhum PDF encontrado em {caminho.parent}")
