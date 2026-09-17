"""
Conciliador Lello XLS — Hub Home Club Tatuapé (e demais condomínios
lello_xls: Residencial Villa Park Osasco, Splendor Square).

O arquivo ".xls" é na verdade HTML puro (mesma convenção MHTML-like do
adapter de demonstrativo — ver adapters/lello_xls.py). A tabela
"DEMONSTRATIVO DE DESPESAS" tem estrutura hierárquica por linhas (1, 2 ou 3
células, sem atributos que marquem o nível — só a contagem/conteúdo da
linha distingue):
  1 célula                    → cabeçalho (conta/categoria/subcategoria) —
                                 só o texto mais recente é guardado, como
                                 "categoria" cosmética (não precisa da
                                 hierarquia exata pra duplicidade/soma)
  3 células, 1ª vazia         → fecha subcategoria/categoria (linha de total
                                 intermediário) — ignorada
  3 células, 1ª = DD/MM/AAAA  → um lançamento (data, histórico, valor)
  2 células, "Total DESPESAS" → fecha a seção inteira (total geral)

⚠️ pandas.read_html corrompe a formatação decimal desses valores (perde a
vírgula, ex.: "44,84" vira "4484") — por isso este extrator usa
BeautifulSoup direto sobre o HTML bruto, preservando o texto original.

Sem comprovante escaneado nem link anexado (mesma limitação do DataDigitus/
Consvicta) — reaproveita gerar_achados_datadigitus() (duplicidade por
data+valor+categoria+histórico e soma extraída x total declarado),
tratando o condomínio como uma "conta" única.
"""
from pathlib import Path
import re

from conciliacao.base import ConciliadorBase, RegistroComprovante

_RE_DATA = re.compile(r'^\d{2}/\d{2}/\d{4}$')


def _num(s: str) -> float:
    if not s:
        return 0.0
    # "3.848,00( 3,65%)" — pega só o primeiro número (valor), ignora o %.
    m = re.match(r'^([\d.]+,\d{2})', s.strip())
    if not m:
        return 0.0
    v = m.group(1).replace(".", "").replace(",", ".")
    try:
        return abs(float(v))
    except Exception:
        return 0.0


class ConciliadorLelloXLS(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        from bs4 import BeautifulSoup

        with open(caminho, encoding="utf-8", errors="replace") as f:
            html = f.read()
        soup = BeautifulSoup(html, "html.parser")

        tabela_despesas = None
        for tabela in soup.find_all("table"):
            primeiro_texto = tabela.get_text(strip=True)[:30].upper()
            if primeiro_texto.startswith("DEMONSTRATIVO DE DESPESAS"):
                tabela_despesas = tabela
                break
        if tabela_despesas is None:
            return []

        registros: list[RegistroComprovante] = []
        categoria_atual: str | None = None
        indice = 0

        for linha in tabela_despesas.find_all("tr"):
            celulas = [c.get_text(strip=True) for c in linha.find_all(["td", "th"])]
            if not celulas or not any(celulas):
                continue

            if len(celulas) == 1:
                texto = celulas[0].strip()
                if texto.upper().startswith("TOTAL") or texto.endswith("Total:"):
                    continue
                categoria_atual = texto
                continue

            if len(celulas) == 2:
                if celulas[0].strip().lower() == "total despesas":
                    indice += 1
                    registros.append(RegistroComprovante(
                        pagina=1,
                        codigo=str(indice),
                        tipo_documento="total_conta_declarado",
                        conta="TOTAL",
                        descricao="TOTAL",
                        valor=_num(celulas[1]),
                        texto_bruto=" | ".join(celulas),
                    ))
                continue  # outras linhas de 2 células são fechamentos de subtotal — ignoradas

            if len(celulas) == 3:
                data, historico, valor = celulas
                if not _RE_DATA.match(data.strip()):
                    continue  # linha de fechamento (1ª célula vazia) ou cabeçalho "Data/Historico/Valor"
                indice += 1
                registros.append(RegistroComprovante(
                    pagina=1,
                    codigo=str(indice),
                    tipo_documento="despesa_listada",
                    descricao=historico.strip()[:200] or None,
                    vencimento=data.strip(),
                    valor=_num(valor),
                    categoria_demonstrativo=categoria_atual,
                    conta="TOTAL",
                    texto_bruto=" | ".join(celulas),
                ))

        return registros
