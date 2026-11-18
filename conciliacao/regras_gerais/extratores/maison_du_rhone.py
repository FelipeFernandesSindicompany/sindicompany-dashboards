"""
Extrator das regras gerais — Maison du Rhône (Predial Ruggiero, Software DataDigitus).

O condomínio recebe, conforme o mês, (a) o balancete em PDF COM texto (jul/ago/2026 "Balancete consolidado"; set/2026 layout nativo Ruggiero de
22 páginas) ou (b) a "Pasta Contábil" ESCANEADA (190 a 200 páginas, nenhuma com texto: balancete impresso no começo, depois extratos bancários,
recibos, notas fiscais e comprovantes). Para (b) o balancete está nas primeiras páginas (relatórios 1.1/3.2/2.1/5.4 e o quadro "Resumo das contas
de balancete"), que ganham uma camada de texto lida por OCR (números votados entre 5 resoluções) — `_ocr_posicional.escrever_pdf_pesquisavel`.

Este módulo faz isso para QUALQUER arquivo sem texto que o extrator receber — em especial o MÊS ANTERIOR lido da pasta do projeto (continuidade de
saldos, rendimento e fornecedores dos meses anteriores dependem dele); o mês atual já vem com a camada de texto (scripts/gerar_relatorio_conciliacao.py,
`ocr_pdf_sem_texto`). A cópia com texto fica no cache do OCR (por impressão digital do arquivo), nunca na pasta do projeto. Os números são conferidos
pelas somas que o próprio balancete traz (leitor datadigitus_ruggiero); o que não fechar entra em `avisos`.
"""
from pathlib import Path

from conciliacao.regras_gerais.extratores import datadigitus as _dd

PAGINAS_BALANCETE = 34       # o balancete e o "Resumo das contas" ficam até a p. ~18; as seguintes (extratos, pendências) são lidas junto sem custo extra relevante


def _sem_texto(caminho: Path) -> bool:
    try:
        import fitz

        doc = fitz.open(str(caminho))
        try:
            return sum(len(doc[i].get_text().strip()) for i in range(min(len(doc), 12))) <= 200
        finally:
            doc.close()
    except Exception:
        return False


def _com_texto(caminho: Path, max_paginas: int = PAGINAS_BALANCETE) -> Path:
    """Caminho de uma cópia com camada de texto por OCR (em cache) se o PDF é só imagem; senão, o próprio arquivo."""
    caminho = Path(caminho)
    if caminho.suffix.lower() != ".pdf" or not _sem_texto(caminho):
        return caminho
    try:
        from conciliacao import ocr
        from conciliacao.regras_gerais.extratores._ocr_posicional import escrever_pdf_pesquisavel

        alvo = ocr._CACHE_DIR / f"{ocr._impressao_arquivo(caminho)}.texto{max_paginas}.pdf"
        if not alvo.exists():
            alvo.parent.mkdir(parents=True, exist_ok=True)
            if not escrever_pdf_pesquisavel(caminho, alvo, max_paginas=max_paginas):
                return caminho
        return alvo
    except Exception:
        return caminho


class Extrator(_dd.Extrator):
    def extrair(self, caminho: Path, mes: str):
        dados = super().extrair(_com_texto(Path(caminho)), mes)
        dados.arquivo = Path(caminho).name
        return dados
