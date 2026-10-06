"""
Extrator das regras gerais — Plano & Estação Campo Limpo - Serra Ribeiro I (administradora Foccus Gestão Condominial,
sistema Consvicta "W0xx"). Cadastrado como lirba_pdf no condominios.json, mas o PDF é a Pasta Digital da Foccus
(180-275 páginas, texto extraível; comprovantes W061A ocupam quase tudo).

Telas usadas (14 meses, abr/2025-jun/2026; falta o PDF de out/2025):
  W020C  "Demonstrativo de Despesas Analítico" (pág. 6-8): grupo (Com Pessoal, Mensais, Manutenção, Diversas) > subconta
         (Salário, Energia elétrica, Elevador...) > uma linha por lançamento "FORNECEDOR histórico [doc NF-xxx] valor";
         linhas que quebram continuam na margem; "Total de <subconta>" e "Total de <grupo>"; fecha em "Total de Despesas".
         O demonstrativo é CONSOLIDADO (todas as contas juntas): o arquivo não diz de qual conta (ORDINARIA, CONTAS DE
         CONSUMO...) cada lançamento saiu — `conta` = "CONSOLIDADO".
  W020B  "Demonstrativo de Receitas Analítico" (pág. 5): grupo (Cotas do Mês, Tarifa bancária, Gás, Fundo de Reserva, Rendimentos...)
         > linhas "N cobranças | competência | valor" (negativos entre parênteses, ex.: "(4,00)").
  W016B  "Resumo Financeiro" (última página; SÓ nos PDFs de 2026): por conta (ORDINARIA, FUNDO DE RESERVA, LOCAÇÃO - SALÃO DE FESTAS,
         VAGA ESTACIONAMENTO, CONTAS DE CONSUMO, MERCADINHO, FEIRA/EVENTOS) Saldo ant., Créditos*, Débitos*, Saldo final.
Conferências (viram `avisos`): Σ lançamentos == "Total de Despesas"; Σ receitas == "Total de Receitas";
Σ por subconta/grupo == total impresso; (2026) Σ lançamentos == Σ Débitos do W016B.
"""
import re
from pathlib import Path

from conciliacao.regras_gerais.extratores.top_nine import (_CENT, _linhas, _marca_parcela, _norm, _num, _texto, _tipo_receita,
                                                           aplicar_config_receitas_negativas)
from conciliacao.regras_gerais.modelo import ContaMes, DadosRegras, LancamentoDespesa, LinhaReceita

_CONTA = "CONSOLIDADO"


def _valor_direita(ws, x_min=500):
    return next((w for w in reversed(ws) if _num(w[4]) is not None and w[0] > x_min), None)


