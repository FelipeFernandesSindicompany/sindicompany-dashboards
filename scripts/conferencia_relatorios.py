"""Conferência mecânica dos PDFs de validação já gerados (só lê; não altera nada).

Para cada PDF "Validação Balancete - <Condomínio> MM.AAAA.pdf" das pastas de projeto:
  - cabeçalho: condomínio e mês batem com o nome do arquivo;
  - tabela "Situação Financeira por Conta": cada linha fecha (anterior + créditos - débitos = atual), o saldo consolidado do
    resumo bate com a soma dos saldos, o total de "Despesas por Categoria" bate com a soma das categorias;
  - os saldos de cada conta batem com a leitura independente do arquivo de origem (extrator das regras gerais);
  - texto: sem 'None', 'nan', '{{', 'undefined'; todo item termina com uma "Pergunta à administradora" que acaba em '?';
  - números: nenhum valor negativo sem sinal (compara as linhas com sinal da leitura independente);
Uso: python scripts/conferencia_relatorios.py [--desde AAAA-MM-DD] [id ...]
"""
import argparse
import glob
import json
import os
import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import fitz  # noqa: E402

from conciliacao import config_validacao, pasta_prestacao  # noqa: E402
from conciliacao.demonstrativo_reader import localizar_arquivo_mes  # noqa: E402
from conciliacao.regras_gerais.extratores import get_extrator  # noqa: E402

PROJETOS = Path.home() / "OneDrive - Perfil de E-mail" / "Documentos" / "Claude" / "Projects"
MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
RE_VALOR = re.compile(r"^R\$ (-?)(\d{1,3}(?:\.\d{3})*,\d{2})$")


def _v(s):
    m = RE_VALOR.match((s or "").strip())
    if not m:
        return None
    x = float(m.group(2).replace(".", "").replace(",", "."))
    return -x if m.group(1) else x


