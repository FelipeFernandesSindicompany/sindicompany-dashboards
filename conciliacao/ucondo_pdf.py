"""
Conciliador uCondo PDF — Saint Simon (administradora Conviver MRV).

Formato bem mais estruturado que os outros: a seção "Comprovantes de
Despesas" tem uma página POR ANEXO de cada despesa (Cobrança, Comprovante
de Pagamento, etc.) repetindo os MESMOS campos-resumo (Categoria,
Vencimento, Valor pago, Fornecedor, Descrição) — quando uma despesa tem 2
anexos, ela aparece em 2 páginas seguidas com os campos idênticos. Por
isso a extração deduplica por (categoria, vencimento, valor, fornecedor,
descrição): sem isso, toda despesa com mais de 1 anexo viraria falsa
"duplicidade".

O total declarado vem da seção "Totalizações" do "Balancete Mensal"
(Receitas | Despesas | Saldo do Mês — pega o valor de Despesas), que já é
a soma combinada de todas as contas do condomínio.

Sem checagem de "comprovante ausente" por item — o campo "Links dos
anexos" lista os TIPOS de documento disponíveis pra aquela despesa (um
menu fixo), não necessariamente o que está de fato anexado, então não é um
sinal confiável de presença/ausência. Reaproveita
gerar_achados_datadigitus() (duplicidade + soma x total declarado).
"""
from pathlib import Path
import re

from conciliacao.base import ConciliadorBase, RegistroComprovante

_RE_TOTALIZACOES = re.compile(
    r'Receitas\s+Despesas\s+Saldo do M[eê]s\s*\n\s*R\$\s*([\d.]+,\d{2})\s+R\$\s*([\d.]+,\d{2})',
    re.IGNORECASE,
)
_RE_CATEGORIA = re.compile(r'Categoria\s+(.+?)\s+Conta\b')
# "Vencimento DD/MM/AAAA Valor R$ X,XX" fica sempre nessa ordem (rótulos
# curtos, não quebram linha) — mais confiável que "Valor pago", que às
# vezes empurra o número pra uma linha adiante (fica colado em "Desconto
# R$ 0,00" quando o texto ao redor é mais longo).
_RE_VENCIMENTO_VALOR = re.compile(r'Vencimento\s+(\d{2}/\d{2}/\d{4})\s+Valor\s+R\$\s*([\d.]+,\d{2})')
_RE_VENCIMENTO = re.compile(r'Vencimento\s+(\d{2}/\d{2}/\d{4})')
_RE_VALOR_PAGO = re.compile(r'Valor pago\s+R\$\s*([\d.]+,\d{2})')
_RE_FORNECEDOR = re.compile(r'Fornecedor\s*(.*?)\s*\n\s*Links dos anexos', re.DOTALL)
_RE_DESCRICAO = re.compile(r'Descri[cç][aã]o\s+(.+?)\s*\n\s*Vencimento')


def _num(s: str) -> float:
    if not s:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(s).strip())
    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except Exception:
        return 0.0


class ConciliadorUcondoPDF(ConciliadorBase):
    def extrair_comprovantes(self, caminho: Path) -> list:
        import pdfplumber

        registros: list[RegistroComprovante] = []
        vistos: set[tuple] = set()
        total_declarado: float | None = None
        indice = 0

        with pdfplumber.open(str(caminho)) as pdf:
            for pagina_num, page in enumerate(pdf.pages, start=1):
                texto = page.extract_text() or ""
                page.flush_cache()

                if total_declarado is None:
                    m_tot = _RE_TOTALIZACOES.search(texto)
                    if m_tot:
                        total_declarado = _num(m_tot.group(2))

                if "Comprovantes de Despesas" not in texto:
                    continue

                m_venc_valor = _RE_VENCIMENTO_VALOR.search(texto)
                if m_venc_valor:
                    vencimento = m_venc_valor.group(1)
                    valor = _num(m_venc_valor.group(2))
                else:
                    m_venc = _RE_VENCIMENTO.search(texto)
                    m_valor = _RE_VALOR_PAGO.search(texto)
                    if not (m_venc and m_valor):
                        continue  # sem data/valor não há despesa reconhecível nessa página
                    vencimento = m_venc.group(1)
                    valor = _num(m_valor.group(1))
                m_desc = _RE_DESCRICAO.search(texto)
                descricao = m_desc.group(1).strip() if m_desc else ""
                m_forn = _RE_FORNECEDOR.search(texto)
                fornecedor = m_forn.group(1).strip() if m_forn else ""
                # "Categoria" pode vir com o rótulo DEPOIS do valor quando o
                # nome é longo o bastante pra quebrar linha (mesma inversão
                # rótulo/valor de tabelas com célula multi-linha vista em
                # outros administradoras) — nesse caso usa a descrição como
                # categoria (cosmético só, não entra na soma/duplicidade real).
                m_cat = _RE_CATEGORIA.search(texto)
                categoria = m_cat.group(1).strip() if m_cat else (descricao or None)

                chave = (categoria, vencimento, round(valor, 2), fornecedor, descricao)
                if chave in vistos:
                    continue  # mesma despesa, outra página de anexo (Cobrança/Comprovante)
                vistos.add(chave)

                indice += 1
                registros.append(RegistroComprovante(
                    pagina=pagina_num,
                    codigo=str(indice),
                    tipo_documento="despesa_listada",
                    descricao=descricao or fornecedor or categoria,
                    fornecedor=fornecedor or None,
                    vencimento=vencimento,
                    valor=valor,
                    categoria_demonstrativo=categoria,
                    conta="TOTAL",
                    texto_bruto=texto,
                ))

        if total_declarado is not None:
            registros.append(RegistroComprovante(
                pagina=1,
                codigo="total",
                tipo_documento="total_conta_declarado",
                conta="TOTAL",
                descricao="TOTAL",
                valor=total_declarado,
                texto_bruto=f"Totalizações — Despesas: {total_declarado}",
            ))

        return registros