class Extrator:
    def __init__(self, condo: dict):
        self.condo = condo

    def extrair(self, caminho: Path, mes: str) -> DadosRegras:
        import fitz

        dados = DadosRegras(mes=mes, arquivo=Path(caminho).name)
        doc = fitz.open(str(caminho))
        try:
            n = len(doc)
            topo = {}
            for i in range(min(n, 14)):
                m = re.search(r"\bW\d{3}[A-Z]\b", doc[i].get_text()[:200])
                if m:
                    topo.setdefault(m.group(0), []).append(i)
            totais: dict = {}
            self._despesas(doc, topo.get("W020C", []), dados, totais)
            self._receitas(doc, topo.get("W020B", []), dados, totais)
            contas = self._resumo(doc)
        finally:
            doc.close()
        dados.contas = contas
        self._conferir(dados, contas, totais)
        dados.cobertura = {"receitas": bool(dados.receitas), "rendimentos": False, "lancamentos": bool(dados.lancamentos)}
        if not dados.receitas:
            dados.motivos_nao_cobertos["receitas"] = "a tela W020B (Demonstrativo de Receitas Analítico) não foi encontrada neste PDF"
        if not dados.lancamentos:
            dados.motivos_nao_cobertos["lancamentos"] = "a tela W020C (Demonstrativo de Despesas Analítico) não foi encontrada neste PDF"
        dados.motivos_nao_cobertos["rendimentos"] = (
            "o demonstrativo da Foccus é consolidado: o rendimento das aplicações ('REND PAGO APLIC AUT...', centavos por linha) vem "
            "num único grupo 'Rendimentos' sem dizer em qual conta foi creditado, e o Resumo Financeiro (W016B, só nos PDFs de 2026) "
            "traz apenas o total de créditos de cada conta — não dá para conferir a distribuição entre contas")
        aplicar_config_receitas_negativas(dados, self.condo)
        return dados

    # ── W020C ────────────────────────────────────────────────────────────────
    # A hierarquia do W020C não é confiável (subconta com UMA linha não imprime "Total de ..."; "Imposto" abre uma subconta e
    # "Retenção ISS", "Darf", "Taxa de Elevadores" aparecem MAIS à esquerda dentro dela). A categoria do lançamento é, portanto,
    # o ÚLTIMO cabeçalho (subconta folha) impresso antes dele: linha sem valor fora da margem.
    def _despesas(self, doc, paginas, dados, totais):
        if not paginas:
            return
        folha = ""
        cur = None
        i = paginas[0]
        while i < len(doc):
            fim = False
            for yc, ws in _linhas(doc[i]):
                if yc > 770:
                    continue
                t = _texto(ws)
                tn = _norm(t)
                x0 = ws[0][0]
                vt = _valor_direita(ws)
                if tn.startswith(("W020C", "DEMONSTRATIVO DE DESPESAS", "ENTRE ", "DESPESAS DOCUMENTO")) and vt is None:
                    continue
                if _norm(" ".join(w[4] for w in ws if w is not vt)) == "TOTAL DE DESPESAS":   # exato: "Total de Despesas judiciais" é de subconta
                    totais["despesas"] = vt and _num(vt[4])
                    fim = True
                    break
                if tn.startswith("TOTAL DE"):
                    cur = None
                    nome = re.sub(r"\s*-?[\d.]+,\d{2}$", "", re.sub(r"^Total de\s+", "", t, flags=re.I)).strip()
                    if vt is not None:
                        totais.setdefault("subtotais", []).append((nome, _num(vt[4])))
                    continue
                if vt is not None:
                    cur = {"tokens": [w[4] for w in ws if w is not vt], "valor": _num(vt[4]), "cat": folha,
                           "pagina": i + 1, "bbox": (ws[0][0], min(w[1] for w in ws), vt[2], max(w[3] for w in ws))}
                    cur["obj"] = self._lanc(cur)
                    dados.lancamentos.append(cur["obj"])
                    continue
                if x0 < 36 and cur is not None:                      # continuação de uma linha que quebrou (margem)
                    cur["tokens"].extend(w[4] for w in ws)
                    cur["obj"].descricao = _marca_parcela(re.sub(r"\s+", " ", " ".join(cur["tokens"])).strip())
                    continue
                cur = None
                folha = t.strip()
            i += 1
            if fim or i - paginas[0] > 6:
                break

    @staticmethod
    def _lanc(c) -> LancamentoDespesa:
        desc = re.sub(r"\s+", " ", " ".join(c["tokens"])).strip()
        # "Documento" (NF-160, NF-9373) vem solto numa coluna: fica no fim da descrição, como impresso
        return LancamentoDespesa(
            descricao=_marca_parcela(desc), valor=c["valor"], categoria=c["cat"], conta=_CONTA, codigo=None, data=None,
            pagina=c["pagina"], bbox=c["bbox"])

    # ── W020B ────────────────────────────────────────────────────────────────
    def _receitas(self, doc, paginas, dados, totais):
        if not paginas:
            return
        folha = ""
        i = paginas[0]
        while i < len(doc):
            fim = False
            for yc, ws in _linhas(doc[i]):
                if yc > 770:
                    continue
                t = _texto(ws)
                tn = _norm(t)
                vt = _valor_direita(ws)
                if tn.startswith(("W020B", "DEMONSTRATIVO DE RECEITAS", "ENTRE ", "RECEITAS COMPETENCIA")) and vt is None:
                    continue
                if _norm(" ".join(w[4] for w in ws if w is not vt)) == "TOTAL DE RECEITAS":   # exato: "Total de Receitas Diversas" é de grupo
                    totais["receitas"] = vt and _num(vt[4])
                    fim = True
                    break
                if tn.startswith("TOTAL DE"):
                    nome = re.sub(r"\s*-?\(?[\d.]+,\d{2}\)?$", "", re.sub(r"^Total de\s+", "", t, flags=re.I)).strip()
                    totais.setdefault("subtotais_rec", []).append((nome, _num(vt[4]) if vt else None))
                    continue
                if vt is None:
                    folha = t.strip()
                    continue
                comp = next((w[4] for w in ws if re.fullmatch(r"\d{2}/\d{4}", w[4]) or w[4].lower() == "acordo"), None)
                desc = " ".join(w[4] for w in ws if w is not vt and w[4] != comp).strip()
                dados.receitas.append(LinhaReceita(
                    conta=_CONTA, descricao=f"{folha} - {desc}" + (f" ({comp})" if comp else ""), valor=_num(vt[4]),
                    tipo=_tipo_receita(folha), pagina=i + 1,
                    bbox=(ws[0][0], min(w[1] for w in ws), vt[2], max(w[3] for w in ws))))
            i += 1
            if fim or i - paginas[0] > 3:
                break

    # ── W016B (só 2026) ──────────────────────────────────────────────────────
    def _resumo(self, doc) -> list:
        contas: list[ContaMes] = []
        n = len(doc)
        for i in range(n - 1, max(n - 4, 0), -1):
            if not re.search(r"Resumo Financeiro", doc[i].get_text()[:400]):
                continue
            em = False
            for yc, ws in _linhas(doc[i]):
                tn = _norm(_texto(ws))
                if tn.startswith("CONTA SALDO ANT"):
                    em = True
                    continue
                if not em:
                    continue
                if tn.startswith("SALDO FINAL"):
                    break
                nums = [_num(w[4]) for w in ws if _num(w[4]) is not None]
                nome = " ".join(w[4] for w in ws if _num(w[4]) is None).strip()
                if len(nums) == 4 and nome:
                    contas.append(ContaMes(nome=nome, saldo_anterior=nums[0], creditos=nums[1], debitos=abs(nums[2]),
                                           saldo_atual=nums[3], pagina=i + 1))
                elif len(nums) == 4 and not nome:
                    pass
                elif len(nums) == 0 and nome and not nome.startswith("(*)"):
                    # nome da conta quebrado em duas linhas ("LOCACAO - SALAO DE FESTAS/" + "CHURRASQUEIRA"): concatena na anterior
                    if contas and contas[-1].nome.endswith("/"):
                        contas[-1].nome += nome
            break
        return contas

    # ── conferências ─────────────────────────────────────────────────────────
    def _conferir(self, dados, contas, totais):
        s_des = round(sum(l.valor for l in dados.lancamentos), 2)
        if totais.get("despesas") is not None and abs(s_des - totais["despesas"]) > _CENT:
            dados.avisos.append(f"Σ lançamentos lidos ({s_des:,.2f}) difere de 'Total de Despesas' ({totais['despesas']:,.2f})")
        s_rec = round(sum(r.valor for r in dados.receitas), 2)
        if totais.get("receitas") is not None and abs(s_rec - totais["receitas"]) > _CENT:
            dados.avisos.append(f"Σ receitas lidas ({s_rec:,.2f}) difere de 'Total de Receitas' ({totais['receitas']:,.2f})")
        por_nome: dict[str, list] = {}
        for nome, v in totais.get("subtotais", []):
            if v is not None:
                por_nome.setdefault(_norm(nome), []).append(v)
        for nome_n, valores in por_nome.items():
            soma = round(sum(l.valor for l in dados.lancamentos if _norm(l.categoria) == nome_n), 2)
            # (um nome pode ser subconta E grupo — "Manutenção": só é inconsistência se as linhas somam MAIS que todos os totais impressos)
            if any(_norm(l.categoria) == nome_n for l in dados.lancamentos) and soma > max(valores) + _CENT:
                dados.avisos.append(f"subconta {nome_n.title()}: lançamentos somam {soma:,.2f}, totais impressos {', '.join(f'{v:,.2f}' for v in valores)}")
        if contas:
            deb = round(sum(c.debitos for c in contas), 2)
            cred = round(sum(c.creditos for c in contas), 2)
            d_deb, d_cred = round(deb - s_des, 2), round(cred - s_rec, 2)
            if abs(d_deb - d_cred) <= _CENT and abs(d_deb) > _CENT:
                # o "(*) Inclui transferência entre contas" do W016B soma a mesma transferência nos Débitos* e nos Créditos*
                dados.avisos.append(f"Débitos* e Créditos* do Resumo Financeiro excedem os lançamentos/receitas lidos em {d_deb:,.2f} nos dois lados: "
                                    "transferência entre contas incluída no resumo (*), não é despesa nem receita")
            else:
                if abs(d_deb) > _CENT:
                    dados.avisos.append(f"Σ lançamentos ({s_des:,.2f}) difere da Σ Débitos* do Resumo Financeiro ({deb:,.2f})")
                if abs(d_cred) > _CENT:
                    dados.avisos.append(f"Σ receitas ({s_rec:,.2f}) difere da Σ Créditos* do Resumo Financeiro ({cred:,.2f})")
