"""ÚLTIMO CHECK dos relatórios de Validação de Balancetes (só lê; não altera nenhum relatório).

Aplica, a cada PDF "Validação Balancete - <Condomínio> MM.AAAA.pdf", as regras que foram sendo corrigidas ao longo do trabalho e gera um
resumo para quem não vai conferir arquivo por arquivo:
  - Excel  output/check_final_<data>.xlsx   (abas: Resumo por relatório · Pontos a corrigir · Regras verificadas)
  - texto  no terminal, só com o que é ALTA (corrigir antes de entregar).

Gravidade:  ALTA  = erro que não pode ser entregue;  MÉDIA = revisar;  INFO = esperado/explicado (fica registrado).

Uso:  python scripts/check_final_relatorios.py [--desde AAAA-MM-DD] [--meses 2026-07,2026-08] [--sem-origem] [id ...]
  --sem-origem  não relê os arquivos de origem (mais rápido; pula saldos x leitura independente, continuidade e cobertura das regras)
"""
import argparse
import glob
import itertools
import json
import os
import re
import sys
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
RE_BENEFICIO = re.compile(r"\bVALE\s*[- ]?\s*(?:TRANSPORTE|REFEIC|ALIMENT|COMBUSTIVEL|CULTURA)|\bCESTA\s*BASICA\b|\bSEGUROS?\b|\bAPOLICE\b|\bPREMIO\b", re.I)
EXCLUIDOS = {"Saint Afonso": "Parque Saint Afonso", "Go Barra Funda": "Go! Barra Funda"}      # condomínios sem validação neste lote
REGRAS = [
    ("Identidade", "Condomínio e mês do cabeçalho batem com o nome do arquivo e com o cadastro"),
    ("Nome do arquivo", "Padrão 'Validação Balancete - <Condomínio> MM.AAAA.pdf'; sem sufixo '(versão vN)' (relatório duplicado na pasta)"),
    ("Saldos x origem", "Saldo anterior e atual de cada conta batem com a leitura independente do arquivo de origem"),
    ("Fechamento", "Anterior + créditos − débitos = atual por conta; consolidado = soma; total por categoria = soma das categorias e fecha com débito de conta(s)"),
    ("Continuidade", "Saldo anterior = saldo final do mês anterior; se não bate, o relatório precisa ter a pergunta correspondente"),
    ("Sinal", "Valor negativo aparece com '-' (nunca como positivo) nos itens e nas tabelas"),
    ("Perguntas", "Todo item tem 'Pergunta à administradora' que termina em '?' (exceto o alerta de saldo negativo, que só informa)"),
    ("Texto", "Sem 'None', 'nan', '{{', 'undefined'; sem texto antigo (atraso 'além do dia útil seguinte')"),
    ("Atraso", "Datas de vencimento/pagamento plausíveis (mesmo ano; diferença até 120 dias)"),
    ("NF de benefício/seguro", "Vale transporte/refeição/cesta e seguro não são cobrados como 'Nota Fiscal não anexada'"),
    ("Escopo", "Condomínio cujo arquivo não traz anexos/balancete completo tem a seção 'Escopo da Validação'"),
    ("Saldo negativo", "Conta com saldo negativo tem o alerta 'há quanto tempo' (condomínios sem regra própria)"),
    ("Rendimento", "Rendimento só em uma conta com outra de saldo ≥ R$ 10.000 sem rendimento → pergunta sobre aplicações"),
    ("Cobertura do lote", "Todo condomínio com arquivo e célula em branco na planilha tem relatório; nenhum relatório de condomínio excluído"),
]


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
    try:
        i = linhas.index("Situação Financeira por Conta")
    except ValueError:
        return None
    j = next((k for k in range(i, len(linhas)) if linhas[k] == "Despesas por Categoria"), len(linhas))
    corpo = linhas[i + 1:j]
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


def _ultima_versao(cid, mes):
    vs = glob.glob(str(RAIZ / "data" / cid / "conciliacao" / mes / "v*"))
    vs = sorted(vs, key=lambda p: int(re.search(r"v(\d+)$", p.replace("\\", "/")).group(1)))
    return Path(vs[-1]) if vs else None


