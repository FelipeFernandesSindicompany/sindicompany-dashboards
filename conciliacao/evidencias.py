"""
Prints com destaque (ver render.preparar_evidencia_extra) montados
AUTOMATICAMENTE pra achados de nível agregado — os que comparam um TOTAL com
a soma de vários lançamentos e por isso não têm "um lançamento" pra mostrar.

Cada família de balancete tem o próprio padrão (onde fica o total declarado,
como a linha se chama), então o localizador é escolhido pela regra que gerou
o achado — nunca por um texto genérico:

  soma_comprovantes_diverge_total_livro_caixa          GCONT (Club Park Butantã)
  soma_lancamentos_diverge_total_da_conta_declarado    DataDigitus, Alliz,
                                                       Consvicta, Lello XLS,
                                                       Auxiliadora, uCondo…
  soma_secao_diverge_total_declarado_no_balancete      Iello/Lello PDF
  saldo_conta_nao_fecha_no_resumo_financeiro           Iello/Lello PDF
  soma_comprovantes_categoria_diverge_do_demonstrativo Addomus

As quatro primeiras guardam o TOTAL DECLARADO como um registro próprio
(tipo "*_declarado", com a página e o valor) — o print é a linha desse total
na página de origem. Addomus não tem esse registro: o valor esperado vem do
demonstrativo lido pelo adapter, então a linha é procurada nas primeiras
páginas pelo nome da categoria + valor. Se a linha não for achada, o achado
sai sem print (nunca com um print que não mostre o erro).

Um achado pode ter prints CURADOS à mão em <versão>/evidencias_extra.json
(ver gerar_relatorio_conciliacao.py) — esses têm prioridade sobre os
automáticos daqui.
"""
from conciliacao.pdf_cache import pdf_plumber_aberto
import re
from pathlib import Path

REGRAS_AGREGADAS = {
    "soma_comprovantes_diverge_total_livro_caixa",
    "soma_lancamentos_diverge_total_da_conta_declarado",
    "soma_secao_diverge_total_declarado_no_balancete",
    "saldo_conta_nao_fecha_no_resumo_financeiro",
    "soma_comprovantes_categoria_diverge_do_demonstrativo",
}

_LEGENDA = {
    "soma_comprovantes_diverge_total_livro_caixa": (
        'Livro Caixa (pág. {pag} do PDF): fechamento declarado = {decl}. '
        'Soma dos comprovantes extraídos: {enc}.'),
    "soma_lancamentos_diverge_total_da_conta_declarado": (
        'Total declarado da conta "{linha}" (pág. {pag} do PDF): {decl}. '
        'Soma dos lançamentos listados: {enc}.'),
    "soma_secao_diverge_total_declarado_no_balancete": (
        'Total declarado da seção "{linha}" (pág. {pag} do PDF): {decl}. '
        'Soma dos itens da seção: {enc}.'),
    "saldo_conta_nao_fecha_no_resumo_financeiro": (
        'Saldo final declarado da conta "{linha}" (pág. {pag} do PDF): {decl}. '
        'Saldo calculado a partir do saldo anterior, créditos e débitos: {enc}.'),
    "soma_comprovantes_categoria_diverge_do_demonstrativo": (
        'Demonstrativo (pág. {pag} do PDF): categoria "{linha}" = {decl}. '
        'Soma dos comprovantes pareados dessa categoria: {enc}.'),
}


def br(valor: float) -> str:
    """1234.5 -> '1.234,50' (o formato como aparece nos PDFs)."""
    return f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_r(valor: float) -> str:
    return "R$ " + br(valor)


def rx_valor(valor: float) -> str:
    """Regex do valor em formato BR, sem colar em outros números (ex.: 1.234,56
    não casa dentro de 11.234,56)."""
    return r"(?<![\d.,])" + re.escape(br(valor)) + r"(?!\d)"


