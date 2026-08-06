"""
Adapter Manager ADM PDF — Prestação de Contas MM.YYYY.PDF

Formato: software Manager ADM (gestão condominial)
Condomínios: Dueto Morumbi

Estrutura do PDF:
  Pág 3-4:  Demonstrativo de Contas
            • Resumo Financeiro Contábil → tAnt/tCred/tDeb/tAtual + contas
            • ORDINARIA / Resumo de Emissões RealizadoPrevisto
              → "151.844,16204.593,94" (total realizado+previsto colados) → real/prev
              → "COTAS EM ATRASO EM DD/MM/YYYY NN,NN" → inad
            • Posição Financeira → "COTAS EM ATRASO NN,NN" → inadProc
              Seção termina em "SALDO ATUAL CREDOR" ou "TOTAIS"
            • "ITAU AGENCIA: ... / NN,NNSALDO\xa0CORRENTE / ..." → banco cc/cdb
  Pág 23+:  Demonstrativo de Despesas
            → "TOTAL DA CONTA NOME  NN,NN  XX%" → categorias de despesa
"""
from pathlib import Path
import re
from adapters.base import AdapterBase, DadosFinanceiros

_CAT_MAP_DEFAULT: dict[str, str] = {
    "PESSOAL":               "PESSOAL",
    "CONSUMO":               "CONSUMO",
    "CONTRATOS/MANUTENCAO":  "CONTRATOS/MANUTENÇÃO",
    "SEGUROS":               "SEGUROS",
    "MATERIAIS/SUPRIMENTOS": "MATERIAIS/SUPRIMENTOS",
    "SERVICOS PRESTADOS":    "SERVIÇOS PRESTADOS",
    "DESPESAS OPERACIONAIS": "DESPESAS OPERACIONAIS",
    "ADMINISTRACAO":         "ADMINISTRAÇÃO",
}

_EXCLUIR_TOTAIS = {
    "ORDINARIA", "ORDINÁRIA",
    "FUNDO DE RESERVA", "FUNDO RESERVA",
    "OBRAS", "MELHORIAS",
}


