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
)
from conciliacao import interpretacao
from conciliacao import render
from conciliacao import bal_reader
from conciliacao import analise_financeira

CONDOMINIOS_JSON = ROOT / "config" / "condominios.json"

MESES_FULL = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}
MESES_ABREV_BAL = {1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
                    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"}


def _mes_chave_bal(mes_str: str) -> str:
    """'2026-07' -> 'jul26' (mesma convenção usada em var BAL nos dashboards)."""
    dt = datetime.strptime(mes_str, "%Y-%m")
    return f"{MESES_ABREV_BAL[dt.month]}{str(dt.year)[2:]}"

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
    "datadigitus_pdf": "DataDigitus",
    "manager_adm_pdf": "Manager ADM",
    "sk_condominios_pdf": "SK Condomínios",
    "alliz_pdf": "Alliz",
    "consvicta_pdf": "Consvicta",
    "habitacional_xlsx": "Habitacional",
    "gk_pdf": "GK ADM",
    "lfc_xlsx": "LFC",
    "lello_xls": "Lello",
    "auxiliadora_xls": "Auxiliadora Predial",
}


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


def etapa_extrair(condo: dict, mes: str, arquivo: Path) -> Path:
    base_dir = storage.condo_mes_dir(condo["pasta_dados"], mes)
    version_dir = storage.new_version_dir(base_dir)
    storage.write_status(version_dir, "extrair")

    entrada = storage.copy_input_file(version_dir, arquivo, arquivo.name)

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

    # Cada administradora tem regras de matching próprias — ver conciliacao/matching.py.
    gerar_achados_por_empresa = {
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
    }
    # Condomínios com conciliador ESPECÍFICO (ver conciliacao/condominios/) podem
    # ter regras de matching próprias, mesmo compartilhando empresa_gestora com
    # outros condomínios de formato diferente (ex.: Club Park Butantã é
    # "lirba_pdf" no cadastro, mas o PDF é do sistema GCONT, não ContasData).
    gerar_achados_por_condo = {
        "club_park_butanta": gerar_achados_gcont,
    }
    funcao_matching = gerar_achados_por_condo.get(
        condo["id"], gerar_achados_por_empresa.get(condo["empresa_gestora"], gerar_achados)
    )
    achados: list[Achado] = funcao_matching(registros, dados_financeiros)
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
    esqueleto = interpretacao.gerar_esqueleto(achados)
    with open(version_dir / "achados_revisados.json", "w", encoding="utf-8") as f:
        json.dump(esqueleto, f, ensure_ascii=False, indent=2)

    storage.write_status(version_dir, "interpretar", concluido=True)
    pendentes = sum(1 for a in esqueleto if a["revisado_por"] == "pendente")
    print(f"[OK] Esqueleto gravado em {version_dir / 'achados_revisados.json'}")
    print(f"[AÇÃO NECESSÁRIA] {pendentes} achado(s) aguardando revisão "
          f"(preencher titulo/paragrafo/o_que_verificar antes de rodar --etapa render).")
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

    # Seção de Análise Financeira — reaproveita os dados já publicados no
    # dashboard (var BAL), sem reprocessar nenhum arquivo de novo. Se o mês (ou
    # o dashboard) não tiver dados publicados ainda, a seção fica de fora do
    # relatório em vez de falhar (achados de conciliação continuam saindo).
    analise = None
    mes_chave = _mes_chave_bal(mes)
    bal_atual = bal_reader.ler_bal_mes(logo_html, mes_chave)
    if bal_atual:
        bal_anterior = bal_reader.ler_bal_mes(logo_html, bal_reader.mes_anterior(mes_chave))
        analise = analise_financeira.montar_analise(bal_atual, bal_anterior, _mes_titulo(mes))
    else:
        print(f"[AVISO] mês '{mes_chave}' não encontrado em {logo_html.name} — "
              f"relatório sairá sem a seção de Análise Financeira.")

    # Rótulo por condomínio específico tem prioridade (ex.: Club Park Butantã
    # é "lirba_pdf" no cadastro, mas o PDF real é do sistema GCONT).
    ADMINISTRADORA_LABEL_POR_CONDO = {"club_park_butanta": "GCONT"}
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

    storage.write_status(version_dir, "render", concluido=True)
    print(f"[OK] Relatório gerado: {destino}")
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