def achar_pagina(pdf_origem: Path, regex: str, limite_paginas: int = 80,
                 parar_em: str | None = None) -> int | None:
    """Primeira página (1-based) cujo texto casa `regex`. `parar_em`: marcador
    de texto que encerra a busca (ex.: GCONT — as páginas de comprovante, que
    vêm depois de toda a parte financeira, não precisam ser varridas)."""
    import pdfplumber

    rx = re.compile(regex, re.IGNORECASE)
    with pdf_plumber_aberto(pdf_origem) as pdf:
        for i, page in enumerate(pdf.pages[:limite_paginas], start=1):
            texto = page.extract_text() or ""
            if parar_em and i > 1 and parar_em in texto:
                break
            if rx.search(texto):
                return i
    return None


def _pagina_contem(pdf_origem: Path, pagina: int, regex: str) -> bool:
    import pdfplumber

    try:
        with pdf_plumber_aberto(pdf_origem) as pdf:
            if not (1 <= pagina <= len(pdf.pages)):
                return False
            return re.search(regex, pdf.pages[pagina - 1].extract_text() or "", re.IGNORECASE) is not None
    except Exception:
        return False


def _localizar_total_declarado(pdf_origem: Path, decl) -> tuple[int, str] | None:
    """(página, regex) da linha do total declarado. A página guardada no
    registro só vale se o valor estiver mesmo nela — em alguns formatos
    (ex.: DataDigitus/Alliz) o total é SOMADO pelo extrator e `pagina` fica
    num valor padrão (1) sem relação com onde o total aparece. Nesse caso
    varre o PDF atrás da linha, preferindo uma que tenha a palavra "total"."""
    rx = rx_valor(decl.valor)
    if decl.pagina and _pagina_contem(pdf_origem, decl.pagina, rx):
        return decl.pagina, rx
    for regex in (r"total.*" + rx, rx):
        pagina = achar_pagina(pdf_origem, regex, limite_paginas=80)
        if pagina:
            return pagina, regex
    return None


def evidencias_agregadas(achado, registros_por_chave: dict, pdf_origem: Path) -> list[dict]:
    """Specs (formato de render.preparar_evidencia_extra) pro achado agregado,
    ou [] quando não há como localizar a linha com segurança."""
    regra = achado.regra_aplicada
    if regra not in _LEGENDA or pdf_origem is None:
        return []
    enc = fmt_r(achado.valor_encontrado) if achado.valor_encontrado is not None else "—"
    base = {"decl": fmt_r(achado.valor_esperado or 0.0), "enc": enc,
            "linha": achado.linha_demonstrativo or ""}

    if regra == "soma_comprovantes_categoria_diverge_do_demonstrativo":
        # Addomus: sem registro de total declarado — o valor esperado veio do
        # demonstrativo; procura "<categoria> ... <valor>" nas primeiras páginas.
        if not achado.valor_esperado or not achado.linha_demonstrativo:
            return []
        regex = re.escape(achado.linha_demonstrativo) + r".*" + rx_valor(achado.valor_esperado)
        pagina = achar_pagina(pdf_origem, regex, limite_paginas=60)
        if pagina is None:
            return []
        return [{"pagina": pagina, "buscar": regex, "linhas_contexto": 2,
                 "legenda": _LEGENDA[regra].format(pag=pagina, **base)}]

    declarados = [registros_por_chave.get(k) for k in achado.registros_relacionados]
    decl = next((r for r in declarados if r and (r.tipo_documento or "").endswith("_declarado")), None)
    if decl is None or decl.valor is None:
        return []
    achou = _localizar_total_declarado(pdf_origem, decl)
    if achou is None:
        return []
    pagina, regex = achou
    return [{"pagina": pagina, "buscar": regex, "linhas_contexto": 2,
             "legenda": _LEGENDA[regra].format(pag=pagina, **base)}]


