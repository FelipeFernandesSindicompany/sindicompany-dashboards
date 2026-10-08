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
import time
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
    gerar_achados_balancete_mensal, gerar_achados_palm_beach, gerar_achados_planilha_com_links,
)
from conciliacao import interpretacao
from conciliacao import render
from conciliacao import analise_financeira
from conciliacao import demonstrativo_reader
from conciliacao import categorias_novas
from conciliacao import pasta_prestacao
from conciliacao import checagens_leitura
from conciliacao import config_validacao
from conciliacao.regras_gerais import pipeline as regras_gerais_pipeline
from conciliacao.regras_gerais import evidencias as regras_gerais_evidencias
from conciliacao import evidencias
from conciliacao import destaques

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
    "habitacional_xlsx": gerar_achados_planilha_com_links,
    "lfc_xlsx": gerar_achados_planilha_com_links,
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
    # SK Condomínios (Reserva Verde): sem registros de comprovante — só as regras gerais.
    "sk_condominios_pdf": lambda registros, dados_financeiros=None, **kw: [],
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
from conciliacao.condominios._planilha_refino import gerar_achados_planilha_refinado as _gerar_achados_planilha_refinado

GERAR_ACHADOS_POR_CONDO = {
    "club_park_butanta": gerar_achados_gcont,
    # Mesmo formato GCONT/HSA do Club Park (comprovante em página de texto nativo,
    # "Parcela <código>") — ver conciliacao/condominios/{parque_saint_afonso,i_gloo_alphaville}.py.
    "parque_saint_afonso": gerar_achados_gcont,
    "i_gloo_alphaville": gerar_achados_gcont,
    "top_nine": gerar_achados_gcont,
    "plano_estacao_campo_limpo": gerar_achados_gcont,
    # Planilhas Habitacional/LFC: mesmo matching de gerar_achados_planilha_com_links + isenção de "IR S/ APLICAÇÃO"
    # (ver conciliacao/condominios/_planilha_refino.py). Baturité/Port Saint Tropez (PDF ContasData) ficam de fora.
    **{_cid: _gerar_achados_planilha_refinado for _cid in (
        "alvorada", "plano_cambuci", "cinque_terre_residenza", "cores", "elo_elo_duo", "go_barra_funda",
        "go_liberdade", "guaratambe", "living_for_consolacao", "onze_22", "sublime", "victoria")},
    # NYC (webware) não tem "Demonstrativo de Despesas" separado nem
    # total confiável pra checar soma — só duplicidade (a mesma função
    # do DataDigitus cobre isso, mesmo sem total_conta_declarado).
    "nyc": gerar_achados_datadigitus,
    # Baturité migrou de habitacional_xlsx (planilha) pra ContasData
    # (PDF) em 2026 — mesma regra de matching do Lirba.
    "baturite": gerar_achados_planilha_com_links,
    # Port Saint Tropez migrou de habitacional_xlsx (planilha) pra ContasData
    # (PDF) em algum mês até março/2026 — mesmo padrão do Baturité.
    "port_saint_tropez": gerar_achados_planilha_com_links,
    # Palm Beach é "lirba_pdf" no cadastro, mas o PDF real é do sistema
    # HABITAT/GROUP condomínios — inteiramente renderizado como imagem, sem
    # código pra parear despesa x comprovante (ver
    # conciliacao/condominios/palm_beach.py).
    "palm_beach": gerar_achados_palm_beach,
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
_TEXTO_NF_NAO_ESTENDIDO = (
    "não aplicável nesta rodada — depende do conteúdo do comprovante já estar sendo lido "
    "(ver linha \"Conteúdo do comprovante\" acima), ainda não validado para este formato."
)

VERIFICACOES_POR_EMPRESA = {
    "addomus_pdf": {
        "conteudo_comprovante": (True, "extraído diretamente do texto do comprovante (PDF pesquisável) "
                                        "e cruzado com o valor da despesa correspondente."),
        "atraso_pagamento": (True, "comparado vencimento x data efetiva de pagamento de cada comprovante."),
        "nota_fiscal_ausente": (True, "quando a própria listagem cita um nº de Nota Fiscal, confere se o "
                                      "comprovante anexado também traz a Nota Fiscal (não só a confirmação bancária)."),
    },
}
for _e in ("lirba_pdf", "gk_pdf", "manager_adm_pdf", "convivium_pdf"):
    VERIFICACOES_POR_EMPRESA[_e] = {
        "conteudo_comprovante": (True, "extraído por OCR quando o comprovante é uma imagem digitalizada; "
                                        "marcado como \"conteúdo não verificável\" quando o OCR não confirma o valor."),
        "atraso_pagamento": (True, "comparado vencimento x \"Pago em\" extraídos por OCR do comprovante, "
                                    "quando os dois são confirmados."),
        "nota_fiscal_ausente": (True, "quando a própria listagem cita um nº de Nota Fiscal, confere se o "
                                      "comprovante anexado também traz a Nota Fiscal (não só a confirmação bancária)."),
    }
for _e in ("habitacional_xlsx", "lfc_xlsx", "datadigitus_pdf", "consvicta_pdf",
           "lello_xls", "alliz_pdf", "auxiliadora_xls", "ucondo_pdf"):
    VERIFICACOES_POR_EMPRESA[_e] = {
        "conteudo_comprovante": (False, _TEXTO_CONTEUDO_NAO_ESTENDIDO),
        "atraso_pagamento": (False, _TEXTO_ATRASO_UMA_DATA),
        "nota_fiscal_ausente": (False, _TEXTO_NF_NAO_ESTENDIDO),
    }
for _e in ("iello_pdf", "lello_pdf"):
    VERIFICACOES_POR_EMPRESA[_e] = {
        "conteudo_comprovante": (False, _TEXTO_BALANCETE_MENSAL),
        "atraso_pagamento": (False, _TEXTO_BALANCETE_MENSAL),
        "nota_fiscal_ausente": (False, _TEXTO_BALANCETE_MENSAL),
    }

VERIFICACOES_POR_CONDO = {
    "club_park_butanta": {
        "conteudo_comprovante": (True, "extraído diretamente do texto de cada página de comprovante (GCONT) "
                                        "e cruzado com o total declarado no Livro Caixa."),
        "atraso_pagamento": (True, "comparado vencimento x liquidação extraídos da própria página do comprovante."),
        "nota_fiscal_ausente": (True, "quando a própria listagem cita um nº de Nota Fiscal, confere se o "
                                      "comprovante anexado também traz a Nota Fiscal (não só a confirmação bancária)."),
    },
    "nyc": {
        "conteudo_comprovante": (False, _TEXTO_CONTEUDO_NAO_ESTENDIDO),
        "atraso_pagamento": (False, _TEXTO_ATRASO_UMA_DATA),
        "nota_fiscal_ausente": (False, _TEXTO_NF_NAO_ESTENDIDO),
    },
    # Baturité migrou pra ContasData (PDF) em 2026 — mesmo perfil do Lirba,
    # mesmo o cadastro em condominios.json ainda dizendo "habitacional_xlsx".
    "baturite": VERIFICACOES_POR_EMPRESA["lirba_pdf"],
    # Palm Beach (HABITAT/GROUP) — PDF inteiramente imagem, sem código pra
    # parear despesa x comprovante; "conteúdo" é confirmado por tipo de
    # documento (ver conciliacao/condominios/palm_beach.py), não por
    # pareamento com uma despesa específica.
    "palm_beach": {
        "conteudo_comprovante": (True, "cada documento da pasta \"Outros documentos\" é classificado por tipo via OCR "
                                        "e, quando aplicável, tem o valor de transação extraído — sem código pra parear "
                                        "com uma despesa específica (formato de origem não fornece esse vínculo)."),
        "atraso_pagamento": (False, "não aplicável — os documentos de pagamento deste formato não trazem data de "
                                     "vencimento separada da data de pagamento."),
        "nota_fiscal_ausente": (False, "não aplicável — sem vínculo despesa-a-despesa neste formato "
                                       "(ver \"Atraso de pagamento\" acima), não dá pra saber qual NF citar."),
    },
}


def _montar_verificacoes(condo: dict, funcao_matching) -> list[dict]:
    """Monta a seção "Verificações realizadas neste relatório" — sempre as 3
    checagens, sempre dizendo se rodaram ou por que não, nunca omitindo."""
    perfil = VERIFICACOES_POR_CONDO.get(condo["id"]) or VERIFICACOES_POR_EMPRESA.get(
        condo["empresa_gestora"],
        {"conteudo_comprovante": (False, _TEXTO_CONTEUDO_NAO_ESTENDIDO),
         "atraso_pagamento": (False, _TEXTO_ATRASO_UMA_DATA),
         "nota_fiscal_ausente": (False, _TEXTO_NF_NAO_ESTENDIDO)},
    )
    subconta_aplicavel = funcao_matching is not gerar_achados_balancete_mensal
    subconta_texto = (
        "categorias comparadas contra o histórico dos últimos meses já processados deste condomínio "
        "(quando ainda não há histórico suficiente, a checagem é pulada só para os meses sem base de comparação)."
        if subconta_aplicavel else _TEXTO_BALANCETE_MENSAL
    )
    aplicavel_conteudo, texto_conteudo = perfil["conteudo_comprovante"]
    aplicavel_atraso, texto_atraso = perfil["atraso_pagamento"]
    aplicavel_nf, texto_nf = perfil.get("nota_fiscal_ausente", (False, _TEXTO_NF_NAO_ESTENDIDO))
    return [
        {"nome": "Conteúdo do comprovante (valor, data, fornecedor)", "aplicavel": aplicavel_conteudo, "texto": texto_conteudo},
        {"nome": "Atraso de pagamento", "aplicavel": aplicavel_atraso, "texto": texto_atraso},
        {"nome": "Categoria/subconta atípica", "aplicavel": subconta_aplicavel, "texto": subconta_texto},
        {"nome": "Nota Fiscal anexada (quando a listagem cita uma)", "aplicavel": aplicavel_nf, "texto": texto_nf},
    ]


def _carregar_condominio(condo_id: str) -> dict:
    with open(CONDOMINIOS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    for c in data["condominios"]:
        if c["id"] == condo_id:
            # cadastro compartilhado (somente leitura) + config PRÓPRIA da Validação
            return config_validacao.aplicar(c)
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
    aviso_periodo = checagens_leitura.verificar_periodo(entrada, mes)
    if aviso_periodo:
        print(f"[AVISO] {aviso_periodo}")
    # Se o arquivo do mês já está na pasta do condomínio no OneDrive (ver
    # conciliacao/pasta_prestacao.py — o fluxo salva lá antes de validar), a
    # origem aponta pra ele. Nada é copiado pra pasta; se o arquivo não estiver
    # lá, avisa e a origem fica sendo o arquivo recebido, como sempre foi.
    na_pasta = pasta_prestacao.localizar_do_mes(condo, mes, arquivo)
    storage.write_origem(version_dir, na_pasta or arquivo)

    conciliador = get_conciliador(condo["empresa_gestora"], condo)
    # Condomínios Lello (Hub, Splendor, Villa Park) mandam planilha (.xls) E, às vezes, o "Demonstrativo de
    # Contas" em PDF (estilo ContasData, só demonstrativos): o PDF é lido pelo conciliador de listagem.
    lello_em_pdf = condo["empresa_gestora"] == "lello_xls" and entrada.suffix.lower() == ".pdf"
    if lello_em_pdf:
        from conciliacao.lirba_pdf import ConciliadorLirbaPDF
        conciliador = ConciliadorLirbaPDF(condo)
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
    if lello_em_pdf:
        # listagem sem comprovantes: duplicidade e soma x total (como DataDigitus), sem o alerta antigo de
        # "categoria nunca vista" — a regra de subcontas das regras gerais já cobre isso, com mais critério.
        _matching_listagem = funcao_matching

        def funcao_matching(registros, dados_financeiros=None, **kw):
            return [a for a in _matching_listagem(registros, dados_financeiros, **kw)
                    if a.regra_aplicada != "categoria_nao_vista_no_historico_recente"]
    achados: list[Achado] = funcao_matching(
        registros, dados_financeiros, pasta_dados=condo["pasta_dados"], mes_atual=mes
    )
    # Regras gerais (receita negativa, rendimento entre contas, pagamento sem
    # identificação, duas parcelas no mês, subcontas): leem o arquivo do mês e o do
    # mês anterior direto da pasta do projeto (ver conciliacao/regras_gerais).
    pasta_busca_regras = pasta_prestacao.pasta_do_condominio(condo) or arquivo.parent
    achados_regras, status_regras, avisos_regras = regras_gerais_pipeline.executar(
        condo, mes, entrada, pasta_busca_regras)
    achados.extend(achados_regras)
    achados.sort(key=lambda a: 0 if a.tipo == "previsto_realizado_inconsistente" else 1)   # divergência do Previsto x Realizado abre a lista
    for aviso in avisos_regras:
        print(f"[AVISO] {aviso}")
    for chave_regra, st in status_regras.items():
        if not st["aplicada"]:
            print(f"[AVISO] regra não verificada neste arquivo — {regras_gerais_pipeline.REGRAS_NOMES[chave_regra]}: {st['motivo']}")
    with open(version_dir / "regras_gerais.json", "w", encoding="utf-8") as f:
        json.dump({"status": status_regras, "avisos": avisos_regras}, f, ensure_ascii=False, indent=2)

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

    # Achados de nível AGREGADO (a "regra_aplicada" compara um total contra a
    # soma de TODOS os lançamentos, não um lançamento específico) listam
    # TODOS os registros do período em registros_relacionados — pegar
    # "registros_relacionados[0]" como se fosse "o" lançamento do achado é
    # arbitrário (é só o primeiro da lista cronológica) e mostra um
    # código/fornecedor/evidência sem relação nenhuma com a divergência
    # (confirmado em dados reais: achado de "soma não confere" do Club Park
    # Butantã mostrava um comprovante da CLARO, só por ser o primeiro da
    # lista). Pra essas regras, não mostra código/fornecedor/evidência
    # nenhum — a divergência é sobre o TOTAL, não sobre um lançamento.
    _REGRAS_AGREGADAS = evidencias.REGRAS_AGREGADAS

    # Prints adicionais com destaque (ver render.preparar_evidencia_extra),
    # curados por relatório em <versão>/evidencias_extra.json — chave = id do
    # achado (ou um id fixo pros achados montados aqui no render, como
    # "DIV-RESUMIDO-LIVRO-CAIXA"). Sem o arquivo, ou sem a chave, o achado
    # sai exatamente como antes.
    try:
        _specs_extras = json.loads((version_dir / "evidencias_extra.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _specs_extras = {}

    def _evidencias_extras(chave: str, specs_auto: list[dict] | None = None) -> list[dict]:
        # Prints curados à mão (evidencias_extra.json) têm prioridade; sem eles
        # valem os automáticos da família (conciliacao/evidencias.py).
        if not pdf_origem:
            return []
        specs = _specs_extras.get(chave) or specs_auto or []
        evs = [render.preparar_evidencia_extra(pdf_origem, s) for s in specs]
        return [e for e in evs if e]

    # O destaque de página escaneada usa OCR (~10 s por página): limita o TEMPO
    # total por relatório pra não alongar a geração quando há dezenas de
    # achados (os que passarem do limite saem com a evidência sem marcação,
    # como antes).
    _LIMITE_OCR_SEGUNDOS = 90.0
    _ocr_gasto = [0.0]

    achados_render = []
    for numero, rev in enumerate(revisados_com_problema, start=1):
        achado = achados_por_id[rev.achado_id]
        primeiro_registro = (
            registros_por_pagina.get(achado.registros_relacionados[0])
            if achado.registros_relacionados and achado.regra_aplicada not in _REGRAS_AGREGADAS
            else None
        )

        evidencia_vetorial = None
        if primeiro_registro and getattr(primeiro_registro, "arquivo_evidencia_externa", None):
            # Evidência baixada de um sistema externo (ver
            # RegistroComprovante.arquivo_evidencia_externa e
            # conciliacao/condominios/central_das_artes.py) — não é uma
            # página do PDF de origem, é um arquivo separado já em disco.
            evidencia_vetorial = render.preparar_evidencia_externa(primeiro_registro.arquivo_evidencia_externa)
        elif pdf_origem and primeiro_registro:
            evidencia_vetorial = render.preparar_evidencia_vetorial(
                pdf_origem, primeiro_registro.pagina,
                bbox_override=getattr(primeiro_registro, "bbox_crop", None),
            )

        # Marca na evidência principal ONDE está o erro (valor/data) — ver
        # conciliacao/destaques.py e evidencias.termos_destaque.
        if evidencia_vetorial and primeiro_registro:
            termos, linha_inteira = evidencias.termos_destaque(achado, primeiro_registro)
            if termos:
                _t0 = time.monotonic()
                evidencia_vetorial = destaques.aplicar(
                    evidencia_vetorial, termos, linha_inteira,
                    permitir_ocr=_ocr_gasto[0] < _LIMITE_OCR_SEGUNDOS)
                if evidencia_vetorial.get("usou_ocr"):
                    _ocr_gasto[0] += time.monotonic() - _t0

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
            "e_achado_agregado": achado.regra_aplicada in _REGRAS_AGREGADAS,
            "evidencias_extras": _evidencias_extras(
                rev.achado_id,
                evidencias.evidencias_agregadas(achado, registros_por_pagina, pdf_origem)
                if achado.regra_aplicada in _REGRAS_AGREGADAS else (
                    regras_gerais_evidencias.specs_para(achado) if (achado.id or "").startswith("RG-") else None),
            ),
            "evidencia_texto": regras_gerais_evidencias.texto_origem(achado),
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
    categorias_novas_lista: list[dict] = []
    # O mês atual é sempre lido da cópia ESTÁVEL em version_dir/input/ (pdf_origem,
    # já calculado acima) — nunca de origem.json diretamente, que guarda o
    # caminho de onde o arquivo veio ORIGINALMENTE e pode já não existir mais
    # (ex.: upload via navegador salva num temp que o SO limpa depois; sem essa
    # separação, isso derrubava a Análise Financeira inteira, inclusive o mês
    # atual, mesmo com uma cópia perfeitamente boa disponível). origem.json
    # continua servindo só pra localizar o mês ANTERIOR na pasta original.
    if pdf_origem:
        arquivo_original = storage.read_origem(version_dir)
        # Pasta do condomínio no OneDrive tem prioridade sobre a pasta de origem
        # gravada na versão (que, em upload pelo Admin, era um temp já apagado).
        pasta_busca_anterior = pasta_prestacao.pasta_do_condominio(condo) or (
            arquivo_original.parent if arquivo_original else None
        )
        bal_atual, bal_anterior = demonstrativo_reader.ler_par_mes_atual_anterior(
            condo, pdf_origem, mes, _mes_titulo(mes),
            f"01/{mes[5:7]}/{mes[:4]} a {_ultimo_dia_mes(mes)}",
            pasta_busca_anterior=pasta_busca_anterior,
        )
        if bal_atual:
            aviso_previsto = None
            try:
                _bruto = storage.read_dataclass_list(version_dir / "achados_brutos.json", Achado)
                if any(a.tipo == "previsto_realizado_inconsistente" for a in _bruto):
                    aviso_previsto = ("o Resumo de Emissão deste arquivo está incompleto ou diferente do padrão dos meses "
                                      "anteriores (veja a divergência \"Previsto x Realizado\" abaixo); confirmar com a administradora.")
            except Exception:
                pass
            analise = analise_financeira.montar_analise(bal_atual, bal_anterior, _mes_titulo(mes), aviso_previsto)
            aviso_fechamento = checagens_leitura.verificar_fechamento_categorias(condo, bal_atual)
            if aviso_fechamento:
                print(f"[AVISO] {aviso_fechamento}")
        else:
            print(f"[AVISO] não foi possível ler os dados financeiros de {pdf_origem.name} — "
                  f"relatório sairá sem a seção de Análise Financeira.")

        # Categorias/subcontas novas (rótulo de despesa que não existia no mês
        # anterior) — checagem opcional, só funciona quando o mês anterior é
        # localizável e tem a mesma estrutura de "Demonstrativo Resumido"
        # (ver conciliacao/categorias_novas.py); degrada pra [] em qualquer
        # outro caso, nunca derruba o resto do relatório.
        if pasta_busca_anterior and pasta_busca_anterior.is_dir():
            ano_mes_ant, mes_num_ant = int(mes[:4]), int(mes[5:7])
            mes_num_ant, ano_mes_ant = (
                (12, ano_mes_ant - 1) if mes_num_ant == 1 else (mes_num_ant - 1, ano_mes_ant)
            )
            caminho_anterior = demonstrativo_reader.localizar_arquivo_mes(
                pasta_busca_anterior, mes_num_ant, ano_mes_ant
            )
            categorias_novas_lista = categorias_novas.detectar_categorias_novas(
                pdf_origem, caminho_anterior
            )
    else:
        print("[AVISO] nenhum arquivo de entrada encontrado em input/ — "
              "relatório sairá sem a seção de Análise Financeira.")

    # Divergência entre o "Total das Despesas" do Demonstrativo Resumido
    # (analise["despesas_total"], usado na tabela "Despesas por Categoria")
    # e o total de fechamento do "Livro Caixa" (registro tipo_documento=
    # "total_declarado", extraído na etapa 'extrair') — duas linhas que o
    # PRÓPRIO sistema da administradora declara, mas que vieram de seções
    # diferentes do PDF. Confirmado em dados reais (Club Park Butantã,
    # ago/2026) que pode haver uma diferença pequena (ex.: R$1.048,85) sem
    # causa identificada na tabela detalhada (que tem layout em 2 colunas
    # que embaralha fornecedor/categoria em lançamentos com descrição
    # longa — não dá pra reconstruir com confiança). Nunca inventa a causa:
    # só reporta a diferença e pergunta pra administradora.
    total_declarado_registro = next(
        (r for r in registros if r.tipo_documento == "total_declarado"), None
    )
    if analise and total_declarado_registro:
        diferenca_resumido_livro_caixa = round(
            analise["despesas_total"] - total_declarado_registro.valor, 2
        )
        if abs(diferenca_resumido_livro_caixa) > 1.0:
            def _fmt_r_local(v: float) -> str:
                return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            achados_render.append({
                "numero": len(achados_render) + 1,
                "titulo": f"Despesas por Categoria não bate com o Livro Caixa — total do período "
                          f"({_fmt_r_local(diferenca_resumido_livro_caixa)})",
                "paragrafo": (
                    f"O \"Total das Despesas\" do Demonstrativo Resumido (usado na tabela \"Despesas por "
                    f"Categoria\" deste relatório) é {_fmt_r_local(analise['despesas_total'])}. O fechamento "
                    f"do Livro Caixa do mesmo PDF é {_fmt_r_local(total_declarado_registro.valor)}. Diferença "
                    f"de {_fmt_r_local(diferenca_resumido_livro_caixa)}. Tentamos reconstruir a tabela "
                    f"detalhada de despesas lançamento por lançamento pra achar a origem exata, mas essa "
                    f"tabela tem um layout em 2 colunas que embaralha fornecedor e categoria quando a "
                    f"descrição é longa — não foi possível confirmar qual lançamento específico causa essa "
                    f"diferença."
                ),
                "severidade_final": "atencao",
                "severidade_label": SEVERIDADE_LABEL.get("atencao", "ATENÇÃO"),
                "o_que_verificar": (
                    f"Essa diferença de {_fmt_r_local(diferenca_resumido_livro_caixa)} entre o Demonstrativo "
                    f"Resumido e o Livro Caixa tem algum motivo específico (ex.: um lançamento por "
                    f"competência que ainda não foi liquidado, ou um critério de data diferente entre as "
                    f"duas seções)? Consegue nos detalhar a origem dessa diferença?"
                ),
                "codigo": None,
                "fornecedor": None,
                "valor_formatado": _fmt_r_local(abs(diferenca_resumido_livro_caixa)),
                "pagina_original_texto": None,
                "evidencia_vetorial": None,
                "e_achado_agregado": True,
                "evidencias_extras": _evidencias_extras(
                    "DIV-RESUMIDO-LIVRO-CAIXA",
                    evidencias.evidencias_resumido_x_livro_caixa(
                        pdf_origem, analise["despesas_total"], total_declarado_registro),
                ),
            })

    # Rótulo por condomínio específico tem prioridade (ex.: Club Park Butantã
    # é "lirba_pdf" no cadastro, mas o PDF real é do sistema GCONT). Central
    # das Artes também é "lirba_pdf" no cadastro, mas a administradora real
    # é a Hausy (sistema Robotton/GoControleDocumentos — ver
    # conciliacao/condominios/central_das_artes.py).
    ADMINISTRADORA_LABEL_POR_CONDO = {
        "club_park_butanta": "GCONT",
        "nyc": "Manager ADM",
        "central_das_artes": "Hausy",
        # Cadastrados como lirba_pdf, mas o PDF é de outra administradora/sistema (lido no próprio arquivo):
        "i_gloo_alphaville": "GCONT",
        "parque_saint_afonso": "GCONT",
        "top_nine": "Conister",
        "plano_estacao_campo_limpo": "Foccus",
        "serra_da_mantiqueira": "FL Condomínios",
        "palm_beach": "Group Condomínios",
    }
    administradora_label = ADMINISTRADORA_LABEL_POR_CONDO.get(
        condo["id"], ADMINISTRADORA_LABEL.get(condo["empresa_gestora"], condo["empresa_gestora"])
    )
    html = render.montar_html(
        condominio_nome=condo["nome"],
        # Confirmado em dados reais: quase nenhum condomínio tem CNPJ
        # cadastrado em condominios.json — "não informado" aparecia em
        # praticamente todo relatório como se fosse um dado real ausente,
        # não um campo genuinamente não preenchido. None (via .get sem
        # default) deixa o template omitir o trecho inteiro.
        cnpj=condo.get("cnpj") or None,
        administradora=administradora_label,
        mes_titulo=_mes_titulo(mes),
        logo_data_uri=logo_data_uri,
        cor=condo.get("cor", "#333"),
        achados=achados_render,
        analise=analise,
        categorias_novas=categorias_novas_lista,
        gerado_em=datetime.now().strftime("%d/%m/%Y"),
    )

    destino = version_dir / "relatorio_final.pdf"
    render.renderizar_pdf(html, destino)
    render.inserir_evidencias_vetoriais(destino, achados_render)
    render.inserir_evidencias_extras(destino, achados_render)

    # Cópia com o nome amigável pedido pelo usuário — "relatorio_final.pdf"
    # continua sendo o nome interno/estável (usado por storage.py e pelo
    # admin em validacaoStorage.ts::caminhoRelatorio), nunca renomeado, pra
    # não quebrar código que já depende dele.
    destino_amigavel = version_dir / _nome_arquivo_relatorio(condo, mes)
    shutil.copy2(destino, destino_amigavel)

    # Cópia automática na pasta do projeto do condomínio (subpasta "Validação de Balancetes"), ao lado dos
    # arquivos de prestação de contas — o mesmo lugar onde o mês anterior é procurado.
    salvo_em = pasta_prestacao.salvar_relatorio(condo, destino_amigavel, version_dir.name)
    if salvo_em:
        print(f"[OK] Relatório salvo também na pasta do projeto: {salvo_em}")
    else:
        print("[AVISO] condomínio sem pasta do projeto configurada — relatório disponível só para baixar no Admin.")

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

    try:
        condo = _carregar_condominio(args.condominio)

        if args.etapa in ("extrair", "todos"):
            if not args.arquivo:
                parser.error("--arquivo é obrigatório em --etapa extrair")
            etapa_extrair(condo, args.mes, Path(args.arquivo))
        if args.etapa in ("interpretar", "todos"):
            etapa_interpretar(condo, args.mes)
        if args.etapa == "render":
            etapa_render(condo, args.mes)
    except SystemExit:
        raise
    except Exception as exc:
        # Erro inesperado: mostra a MENSAGEM (o Admin exibe a 1ª linha "[ERRO]") e guarda o detalhe técnico em
        # data/validacao_erros.log — antes saía só "Processo encerrado com código 1", sem dizer o que falhou.
        import traceback

        detalhe = traceback.format_exc()
        print(f"[ERRO] {type(exc).__name__}: {exc} (etapa {args.etapa}, {args.condominio}, {args.mes})")
        print(detalhe, file=sys.stderr)
        try:
            with open(ROOT / "data" / "validacao_erros.log", "a", encoding="utf-8") as f:
                f.write(f"\n===== {datetime.now():%d/%m/%Y %H:%M:%S} — {args.condominio} {args.mes} etapa {args.etapa}\n{detalhe}\n")
        except OSError:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
