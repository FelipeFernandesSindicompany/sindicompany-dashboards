import pdfplumber, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Gravura Residencial\Prestação de Contas 04.2026.PDF"
with pdfplumber.open(path) as pdf:
    print(f"Total de páginas: {len(pdf.pages)}")
    for i, p in enumerate(pdf.pages):
        t = p.extract_text()
        if not t:
            continue
        # Mostra páginas com palavras-chave relevantes
        keywords = ["resumo", "financeiro", "total", "despesa", "devedor", "saldo", "inadim"]
        if any(k in t.lower() for k in keywords):
            print(f"\n=== PAG {i+1} ===")
            print(t[:2000])
