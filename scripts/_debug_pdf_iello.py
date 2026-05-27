import pdfplumber, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Giardino D'Itália\Prestação de Contas 04.2026.pdf"
with pdfplumber.open(path) as pdf:
    for i, p in enumerate(pdf.pages):
        print(f"\n=== PAG {i+1} ===")
        t = p.extract_text()
        if t: print(t[:3000])