def _norm(s: str) -> str:
    """Substitui non-breaking spaces e normaliza espaços."""
    return s.replace("\xa0", " ").strip()


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = _norm(s).lstrip("-")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_br(line: str) -> list[float]:
    return [_num(m) for m in re.findall(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", line)]


def _two_concat(line: str) -> tuple[float, float] | None:
    """Divide 'NN.NNN,NNKK.KKK,KK' em (primeiro, segundo)."""
    nums = re.findall(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", line)
    if len(nums) == 2:
        return _num(nums[0]), _num(nums[1])
    return None


class AdapterManagerAdmPDF(AdapterBase):

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        raise NotImplementedError("Manager ADM usa PDF, não XLSX")

    def ler_pdf(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        from pypdf import PdfReader

        reader = PdfReader(str(caminho))
        all_text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                all_text += t + "\n"

        # Normaliza non-breaking spaces em todo o texto
        all_text = all_text.replace("\xa0", " ")
        lines = [l.strip() for l in all_text.split("\n") if l.strip()]

        # ── Período ───────────────────────────────────────────────────────────
        per_ini = per_fim = ""
        for l in lines:
            m = re.search(r"Per[íi]odo:\s*(\d{2}/\d{2}/\d{4})\s*a\s*(\d{2}/\d{2}/\d{4})", l)
            if m:
                per_ini, per_fim = m.group(1), m.group(2)
                break
        last_day = per_fim  # "30/06/2026"

        # ── Resumo Financeiro Contábil ────────────────────────────────────────
        contas_detalhe: list[dict] = []
        t_ant = t_cred = t_deb = t_atual = 0.0
        in_rfc = False

        for l in lines:
            if "Resumo Financeiro Cont" in l and "Saldo anterior" in l:
                in_rfc = True
                continue
            if not in_rfc:
                continue
            nums = _find_br(l)
            if len(nums) == 4:
                name_raw = re.sub(r"\s*-?\d{1,3}(?:\.\d{3})*,\d{2}.*$", "", l).strip()
                if name_raw.upper().startswith("TOTAL"):
                    t_ant, t_cred, t_deb, t_atual = nums
                    in_rfc = False
                    break
                else:
                    contas_detalhe.append({
                        "nome":       name_raw,
                        "saldo_ant":  nums[0],
                        "creditos":   nums[1],
                        "debitos":    nums[2],
                        "saldo_atual": nums[3],
                    })

        # ── Resumo de Emissões ORDINARIA — prev / real ────────────────────────
        # Varredura sequencial com estados para evitar contaminação de outras contas
        prev = real = inadProc_val = 0.0
        # Estados: 'idle' → 'emissoes' → 'posicao' → 'done'
        state = "idle"
        for i, l in enumerate(lines):
            if state == "idle":
                lup = l.upper()
                if lup in ("ORDINARIA", "ORDINÁRIA"):
                    # Confirma que a próxima linha relevante é Resumo de Emissões
                    nxt = lines[i + 1] if i + 1 < len(lines) else ""
                    if "RealizadoPrevisto" in nxt:
                        state = "emissoes"
                continue

            if state == "emissoes":
                if "RealizadoPrevisto" in l or "Resumo de Emiss" in l:
                    continue
                # Total da seção: exatamente dois números colados, sem label
                if re.match(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}-?\d{1,3}(?:\.\d{3})*,\d{2}$", l):
                    pair = _two_concat(l)
                    if pair:
                        real, prev = pair
                    continue
                # Início Posição Financeira
                if "Posi" in l and "Financeira" in l:
                    state = "posicao"
                    continue
                # Fim da seção Emissões sem achar Posição (raro): próxima conta
                if l.upper() in ("IMPOSTO PREDIAL", "FUNDO DE RESERVA", "OBRAS",
                                  "ALUGUEL S.FESTA /CHURRASQUEIRA"):
                    state = "done"
                continue

            if state == "posicao":
                # Cotas em atraso recebidas no período
                if re.match(r"^COTAS\s+EM\s+ATRASO\s+[\d]", l, re.IGNORECASE):
                    nums = _find_br(l)
                    if nums:
                        inadProc_val = nums[0]
                # Fim da Posição Financeira
                if l.upper().startswith("SALDO ATUAL") or l.upper().startswith("TOTAIS"):
                    state = "done"
                continue

            if state == "done":
                break

        # ── inad — soma de todos "COTAS EM ATRASO EM {last_day}" no texto ────
        inad_val = 0.0
        if last_day:
            pattern = re.compile(
                r"COTAS\s+EM\s+ATRASO\s+EM\s+" + re.escape(last_day) + r"\s+([\d.,]+)",
                re.IGNORECASE,
            )
            for l in lines:
                m = pattern.search(l)
                if m:
                    inad_val += _num(m.group(1))

        # ── Banco ─────────────────────────────────────────────────────────────
        banco_cc = banco_cdb = 0.0
        for i, l in enumerate(lines):
            if "ITAU" in l.upper() and "CORRENTE" in l.upper() and "AGENCIA" in l.upper():
                for ll in lines[i + 1: i + 6]:
                    if "SALDO CORRENTE" in ll.upper():
                        nums = _find_br(ll)
                        if nums:
                            banco_cc = nums[0]
                    elif "SALDO APLICACAO" in ll.upper() or "CDB DI" in ll.upper():
                        nums = _find_br(ll)
                        if nums:
                            banco_cdb = nums[0]
                break

        # ── Despesas — TOTAL DA CONTA ─────────────────────────────────────────
        cat_map: dict[str, str] = {**_CAT_MAP_DEFAULT, **self.parser_config.get("cat_map", {})}
        categorias: dict[str, float] = {}
        desp_total = 0.0

        for l in lines:
            # "TOTAL DA CONTA PESSOAL 87.573,62 51,83%"
            m = re.match(r"TOTAL\s+DA\s+CONTA\s+(.+?)\s+(\d[\d.,]+)\s+\d+", l)
            if not m:
                m = re.match(r"TOTAL\s+DA\s+CONTA\s+(.+?)\s+(\d[\d.,]+)\s*$", l)
            if m:
                nome_bruto = m.group(1).strip().upper()
                valor = _num(m.group(2))
                if nome_bruto in _EXCLUIR_TOTAIS:
                    continue
                nome_can = cat_map.get(nome_bruto, nome_bruto)
                categorias[nome_can] = categorias.get(nome_can, 0.0) + valor

            m2 = re.match(r"TOTAL\s+DAS\s+DESPESAS\s+(\d[\d.,]+)", l)
            if m2:
                desp_total = _num(m2.group(1))

        if not desp_total and categorias:
            desp_total = round(sum(categorias.values()), 2)

        # ── Montar DadosFinanceiros ───────────────────────────────────────────
        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
            receita_prevista=prev,
            # receita_realizada = tCred contábil (usado como tCred no BAL)
            receita_realizada=t_cred,
            # receita_cotas = Realizado do Resumo de Emissões (usado como 'real' no BAL)
            receita_cotas=real,
            despesa_total=desp_total,
            saldo_anterior=t_ant,
            saldo_atual=t_atual,
            inadimplencia_valor=inad_val,
            inadimplencia_recebida=inadProc_val,
            categorias_despesa=categorias,
            contas_detalhe=contas_detalhe,
            banco_cc=banco_cc,
            banco_cdb=banco_cdb,
            banco_priv=0.0,
            fac=0.0,
        )
        return dados
