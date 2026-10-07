"""
Executa as regras gerais para um condomínio/mês: lê o arquivo do mês e o do mês
anterior (da pasta do projeto), aplica as regras e devolve achados + status.

Tudo vem dos ARQUIVOS de prestação de contas; nunca de dashboards. Falha de leitura
nunca derruba a geração do relatório: vira aviso e a regra fica "não verificada".
"""
import time
from pathlib import Path
from typing import Optional

from conciliacao import demonstrativo_reader
from conciliacao.base import Achado
from conciliacao.regras_gerais.extratores import get_extrator
from conciliacao.regras_gerais.regras import REGRAS_NOMES, aplicar_regras, verificar_extracao  # noqa: F401 (REGRAS_NOMES reexportado)


MESES_HISTORICO = 6
LIMITE_SEGUNDOS_HISTORICO = 150.0


def _mes_anterior(mes: str) -> tuple[int, int]:
    ano, m = int(mes[:4]), int(mes[5:7])
    return (12, ano - 1) if m == 1 else (m - 1, ano)


def executar(condo: dict, mes: str, arquivo: Path, pasta_busca_anterior: Optional[Path]) -> tuple[list[Achado], dict, list[str]]:
    """(achados, status, avisos). status[regra] = {"aplicada": bool, "motivo": str|None}."""
    avisos: list[str] = []
    extrator = get_extrator(condo)
    if extrator is None:
        status = {k: {"aplicada": False, "motivo": "este formato de arquivo ainda não tem a leitura das regras gerais"}
                  for k in REGRAS_NOMES}
        return [], status, avisos

    try:
        dados = extrator.extrair(arquivo, mes)
    except Exception as exc:
        avisos.append(f"não foi possível ler {arquivo.name} para as regras gerais ({exc})")
        status = {k: {"aplicada": False, "motivo": f"falha ao ler o arquivo: {exc}"} for k in REGRAS_NOMES}
        return [], status, avisos
    avisos += list(dados.avisos)
    avisos += verificar_extracao(dados)

    # Meses anteriores (até MESES_HISTORICO, do mais recente para o mais antigo), lidos DIRETO dos arquivos
    # da pasta do projeto. O imediatamente anterior serve ao rendimento; a regra de subcontas compara com
    # a união de todos (uma despesa eventual que some e volta não vira alarme). Para de ler se a
    # leitura estiver demorando (PDF grande, OCR) — o que já foi lido basta.
    historico: list = []
    outro_formato: list = []
    anterior = None
    if pasta_busca_anterior and pasta_busca_anterior.is_dir():
        inicio = time.monotonic()
        m_atual = mes
        for k in range(MESES_HISTORICO):
            mes_k, ano_k = _mes_anterior(m_atual)
            m_atual = f"{ano_k}-{mes_k:02d}"
            arq_k = demonstrativo_reader.localizar_arquivo_mes(pasta_busca_anterior, mes_k, ano_k, preferir_sufixo=arquivo.suffix)
            if arq_k is None:
                if k == 0:
                    avisos.append(f"arquivo de {mes_k:02d}/{ano_k} não encontrado na pasta do projeto — "
                                  f"comparação com o mês anterior (subcontas e rendimento) fica de fora")
                continue
            if k > 0 and time.monotonic() - inicio > LIMITE_SEGUNDOS_HISTORICO:
                break
            try:
                dados_k = extrator.extrair(arq_k, m_atual)
            except Exception as exc:
                if k == 0:
                    avisos.append(f"não foi possível ler o mês anterior ({arq_k.name}): {exc}")
                continue
            if k == 0:
                anterior = dados_k      # rendimento: nomes de conta são os mesmos em qualquer formato
            if arq_k.suffix.lower() != arquivo.suffix.lower():
                # Subcontas só se comparam entre meses do MESMO formato (a planilha Lello e o PDF do mesmo
                # condomínio nomeiam as subcontas em níveis diferentes: comparar geraria alertas falsos).
                outro_formato.append(f"{mes_k:02d}/{ano_k}")
                continue
            historico.append(dados_k)

    if outro_formato:
        avisos.append(f"meses anteriores em outro formato de arquivo ({', '.join(outro_formato)}) ficaram fora da comparação "
                      f"de subcontas — a planilha e o PDF nomeiam as subcontas em níveis diferentes")
    achados, status = aplicar_regras(dados, anterior, condo.get("regras"), historico=historico)
    return achados, status, avisos
