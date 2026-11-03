"""
Conciliador específico — I-Gloo Alphaville (administradora HSA Condomínios,
sistema GCONT/"W061A").

Cadastrado como "lirba_pdf", mas o PDF é do mesmo sistema do Club Park
Butantã: uma página "Comprovantes de despesas" (texto nativo, "Parcela
<código>", "Pago a:", "Destina-se a:") por pagamento. O parser ContasData
devolvia 0 registros. Reaproveita o parser GCONT via _gcont_comum.py.

Diferença para o Club Park/Saint Afonso: o HSA NÃO traz o Livro Caixa
"N itens VALOR". O fechamento independente vem dos "Demonstrativo Analítico"
de cada conta ("Ordinária", "Gás", "Água", ...), cada um terminando em
"Total de DESPESAS ... VALOR". Confirmado em jul/2026: 137.055,62 (Ordinária)
+ 26.763,57 (Gás) + 14.948,94 (Água) = 178.768,13 = soma das 73 capas.
Esse total vira um registro "total_demonstrativos_declarado" (nome distinto
de "total_declarado" de propósito: o render compara "total_declarado" com o
total do Demonstrativo Resumido e geraria falso achado aqui). Se nenhum total
for lido, não é emitido (não inventa).
"""
import re
from pathlib import Path

from conciliacao.base import RegistroComprovante
from conciliacao.condominios._gcont_comum import ConciliadorGcontNativo
from conciliacao.condominios.club_park_butanta import _num

_RE_SECAO = re.compile(r'Demonstrativo Anal[ií]tico\s+"([^"]+)"')
_RE_TOTAL_DESP = re.compile(r"Total de DESPESAS\s*\n(.{0,80})", re.DOTALL)
_RE_VALOR = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})*,\d{2})(?![\d%])")


def _totais_demonstrativos(caminho: Path) -> list[tuple[int, str, float]]:
    """[(pagina, conta, total_despesas)] dos Demonstrativos Analíticos."""
    import fitz

    out = []
    with fitz.open(str(caminho)) as doc:
        secao = None
        for i, page in enumerate(doc):
            t = page.get_text()
            if "Comprovantes de despesas" in t:
                break  # a parte financeira termina antes das capas
            m = _RE_SECAO.search(t)
            if m:
                secao = m.group(1)
            if secao is None:
                continue
            for mt in _RE_TOTAL_DESP.finditer(t):
                v = _RE_VALOR.search(mt.group(1))
                if v:
                    out.append((i + 1, secao, _num(v.group(1))))
                    break  # um total de despesas por seção
            # Cada Demonstrativo Analítico fecha com "Mov. Líquido(Receitas-Despesas) ... Saldo em dd/mm". Depois
            # disso, qualquer "Total de DESPESAS" é de OUTRA tabela (ex.: o Comparativo mês x mês, que em 11/2025
            # trazia o total do mês anterior e foi lido como se fosse da seção Benfeitorias).
            if "Mov. Líquido" in t:
                secao = None
    return out


_RE_DATA_CURTA = re.compile(r"^\d{2}/\d{2}/\d{2}$")
_RE_VALOR_LINHA = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")
_RE_ITENS = re.compile(r"^\d+ itens$")
_RODAPE_HSA = ("HSA CONDOM", "Rua da Consola", "(11) 3125", "Doc.", "Liquid.", "Fornecedor", "Ch.", "Valor liqu")


def _lancamentos_despesas_liquidadas(caminho: Path) -> list[RegistroComprovante]:
    """Arquivo reduzido da HSA (sem as capas "Comprovantes de despesas"): a listagem "Despesas liquidadas" (W014C) traz uma linha por
    pagamento — [doc], data de liquidação, fornecedor (1 a 3 linhas), [cheque], valor — e fecha com "N itens TOTAL". Cada linha vira um
    lançamento listado (sem comprovante), para a soma e a duplicidade poderem ser conferidas."""
    import fitz

    saida: list[RegistroComprovante] = []
    with fitz.open(str(caminho)) as doc:
        dentro = False
        estado, doc_nf, data, forn = "pre", [], None, []
        for i, page in enumerate(doc):
            for bruto in page.get_text().splitlines():
                linha = bruto.strip()
                if "Despesas liquidadas" in linha:
                    dentro = True
                    continue
                if not dentro:
                    continue
                if _RE_ITENS.match(linha):
                    return saida
                if not linha or linha.startswith(_RODAPE_HSA) or linha.startswith("W0") or linha.startswith("Entre "):
                    continue
                if estado == "pre":
                    if _RE_DATA_CURTA.match(linha):
                        data, forn, estado = linha, [], "forn"
                    else:
                        doc_nf.append(linha)
                elif estado == "forn":
                    if _RE_VALOR_LINHA.match(linha):
                        valor = _num(linha)
                        nome = " ".join(forn).strip()
                        saida.append(RegistroComprovante(
                            pagina=i + 1, tipo_documento="despesa_listada", codigo=str(len(saida) + 1), descricao=nome, fornecedor=nome,
                            vencimento=data, pagamento=data, valor=valor, autenticacao=(doc_nf[-1] if doc_nf else None),
                            texto_bruto=f"{data} | {nome} | {linha}"))
                        estado, doc_nf, data, forn = "pre", [], None, []
                    else:
                        forn.append(linha)
    return saida


