"""
Utilitário para adicionar um novo condomínio ao config sem editar JSON manualmente.
Uso:
  python scripts/novo_condominio.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "condominios.json"


def slugify(texto: str) -> str:
    texto = texto.lower().strip()
    texto = re.sub(r"[áàãâä]", "a", texto)
    texto = re.sub(r"[éèêë]", "e", texto)
    texto = re.sub(r"[íìîï]", "i", texto)
    texto = re.sub(r"[óòõôö]", "o", texto)
    texto = re.sub(r"[úùûü]", "u", texto)
    texto = re.sub(r"ç", "c", texto)
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    return texto.strip("_")


def main():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    empresas_disponiveis = list(config["empresas"].keys())
    print("\n=== Novo Condomínio ===\n")

    nome = input("Nome do condomínio: ").strip()
    if not nome:
        print("Nome obrigatório.")
        sys.exit(1)

    id_sugerido = slugify(nome)
    id_input = input(f"ID (sugestão: {id_sugerido}): ").strip()
    cond_id = slugify(id_input) if id_input else id_sugerido

    # Verifica duplicata
    if any(c["id"] == cond_id for c in config["condominios"]):
        print(f"[ERRO] Já existe um condomínio com id '{cond_id}'.")
        sys.exit(1)

    print(f"\nEmpresas disponíveis: {', '.join(empresas_disponiveis)}")
    empresa = input("Empresa gestora: ").strip()
    if empresa not in empresas_disponiveis:
        adicionar = input(f"Empresa '{empresa}' não cadastrada. Deseja cadastrá-la agora? (s/n): ").strip().lower()
        if adicionar == "s":
            adapter_mod = input(f"Nome do módulo adapter (ex: adapters.empresa_c): ").strip()
            descricao = input("Descrição do formato: ").strip()
            config["empresas"][empresa] = {
                "nome": empresa.replace("_", " ").title(),
                "adapter": adapter_mod,
                "formatos": ["xlsx"],
                "descricao": descricao,
            }
            print(f"  [OK] Empresa '{empresa}' cadastrada. Lembre-se de criar o arquivo {adapter_mod.replace('.', '/')}.py")
        else:
            print("Abortado.")
            sys.exit(1)

    unidades = input("Número de unidades: ").strip()
    try:
        unidades = int(unidades)
    except ValueError:
        unidades = 0

    cor = input("Cor do dashboard (hex, ex: #2563eb): ").strip() or "#2563eb"

    novo = {
        "id": cond_id,
        "nome": nome,
        "empresa_gestora": empresa,
        "pasta_dados": f"data/{cond_id}",
        "ativo": True,
        "cor": cor,
        "unidades": unidades,
    }

    config["condominios"].append(novo)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    # Cria pasta de dados
    pasta = ROOT / "data" / cond_id
    pasta.mkdir(parents=True, exist_ok=True)

    print(f"\n[OK] Condomínio '{nome}' adicionado com sucesso!")
    print(f"     Coloque os arquivos mensais em: data/{cond_id}/YYYY-MM/")
    print(f"     Depois rode: python scripts/processar.py --mes YYYY-MM --condominio {cond_id}")


if __name__ == "__main__":
    main()
