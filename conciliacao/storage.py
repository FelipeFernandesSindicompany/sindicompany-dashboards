"""
Layout em disco do motor de conciliação — versionado, nunca sobrescreve.

    data/<pasta_dados>/conciliacao/<mes>/
      v1/
        input/<nome original do arquivo>
        registros_comprovantes.json
        achados_brutos.json
        achados_revisados.json
        relatorio_final.pdf
        status.json
      latest              ← arquivo texto "v1" (sem symlink — compatibilidade Windows)

Nova versão só é criada pela etapa "extrair" (nova entrada recebida).
As etapas "interpretar" e "render" atualizam a versão corrente in-place.
"""
import dataclasses
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Type

ROOT = Path(__file__).parent.parent


def condo_mes_dir(pasta_dados: str, mes: str) -> Path:
    """'data/spazio_jardins_da_orla', '2026-08' -> Path(.../data/spazio_jardins_da_orla/conciliacao/2026-08)"""
    return ROOT / pasta_dados / "conciliacao" / mes


def _version_num(p: Path) -> int:
    m = re.match(r"^v(\d+)$", p.name)
    return int(m.group(1)) if m else 0


def list_versions(base_dir: Path) -> list[int]:
    if not base_dir.exists():
        return []
    return sorted(_version_num(p) for p in base_dir.glob("v*") if p.is_dir() and _version_num(p) > 0)


def latest_version_dir(base_dir: Path) -> Path | None:
    """Lê o ponteiro 'latest' (arquivo texto); cai para a maior vN existente se ausente."""
    pointer = base_dir / "latest"
    if pointer.exists():
        nome = pointer.read_text(encoding="utf-8").strip()
        candidate = base_dir / nome
        if candidate.is_dir():
            return candidate
    versoes = list_versions(base_dir)
    return (base_dir / f"v{versoes[-1]}") if versoes else None


def new_version_dir(base_dir: Path) -> Path:
    """Cria e retorna a próxima pasta vN+1 (não mexe em versões anteriores)."""
    proximo = (max(list_versions(base_dir)) if list_versions(base_dir) else 0) + 1
    version_dir = base_dir / f"v{proximo}"
    (version_dir / "input").mkdir(parents=True, exist_ok=False)
    _set_latest(base_dir, version_dir)
    return version_dir


def _set_latest(base_dir: Path, version_dir: Path) -> None:
    (base_dir / "latest").write_text(version_dir.name, encoding="utf-8")


def copy_input_file(version_dir: Path, src: Path, nome_destino: str) -> Path:
    """Copia o arquivo original recebido para input/ — nunca move nem altera o original."""
    dest = version_dir / "input" / nome_destino
    shutil.copy2(src, dest)
    return dest


def write_origem(version_dir: Path, arquivo_original: Path) -> None:
    """
    Guarda o caminho ORIGINAL (pasta do projeto) do arquivo recebido em
    --etapa extrair — usado depois em --etapa render pra localizar o
    arquivo do mês anterior na mesma pasta (ver
    conciliacao/demonstrativo_reader.py). A cópia em input/ preserva o
    nome, mas não a pasta de origem.
    """
    with open(version_dir / "origem.json", "w", encoding="utf-8") as f:
        json.dump({"arquivo_original": str(arquivo_original)}, f, ensure_ascii=False, indent=2)


def read_origem(version_dir: Path) -> Path | None:
    p = version_dir / "origem.json"
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        dados = json.load(f)
    caminho = dados.get("arquivo_original")
    return Path(caminho) if caminho else None


def _to_jsonable(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    return obj


def write_dataclass_list(path: Path, items: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_to_jsonable(items), f, ensure_ascii=False, indent=2)


def read_dataclass_list(path: Path, cls: Type) -> list:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [cls(**item) for item in raw]


def read_status(version_dir: Path) -> dict:
    p = version_dir / "status.json"
    if not p.exists():
        return {"etapa_atual": None, "iniciado_em": None, "concluido_em": None, "erros": []}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_status(version_dir: Path, etapa_atual: str, erro: str | None = None, concluido: bool = False) -> None:
    status = read_status(version_dir)
    agora = datetime.now(timezone.utc).isoformat()
    if status.get("iniciado_em") is None:
        status["iniciado_em"] = agora
    status["etapa_atual"] = etapa_atual
    if erro:
        status.setdefault("erros", []).append({"etapa": etapa_atual, "erro": erro, "em": agora})
    if concluido:
        status["concluido_em"] = agora
    with open(version_dir / "status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
