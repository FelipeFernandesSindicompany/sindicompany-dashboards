"""
Gera o esqueleto de um novo adapter para uma empresa que ainda não existe.
Uso:
  python scripts/novo_adapter.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ADAPTERS_DIR = ROOT / "adapters"

TEMPLATE = '''\
"""
Adapter {empresa_titulo} — descreva aqui o formato do arquivo.

Estrutura esperada do XLSX:
  - Aba "...": col A = ..., col B = ...
  - (documente conforme o arquivo real da empresa)
"""
from pathlib import Path
import openpyxl
from adapters.base import AdapterBase, DadosFinanceiros


class Adapter{classe}(AdapterBase):

    def ler_xlsx(self, caminho: Path, mes_referencia: str) -> DadosFinanceiros:
        wb = openpyxl.load_workbook(caminho, data_only=True)
        dados = DadosFinanceiros(
            condominio_id=self.config.get("id", ""),
            mes_referencia=mes_referencia,
        )

        # TODO: implemente a leitura do formato específico desta empresa
        # Exemplo:
        # ws = wb["NomeDaAba"]
        # for row in ws.iter_rows(min_row=2, values_only=True):
        #     ...

        dados.total_unidades = self.config.get("unidades", 0)
        dados.saldo_atual = self.calcular_saldo(dados)
        return dados
'''

INIT_LINE = "from adapters.{modulo} import Adapter{classe}\n"
DICT_LINE = '    "{empresa_id}": Adapter{classe},\n'


def to_pascal(s: str) -> str:
    return "".join(w.capitalize() for w in s.split("_"))


def main():
    print("\n=== Novo Adapter de Empresa ===\n")
    empresa_id = input("ID da empresa (ex: empresa_c): ").strip().lower().replace(" ", "_")
    if not empresa_id:
        sys.exit(1)

    classe = to_pascal(empresa_id)
    modulo = empresa_id
    caminho = ADAPTERS_DIR / f"{modulo}.py"

    if caminho.exists():
        print(f"[AVISO] {caminho} já existe. Abortado para não sobrescrever.")
        sys.exit(1)

    # Gera arquivo do adapter
    codigo = TEMPLATE.format(
        empresa_titulo=empresa_id.replace("_", " ").title(),
        classe=classe,
    )
    caminho.write_text(codigo, encoding="utf-8")
    print(f"[OK] Criado: adapters/{modulo}.py")

    # Atualiza __init__.py
    init_path = ADAPTERS_DIR / "__init__.py"
    conteudo = init_path.read_text(encoding="utf-8")

    # Adiciona import após última linha de import
    nova_linha_import = f"from adapters.{modulo} import Adapter{classe}\n"
    if nova_linha_import not in conteudo:
        conteudo = conteudo.replace(
            "\nADAPTERS = {",
            f"{nova_linha_import}\nADAPTERS = {{"
        )

    # Adiciona entrada no dicionário ADAPTERS
    nova_entrada = f'    "{empresa_id}": Adapter{classe},\n'
    if nova_entrada not in conteudo:
        conteudo = conteudo.replace("}\n", f"{nova_entrada}}}\n", 1)

    init_path.write_text(conteudo, encoding="utf-8")
    print(f"[OK] adapters/__init__.py atualizado")
    print(f"\nPróximo passo: edite adapters/{modulo}.py e implemente o método ler_xlsx()")


if __name__ == "__main__":
    main()
