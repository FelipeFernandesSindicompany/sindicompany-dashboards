"""
Conciliador específico — Moema Top Nine (administradora Conister, sistema GCONT "W0xx", "Pasta Digital").

Estrutura da pasta (ex.: 09.2026, 138 páginas): o "Demonstrativo de Despesas — Detalhado, com conta categoria" (texto, UMA linha por despesa:
"2.1.1  Salário Agosto/2026" + valor, sem código nem data) e, depois, as páginas "Comprovantes de despesas — Credt. em <mês>; Parcela NNNNN" ou
"...; Movimentação Direta NNNNN" (débito automático: Enel, Sabesp, Comgás, Vivo, tarifa). Cada pagamento tem uma CAPA em texto nativo ("Destina-se
a:" com o código da conta categoria, o complemento e o valor) seguida das páginas do anexo (nota fiscal, boleto, comprovante bancário), que são
IMAGENS sem texto.

Antes (set/2026 e antes) o conciliador só lia as capas e nunca olhava o anexo: o relatório saía com "0 problemas" sem ter conferido comprovante
nenhum, e as "Movimentação Direta" nem eram lidas. Agora:
  * cada linha do demonstrativo vira uma `despesa_listada` (código da conta categoria + valor + complemento);
  * é pareada com a CAPA que traz o mesmo código de categoria e o mesmo valor (uma capa pode cobrir mais de uma linha);
  * as páginas da capa (capa + anexos) viram o "comprovante" daquele pagamento e passam por toda a cadeia do formato Lirba/ContasData
    (OCR do anexo, valor lido na imagem, marcador de Nota Fiscal, conta de concessionária, atraso de pagamento).
Linha do demonstrativo sem capa = "sem comprovante" (a tarifa bancária debitada pelo banco é isenta pelo matching).
"""
import re
from pathlib import Path

from conciliacao.base import RegistroComprovante
from conciliacao.lirba_pdf import ConciliadorLirbaPDF

_RE_VALOR = re.compile(r"^-?[\d.]+,\d{2}$")
_RE_ITEM = re.compile(r"^(2\.\d+\.\d+)\s+(.+)$")
_RE_GRUPO = re.compile(r"^(2\.\d+)\s+(\D.*)$")
_RE_CHAVE_CAPA = re.compile(r"Credt\.\s+em [^;\n]+;\s*(Parcela|Movimenta[çc][ãa]o Direta)\s+(\d+)", re.IGNORECASE)
_RE_DATA = re.compile(r"\d{2}/\d{2}/\d{4}")


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _linhas(texto: str) -> list:
    return [l.strip() for l in (texto or "").split("\n") if l.strip()]


def _ler_itens(linhas: list, parar_em=("Valor Emitido", "Conister", "Total de ")) -> list:
    """[(código da conta categoria, complemento, valor, posição da linha)] — o valor é a primeira linha numérica depois do item."""
    itens = []
    atual = None
    for pos, l in enumerate(linhas):
        m = _RE_ITEM.match(l)
        if m:
            atual = [m.group(1), re.sub(r"\s+", " ", m.group(2)).strip(), None, pos]
            itens.append(atual)
            continue
        if atual is None:
            continue
        if l.startswith(parar_em) or re.search(r"\d+ de \d+$", l) and not _RE_VALOR.match(l):
            if atual[2] is None:
                atual = None
            continue
        if _RE_VALOR.match(l):
            if atual[2] is None:
                atual[2] = _num(l)
            continue
        if atual[2] is None:
            atual[1] = (atual[1] + " " + l).strip()
    return [(c, d, v, pos) for c, d, v, pos in itens if v is not None]


