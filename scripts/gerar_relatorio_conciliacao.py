"""
CLI do motor de conciliação — mesmo estilo de scripts/injetar_mes.py
(argparse, ROOT no sys.path, mensagens em pt-BR).

Etapas independentes e retomáveis (cada uma lê/escreve em
data/<pasta_dados>/conciliacao/<mes>/vN/ — ver conciliacao/storage.py):

  extrair      Lê o PDF da pasta de prestação de contas, extrai
               RegistroComprovante[] (conciliacao/<administradora>.py) e roda
               o matching determinístico (conciliacao/matching.py) contra o
               demonstrativo (reaproveita o adapter existente em adapters/).
               Sempre cria uma NOVA versão (vN+1).

  interpretar  Gera (ou re-gera) o esqueleto de achados_revisados.json a
               partir dos achados brutos da versão corrente, para revisão
               humana ou por agente. Atualiza a versão corrente in-place.

  render       Valida achados_revisados.json (conciliacao/interpretacao.py)
               e gera relatorio_final.pdf (conciliacao/render.py). Atualiza a
               versão corrente in-place.

Uso:
  python scripts/gerar_relatorio_conciliacao.py --condominio spazio_jardins_da_orla \
      --mes 2026-08 --arquivo "ORLA AGOSTO 2026.pdf" --etapa extrair

  python scripts/gerar_relatorio_conciliacao.py --condominio spazio_jardins_da_orla \
      --mes 2026-08 --etapa interpretar

  python scripts/gerar_relatorio_conciliacao.py --condominio spazio_jardins_da_orla \
      --mes 2026-08 --etapa render
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from adapters import get_adapter
from conciliacao import get_conciliador
from conciliacao import storage
from conciliacao.base import Achado, AchadoRevisado, RegistroComprovante, chave_registro
from conciliacao.matching import (
    gerar_achados, gerar_achados_lirba, gerar_achados_datadigitus, gerar_achados_gcont,
    gerar_achados_balancete_mensal,
)
from conciliacao import interpretacao
from conciliacao import render
from conciliacao import analise_financeira
from conciliacao import demonstrativo_reader

CONDOMINIOS_JSON = ROOT / "config" / "condominios.json"

MESES_FULL = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}
SEVERIDADE_LABEL = {
    "critico": "GRAVIDADE CRÍTICA",
    "alto": "GRAVIDADE ALTA",
    "atencao": "ATENÇÃO",
    "informativo": "VERIFICADO / INFORMATIVO",
}

# Nome de exibição por empresa_gestora — mesmos ids usados em adapters/__init__.py::ADAPTERS.
ADMINISTRADORA_LABEL = {
    "addomus_pdf": "Addomus",
    "lirba_pdf": "Lirba",
    "iello_pdf": "Iello",
    "lello_pdf": "Lello",
    "datadigitus_pdf": "DataDigitus",
    "manager_adm_pdf": "Manager ADM",
    "sk_condominios_pdf": "SK Condomínios",
    "alliz_pdf": "Alliz",
    "consvicta_pdf": "Consvicta",
    "habitacional_xlsx": "Habitacional",
    "gk_pdf": "GK ADM",
    "convivium_pdf": "Convivium",
    "lfc_xlsx": "LFC",
    "lello_xls": "Lello",
    "auxiliadora_xls": "Auxiliadora Predial",
    "ucondo_pdf": "Conviver MRV",
}

# Cada administradora tem regras de matching próprias — ver conciliacao/matching.py.
# Definido em nível de módulo (não só dentro de etapa_extrair) porque
# etapa_render também precisa saber qual função foi usada, para montar o
# registro interno de verificações (verificacoes.json) — ver _montar_verificacoes().
GERAR_ACHADOS_POR_EMPRESA = {
    "addomus_pdf": gerar_achados,
    "lirba_pdf": gerar_achados_lirba,
    # Habitacional usa o mesmo par "despesa_listada"/"comprovante_anexado"
    # do Lirba (só muda a origem: hyperlink do Excel em vez de página de
    # PDF) — reaproveita a regra de matching sem duplicar.
    "habitacional_xlsx": gerar_achados_lirba,
    "lfc_xlsx": gerar_achados_lirba,
    # DataDigitus não tem comprovante escaneado nem link anexado — só a
    # listagem de despesas do próprio demonstrativo, então usa regras
    # diferentes (duplicidade por data+valor+categoria e divergência
    # soma-x-total-declarado), ver conciliacao/matching.py.
    "datadigitus_pdf": gerar_achados_datadigitus,
    # gk_pdf/manager_adm_pdf usam o mesmo motor ContasData do Lirba —
    # mesma regra de matching.
    "gk_pdf": gerar_achados_lirba,
    "manager_adm_pdf": gerar_achados_lirba,
    "convivium_pdf": gerar_achados_lirba,
    # Consvicta (Gardens Living Club) não tem vínculo textual entre
    # despesa e comprovante (páginas de imagem sem "Parcela" referenciada
    # em nenhum outro lugar) — mesmas regras de consistência do DataDigitus.
    "consvicta_pdf": gerar_achados_datadigitus,
    # Lello XLS (na verdade HTML) também não tem comprovante escaneado
    # nem link anexado — mesmas regras de consistência do DataDigitus.
    "lello_xls": gerar_achados_datadigitus,
    # Alliz também não tem pareamento por código nem "conta" confiável
    # nas páginas de comprovante — mesmas regras de consistência.
    "alliz_pdf": gerar_achados_datadigitus,
    "auxiliadora_xls": gerar_achados_datadigitus,
    "ucondo_pdf": gerar_achados_datadigitus,
    "iello_pdf": gerar_achados_balancete_mensal,
    "lello_pdf": gerar_achados_balancete_mensal,
}
# Condomínios com conciliador ESPECÍFICO (ver conciliacao/condominios/) podem
# ter regras de matching próprias, mesmo compartilhando empresa_gestora com
# outros condomínios de formato diferente (ex.: Club Park Butantã é
# "lirba_pdf" no cadastro, mas o PDF é do sistema GCONT, não ContasData).
GERAR_ACHADOS_POR_CONDO = {
    "club_park_butanta": gerar_achados_gcont,
    # NYC (webware) não tem "Demonstrativo de Despesas" separado nem
    # total confiável pra checar soma — só duplicidade (a mesma função
    # do DataDigitus cobre isso, mesmo sem total_conta_declarado).
    "nyc": gerar_achados_datadigitus,
    # Baturité migrou de habitacional_xlsx (planilha) pra ContasData
    # (PDF) em 2026 — mesma regra de matching do Lirba.
    "baturite": gerar_achados_lirba,
}


def obter_funcao_matching(condo: dict):
    return GERAR_ACHADOS_POR_CONDO.get(
        condo["id"], GERAR_ACHADOS_POR_EMPRESA.get(condo["empresa_gestora"], gerar_achados)
    )


# ── Rodada 1 de verificações abrangentes ────────────────────────────────────
# (ver plano em C:\Users\MF PRINTER\.claude\plans\humming-swimming-hellman.md)
# Cobre Addomus, GCONT (Club Park Butantã) e toda a família Lirba/ContasData
# de ponta a ponta (conteúdo do comprovante via OCR + atraso de pagamento).
# Os demais formatos ficam "não aplicável" nesta rodada — mas de forma
# EXPLÍCITA no relatório (ver seção "Verificações realizadas" no template),
# nunca omitida em silêncio, até serem investigados e validados
# individualmente numa rodada seguinte, formato por formato.
_TEXTO_ATRASO_UMA_DATA = (
    "não aplicável nesta rodada — este formato registra só uma data por lançamento, "
    "sem confirmação independente da data efetiva de pagamento."
)
_TEXTO_CONTEUDO_NAO_ESTENDIDO = (
    "não aplicável nesta rodada — verificação automática de conteúdo ainda não "
    "implementada/validada para este formato."
)
_TEXTO_BALANCETE_MENSAL = (
    "não aplicável — este formato só tem totais agregados por categoria/conta, "
    "sem lançamentos nem comprovantes individuais para conferir."
)

VERIFICACOES_POR_EMPRESA = {
    "addomus_pdf": {
        "conteudo_comprovante": (True, "extraído diretamente do texto do comprovante (PDF pesquisável) "
                                        "e cruzado com o valor da despesa correspondente."),
        "atraso_pagamento": (True, "comparado vencimento x data efetiva de pagamento de cada comprovante."),
    },
}
for _e in ("lirba_pdf", "gk_pdf", "manager_adm_pdf", "convivium_pdf"):
    VERIFICACOES_POR_EMPRESA[_e] = {
        "conteudo_comprovante": (True, "extraído por OCR quando o comprovante é uma imagem digitalizada; "
                                        "marcado como \"conteúdo não verificável\" quando o OCR não confirma o valor."),
        "atraso_pagamento": (True, "comparado vencimento x \"Pago em\" extraídos por OCR do comprovante, "
                                    "quando os dois são confirmados."),
    }
for _e in ("habitacional_xlsx", "lfc_xlsx", "datadigitus_pdf", "consvicta_pdf",
           "lello_xls", "alliz_pdf", "auxiliadora_xls", "ucondo_pdf"):
    VERIFICACOES_POR_EMPRESA[_e] = {
        "conteudo_comprovante": (False, _TEXTO_CONTEUDO_NAO_ESTENDIDO),
        "atraso_pagamento": (False, _TEXTO_ATRASO_UMA_DATA),
    }
for _e in ("iello_pdf", "lello_pdf"):
    VERIFICACOES_POR_EMPRESA[_e] = {
        "conteudo_comprovante": (False, _TEXTO_BALANCETE_MENSAL),
        "atraso_pagamento": (False, _TEXTO_BALANCETE_MENSAL),
    }

VERIFICACOES_POR_CONDO = {
    "club_park_butanta": {
        "conteudo_comprovante": (True, "extraído diretamente do texto de cada página de comprovante (GCONT) "
                                        "e cruzado com o total declarado no Livro Caixa."),
        "atraso_pagamento": (True, "comparado vencimento x liquidação extraídos da própria página do comprovante."),
    },
    "nyc": {
        "conteudo_comprovante": (False, _TEXTO_CONTEUDO_NAO_ESTENDIDO),
        "atraso_pagamento": (False, _TEXTO_ATRASO_UMA_DATA),
    },
    # Baturité migrou pra ContasData (PDF) em 2026 — mesmo perfil do Lirba,
    # mesmo o cadastro em condominios.json ainda dizendo "habitacional_xlsx".
    "baturite": VERIFICACOES_POR_EMPRESA["lirba_pdf"],
}


def _montar_verificacoes(condo: dict, funcao_matching) -> list[dict]:
    """Monta a seção "Verificações realizadas neste relatório" — sempre as 3
    checagens, sempre dizendo se rodaram ou por que não, nunca omitindo."""
    perfil = VERIFICACOES_POR_CONDO.get(condo["id"]) or VERIFICACOES_POR_EMPRESA.get(
        condo["empresa_gestora"],
        {"conteudo_comprovante": (False, _TEXTO_CONTEUDO_NAO_ESTENDIDO),
         "atraso_pagamento": (False, _TEXTO_ATRASO_UMA_DATA)},
    )
    subconta_aplicavel = funcao_matching is not gerar_achados_balancete_mensal
    subconta_texto = (
        "categorias comparadas contra o histórico dos últimos meses já processados deste condomínio "
        "(quando ainda não há histórico suficiente, a checagem é pulada só para os meses sem base de comparação)."
        if subconta_aplicavel else _TEXTO_BALANCETE_MENSAL
    )
    aplicavel_conteudo, texto_conteudo = perfil["conteudo_comprovante"]
    aplicavel_atraso, texto_atraso = perfil["atraso_pagamento"]
    return [
        {"nome": "Conteúdo do comprovante (valor, data, fornecedor)", "aplicavel": aplicavel_conteudo, "texto": texto_conteudo},
        {"nome": "Atraso de pagamento", "aplicavel": aplicavel_atraso, "texto": texto_atraso},
        {"nome": "Categoria/subconta atípica", "aplicavel": subconta_aplicavel, "texto": subconta_texto},
    ]


def _carregar_condominio(condo_id: str) -> dict:
    with open(CONDOMINIOS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    for c in data["condominios"]:
        if c["id"] == condo_id:
            return c
    raise ValueError(f"Condomínio '{condo_id}' não encontrado em {CONDOMINIOS_JSON}")


def _mes_titulo(mes: str) -> str:
    dt = datetime.strptime(mes, "%Y-%m")
    return f"{MESES_FULL[dt.month]} / {dt.year}"


def _ultimo_dia_mes(mes: str) -> str:
    import calendar
    dt = datetime.strptime(mes, "%Y-%m")
    ultimo = calendar.monthrange(dt.year, dt.month)[1]
    return f"{ultimo:02d}/{dt.month:02d}/{dt.year}"


# Caracteres inválidos em nome de arquivo no Windows — nome de condomínio
# nunca deveria ter nenhum deles, mas filtra por segurança.
_CARACTERES_INVALIDOS_ARQUIVO = str.maketrans("", "", '\\/:*?"<>|')


def _nome_arquivo_relatorio(condo: dict, mes: str) -> str:
    """
    "Validação Balancete - <Nome do Condomínio> MM.AAAA.pdf" — padrão de nome
    de arquivo pedido pelo usuário pro relatório entregue (a barra de
    "MM/AAAA" vira ponto, já que "/" não é permitido em nome de arquivo).
    """
    ano, mes_num = mes.split("-")
    nome = condo["nome"].translate(_CARACTERES_INVALIDOS_ARQUIVO)
    return f"Validação Balancete - {nome} {mes_num}.{ano}.pdf"


def etapa_extrair(condo: dict, mes: str, arquivo: Path) -> Path:
    base_dir = storage.condo_mes_dir(condo["pasta_dados"], mes)
    version_dir = storage.new_version_dir(base_dir)
    storage.write_status(version_dir, "extrair")

    entrada = storage.copy_input_file(version_dir, arquivo, arquivo.name)
    storage.write_origem(version_dir, arquivo)

    conciliador = get_conciliador(condo["empresa_gestora"], condo)
    registros: list[RegistroComprovante] = conciliador.extrair_comprovantes(entrada)
    storage.write_dataclass_list(version_dir / "registros_comprovantes.json", registros)

    dados_financeiros = None
    # A regra de divergência por categoria (regra 6 de gerar_achados / regra 3 de
    # gerar_achados_lirba) exige que os nomes de categoria da extração batam
    # com os do adapter de demonstrativo já existente. Confirmado para Addomus;
    # para Lirba, o agrupamento do adapter (adapters/lirba_pdf.py) não bate 1:1
    # com o cat_map de condominios.json aplicado aqui (ex.: adapter mantém
    # "Materiais de Consumo" e "Material de Expediente" separados, cat_map
    # funde os dois em "Materiais") — pular a regra até isso ser revisado, pra
    # não gerar falsa divergência.
    EMPRESAS_COM_CHECAGEM_CATEGORIA = {"addomus_pdf"}
    if condo["empresa_gestora"] in EMPRESAS_COM_CHECAGEM_CATEGORIA:
        try:
            adapter = get_adapter(condo["empresa_gestora"], condo)
            dados_financeiros = adapter.ler_pdf(entrada, mes)
        except Exception as exc:
            print(f"[AVISO] não foi possível ler o demonstrativo consolidado ({exc}); "
                  f"pulando a regra de divergência por categoria.")

    # Qual função de matching usar (ver GERAR_ACHADOS_POR_EMPRESA/_POR_CONDO,
    # definidos em nível de módulo — etapa_render também precisa saber isso
    # pra montar a seção "Verificações realizadas neste relatório").
    funcao_matching = obter_funcao_matching(condo)
    achados: list[Achado] = funcao_matching(
        registros, dados_financeiros, pasta_dados=condo["pasta_dados"], mes_atual=mes
    )
    storage.write_dataclass_list(version_dir / "achados_brutos.json", achados)

    storage.write_status(version_dir, "extrair", concluido=True)
    print(f"[OK] {len(registros)} registros extraídos, {len(achados)} achados gerados.")
    print(f"[OK] Versão criada: {version_dir}")
    return version_dir


def etapa_interpretar(condo: dict, mes: str) -> Path:
    base_dir = storage.condo_mes_dir(condo["pasta_dados"], mes)
    version_dir = storage.latest_version_dir(base_dir)
    if not version_dir:
        raise FileNotFoundError(f"Nenhuma versão encontrada em {base_dir} — rode --etapa extrair primeiro.")

    achados = storage.read_dataclass_list(version_dir / "achados_brutos.json", Achado)
    registros = storage.read_dataclass_list(version_dir / "registros_comprovantes.json", RegistroComprovante)
    esqueleto = interpretacao.gerar_esqueleto(achados, registros)
    with open(version_dir / "achados_revisados.json", "w", encoding="utf-8") as f:
        json.dump(esqueleto, f, ensure_ascii=False, indent=2)

    storage.write_status(version_dir, "interpretar", concluido=True)
    print(f"[OK] Esqueleto gravado em {version_dir / 'achados_revisados.json'} "
          f"(narrativa gerada automaticamente para os {len(esqueleto)} achado(s) — nenhuma revisão manual necessária).")
    return version_dir


def etapa_render(condo: dict, mes: str) -> Path:
    base_dir = storage.condo_mes_dir(condo["pasta_dados"], mes)
    version_dir = storage.latest_version_dir(base_dir)
    if not version_dir:
        raise FileNotFoundError(f"Nenhuma versão encontrada em {base_dir} — rode --etapa extrair primeiro.")

    achados = storage.read_dataclass_list(version_dir / "achados_brutos.json", Achado)
    revisados = storage.read_dataclass_list(version_dir / "achados_revisados.json", AchadoRevisado)

    erros = interpretacao.validar(achados, revisados)
    if erros:
        print("[ERRO] achados_revisados.json inválido:")
        for e in erros:
            print(f"  - {e}")
        raise SystemExit(1)

    registros = storage.read_dataclass_list(version_dir / "registros_comprovantes.json", RegistroComprovante)
    # Mesma chave usada em conciliacao/matching.py ao montar registros_relacionados
    # (página sozinha não é única em formatos "listagem", ver base.py::chave_registro).
    registros_por_pagina = {chave_registro(r): r for r in registros}
    achados_por_id = {a.id: a for a in achados}

    entradas_pdf = list((version_dir / "input").glob("*"))
    pdf_origem = entradas_pdf[0] if entradas_pdf else None

    # O relatório final só lista problemas/divergências — achados já confirmados
    # como corretos (severidade_final "informativo": comprovante confere,
    # confirmado via relatório fiscal, ou limitação de escopo sem divergência
    # real) não entram no PDF, só nos arquivos brutos/revisados em disco.
    revisados_com_problema = [r for r in revisados if r.severidade_final != "informativo"]
    numero_excluidos = len(revisados) - len(revisados_com_problema)

    achados_render = []
    for numero, rev in enumerate(revisados_com_problema, start=1):
        achado = achados_por_id[rev.achado_id]
        primeiro_registro = (
            registros_por_pagina.get(achado.registros_relacionados[0])
            if achado.registros_relacionados else None
        )

        evidencia_vetorial = None
        if pdf_origem and primeiro_registro:
            evidencia_vetorial = render.preparar_evidencia_vetorial(pdf_origem, primeiro_registro.pagina)

        valor = achado.valor_encontrado if achado.valor_encontrado is not None else achado.valor_esperado
        achados_render.append({
            "numero": numero,
            "titulo": rev.titulo,
            "paragrafo": rev.paragrafo,
            "severidade_final": rev.severidade_final,
            "severidade_label": SEVERIDADE_LABEL.get(rev.severidade_final, rev.severidade_final.upper()),
            "o_que_verificar": rev.o_que_verificar,
            "codigo": primeiro_registro.codigo if primeiro_registro else None,
            "fornecedor": primeiro_registro.fornecedor if primeiro_registro else None,
            "valor_formatado": f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if valor else None,
            "pagina_original_texto": primeiro_registro.pagina_original_texto if primeiro_registro else None,
            "evidencia_vetorial": evidencia_vetorial,
        })

    logo_html = ROOT / "docs" / condo["html_file"]
    logo_data_uri = render.resolver_logo(condo["nome"], logo_html)

    # Seção de Análise Financeira — lê DIRETO da pasta de projeto (arquivo do
    # mês atual + mês anterior localizado automaticamente na mesma pasta),
    # nunca do dashboard já publicado. O sistema de validação não deve se
    # ancorar em dados do dashboard (que podem estar desatualizados ou nem
    # existir ainda) — só nos próprios PDFs/XLSX de prestação de contas, a
    # mesma fonte que a conciliação de comprovantes já usa.
    analise = None
    arquivo_original = storage.read_origem(version_dir)
    if arquivo_original:
        bal_atual, bal_anterior = demonstrativo_reader.ler_par_mes_atual_anterior(
            condo, arquivo_original, mes, _mes_titulo(mes),
            f"01/{mes[5:7]}/{mes[:4]} a {_ultimo_dia_mes(mes)}",
        )
        if bal_atual:
            analise = analise_financeira.montar_analise(bal_atual, bal_anterior, _mes_titulo(mes))
        else:
            print(f"[AVISO] não foi possível ler os dados financeiros de {arquivo_original.name} — "
                  f"relatório sairá sem a seção de Análise Financeira.")
    else:
        print("[AVISO] origem do arquivo do mês atual não encontrada (versão antiga, gerada antes "
              "dessa mudança) — relatório sairá sem a seção de Análise Financeira.")

    # Rótulo por condomínio específico tem prioridade (ex.: Club Park Butantã
    # é "lirba_pdf" no cadastro, mas o PDF real é do sistema GCONT).
    ADMINISTRADORA_LABEL_POR_CONDO = {"club_park_butanta": "GCONT", "nyc": "Manager ADM"}
    administradora_label = ADMINISTRADORA_LABEL_POR_CONDO.get(
        condo["id"], ADMINISTRADORA_LABEL.get(condo["empresa_gestora"], condo["empresa_gestora"])
    )
    html = render.montar_html(
        condominio_nome=condo["nome"],
        cnpj=condo.get("cnpj", "não informado"),
        administradora=administradora_label,
        mes_titulo=_mes_titulo(mes),
        logo_data_uri=logo_data_uri,
        cor=condo.get("cor", "#333"),
        achados=achados_render,
        analise=analise,
        gerado_em=datetime.now().strftime("%d/%m/%Y"),
    )

    destino = version_dir / "relatorio_final.pdf"
    render.renderizar_pdf(html, destino)
    render.inserir_evidencias_vetoriais(destino, achados_render)

    # Cópia com o nome amigável pedido pelo usuário — "relatorio_final.pdf"
    # continua sendo o nome interno/estável (usado por storage.py e pelo
    # admin em validacaoStorage.ts::caminhoRelatorio), nunca renomeado, pra
    # não quebrar código que já depende dele.
    destino_amigavel = version_dir / _nome_arquivo_relatorio(condo, mes)
    shutil.copy2(destino, destino_amigavel)

    # Quais verificações (conteúdo/atraso/subconta) rodaram de fato pra esse
    # condomínio/mês NÃO entra no PDF entregue ao síndico/condomínio —
    # detalhe de implementação interno, sem sentido pra quem recebe o
    # relatório (feedback explícito do usuário). Fica só aqui, pra quem
    # revisar a pasta de conciliação internamente saber o que rodou de fato.
    verificacoes = _montar_verificacoes(condo, obter_funcao_matching(condo))
    with open(version_dir / "verificacoes.json", "w", encoding="utf-8") as f:
        json.dump(verificacoes, f, ensure_ascii=False, indent=2)

    storage.write_status(version_dir, "render", concluido=True)
    print(f"[OK] Relatório gerado: {destino_amigavel}")
    print(f"[OK] {len(achados_render)} problema(s)/divergência(s) no relatório "
          f"({numero_excluidos} achado(s) já confirmados como corretos foram omitidos).")
    return version_dir


def main():
    parser = argparse.ArgumentParser(description="Gera relatório de conciliação/validação mensal.")
    parser.add_argument("--condominio", required=True, help="id do condomínio em config/condominios.json")
    parser.add_argument("--mes", required=True, help="'YYYY-MM', ex: 2026-08")
    parser.add_argument("--arquivo", help="PDF da pasta de prestação de contas (obrigatório em --etapa extrair)")
    parser.add_argument("--etapa", required=True, choices=["extrair", "interpretar", "render", "todos"])
    args = parser.parse_args()

    condo = _carregar_condominio(args.condominio)

    if args.etapa in ("extrair", "todos"):
        if not args.arquivo:
            parser.error("--arquivo é obrigatório em --etapa extrair")
        etapa_extrair(condo, args.mes, Path(args.arquivo))
    if args.etapa in ("interpretar", "todos"):
        etapa_interpretar(condo, args.mes)
    if args.etapa == "render":
        etapa_render(condo, args.mes)


if __name__ == "__main__":
    main()