def evidencias_resumido_x_livro_caixa(pdf_origem: Path, despesas_total: float, livro_caixa) -> list[dict]:
    """
    GCONT: prints do achado "Despesas por Categoria não bate com o Livro Caixa"
    (montado no render, ver gerar_relatorio_conciliacao.py): o "Total das
    Despesas" do Demonstrativo Resumido, o fechamento do Livro Caixa
    (`livro_caixa`: registro total_declarado) e — quando existe — a linha
    "N Itens Total" da tabela "Despesas por categoria", que mostra de que
    lado está a diferença. Só entra o print cuja linha foi de fato achada.
    """
    if pdf_origem is None or livro_caixa is None:
        return []
    marcador = "Comprovantes de despesas"
    textos: list[tuple[int, str, str]] = []  # (pagina, regex, legenda)

    p_resumido = achar_pagina(pdf_origem, r"Total das Despesas.*" + rx_valor(despesas_total),
                              limite_paginas=60, parar_em=marcador)
    if p_resumido:
        textos.append((p_resumido, r"Total das Despesas.*" + rx_valor(despesas_total),
                       f'Demonstrativo Resumido (pág. {p_resumido} do PDF): Total das Despesas = '
                       f'{fmt_r(despesas_total)} — é a base da tabela "Despesas por Categoria" deste relatório.'))
    if livro_caixa.pagina and livro_caixa.valor is not None:
        textos.append((livro_caixa.pagina, rx_valor(livro_caixa.valor),
                       f'Livro Caixa (pág. {livro_caixa.pagina} do PDF): fechamento = {fmt_r(livro_caixa.valor)}.'))
        regex_tabela = r"\d+\s+Itens\s+Total.*" + rx_valor(livro_caixa.valor)
        p_tabela = achar_pagina(pdf_origem, regex_tabela, limite_paginas=120, parar_em=marcador)
        if p_tabela and p_tabela != livro_caixa.pagina:
            diferenca = fmt_r(abs(despesas_total - livro_caixa.valor))
            origem = (f"a diferença de {diferenca} está só no total do Demonstrativo Resumido (1)"
                      if p_resumido else f"a diferença é de {diferenca}")
            textos.append((p_tabela, regex_tabela,
                           f'Tabela "Despesas por categoria" (pág. {p_tabela} do PDF): total = '
                           f'{fmt_r(livro_caixa.valor)}, igual ao Livro Caixa — {origem}.'))

    return [{"pagina": pag, "buscar": rx, "linhas_contexto": 2, "legenda": f"{n}) {leg}"}
            for n, (pag, rx, leg) in enumerate(textos, start=1)]


def termos_destaque(achado, registro) -> tuple[list[str], bool]:
    """
    (termos, linha_inteira) a marcar na evidência PRINCIPAL de um achado por
    lançamento — o que mostra ONDE está o erro:
      - divergência de valor: o valor lido no comprovante e o da listagem;
      - duplicidade: o valor repetido;
      - atraso de pagamento: as datas de vencimento e pagamento;
      - lançamento sem comprovante: a LINHA do lançamento na listagem
        (linha_inteira=True, achada pelo valor).
    Outros tipos (NF ausente, CNPJ...) não têm um texto a marcar — o erro é
    justamente algo que não está lá. Achados agregados usam evidencias_agregadas.
    """
    if achado.regra_aplicada in REGRAS_AGREGADAS:
        return [], False
    if achado.tipo == "divergencia_valor":
        return [br(v) for v in (achado.valor_encontrado, achado.valor_esperado) if v], False
    if achado.tipo == "duplicidade":
        v = achado.valor_encontrado or achado.valor_esperado
        return ([br(v)] if v else []), False
    if achado.tipo == "atraso_pagamento" and registro is not None:
        return [d for d in (registro.vencimento, registro.pagamento) if d], False
    if achado.tipo == "sem_comprovante" and registro is not None and registro.valor:
        return [br(registro.valor)], True
    return [], False