class Conciliador(ConciliadorLirbaPDF):
    def _extrair_despesas_listadas(self, caminho: Path):
        import fitz

        despesas: list[RegistroComprovante] = []
        capas: dict[str, dict] = {}          # chave -> {"paginas": [...], "itens": [(cod, desc, valor, pos)], "venc": str|None, "forn": str|None}
        total_declarado = None
        with fitz.open(str(caminho)) as doc:
            for i in range(len(doc)):
                texto = doc[i].get_text()
                cab = texto[:400]
                if "Comprovantes de despesas" in cab:
                    m = _RE_CHAVE_CAPA.search(cab)
                    if not m:
                        continue
                    chave = f"{'MD' if m.group(1).lower().startswith('mov') else 'P'}{m.group(2)}"
                    cp = capas.setdefault(chave, {"paginas": [], "itens": [], "venc": None, "forn": None})
                    cp["paginas"].append(i + 1)
                    if "Destina-se a" in texto and not cp["itens"]:
                        cp["itens"] = _ler_itens(_linhas(texto.split("Destina-se a:")[-1]))
                        ls = _linhas(texto.split("Destina-se a:")[0])
                        for k, l in enumerate(ls):
                            if l.startswith("Pago a:") and k + 1 < len(ls):
                                datas = _RE_DATA.findall(ls[k + 1])
                                if datas:
                                    cp["venc"] = datas[0]
                                    cp["forn"] = re.sub(r"\s+", " ", ls[k + 1].split(datas[0])[0]).strip() or None
                    continue
                if re.search(r'Demonstrativo de Despesas\s*"', cab) and "Detalhado" in cab:
                    conta = re.search(r'Demonstrativo de Despesas\s*"([^"]+)"', cab).group(1)
                    ls = _linhas(texto)
                    grupos_pos = []                       # [(posição da linha, nome do grupo)]
                    for k, l in enumerate(ls):
                        mg = _RE_GRUPO.match(l)
                        if mg and not _RE_ITEM.match(l):
                            grupos_pos.append((k, mg.group(2).strip()))
                        if l == "Total de Despesas" and k + 1 < len(ls) and _RE_VALOR.match(ls[k + 1]):
                            total_declarado = (total_declarado or 0.0) + _num(ls[k + 1])
                    for cod, desc, valor, pos in _ler_itens(ls):
                        grupo = next((g for k, g in reversed(grupos_pos) if k < pos), None)
                        despesas.append(RegistroComprovante(
                            pagina=i + 1, tipo_documento="despesa_listada", codigo=None, descricao=f"{cod} {desc}",
                            valor=valor, conta=conta, categoria_demonstrativo=grupo,
                            texto_bruto=f"{cod} {desc} {valor:,.2f}",
                        ))
                        despesas[-1].autenticacao = cod       # código da conta categoria: chave do pareamento com a capa

        # pareamento linha do demonstrativo x capa (código da conta categoria + valor)
        disponiveis = {ch: list(cp["itens"]) for ch, cp in capas.items()}
        paginas_por_codigo: dict[str, list[int]] = {}
        primeira: dict[str, int] = {}
        for n, d in enumerate(despesas, start=1):
            cod = d.autenticacao
            achada = None
            for ch, itens in disponiveis.items():
                for it in itens:
                    if it[0] == cod and abs(it[2] - d.valor) <= 0.01:
                        achada = (ch, it)
                        break
                if achada:
                    break
            d.autenticacao = None
            if achada is None:
                d.codigo = f"L{n:03d}"                          # sem capa: fica só a despesa listada (vira "sem comprovante")
                continue
            ch, it = achada
            disponiveis[ch].remove(it)
            d.codigo = ch
            cp = capas[ch]
            d.vencimento = cp["venc"]
            if cp["forn"]:
                d.fornecedor = cp["forn"]
                d.descricao = f"{d.descricao} - {cp['forn']}"
            paginas_por_codigo[ch] = list(cp["paginas"])
            primeira[ch] = cp["paginas"][0]
        sobras = [(ch, it) for ch, its in disponiveis.items() for it in its]
        if sobras:
            print(f"[AVISO] {len(sobras)} item(ns) de capa de comprovante sem linha correspondente no demonstrativo: "
                  + "; ".join(f"{ch} {it[0]} {it[2]:,.2f}" for ch, it in sobras[:6]))
        if total_declarado is not None and abs(total_declarado - sum(d.valor for d in despesas)) > 0.01:
            print(f"[AVISO] soma das linhas lidas ({sum(d.valor for d in despesas):,.2f}) difere do 'Total de Despesas' ({total_declarado:,.2f})")
        self._paginas_por_codigo = paginas_por_codigo
        return despesas, primeira
