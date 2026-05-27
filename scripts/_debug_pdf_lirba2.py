import pdfplumber, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"C:\Users\MF PRINTER\OneDrive - Perfil de E-mail\Documentos\Claude\Projects\Dashboard de Análise de Balancete Gravura Residencial\Prestação de Contas 04.2026.PDF"
with pdfplumber.open(path) as pdf:
    # Página 15 (index 14) - Resumo Financeiro Contábil
    print("=== PAG 15 (Resumo Financeiro Contábil) ===")
    t = pdf.pages[14].extract_text()
    if t: print(t)

    # Página 16 (index 15) - continua?
    print("\n=== PAG 16 ===")
    t = pdf.pages[15].extract_text()
    if t: print(t[:3000])

    # Páginas de despesas (22+)
    print("\n=== PAG 22 (Demonstrativo de Despesas) ===")
    t = pdf.pages[21].extract_text()
    if t: print(t[:2000])

    print("\n=== PAG 23 ===")
    t = pdf.pages[22].extract_text()
    if t: print(t[:2000])

    # Relação de devedores
    print("\n=== PAG 350 (COTAS EM ABERTO) ===")
    t = pdf.pages[349].extract_text()
    if t: print(t[:3000])
