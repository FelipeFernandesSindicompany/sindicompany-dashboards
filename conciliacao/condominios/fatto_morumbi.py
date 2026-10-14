"""
Conciliador específico — Fatto Morumbi.

Cadastrado como empresa_gestora="manager_adm_pdf" (PDF "Prestação de Contas MM.AAAA", ContasData/Manager ADM, até jul/2026), mas
em ago/2026 a administradora passou a entregar a planilha Habitacional ("Demonstrações Por Conta", `prestacao_contas_8_2026.xlsx`) —
mesma migração já vista em Cores, Baturité e Onze 22. O formato é escolhido pela extensão do arquivo recebido:
  PDF              → ContasData (Lirba), como sempre
  .xlsx/.xlsm/.xls → leitor de planilha Habitacional (despesas + hyperlink "Link" na coluna Anexo) e, depois, cada anexo é BAIXADO do
                     Webware (conciliacao/webware_documentos.py: JPEG ou PDF, um ou mais documentos por lançamento), lido (texto nativo
                     ou OCR) e tem o valor extraído — assim a planilha passa pelo MESMO conferidor de conteúdo (valor, nota fiscal, atraso)
                     do PDF, em vez de só "existe link".
"""
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from conciliacao import gocontroledocumentos, ocr, webware_documentos
from conciliacao.habitacional_xlsx import ConciliadorHabitacionalXLSX
from conciliacao.lirba_pdf import ConciliadorLirbaPDF
from conciliacao.lirba_pdf import preencher_de_texto as _preencher_via_cadeia_compartilhada
from conciliacao.lirba_pdf import valor_aparece_no_texto as _valor_aparece_no_texto

TRABALHADORES = 6
MAX_PAGINAS_PDF = 8
_RE_TOTAL_DAMSP = re.compile(r"Total\s*\(R\$\)\s*([\d.]+,\d{2}|\d{3,})")


def _total_damsp(texto: str) -> float | None:
    """Campo "Total (R$)" da guia DAMSP (ISS), que é o valor pago (o campo "Valor" é sem multa/juros). O OCR às vezes perde a vírgula
    ("2479" = 24,79): sem vírgula, os dois últimos dígitos são os centavos."""
    m = _RE_TOTAL_DAMSP.search(texto or "")
    if not m:
        return None
    s = m.group(1)
    return round(float(s.replace(".", "").replace(",", ".")), 2) if "," in s else round(int(s) / 100, 2)


def _texto_do_documento(dados: bytes, tipo: str) -> list[str]:
    """Um texto por página: PDF → texto nativo (OCR na página sem texto); JPEG → OCR."""
    if tipo != "pdf":
        return [ocr.ocr_imagem_bytes(dados) or ""]
    textos: list[str] = []
    try:
        import fitz
        with fitz.open(stream=dados, filetype="pdf") as doc:
            for i in range(min(len(doc), MAX_PAGINAS_PDF)):
                t = (doc[i].get_text() or "").strip()
                if len(t) < 30:
                    try:
                        t = ocr.ocr_imagem_bytes(doc[i].get_pixmap(dpi=200).tobytes("png")) or ""
                    except Exception:
                        t = ""
                textos.append(t)
    except Exception:
        return []
    return textos


class Conciliador(ConciliadorLirbaPDF):
    def extrair_comprovantes(self, caminho: Path) -> list:
        if not str(caminho).lower().endswith((".xlsx", ".xlsm", ".xls")):
            return super().extrair_comprovantes(caminho)
        registros = ConciliadorHabitacionalXLSX(self.config).extrair_comprovantes(caminho)
        despesa_por_codigo = {r.codigo: r for r in registros if r.tipo_documento == "despesa_listada"}
        alvos = [r for r in registros if r.tipo_documento == "comprovante_anexado" and webware_documentos.eh_link_webware(r.texto_bruto)]
        with ThreadPoolExecutor(max_workers=TRABALHADORES) as pool:
            list(pool.map(lambda r: self._ler_anexo(caminho, r, despesa_por_codigo.get(r.codigo)), alvos))
        return registros

    def _ler_anexo(self, caminho: Path, comp, despesa) -> None:
        """Baixa os documentos do anexo, lê (texto/OCR) e preenche valor/data/fornecedor do comprovante. Nunca lança."""
        try:
            docs = webware_documentos.baixar_documentos(comp.texto_bruto)
            if not docs:
                return                      # download falhou: fica só o link (comprovante "anexado" sem conteúdo lido)
            esperado = abs(despesa.valor) if despesa and despesa.valor else None
            textos_doc: list[str] = []
            candidatos = []
            for dados, tipo in docs:
                paginas = _texto_do_documento(dados, tipo)
                texto = "\n".join(p for p in paginas if p)
                textos_doc.append(texto)
                cand = type(comp)(pagina=comp.pagina, tipo_documento="comprovante_anexado", codigo=comp.codigo)
                _preencher_via_cadeia_compartilhada(cand, texto)
                candidatos.append(cand)
            melhor = next((c for c in candidatos if c.valor and esperado is not None and abs(c.valor - esperado) <= 0.01),
                          next((c for c in candidatos if c.valor), None))
            # O valor da listagem aparece, formatado como moeda, no texto de algum documento lido (ex.: DAMSP com "Valor 15,00" e "Total 15,49";
            # NFS-e cujo total o leitor parcial pegou como 17,49): está confirmado — mesma regra que o motor aplica ao PDF.
            confirmado = esperado is not None and any(
                _valor_aparece_no_texto(t, esperado) or _total_damsp(t) == round(esperado, 2) for t in textos_doc)
            if confirmado:
                melhor = melhor or candidatos[0]
                melhor.valor = esperado
            if melhor is not None:
                comp.valor = melhor.valor
                comp.vencimento = melhor.vencimento
                comp.pagamento = melhor.pagamento
                comp.fornecedor = melhor.fornecedor
                comp.cnpj_cpf = melhor.cnpj_cpf
                comp.autenticacao = melhor.autenticacao
            comp.texto_bruto = "\n\n---\n\n".join(t for t in textos_doc if t.strip())
            comp.arquivo_evidencia_externa = gocontroledocumentos.salvar_evidencia_externa(caminho, comp.codigo, docs[0][0], docs[0][1])
        except Exception:                   # um anexo com problema não derruba os demais
            return
