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
import re
from pathlib import Path

MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez"]

# Convenções de nome de arquivo observadas nas pastas de projeto reais:
#   "Prestação de Contas 07.2026.pdf"      -> MM.YYYY
#   "prestacao_contas_7_2026.xlsx"          -> M_YYYY (sem zero à esquerda)
#   "prestacaocontas_1779_2026_07.xls"      -> YYYY_MM no final
_RE_MES_ANO_PATTERNS = [
    re.compile(r'(\d{1,2})\.(\d{4})(?!\d)'),
    re.compile(r'(?<!\d)(\d{1,2})_(\d{4})(?!\d)'),
    re.compile(r'(\d{4})_(\d{1,2})(?!\d)(?=\D*$)'),
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
        else:  # MM.YYYY ou M_YYYY
            mes, ano = int(g1), int(g2)
        if 1 <= mes <= 12 and 2000 <= ano <= 2100:
            return mes, ano
    return None


def localizar_arquivo_mes(pasta: Path, mes: int, ano: int) -> Path | None:
    """
    Procura, na mesma pasta do arquivo do mês atual, um arquivo de outro
    mês/ano (mesma convenção de nome, extensões de prestação de contas
    conhecidas). Usado pra achar o "mês anterior" automaticamente, sem
    precisar que o usuário envie os dois arquivos toda vez.
    """
    if not pasta.is_dir():
        return None
    extensoes = {".pdf", ".xlsx", ".xls"}
    candidatos = []
    for arq in pasta.iterdir():
        if not arq.is_file() or arq.suffix.lower() not in extensoes:
            continue
        achado = _extrair_mes_ano(arq.name)
        if achado == (mes, ano):
            candidatos.append(arq)
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
    from adapters import get_adapter

    try:
        adapter = get_adapter(condo["empresa_gestora"], condo)
        if caminho_arquivo.suffix.lower() in (".xlsx", ".xls"):
            dados = adapter.ler_xlsx(caminho_arquivo, mes_referencia)
        else:
            dados = adapter.ler_pdf(caminho_arquivo, mes_referencia)
    except Exception as exc:
        print(f"[AVISO] não foi possível ler dados financeiros de {caminho_arquivo.name}: {exc}")
        return None
    return _dados_financeiros_para_bal(dados, mes_titulo, periodo)


def ler_par_mes_atual_anterior(condo: dict, caminho_mes_atual: Path, mes_referencia: str,
                                mes_titulo: str, periodo: str) -> tuple[dict | None, dict | None]:
    """
    Lê o mês atual (arquivo já em mãos) e tenta localizar + ler o mês
    anterior automaticamente na MESMA pasta (pasta de projeto de onde o
    arquivo do mês atual veio). Retorna (dados_atual, dados_anterior) —
    qualquer um dos dois pode vir None se não for possível ler.
    """
    dados_atual = ler_dados_arquivo(condo, caminho_mes_atual, mes_referencia, mes_titulo, periodo)

    achado = _extrair_mes_ano(caminho_mes_atual.name)
    dados_anterior = None
    if achado:
        mes_atual_num, ano_atual = achado
        mes_ant_num, ano_ant = _mes_anterior_num(mes_atual_num, ano_atual)
        arquivo_anterior = localizar_arquivo_mes(caminho_mes_atual.parent, mes_ant_num, ano_ant)
        if arquivo_anterior:
            mes_ref_anterior = f"{ano_ant}-{mes_ant_num:02d}"
            titulo_anterior = f"{MESES_ABREV[mes_ant_num - 1].capitalize()}/{ano_ant}"
            dados_anterior = ler_dados_arquivo(condo, arquivo_anterior, mes_ref_anterior, titulo_anterior, "")
        else:
            print(f"[AVISO] não achei o arquivo do mês anterior ({mes_ant_num:02d}/{ano_ant}) "
                  f"na pasta {caminho_mes_atual.parent} — Análise Financeira sairá sem comparação com o mês anterior.")

    return dados_atual, dados_anterior
