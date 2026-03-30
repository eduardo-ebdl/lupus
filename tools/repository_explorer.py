"""Tool utilitária: mapeamento completo e anotado do repositório.

Mais detalhado que discover_project — retorna a árvore de diretórios completa
com tipos de arquivo identificados, sumário por categoria e arquivos-chave.
Funciona com qualquer repositório configurado via PROJECT_PATH.
"""

import json
import os
import re

from langchain.tools import tool


def _get_project_root() -> str:
    """Retorna o root do projeto via ctx_manager (fonte centralizada)."""
    from core.context_manager import get_project_path
    return get_project_path()


# Padrões que indicam possíveis segredos hardcoded
_SECRET_PATTERNS = [
    (r'(?i)(password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']', "password"),
    (r'(?i)(api[_-]?key|apikey)\s*=\s*["\'][^"\']{8,}["\']', "api_key"),
    (r'(?i)(secret[_-]?key|secret)\s*=\s*["\'][^"\']{8,}["\']', "secret"),
    (r'(?i)(token)\s*=\s*["\'][^"\']{8,}["\']', "token"),
    (r'(?i)(aws[_-]?access[_-]?key[_-]?id)\s*=\s*["\'][A-Z0-9]{16,}["\']', "aws_key"),
    (r'AKIA[0-9A-Z]{16}', "aws_access_key"),
    (r'(?i)(private[_-]?key)\s*=\s*["\'][^"\']{10,}["\']', "private_key"),
    (r'-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----', "private_key_pem"),
]

_SECRET_SKIP_FILES = {".env.example", ".env.sample", ".env.template"}


def _scan_secrets(project_root: str, files: list[dict]) -> list[dict]:
    """Verifica arquivos de texto por possíveis segredos hardcoded."""
    findings: list[dict] = []
    scannable_types = {"python", "javascript", "typescript", "config", "shell", "text", "json"}

    for entry in files:
        if entry["type"] not in scannable_types:
            continue
        fname = os.path.basename(entry["path"])
        if fname in _SECRET_SKIP_FILES:
            continue

        fpath = os.path.join(project_root, entry["path"])
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                content = f.read(8000)  # lê no máximo 8 KB
        except OSError:
            continue

        for pattern, secret_type in _SECRET_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                findings.append({
                    "file": entry["path"],
                    "type": secret_type,
                    "matches": len(matches),
                })
                break  # um aviso por arquivo é suficiente

    return findings


_SKIP_DIRS = {
    "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "rag",
}

_FILE_TYPES = {
    # Data
    ".sql": "sql", ".csv": "data", ".parquet": "data",
    ".xlsx": "data", ".xls": "data", ".db": "data", ".sqlite": "data",
    # Python
    ".py": "python", ".ipynb": "notebook",
    # Config
    ".yml": "config", ".yaml": "config", ".toml": "config",
    ".cfg": "config", ".ini": "config", ".env": "config",
    # Web / Frontend
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".html": "html", ".css": "css", ".scss": "css",
    # IaC
    ".tf": "terraform", ".hcl": "terraform",
    # Docs / Text
    ".md": "markdown", ".rst": "docs", ".txt": "text",
    # Build / Other
    ".json": "json", ".sh": "shell", ".lock": "lockfile",
}

_KEY_FILES = {
    "dbt_project.yml", "databricks.yml", "requirements.txt", "pyproject.toml",
    "package.json", "package-lock.json", "pom.xml", "build.gradle", "go.mod",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Makefile", "README.md",
    ".env.example", ".gitignore", "main.py", "app.py", "manage.py",
    "setup.py", "setup.cfg", "conftest.py",
}


def _file_type(fname: str) -> str:
    if fname.lower() == "dockerfile":
        return "docker"
    ext = os.path.splitext(fname)[1].lower()
    return _FILE_TYPES.get(ext, "other")


@tool
def explore_repository(max_depth: int = 3) -> str:
    """Retorna a estrutura completa e anotada do repositório em PROJECT_PATH.

    Lista todos os arquivos com tipos identificados, sumário por categoria,
    arquivos-chave (configs, entry points) e organização por diretório.

    Use quando precisar de uma visão detalhada da estrutura antes de analisar
    partes específicas — especialmente em projetos que discover_project não
    mapeou completamente, ou antes de suggest_improvements.

    Args:
        max_depth: Profundidade máxima de diretórios a percorrer (padrão: 3, máximo: 10).
    """
    max_depth = max(1, min(max_depth, 10))
    project_root = _get_project_root()

    if not os.path.isdir(project_root):
        return json.dumps({
            "error": f"Diretório não encontrado: {project_root}",
            "hint": "Configure PROJECT_PATH para apontar para o repositório.",
        }, ensure_ascii=False, indent=2)

    files = []
    type_counts: dict[str, int] = {}
    key_files_found: list[str] = []
    dirs_summary: dict[str, dict] = {}

    for dirpath, dirs, filenames in os.walk(project_root):
        # Filtra e ordena diretórios in-place para controlar o walk
        dirs[:] = sorted([
            d for d in dirs
            if not d.startswith(".")
            and d not in _SKIP_DIRS
            and not d.endswith(".egg-info")
        ])

        rel_dir = os.path.relpath(dirpath, project_root).replace("\\", "/")
        depth = 0 if rel_dir == "." else len(rel_dir.split("/"))

        if depth > max_depth:
            dirs.clear()
            continue

        for fname in sorted(filenames):
            if fname.startswith(".") and fname not in {".env.example", ".gitignore"}:
                continue

            rel_path = os.path.join(rel_dir, fname).replace("\\", "/")
            if rel_path.startswith("./"):
                rel_path = rel_path[2:]

            ftype = _file_type(fname)
            files.append({"path": rel_path, "type": ftype})
            type_counts[ftype] = type_counts.get(ftype, 0) + 1

            if fname in _KEY_FILES:
                key_files_found.append(rel_path)

            dir_key = rel_dir if rel_dir != "." else "(root)"
            if dir_key not in dirs_summary:
                dirs_summary[dir_key] = {"file_count": 0, "types": []}
            dirs_summary[dir_key]["file_count"] += 1
            if ftype not in dirs_summary[dir_key]["types"]:
                dirs_summary[dir_key]["types"].append(ftype)

    secret_warnings = _scan_secrets(project_root, files)

    result = {
        "project_root": project_root,
        "total_files": len(files),
        "type_summary": type_counts,
        "key_files": key_files_found,
        "directories": dirs_summary,
        "files": files,
    }
    if secret_warnings:
        result["security_warnings"] = {
            "count": len(secret_warnings),
            "message": "Possíveis segredos hardcoded detectados. Verifique os arquivos abaixo.",
            "findings": secret_warnings,
        }

    return json.dumps(result, ensure_ascii=False, indent=2)
