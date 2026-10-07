"""
Pasta de prestações de contas de cada condomínio no OneDrive sincronizado.

Por quê: o Admin grava o PDF enviado numa pasta temporária (apagada logo
depois) e o motor procurava o mês ANTERIOR na pasta desse arquivo temporário
— nunca achava, e era preciso apontar o origem.json à mão (foi o que
aconteceu com Ciudad Real e Club Park Butantã). Agora cada condomínio tem uma
pasta fixa (campo `pasta_prestacao` em config/condominios.json, relativa à
raiz abaixo): o mês anterior é procurado ali. O arquivo do mês atual NÃO é
copiado pra lá — o fluxo de trabalho já salva o PDF na pasta antes de pedir
a validação; aqui só se localiza esse arquivo (pra servir de origem) e
avisa se ele não estiver na pasta, já que sem ele o mês seguinte não
encontrará este mês.

A raiz é a PASTA SINCRONIZADA no PC onde o sistema roda — o sistema não lê
links do OneDrive/SharePoint (exigiriam login Microsoft). Ordem de busca:
  1. variável de ambiente SINDICOMPANY_PRESTACOES_RAIZ
  2. "pasta_prestacoes_raiz" em data/config_local.json (data/ não vai pro git;
     é o lugar certo pra um caminho específico desta máquina)
  3. <home>/OneDrive*/Documentos/Claude/Projects
"""
import json
import os
from pathlib import Path

_CONFIG_LOCAL = Path(__file__).parent.parent / "data" / "config_local.json"


def raiz_prestacoes() -> Path | None:
    candidatos: list[Path] = []
    if os.environ.get("SINDICOMPANY_PRESTACOES_RAIZ"):
        candidatos.append(Path(os.environ["SINDICOMPANY_PRESTACOES_RAIZ"]))
    try:
        valor = json.loads(_CONFIG_LOCAL.read_text(encoding="utf-8")).get("pasta_prestacoes_raiz")
        if valor:
            candidatos.append(Path(valor))
    except (OSError, ValueError):
        pass
    candidatos += sorted(Path.home().glob("OneDrive*/Documentos/Claude/Projects"))
    return next((c for c in candidatos if c.is_dir()), None)


def pasta_do_condominio(condo: dict) -> Path | None:
    """Pasta do condomínio dentro da raiz, ou None se não configurada/inexistente."""
    relativa = condo.get("pasta_prestacao")
    raiz = raiz_prestacoes()
    if not relativa or raiz is None:
        return None
    pasta = raiz / relativa
    return pasta if pasta.is_dir() else None


def localizar_do_mes(condo: dict, mes: str, arquivo: Path) -> Path | None:
    """
    Devolve o caminho do arquivo do mês DENTRO da pasta do condomínio (o que
    foi enviado de dentro dela, ou o que já está lá com o nome do mês), ou
    None se o condomínio não tem pasta configurada ou o arquivo do mês não
    está nela. Nunca grava nada na pasta.
    """
    from conciliacao.demonstrativo_reader import localizar_arquivo_mes

    pasta = pasta_do_condominio(condo)
    if pasta is None:
        return None
    try:
        if arquivo.resolve().parent == pasta.resolve():
            return arquivo  # enviado de dentro da pasta
    except OSError:
        pass

    existente = localizar_arquivo_mes(pasta, int(mes[5:7]), int(mes[:4]), preferir_sufixo=arquivo.suffix)
    if existente is None:
        print(f"[AVISO] o arquivo de {mes[5:7]}/{mes[:4]} não está na pasta do OneDrive do condomínio "
              f"({pasta.name}) — a validação segue, mas o mês seguinte não achará este mês para "
              f"comparar. Salve o PDF nessa pasta.")
        return None
    if existente.stat().st_size != arquivo.stat().st_size:
        print(f"[AVISO] {existente.name}, na pasta do OneDrive, tem tamanho diferente do arquivo enviado "
              f"— confira se é a mesma versão.")
    return existente


NOME_PASTA_VALIDACOES = "Validação de Balancetes"


def salvar_relatorio(condo: dict, relatorio: Path, versao: str) -> Path | None:
    """Guarda uma cópia do relatório final em `<pasta do projeto do condomínio>/Validação de Balancetes/`,
    o mesmo lugar onde a Validação procura o mês anterior (a pasta é criada se não existir).

    Nome: o do próprio relatório ("Validação Balancete - <Condomínio> MM.AAAA.pdf"). Se já existir um arquivo
    com esse nome (revalidação do mês, ou relatório entregue antes), NÃO é sobrescrito: a cópia nova leva
    " (versão vN)" no nome, com o número da versão da Validação. Devolve o caminho salvo, ou None se o
    condomínio não tem pasta do projeto ou a gravação falhou (nunca derruba a geração do relatório)."""
    pasta = pasta_do_condominio(condo)
    if pasta is None:
        return None
    try:
        destino_dir = pasta / NOME_PASTA_VALIDACOES
        destino_dir.mkdir(parents=True, exist_ok=True)
        destino = destino_dir / relatorio.name
        if destino.exists():
            destino = destino_dir / f"{relatorio.stem} (versão {versao}){relatorio.suffix}"
            n = 2
            while destino.exists():
                destino = destino_dir / f"{relatorio.stem} (versão {versao}-{n}){relatorio.suffix}"
                n += 1
        import shutil

        shutil.copy2(relatorio, destino)
        return destino
    except OSError as exc:
        print(f"[AVISO] não foi possível salvar o relatório na pasta do projeto ({exc}) — ele continua disponível "
              f"para baixar no Admin.")
        return None
