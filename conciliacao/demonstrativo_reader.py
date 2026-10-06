"""
Leitor de demonstrativo financeiro DIRETO DA PASTA DO PROJETO — substitui
conciliacao/bal_reader.py como fonte da seção "Análise Financeira" dos
relatórios de conciliação.

Por quê: bal_reader.py lia o `var BAL` já publicado no dashboard HTML —
mas isso faz a Análise Financeira depender de o dashboard já estar
atualizado com aquele mês, o que nem sempre é verdade (ex.: Baturité tinha
um mês de atraso, e o formato de origem mudou de XLSX pra PDF sem o
cadastro do condomínio ser atualizado). O sistema de validação não deve se
ancorar em dados do dashboard — deve ler os PDFs/XLSX da própria pasta de
prestação de contas, igual à conciliação de comprovantes já faz.

Reaproveita o MESMO adapter que cada condomínio já usa pra injeção mensal
(adapters.get_adapter), então nenhuma lógica de parsing é duplicada — só
converte o DadosFinanceiros resultante pro mesmo formato de dict que
conciliacao/analise_financeira.py::montar_analise() já espera (idêntico ao
shape do var BAL, pra não precisar mexer naquele módulo).
"""
from conciliacao.pdf_cache import pdf_plumber_aberto
import re
from pathlib import Path

MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez"]

# Convenções de nome de arquivo observadas nas pastas de projeto reais:
#   "Prestação de Contas 07.2026.pdf"      -> MM.YYYY
#   "prestacao_contas_7_2026.xlsx"          -> M_YYYY (sem zero à esquerda)
#   "prestacaocontas_1779_2026_07.xls"      -> YYYY_MM no final
#   "Prestacao de contas JUL 2026.pdf"      -> mês por extenso abreviado + ano (Reserva Verde)
#   "072026.pdf"                            -> MMYYYY colado (NYC Berrini)
_MESES_ABREV = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
                "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}
_RE_MES_ANO_PATTERNS = [
    re.compile(r'(\d{1,2})\.(\d{4})(?!\d)'),
    re.compile(r'(?<!\d)(\d{1,2})_(\d{4})(?!\d)'),
    re.compile(r'(\d{4})_(\d{1,2})(?!\d)(?=\D*$)'),
    re.compile(r'(?<![a-z])(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*[\s_.\-]+(\d{4})(?!\d)', re.IGNORECASE),
    re.compile(r'(?<!\d)(\d{2})(\d{4})(?!\d)'),
]


def _extrair_mes_ano(nome_arquivo: str) -> tuple[int, int] | None:
    """Acha (mês, ano) no nome do arquivo, testando as convenções conhecidas."""
    for i, pat in enumerate(_RE_MES_ANO_PATTERNS):
        m = pat.search(nome_arquivo)
        if not m:
            continue
        g1, g2 = m.groups()
        if i == 2:  # YYYY_MM
            ano, mes = int(g1), int(g2)
        elif i == 3:  # JUL 2026
            mes, ano = _MESES_ABREV[g1.lower()], int(g2)
        else:  # MM.YYYY, M_YYYY ou MMYYYY
            mes, ano = int(g1), int(g2)
        if 1 <= mes <= 12 and 2000 <= ano <= 2100:
            return mes, ano
    return None


def localizar_arquivo_mes(pasta: Path, mes: int, ano: int) -> Path | None:
    """
    Procura, na pasta do condomínio, um arquivo do mês/ano pedido (convenções
    de nome em `_RE_MES_ANO_PATTERNS`, extensões de prestação de contas
    conhecidas). Usado pra achar o "mês anterior" automaticamente, sem
    precisar que o usuário envie os dois arquivos toda vez.

    Procura primeiro na própria pasta; só se não achar, desce nas subpastas
    (Cap D'Antibes guarda por ano, em subpastas 2025 e 2026; NYC tem a subpasta
    "Pasta Digital" com o PDF completo ao lado do arquivo-resumo da raiz — a
    raiz tem prioridade).
    """
    if not pasta.is_dir():
        return None
    extensoes = {".pdf", ".xlsx", ".xls"}

    def _candidatos(arquivos):
        # "Validação Balancete - <Condomínio> MM.AAAA.pdf" é o RELATÓRIO gerado (às vezes salvo na
        # pasta do projeto), não a prestação de contas: nunca serve de arquivo do mês.
        return [a for a in arquivos
                if a.is_file() and a.suffix.lower() in extensoes
                and not a.name.lower().startswith(("validação balancete", "validacao balancete"))
                and _extrair_mes_ano(a.name) == (mes, ano)]

    candidatos = _candidatos(pasta.iterdir())
    if not candidatos:
        candidatos = _candidatos(a for a in pasta.rglob("*") if a.parent != pasta)
    if not candidatos:
        return None
    # Mais de um candidato (raro) — prefere o modificado mais recentemente
    # (mais provável de ser a versão final, não um rascunho antigo).
    return max(candidatos, key=lambda p: p.stat().st_mtime)