def _norm(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def tabela_contas(linhas):
    """Linhas (strings) -> [(conta, ant, cre, deb, atu)] da seção 'Situação Financeira por Conta'."""
    try:
        i = linhas.index("Situação Financeira por Conta")
    except ValueError:
        return None
    j = next((k for k in range(i, len(linhas)) if linhas[k] == "Despesas por Categoria"), len(linhas))
    corpo = linhas[i + 1:j]
    # cabeçalho: Conta / Saldo anterior / Créditos / Débitos / Saldo atual
    if corpo[:5] == ["Conta", "Saldo anterior", "Créditos", "Débitos", "Saldo atual"]:
        corpo = corpo[5:]
    out = []
    for k in range(0, len(corpo) - 4, 5):
        nome, *nums = corpo[k:k + 5]
        vs = [_v(x) for x in nums]
        if None in vs:
            return out or None
        out.append((nome, *vs))
    return out


def tabela_categorias(linhas):
    try:
        i = linhas.index("Despesas por Categoria")
    except ValueError:
        return None
    cats, total = [], None
    k = i + 1
    if linhas[k:k + 3] == ["Categoria", "Valor", "% do total"]:
        k += 3
    while k + 2 < len(linhas):
        if linhas[k] == "Total":
            total = _v(linhas[k + 1])
            break
        v = _v(linhas[k + 1])
        if v is None:
            break
        cats.append((linhas[k], v))
        k += 3
    return cats, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--desde", default="2026-10-15")
    a = ap.parse_args()
    corte = datetime.strptime(a.desde, "%Y-%m-%d").timestamp()
    condos = {c["id"]: c for c in json.load(open(RAIZ / "config" / "condominios.json", encoding="utf-8"))["condominios"]}
    por_nome = {_norm(c["nome"]): c for c in condos.values()}
    arquivos = sorted(glob.glob(str(PROJETOS / "*" / "Validação de Balancetes" / "Validação Balancete - * 0[5-9].2026*.pdf")))
    total_problemas = 0
    for f in arquivos:
        if os.path.getmtime(f) < corte:
            continue
        nome_arq = os.path.basename(f)
        m = re.match(r"Validação Balancete - (.+) (\d{2})\.(\d{4})(?: \(versão v\d+\))?\.pdf$", nome_arq)
        if not m:
            print(f"?? nome fora do padrão: {nome_arq}")
            continue
        nome_condo, mm, aaaa = m.group(1), int(m.group(2)), int(m.group(3))
        condo = por_nome.get(_norm(nome_condo)) or next((c for k, c in por_nome.items() if _norm(nome_condo) in k or k in _norm(nome_condo)), None)
        if a.ids and (condo is None or condo["id"] not in a.ids):
            continue
        doc = fitz.open(f)
        texto = "".join(p.get_text() for p in doc)
        linhas = [x.strip() for x in texto.splitlines() if x.strip()]
        probs = []
        if "(versão v" in nome_arq:
            probs.append("arquivo com sufixo (versão vN): existe outro relatório do mesmo mês na pasta")
        # cabeçalho
        cab = next((x for x in linhas if "· " in x and "/" in x and "Administradora" in x), "")
        if f"{MESES[mm]} / {aaaa}" not in cab:
            probs.append(f"cabeçalho não confere com o mês do arquivo ({cab!r})")
        if condo and _norm(condo["nome"]) not in _norm(cab):
            probs.append(f"nome do condomínio no cabeçalho difere do cadastro ({cab!r} x {condo['nome']!r})")
        # texto
        for pad in (r"\bNone\b", r"\bnan\b", r"\bNaN\b", r"\{\{", r"\}\}", r"undefined", r"R\$ R\$", r"R\$ -R\$", r"-R\$ -"):
            mm_ = re.search(pad, texto)
            if mm_:
                probs.append(f"texto suspeito {pad!r}: ...{texto[max(0, mm_.start() - 40):mm_.end() + 40]!r}")
        # itens e perguntas
        n_itens = len(re.findall(r"\n\d+\. [^\n]+\n(?:ATENÇÃO|ALTO|CRÍTICO|INFORMATIVO)", texto))
        perguntas = re.findall(r"Pergunta à administradora:(.*?)(?=\n\d+\. |\nAnexo de apoio|\Z)", texto, re.S)
        for p in perguntas:
            ult = re.split(r"@@|Página:", p)[0].strip()
            ult = re.split(r"\n\s*Demonstrativo de Despesas\s*\n\s*Página", ult)[0].strip()
            if not ult.rstrip().endswith("?"):
                probs.append(f"pergunta que não termina em '?': {ult[-80:]!r}")
        if n_itens and len(perguntas) < n_itens:
            probs.append(f"{n_itens} itens mas só {len(perguntas)} perguntas à administradora")
        # tabela de contas
        contas = tabela_contas(linhas)
        if contas:
            for nome, ant, cre, deb, atu in contas:
                dif = round(ant + cre - deb - atu, 2)
                if abs(dif) > 0.011:
                    probs.append(f"conta {nome}: anterior+créditos-débitos != atual (diferença {dif:,.2f}) — conferir se há transferência entre contas")
            mcons = re.search(r"O saldo consolidado do condomínio encerrou [^\n]*?em (R\$ -?[\d.]+,\d{2})", texto.replace("\n", " "))
            if mcons:
                cons = _v(mcons.group(1))
                soma = round(sum(c[4] for c in contas), 2)
                if cons is not None and abs(cons - soma) > 0.011:
                    probs.append(f"saldo consolidado do resumo ({cons:,.2f}) != soma dos saldos das contas ({soma:,.2f})")
        cats = tabela_categorias(linhas)
        if cats and cats[1] is not None:
            soma_c = round(sum(v for _, v in cats[0]), 2)
            if abs(soma_c - cats[1]) > 0.02:
                probs.append(f"total de despesas por categoria ({cats[1]:,.2f}) != soma das categorias ({soma_c:,.2f})")
            if contas:
                # o total por categoria costuma ser só o da conta Ordinária: deve igualar o débito de algum conjunto de contas
                import itertools
                debs = [c[3] for c in contas if abs(c[3]) > 0.005]
                achou = any(abs(sum(sub) - cats[1]) <= 0.02 for n in range(1, min(len(debs), 6) + 1) for sub in itertools.combinations(debs, n))
                if not achou:
                    probs.append(f"total de despesas por categoria ({cats[1]:,.2f}) não fecha com o débito de nenhuma conta nem combinação delas (débitos: {[round(x, 2) for x in debs]})")
        # leitura independente do arquivo de origem
        if condo and contas:
            cfg = config_validacao.aplicar(condo)
            pasta = pasta_prestacao.pasta_do_condominio(cfg)
            ex = get_extrator(cfg)
            arq = localizar_arquivo_mes(pasta, mm, aaaa, preferir_sufixo=(".xlsx" if cfg.get("empresa_gestora") in ("habitacional_xlsx", "lfc_xlsx") else None)) if pasta else None
            if ex is not None and arq is not None:
                try:
                    d = ex.extrair(arq, f"{aaaa}-{mm:02d}")
                    ind = {_norm(c.nome): c for c in d.contas}
                    for nome, ant, cre, deb, atu in contas:
                        c = ind.get(_norm(nome))
                        if c is None:
                            continue
                        if abs(c.saldo_atual - atu) > 0.011:
                            probs.append(f"SALDO ATUAL de {nome}: relatório {atu:,.2f} x leitura independente {c.saldo_atual:,.2f}")
                        if abs(c.saldo_anterior - ant) > 0.011:
                            probs.append(f"SALDO ANTERIOR de {nome}: relatório {ant:,.2f} x leitura independente {c.saldo_anterior:,.2f}")
                except Exception as e:
                    probs.append(f"(leitura independente falhou: {str(e)[:100]})")
        total_problemas += len(probs)
        marca = "OK " if not probs else "!! "
        print(f"{marca}{nome_arq}  [{len(doc)} págs, {n_itens} itens, {len(perguntas)} perguntas]")
        for p in probs:
            print("      -", p)
    print(f"\nTOTAL de pontos a revisar: {total_problemas}")


main()
