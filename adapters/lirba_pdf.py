"""
Adapter LIRBA PDF — Prestação de Contas MM.YYYY.PDF (formato LIRBA administradora)

Estrutura confirmada (Gravura Residencial, 355 páginas):
  Pág 2: ÍNDICE — contém nomes de todas as seções (armadilha para detecção por keyword)

  Pág 15: "Resumo Financeiro Contábil" (dados reais, com header + TOTAL line)
    Header: "Resumo Financeiro Contábil Saldo anterior Créditos Débitos Saldo atual"
    TOTAL  113.332,33  300.485,52  225.743,53  188.074,32
    CDB: "FUNDO DE INVESTIMENTO - ITAU PRIVILEGE RF REF DI  123.328,60"

  Pág 22+: "Demonstrativo de Despesas" (páginas com "Período:" = dados reais)
    Fim de cada conta: "TOTAL DA CONTA ORDINARIA  150.802,67"
    Contas tipicamente úteis: ORDINARIA, MELHORAMENTOS, BENFEITORIAS, CONSUMO,
    SALAO FESTAS, MATERIAL IMPLANTACAO, SEGURANCA, I.P.T.U.

  Pág 350: "RELAÇÃO DE COTAS EM ABERTO"
    "Total da unidade: 3.342,28" por devedor
    "Total geral: 19.089,92" ao final

  Detecção robusta: páginas de dados têm header "Período: dd/mm/YYYY a dd/mm/YYYY"
  O índice (pág 2) tem os nomes das seções mas SEM "Período:" → ignorado

Condomínios: Gravura Residencial, Gravura Studio, Highlights, Organy Residencial,
             Organy Studio, Padre Carvalho, Praça Saúde (Comercial/Moradia/Residencial),
             Residencial Napoleão, Saint Afonso, Serra da Mantiqueira, Upper Itaim,
             Vibra Butantã, Villa Sardenha, Reserva Verde, Top Nine, Blue Sky,
             Club Park Butantã, I-Gloo, Monte Tabor, Palm Beach, Plano & Mooca,
             Plano Estação Campo Limpo, Plano Rio Bonito, Platinum, Patrícia
"""
from pathlib import Path
import re
from adapters.base import AdapterBase, DadosFinanceiros

# Contas a excluir das categorias de despesa (saldo/reserva, não despesas operacionais)
_EXCLUIR_CONTAS = {
    "FUNDO DE RESERVA", "FUNDO EMERGENCIAL", "INDIVIDUALIZAÇÃO",
    "FUNDO MELHORIAS",
}


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


class AdapterLirbaPDF(AdapterBase):

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Instale pdfplumber: pip install pdfplumber")

        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        # Lê todo o texto de uma vez (LIRBA pode ter 100-400 páginas)
        textos = []
        with pdfplumber.open(str(caminho)) as pdf:
            for page in pdf.pages:
                textos.append(page.extract_text() or "")

        # Página de dados real = tem "Período:" no header
        # O índice tem os nomes das seções mas não tem "Período:"
        def e_pagina_dados(txt: str) -> bool:
            return bool(re.search(r"Per[íi]odo:\s*\d{2}/\d{2}/\d{4}", txt))

        # ── Resumo Financeiro Contábil ──
        for txt in textos:
            if "Resumo Financeiro Contábil" not in txt:
                continue
            if not e_pagina_dados(txt):
                continue  # É o índice, ignora
            m = re.search(
                r"TOTAL\s+([\d.,\-]+)\s+([\d.,\-]+)\s+([\d.,\-]+)\s+([\d.,\-]+)",
                txt
            )
            if m:
                dados.saldo_anterior    = _num(m.group(1))
                dados.receita_realizada = _num(m.group(2))
                dados.despesa_total     = _num(m.group(3))
                dados.saldo_atual       = _num(m.group(4))
                dados.receita_prevista  = dados.receita_realizada

            # CDB / aplicação
            m_app = re.search(r"([\d.,]+)\s*$", txt, re.MULTILINE)
            # Busca mais específica para linha de aplicação
            for linha in txt.split("\n"):
                if re.search(r"(APLICA[ÇC][ÃA]O|INVESTIMENTO|FUNDO\s+DE\s+INV)", linha, re.IGNORECASE):
                    nums = re.findall(r"[\d.,]{6,}", linha)
                    if nums:
                        dados.categorias_despesa  # placeholder para CDB — não usado aqui
            break

        # ── Despesas: "TOTAL DA CONTA X  valor" ──
        texto_completo = "\n".join(textos)
        for m in re.finditer(
            r"TOTAL DA CONTA\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ /\-]+?)\s+([\d.,]+)",
            texto_completo, re.IGNORECASE
        ):
            conta = m.group(1).strip().upper()
            val   = _num(m.group(2))
            if val <= 0:
                continue
            if any(ex in conta for ex in _EXCLUIR_CONTAS):
                continue
            cat = conta.title()
            dados.categorias_despesa[cat] = (
                dados.categorias_despesa.get(cat, 0) + val
            )

        # Fallback
        if not dados.categorias_despesa and dados.despesa_total > 0:
            dados.categorias_despesa["Despesas Gerais"] = dados.despesa_total

        # ── Inadimplência ──
        # "Total geral: 19.089,92" na seção de devedores
        m_inad = re.search(r"Total geral:\s*([\d.,]+)", texto_completo, re.IGNORECASE)
        if m_inad:
            dados.inadimplencia_valor = _num(m_inad.group(1))
        else:
            # Fallback: soma "Total da unidade:"
            total_inad = sum(
                _num(m.group(1))
                for m in re.finditer(r"Total da unidade:\s*([\d.,]+)", texto_completo)
            )
            if total_inad > 0:
                dados.inadimplencia_valor = total_inad

        dados.total_unidades = self.config.get("unidades", 0)
        if dados.receita_realizada > 0 and dados.inadimplencia_valor > 0:
            dados.inadimplencia_percentual = round(
                dados.inadimplencia_valor / dados.receita_realizada * 100, 2
            )
        return dados

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        for ext in [".pdf", ".PDF"]:
            p = caminho.parent / (caminho.stem + ext)
            if p.exists():
                return self.ler_pdf(p, mes_referencia)
        raise FileNotFoundError(f"Nenhum PDF encontrado em {caminho.parent}")