def _mes_anterior_num(mes: int, ano: int) -> tuple[int, int]:
    return (12, ano - 1) if mes == 1 else (mes - 1, ano)


def _dados_financeiros_para_bal(d, mes_titulo: str, periodo: str) -> dict:
    """Converte DadosFinanceiros (adapters/base.py) pro mesmo shape de dict
    que conciliacao/analise_financeira.py::montar_analise() espera (idêntico
    ao formato do var BAL do dashboard).

    tAnt/tCred/tDeb/tAtual são a SOMA de contas_detalhe, não os campos
    saldo_anterior/receita_realizada/despesa_total/saldo_atual do adapter
    (confirmado comparando com o var BAL já publicado: para Addomus, por
    exemplo, receita_realizada é só uma conta específica ("Garantidora"),
    bem menor que a soma real de créditos de todas as contas) — só cai pros
    campos do adapter quando o adapter não preenche contas_detalhe.
    """
    contas = [
        {
            "n": c.get("nome", c.get("nome_curto", "")),
            "a": c.get("saldo_ant", 0.0),
            "c": c.get("creditos", 0.0),
            "d": c.get("debitos", 0.0),
            "s": c.get("saldo_atual", 0.0),
        }
        for c in d.contas_detalhe
    ]
    if contas:
        tAnt = sum(c["a"] for c in contas)
        tCred = sum(c["c"] for c in contas)
        tDeb = sum(c["d"] for c in contas)
        tAtual = sum(c["s"] for c in contas)
    else:
        tAnt, tCred, tDeb, tAtual = d.saldo_anterior, d.receita_realizada, d.despesa_total, d.saldo_atual

    return {
        "tit": mes_titulo,
        "per": periodo,
        "tAnt": tAnt,
        "tCred": tCred,
        "tDeb": tDeb,
        "tAtual": tAtual,
        "contas": contas,
        "prev": d.receita_prevista,
        "real": d.receita_cotas or d.receita_realizada,
        "tDesp": d.despesa_total,
        "inad": d.inadimplencia_valor,
        "inadProc": d.inadimplencia_recebida,
        "banco": {"cc": d.banco_cc, "cdb": d.banco_cdb, "priv": d.banco_priv},
        "desp": [{"c": k, "v": v} for k, v in d.categorias_despesa.items()],
    }


def ler_dados_arquivo(condo: dict, caminho_arquivo: Path, mes_referencia: str,
                       mes_titulo: str = "", periodo: str = "") -> dict | None:
    """
    Lê os dados financeiros de UM arquivo de prestação de contas (PDF ou
    XLSX), via o adapter já usado pra injeção mensal do condomínio
    (adapters.get_adapter — mesma lógica de despacho da conciliação,
    incluindo overrides específicos por condomínio). Retorna None (não
    levanta exceção) se o adapter falhar — quem chama decide se omite a
    seção em vez de quebrar o relatório.
    """
    # Leitor PRÓPRIO da Validação (conciliacao/leitores_validacao): versões corrigidas
    # dos adaptadores, sem tocar nos adapters/ que a injeção dos dashboards usa.
    from conciliacao.leitores_validacao import get_leitor

    try:
        adapter = get_leitor(condo)
        if caminho_arquivo.suffix.lower() in (".xlsx", ".xls"):
            dados = adapter.ler_xlsx(caminho_arquivo, mes_referencia)
        else:
            dados = adapter.ler_pdf(caminho_arquivo, mes_referencia)
    except Exception as exc:
        print(f"[AVISO] não foi possível ler dados financeiros de {caminho_arquivo.name}: {exc}")
        return None

    # O adapter pode "ter sucesso" tecnicamente (sem lançar exceção) e ainda
    # assim não achar nada — confirmado em dados reais (Palm Beach): o
    # arquivo usado na conciliação é um export "GROUP condomínios" diferente
    # do que o adapter normalmente lê pra injeção mensal (nenhuma das seções
    # que ele procura, "Posição Financeira"/"Resumo Financeiro Contábil",
    # existe nesse arquivo) — sem essa checagem, o relatório mostrava R$ 0,00
    # em tudo como se fosse um saldo real, em vez de "não foi possível ler".
    if not dados.contas_detalhe and dados.saldo_atual == 0.0 and dados.receita_realizada == 0.0:
        print(f"[AVISO] {caminho_arquivo.name} não trouxe nenhum dado financeiro reconhecível "
              f"(adapter não encontrou as seções esperadas nesse arquivo) — tratando como falha de leitura.")
        return None

    bal = _dados_financeiros_para_bal(dados, mes_titulo, periodo)

    # A coluna "Débitos" de cada conta pode incluir transferências entre as
    # contas do próprio condomínio — mas só dá pra afirmar isso quando o PDF
    # diz (GCONT traz a nota de rodapé "(*) Inclui transferência entre
    # contas." no Resumo Financeiro). Cada administradora é diferente; sem o
    # marcador, a diferença entre débitos e despesas não tem causa conhecida
    # e o relatório não deve inventar uma (ver analise_financeira.py).
    bal["debitos_incluem_transferencias"] = False
    if caminho_arquivo.suffix.lower() == ".pdf":
        try:
            import pdfplumber
            with pdf_plumber_aberto(caminho_arquivo) as pdf:
                for pagina in pdf.pages[:15]:
                    if re.search(r"Inclui\s+transfer.ncia\s+entre\s+contas", pagina.extract_text() or "", re.IGNORECASE):
                        bal["debitos_incluem_transferencias"] = True
                        break
        except Exception:
            pass

    # Mesmo problema do previsto/realizado (ver conciliacao/analise_financeira.py):
    # inadimplencia_valor parte do default 0.0 da dataclass e só é sobrescrito
    # se o adapter achar a seção de devedores/cotas em aberto no arquivo — um
    # upload parcial (ex.: Central das Artes, só a listagem de despesas, sem
    # nenhuma seção de inadimplência) fica com 0.0 igual a um mês
    # genuinamente sem inadimplência, e não tem como saber a diferença só
    # pelo número. Confere direto no texto bruto do arquivo (só PDF — XLSX
    # não usa essa lógica de seção por texto) e trata como "não disponível"
    # (None) quando nenhum marcador de inadimplência aparece.
    if bal["inad"] == 0.0 and caminho_arquivo.suffix.lower() == ".pdf":
        try:
            import pdfplumber
            with pdf_plumber_aberto(caminho_arquivo) as pdf:
                texto_bruto = "\n".join(p.extract_text() or "" for p in pdf.pages).upper()
            marcadores = ("COTAS EM ABERTO", "DEVEDOR", "INADIMPL")
            if not any(m in texto_bruto for m in marcadores):
                bal["inad"] = None
        except Exception:
            pass

    return bal