def _carregar_fila(meses):
    """(id, mes) com arquivo na pasta e célula em branco na planilha — mesma lógica do lote."""
    try:
        src = (RAIZ / "scripts" / "validar_lote_jul_ago.py").read_text(encoding="utf-8").replace("\nmain()\n", "\n")
        ns = {"__name__": "lote", "__file__": str(RAIZ / "scripts" / "validar_lote_jul_ago.py")}
        exec(compile(src, "lote", "exec"), ns)
        return [(i["id"], i["mes"], i["nome"]) for i in ns["fila"](meses, None, True)]
    except Exception as e:
        print(f"[AVISO] não foi possível montar a lista de relatórios esperados: {e}")
        return []


def analisar(f, condos, por_nome, com_origem):
    """Devolve (info_relatorio, achados) onde achados = [(gravidade, regra, texto)]."""
    nome_arq = os.path.basename(f)
    ach = []

    def add(g, regra, txt):
        ach.append((g, regra, txt))

    m = re.match(r"Validação Balancete - (.+) (\d{2})\.(\d{4})(?: \(versão v[\d-]+\))?\.pdf$", nome_arq)
    if not m:
        add("ALTA", "Nome do arquivo", "nome fora do padrão 'Validação Balancete - <Condomínio> MM.AAAA.pdf'")
        return {"arquivo": nome_arq, "condo": None, "mes": None, "itens": 0}, ach
    nome_condo, mm, aaaa = m.group(1), int(m.group(2)), int(m.group(3))
    condo = por_nome.get(_norm(nome_condo)) or next((c for k, c in por_nome.items() if _norm(nome_condo) in k or k in _norm(nome_condo)), None)
    if "(versão v" in nome_arq:
        add("ALTA", "Nome do arquivo", "sufixo '(versão vN)': há outro relatório do mesmo mês na pasta — deixar só o mais recente com o nome padrão")
    if condo is None:
        add("ALTA", "Identidade", f"condomínio '{nome_condo}' não encontrado no cadastro")
    doc = fitz.open(f)
    texto = "".join(p.get_text() for p in doc)
    linhas = [x.strip() for x in texto.splitlines() if x.strip()]
    mes = f"{aaaa}-{mm:02d}"
    info = {"arquivo": nome_arq, "condo": condo["id"] if condo else None, "mes": mes, "paginas": len(doc)}

    cab = next((x for x in linhas if "· " in x and "/" in x and "Administradora" in x), "")
    if f"{MESES[mm]} / {aaaa}" not in cab:
        add("ALTA", "Identidade", f"cabeçalho não confere com o mês do arquivo ({cab!r})")
    if condo and _norm(condo["nome"]) not in _norm(cab):
        add("ALTA", "Identidade", f"nome no cabeçalho difere do cadastro ({cab!r} x {condo['nome']!r})")

    for pad in (r"\bNone\b", r"\bnan\b", r"\bNaN\b", r"\{\{", r"\}\}", r"undefined", r"R\$ R\$", r"R\$ -R\$", r"-R\$ -"):
        mt = re.search(pad, texto)
        if mt:
            add("ALTA", "Texto", f"texto suspeito {pad!r}: ...{texto[max(0, mt.start() - 40):mt.end() + 40]!r}")
    if "além do dia útil seguinte" in texto:
        add("ALTA", "Texto", "texto antigo de atraso ('além do dia útil seguinte') — relatório precisa ser regenerado")
    if "Nenhuma divergência encontrada" in texto:
        add("ALTA", "Texto", "frase 'Nenhuma divergência encontrada' (não deve aparecer em relatório entregue)")

    # itens e perguntas
    i0 = texto.find("Divergências e Pendências")
    corpo = texto[i0:] if i0 >= 0 else ""
    titulos = re.findall(r"\n(\d+)\. ([^\n]+(?:\n[^\n]+)?)\n(?:ATENÇÃO|ALTO|CRÍTICO|INFORMATIVO)", corpo)
    n_itens = len(titulos)
    info["itens"] = n_itens
    perguntas = re.findall(r"Pergunta à administradora:(.*?)(?=\n\d+\. |\nAnexo de apoio|\Z)", texto, re.S)
    alertas_so_info = sum(1 for _, t in titulos if t.replace("\n", " ").startswith("Contas com saldo negativo"))
    for p in perguntas:
        ult = re.split(r"@@|Página:", p)[0].strip()
        ult = re.split(r"\n\s*Demonstrativo de Despesas\s*\n\s*Página", ult)[0].strip()
        if not ult.rstrip().endswith("?"):
            add("ALTA", "Perguntas", f"pergunta que não termina em '?': {ult[-90:]!r}")
    if n_itens - alertas_so_info > len(perguntas):
        add("ALTA", "Perguntas", f"{n_itens - alertas_so_info} itens com pergunta esperada, mas só {len(perguntas)} perguntas")
    titulos_txt = [t.replace("\n", " ") for _, t in titulos]
    for t, c in __import__("collections").Counter(titulos_txt).items():
        if c > 1:
            add("INFO", "Perguntas", f"item repetido {c}x: {t[:100]}")
    if "possível erro de leitura do OCR" in texto:
        add("MÉDIA", "Texto", f"{texto.count('possível erro de leitura do OCR')} item(ns) 'valor não confirma — possível erro de leitura do OCR': conferir na imagem do anexo (podem ser falsos positivos)")
    if "conteúdo não confirmado automaticamente" in texto:
        add("MÉDIA", "Texto", f"{texto.count('conteúdo não confirmado automaticamente')} item(ns) com comprovante cujo conteúdo não foi confirmado: conferir na imagem do anexo")
    if texto.count("Nota Fiscal não anexada") >= 6:
        add("MÉDIA", "NF de benefício/seguro", f"{texto.count('Nota Fiscal não anexada')} itens 'Nota Fiscal não anexada': ver se há padrão (benefício, seguro, recibo)")

    # atraso plausível
    for dv, dp in re.findall(r"vencimento em (\d{2}/\d{2}/\d{4}) e pagamento efetivado em (\d{2}/\d{2}/\d{4})", texto):
        try:
            v1, p1 = datetime.strptime(dv, "%d/%m/%Y"), datetime.strptime(dp, "%d/%m/%Y")
        except ValueError:
            add("ALTA", "Atraso", f"data inválida no atraso ({dv} / {dp})")
            continue
        if (p1 - v1).days > 120 or (p1 - v1).days < -60 or abs(p1.year - aaaa) > 1:
            add("ALTA", "Atraso", f"atraso com data implausível: vencimento {dv}, pagamento {dp} (provável erro de OCR)")

    # tabelas
    contas = tabela_contas(linhas)
    if contas:
        for nome, ant, cre, deb, atu in contas:
            dif = round(ant + cre - deb - atu, 2)
            if abs(dif) > 0.011:
                tem_mov = "fora das despesas e receitas" in texto
                add("INFO" if tem_mov else "MÉDIA", "Fechamento",
                    f"conta {nome}: anterior+créditos−débitos ≠ atual (diferença {dif:,.2f})" + (" — já perguntado no relatório (movimento entre contas)" if tem_mov else " — sem a pergunta de movimento entre contas"))
        mcons = re.search(r"O saldo consolidado do condomínio encerrou [^\n]*?em (R\$ -?[\d.]+,\d{2})", texto.replace("\n", " "))
        if mcons:
            cons, soma = _v(mcons.group(1)), round(sum(c[4] for c in contas), 2)
            if cons is not None and abs(cons - soma) > 0.011:
                add("ALTA", "Fechamento", f"saldo consolidado do resumo ({cons:,.2f}) ≠ soma dos saldos ({soma:,.2f})")
    cats = tabela_categorias(linhas)
    if cats and cats[1] is not None:
        soma_c = round(sum(v for _, v in cats[0]), 2)
        if abs(soma_c - cats[1]) > 0.02:
            add("ALTA", "Fechamento", f"total por categoria ({cats[1]:,.2f}) ≠ soma das categorias ({soma_c:,.2f})")
        if contas:
            debs = [c[3] for c in contas if abs(c[3]) > 0.005]
            if not any(abs(sum(s) - cats[1]) <= 0.02 for n in range(1, min(len(debs), 6) + 1) for s in itertools.combinations(debs, n)):
                add("INFO", "Fechamento", f"total por categoria ({cats[1]:,.2f}) não coincide com o débito de nenhuma conta (o total exclui transferências entre contas)")

    # sinal: valor negativo da leitura aparece com '-'
    if condo:
        v = _ultima_versao(condo["id"], mes)
        if v and (v / "achados_brutos.json").exists() and (v / "achados_revisados.json").exists():
            try:
                br = {b["id"]: b for b in json.load(open(v / "achados_brutos.json", encoding="utf-8"))}
                rev = json.load(open(v / "achados_revisados.json", encoding="utf-8"))
                rev = rev.get("achados", rev) if isinstance(rev, dict) else rev
                reg = json.load(open(v / "registros_comprovantes.json", encoding="utf-8"))
                reg = reg.get("registros", reg) if isinstance(reg, dict) else reg
                por_chave = {f"pag{r['pagina']}_cod{r['codigo']}": r for r in reg}
                for a in rev:
                    if a.get("severidade_final") == "informativo":
                        continue
                    b = br.get(a["achado_id"], {})
                    vals = [x for x in (b.get("valor_esperado"), b.get("valor_encontrado")) if isinstance(x, (int, float))]
                    if any(x < -0.005 for x in vals):
                        blob = a["titulo"] + " " + a["paragrafo"]
                        if not re.search(r"-\s?R\$|R\$\s?-", blob):
                            add("ALTA", "Sinal", f"valor negativo exibido sem sinal: {a['titulo'][:100]}")
                    # NF cobrada de benefício/seguro
                    if b.get("tipo") == "nota_fiscal_ausente":
                        for k in b.get("registros_relacionados", []):
                            r = por_chave.get(k)
                            if r and r.get("tipo_documento") == "despesa_listada" and RE_BENEFICIO.search(_norm(r.get("descricao") or "")):
                                add("ALTA", "NF de benefício/seguro", f"NF cobrada de benefício/seguro: {r['descricao'][:80]}")
            except Exception as e:
                add("INFO", "Sinal", f"(não foi possível ler os achados da versão: {str(e)[:80]})")

    # escopo (arquivo sem anexos / balancete completo)
    if condo:
        cfg = config_validacao.aplicar(condo)
        exige = bool(cfg.get("aviso_escopo"))
        if cfg.get("aviso_escopo_por_extensao"):
            v = _ultima_versao(condo["id"], mes)
            if v:
                try:
                    orig = json.load(open(v / "origem.json", encoding="utf-8")).get("arquivo_original", "")
                    exige = exige or Path(orig).suffix.lower() in cfg["aviso_escopo_por_extensao"]
                except Exception:
                    pass
        if exige and "Escopo da Validação" not in texto:
            add("ALTA", "Escopo", "o arquivo não traz anexos/balancete completo e o relatório não tem a seção 'Escopo da Validação'")

    # leitura independente
    if com_origem and condo and contas:
        cfg = config_validacao.aplicar(condo)
        pasta = pasta_prestacao.pasta_do_condominio(cfg)
        ex = get_extrator(cfg)
        suf = ".xlsx" if cfg.get("empresa_gestora") in ("habitacional_xlsx", "lfc_xlsx") else None
        arq = localizar_arquivo_mes(pasta, mm, aaaa, preferir_sufixo=suf) if pasta else None
        if ex is not None and arq is not None:
            try:
                d = ex.extrair(arq, mes)
                ind = {_norm(c.nome): c for c in d.contas}
                ma, aa = (mm - 1, aaaa) if mm > 1 else (12, aaaa - 1)
                arq_ant = localizar_arquivo_mes(pasta, ma, aa, preferir_sufixo=arq.suffix)
                if arq_ant is not None:
                    try:
                        d_ant = ex.extrair(arq_ant, f"{aa}-{ma:02d}")
                        ant_ind = {_norm(c.nome): c for c in d_ant.contas}
                        comuns = [(k, c) for k, c in ind.items() if k in ant_ind and not k.startswith("CONSOLIDADO")]
                        quebras = [(c.nome, c.saldo_anterior, ant_ind[k].saldo_atual) for k, c in comuns if abs(c.saldo_anterior - ant_ind[k].saldo_atual) > 0.011]
                        if quebras:
                            tem = "diferente do saldo final de" in texto
                            g = "INFO" if tem else "ALTA"
                            todas = comuns and len(quebras) == len(comuns)
                            add(g, "Continuidade", f"{len(quebras)} de {len(comuns)} contas com saldo anterior ≠ saldo final do mês anterior (ex.: {quebras[:2]})"
                                + (" — já perguntado no relatório" if tem else " — SEM a pergunta no relatório")
                                + (" — NENHUMA conta bate: o arquivo pode ser de outro condomínio" if todas else ""))
                    except Exception as e:
                        add("INFO", "Continuidade", f"(não conferida: {str(e)[:80]})")
                for nome, ant, cre, deb, atu in contas:
                    c = ind.get(_norm(nome))
                    if c is None:
                        continue
                    if abs(c.saldo_atual - atu) > 0.011:
                        add("ALTA", "Saldos x origem", f"saldo atual de {nome}: relatório {atu:,.2f} × origem {c.saldo_atual:,.2f}")
                    if abs(c.saldo_anterior - ant) > 0.011:
                        add("ALTA", "Saldos x origem", f"saldo anterior de {nome}: relatório {ant:,.2f} × origem {c.saldo_anterior:,.2f}")
                # saldo negativo com alerta
                negativas = [c for c in d.contas if not c.nome.upper().startswith("CONSOLIDADO") and c.saldo_atual < -1.0]
                if negativas and "saldo negativo e há quanto tempo" not in texto and cfg.get("regras", {}).get("saldo_negativo") is None \
                        and "Contas com saldo negativo" not in texto:
                    add("ALTA", "Saldo negativo", f"conta(s) com saldo negativo ({', '.join(c.nome for c in negativas[:3])}) sem o alerta 'há quanto tempo'")
                # rendimento concentrado
                if d.cobertura.get("rendimentos") or d.cobertura.get("receitas"):
                    todas_c = [c for c in d.contas if not c.nome.upper().startswith("CONSOLIDADO")]
                    com = [c for c in todas_c if c.rendimento > 0.011]
                    ign = [_norm(n) for n in ((cfg.get("regras") or {}).get("rendimento") or {}).get("ignorar_contas", [])]   # contas que o condomínio declara sem rendimento
                    sem = [c for c in todas_c if c not in com and _norm(c.nome) not in ign and (c.saldo_anterior + c.saldo_atual) / 2 >= 10000]
                    if len(com) == 1 and sem and not re.search(r"Rendimento (creditado|não creditado|fora da proporção)|Nenhuma conta recebeu", texto):
                        add("MÉDIA", "Rendimento", f"rendimento só em {com[0].nome} e sem rendimento em {', '.join(c.nome for c in sem[:3])} (≥ R$ 10 mil), mas o relatório não pergunta sobre aplicações")
            except Exception as e:
                add("INFO", "Saldos x origem", f"(leitura independente não feita: {str(e)[:100]})")
    return info, ach


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--desde", default="2026-10-14")
    ap.add_argument("--meses", default="2026-07,2026-08")
    ap.add_argument("--sem-origem", action="store_true")
    a = ap.parse_args()
    corte = datetime.strptime(a.desde, "%Y-%m-%d").timestamp()
    condos = {c["id"]: c for c in json.load(open(RAIZ / "config" / "condominios.json", encoding="utf-8"))["condominios"]}
    por_nome = {_norm(c["nome"]): c for c in condos.values()}
    arquivos = sorted(glob.glob(str(PROJETOS / "*" / "Validação de Balancetes" / "Validação Balancete - * 0[5-9].2026*.pdf")))
    resultados, pontos = [], []
    for f in arquivos:
        if os.path.getmtime(f) < corte:
            continue
        info, ach = analisar(f, condos, por_nome, not a.sem_origem)
        if a.ids and (info.get("condo") not in a.ids):
            continue
        resultados.append((info, ach))
        for g, regra, txt in ach:
            pontos.append((info["arquivo"], g, regra, txt))
        alta = sum(1 for g, _, _ in ach if g == "ALTA")
        med = sum(1 for g, _, _ in ach if g == "MÉDIA")
        print(f"{'ALTA ' if alta else ('MÉDIA' if med else 'OK   ')} {info['arquivo']}  [{info.get('itens', 0)} itens]  ALTA={alta} MÉDIA={med}")
        for g, regra, txt in ach:
            if g == "ALTA":
                print(f"      ! [{regra}] {txt}")
    # cobertura do lote
    existentes = {(i["condo"], i["mes"]) for i, _ in resultados if i.get("condo")}
    for cid, mes, nome in _carregar_fila(a.meses.split(",")):
        if cid in ("fatto_morumbi", "go_barra_funda", "parque_saint_afonso"):
            continue
        if (cid, mes) not in existentes and (not a.ids or cid in a.ids):
            aaaa, mm = mes.split("-")
            antigo = [f for f in arquivos if f"{mm}.{aaaa}" in os.path.basename(f) and _norm(nome) in _norm(os.path.basename(f))]
            txt = ("existe relatório, mas gerado ANTES das correções do lote (não passou pelas regras novas); rodar o check nele e refazer se necessário"
                   if antigo else "tem arquivo na pasta e célula em branco na planilha, mas não há relatório gerado")
            pontos.append((f"{nome} {mes}", "ALTA", "Cobertura do lote", txt))
            print(f"ALTA  [Cobertura do lote] {nome} {mes}: {txt}")
    for pasta, nome in EXCLUIDOS.items():
        d = PROJETOS / f"Dashboard de Análise de Balancete {pasta}" / "Validação de Balancetes"
        for f in glob.glob(str(d / f"*{nome}*0[78].2026*.pdf")):
            pontos.append((os.path.basename(f), "ALTA", "Cobertura do lote", "relatório de condomínio sem validação neste lote (arquivo de outro condomínio?) — apagar"))
            print(f"ALTA  [Cobertura do lote] relatório de condomínio excluído: {os.path.basename(f)}")
    # saídas
    saida = RAIZ / "output"
    saida.mkdir(exist_ok=True)
    arq_xlsx = saida / f"check_final_{datetime.now():%Y-%m-%d}.xlsx"
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Resumo por relatório"
        ws.append(["Relatório", "Itens no relatório", "ALTA", "MÉDIA", "INFO", "Situação"])
        for info, ach in resultados:
            c = {g: sum(1 for x, _, _ in ach if x == g) for g in ("ALTA", "MÉDIA", "INFO")}
            ws.append([info["arquivo"], info.get("itens", 0), c["ALTA"], c["MÉDIA"], c["INFO"],
                       "CORRIGIR" if c["ALTA"] else ("REVISAR" if c["MÉDIA"] else "OK")])
        w2 = wb.create_sheet("Pontos a corrigir")
        w2.append(["Relatório", "Gravidade", "Regra", "Ponto"])
        ordem = {"ALTA": 0, "MÉDIA": 1, "INFO": 2}
        for p in sorted(pontos, key=lambda x: (ordem[x[1]], x[0])):
            w2.append(list(p))
        w3 = wb.create_sheet("Regras verificadas")
        w3.append(["Regra", "O que é conferido"])
        for r in REGRAS:
            w3.append(list(r))
        cor = {"CORRIGIR": "F8CBAD", "REVISAR": "FFE699", "OK": "C6E0B4"}
        for row in ws.iter_rows(min_row=2):
            row[5].fill = PatternFill("solid", fgColor=cor[row[5].value])
        for w, larg in ((ws, [62, 12, 8, 8, 8, 12]), (w2, [62, 11, 24, 120]), (w3, [26, 140])):
            for i, l in enumerate(larg):
                w.column_dimensions[chr(65 + i)].width = l
            for c in w[1]:
                c.font = Font(bold=True)
            for row in w.iter_rows(min_row=2):
                for c in row:
                    c.alignment = Alignment(wrap_text=True, vertical="top")
            w.freeze_panes = "A2"
        wb.save(arq_xlsx)
    except Exception as e:
        print("[AVISO] não consegui gerar o Excel:", e)
    n = {g: sum(1 for p in pontos if p[1] == g) for g in ("ALTA", "MÉDIA", "INFO")}
    print(f"\nRELATÓRIOS: {len(resultados)} | ALTA: {n['ALTA']} | MÉDIA: {n['MÉDIA']} | INFO: {n['INFO']}")
    print(f"Excel: {arq_xlsx}")


main()