def _registros_demonstrativo_analitico(caminho: Path, config: dict) -> tuple[list, list]:
    """Arquivo reduzido da HSA de set/2026 (17 páginas: só os "Demonstrativo Analítico" de cada conta + Resumo Financeiro, sem as capas de comprovante
    nem a listagem "Despesas liquidadas"): cada lançamento do Demonstrativo vira uma `despesa_listada` (fornecedor, data de liquidação, valor, documento)
    e as linhas que trazem o link público do portal da HSA (Superlógica: ".../areadocondomino/publico/arquivos?...idParcela=...") para os documentos do
    pagamento seguem para `_anexar_comprovantes_do_portal`. Devolve (registros, linhas com link)."""
    import fitz

    from conciliacao.condominios.club_park_butanta import _margem
    from conciliacao.regras_gerais.extratores.i_gloo_alphaville import Extrator

    dados = Extrator(config).extrair(caminho, "")
    registros: list[RegistroComprovante] = []
    linhas: list = []
    with fitz.open(str(caminho)) as doc:
        for n, l in enumerate(dados.lancamentos, start=1):
            forn = re.sub(r"\s+(?:[A-Za-zçÇãÃ]+/\d{4}|Parc\.\s*\d+\s*de\s*\d+)\s*$", "", (l.descricao or "")).strip()
            forn = re.sub(r"\s+NF-.*$", "", forn).strip() or (l.descricao or "")
            reg = RegistroComprovante(
                pagina=l.pagina, tipo_documento="despesa_listada", codigo=f"L{n:03d}", descricao=(l.descricao or "")[:200], fornecedor=forn,
                vencimento=None, pagamento=l.data, valor=l.valor, autenticacao=l.codigo or None,
                texto_bruto=f"[W020A] {l.descricao} {l.data} {l.valor:,.2f}", bbox_crop=_margem(l.bbox))
            registros.append(reg)
            uri = None
            if l.bbox and l.pagina:
                topo, base = l.bbox[1], l.bbox[3]
                for lk in doc[l.pagina - 1].get_links():
                    u = lk.get("uri") or ""
                    if "idParcela=" in u and lk["from"][3] >= topo - 2 and lk["from"][1] <= base + 2:
                        uri = u
                        break
            linhas.append({"data": l.data, "desc": forn, "valor": l.valor, "uri": uri, "pagina": l.pagina})
    # um pagamento só (mesmo link do portal, mesmo fornecedor) que quita 2+ lançamentos do Demonstrativo (ex.: a transferência de R$ 472,35 à HSA que paga
    # três despesas; o boleto de R$ 305,99 da Eletrocol que paga duas notas): uma linha por pagamento, com a SOMA — o anexador a reparte entre os lançamentos
    from conciliacao import portal_gcont
    from conciliacao.condominios.club_park_butanta import _norm_forn

    grupos: dict = {}
    for l in linhas:
        if l["uri"]:
            grupos.setdefault((portal_gcont.id_parcela(l["uri"]), _norm_forn(l["desc"])[:10]), []).append(l)
    for g in grupos.values():
        if len(g) >= 2:
            g[0]["valor"] = round(sum(x["valor"] for x in g), 2)
            for x in g[1:]:
                linhas.remove(x)
    return registros, linhas


class Conciliador(ConciliadorGcontNativo):
    def extrair_comprovantes(self, caminho) -> list:
        registros = super().extrair_comprovantes(caminho)
        if not any(r.tipo_documento == "despesa_com_comprovante" for r in registros):
            try:
                registros = registros + _lancamentos_despesas_liquidadas(Path(caminho))
            except Exception as exc:
                print(f"[AVISO] não foi possível ler a listagem 'Despesas liquidadas': {exc}")
            if not any(r.tipo_documento == "despesa_listada" for r in registros):
                # variante reduzida de set/2026: Demonstrativo Analítico + links do portal com os comprovantes
                try:
                    regs, linhas = _registros_demonstrativo_analitico(Path(caminho), self.config)
                    registros = registros + regs
                    if any(l["uri"] for l in linhas):
                        from conciliacao.condominios.club_park_butanta import _anexar_comprovantes_do_portal

                        _anexar_comprovantes_do_portal(Path(caminho), None, registros, linhas=linhas)
                        if any(r.tipo_documento == "comprovante_anexado" for r in registros):
                            # tarifa debitada pelo banco não tem documento no portal: sai da conferência de comprovantes (como no Club Park)
                            registros[:] = [r for r in registros if not (r.tipo_documento == "despesa_listada" and (r.fornecedor or "").strip().lower().startswith("banco "))]
                except Exception as exc:
                    print(f"[AVISO] não foi possível ler o Demonstrativo Analítico/links do portal: {exc}")
            return registros
        if any(r.tipo_documento == "total_declarado" for r in registros):
            return registros
        try:
            totais = _totais_demonstrativos(Path(caminho))
        except Exception:
            totais = []
        if totais:
            partes = "; ".join(f"{c}: {v:,.2f}" for _, c, v in totais)
            registros.append(RegistroComprovante(
                pagina=totais[0][0],
                tipo_documento="total_demonstrativos_declarado",
                valor=round(sum(v for _, _, v in totais), 2),
                descricao=f"Total de DESPESAS dos Demonstrativos Analíticos ({partes})",
                texto_bruto=partes,
            ))
        return registros