def ler_par_mes_atual_anterior(condo: dict, caminho_mes_atual: Path, mes_referencia: str,
                                mes_titulo: str, periodo: str,
                                pasta_busca_anterior: Path | None = None) -> tuple[dict | None, dict | None]:
    """
    Lê o mês atual (arquivo já em mãos, sempre a cópia estável salva em
    version_dir/input/ — nunca falha por causa de um caminho temporário de
    upload que já foi limpo) e tenta localizar + ler o mês anterior
    automaticamente em `pasta_busca_anterior` (a pasta de projeto de onde o
    arquivo do mês atual veio ORIGINALMENTE, antes da cópia — pode não
    existir mais, ex.: upload via navegador sem pasta de projeto real por
    trás; nesse caso só a comparação com o mês anterior é pulada, não a
    leitura do mês atual). Retorna (dados_atual, dados_anterior) — qualquer
    um dos dois pode vir None se não for possível ler.

    O mês/ano do arquivo ATUAL vem de `mes_referencia` (sempre explícito,
    "YYYY-MM" — já é conhecido por quem chama, vindo do próprio fluxo de
    upload/versão), NUNCA de tentar re-descobrir pelo NOME do arquivo — um
    upload feito pelo Admin (plataforma web) salva a cópia com um nome
    genérico (ex.: "sc_conciliacao_<id>.pdf"), sem o padrão MM.YYYY que
    `_extrair_mes_ano` procura. Confirmado em dados reais (Ciudad Real,
    ago/2026) que isso fazia a comparação com o mês anterior falhar
    SILENCIOSAMENTE (nem o AVISO aparecia, porque também dependia do mesmo
    `achado`) pra qualquer arquivo vindo do Admin — não só quando a pasta
    original já não existe mais, que é o único caso que deveria pular a
    comparação.
    """
    dados_atual = ler_dados_arquivo(condo, caminho_mes_atual, mes_referencia, mes_titulo, periodo)

    pasta_busca = pasta_busca_anterior or caminho_mes_atual.parent
    ano_atual, mes_atual_num = int(mes_referencia[:4]), int(mes_referencia[5:7])
    mes_ant_num, ano_ant = _mes_anterior_num(mes_atual_num, ano_atual)
    dados_anterior = None
    if pasta_busca.is_dir():
        arquivo_anterior = localizar_arquivo_mes(pasta_busca, mes_ant_num, ano_ant)
        if arquivo_anterior:
            mes_ref_anterior = f"{ano_ant}-{mes_ant_num:02d}"
            titulo_anterior = f"{MESES_ABREV[mes_ant_num - 1].capitalize()}/{ano_ant}"
            dados_anterior = ler_dados_arquivo(condo, arquivo_anterior, mes_ref_anterior, titulo_anterior, "")
        else:
            print(f"[AVISO] não achei o arquivo do mês anterior ({mes_ant_num:02d}/{ano_ant}) "
                  f"na pasta {pasta_busca} — Análise Financeira sairá sem comparação com o mês anterior.")
    else:
        print(f"[AVISO] pasta original do upload ({pasta_busca}) não existe mais — "
              f"Análise Financeira sairá sem comparação com o mês anterior.")

    return dados_atual, dados_anterior
