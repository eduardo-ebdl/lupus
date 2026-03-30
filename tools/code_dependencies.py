"""Tool de domínio: mapa de dependências entre arquivos de código.

Analisa imports/requires estáticos nos arquivos do repositório e constrói
um grafo de dependências interno — útil para entender acoplamento, módulos
centrais e arquivos de entrada (entry points).

Suporta: Python (.py), JavaScript/TypeScript (.js/.jsx/.ts/.tsx), Go (.go).
"""

import json
import os
import re

from langchain.tools import tool

from tools import cache as _cache


def _get_project_root() -> str:
    """Retorna o root do projeto via ctx_manager (fonte centralizada)."""
    from core.context_manager import get_project_path
    return get_project_path()


_SKIP_DIRS = {
    "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "rag", ".git",
}

# ---------------------------------------------------------------------------
# Parsers por linguagem
# ---------------------------------------------------------------------------

def _parse_python_imports(source: str) -> list[str]:
    """Extrai módulos importados em um arquivo Python."""
    imports = []
    # import foo, import foo.bar
    for m in re.finditer(r"^import\s+([\w.,\s]+)", source, re.MULTILINE):
        for part in m.group(1).split(","):
            top = part.strip().split(".")[0].split(" as ")[0].strip()
            if top:
                imports.append(top)
    # from foo import bar, from .foo import bar
    for m in re.finditer(r"^from\s+(\.{0,2}[\w.]*)\s+import", source, re.MULTILINE):
        mod = m.group(1).lstrip(".")
        top = mod.split(".")[0] if mod else "(relative)"
        if top:
            imports.append(top)
    return imports


def _parse_js_imports(source: str) -> list[str]:
    """Extrai módulos importados em JS/TS (import + require)."""
    imports = []
    # import ... from '...'
    for m in re.finditer(r"""(?:import|export).*?from\s+['"]([^'"]+)['"]""", source):
        imports.append(m.group(1))
    # require('...')
    for m in re.finditer(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", source):
        imports.append(m.group(1))
    return imports


def _parse_go_imports(source: str) -> list[str]:
    """Extrai imports de um arquivo Go."""
    imports = []
    # import "pkg" ou import ( "pkg" )
    for m in re.finditer(r'"([^"]+)"', source):
        imports.append(m.group(1))
    return imports


# ---------------------------------------------------------------------------
# Collector principal
# ---------------------------------------------------------------------------

def _collect_files(project_root: str) -> dict[str, dict]:
    """
    Percorre o repositório e extrai dependências de cada arquivo suportado.
    Retorna um dict: rel_path → {language, imports: [str], is_internal: bool}
    """
    files: dict[str, dict] = {}

    for dirpath, dirs, filenames in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, project_root).replace("\\", "/")

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in {".py", ".js", ".jsx", ".ts", ".tsx", ".go"}:
                continue

            rel_path = os.path.join(rel_dir, fname).replace("\\", "/")
            if rel_path.startswith("./"):
                rel_path = rel_path[2:]

            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    source = f.read()
            except OSError:
                continue

            if ext == ".py":
                language = "python"
                raw_imports = _parse_python_imports(source)
            elif ext in {".js", ".jsx", ".ts", ".tsx"}:
                language = "javascript" if ext in {".js", ".jsx"} else "typescript"
                raw_imports = _parse_js_imports(source)
            else:
                language = "go"
                raw_imports = _parse_go_imports(source)

            files[rel_path] = {
                "language": language,
                "imports": sorted(set(raw_imports)),
            }

    return files


def _resolve_internal(
    files: dict[str, dict],
    project_root: str,
) -> dict[str, dict]:
    """
    Separa imports em internos (outros arquivos do repo) vs externos (libs).
    Adiciona 'internal_deps' e 'external_deps' a cada entrada.
    """
    # Conjunto de módulos Python que existem no repo (sem extensão)
    py_modules = set()
    for rel_path in files:
        if rel_path.endswith(".py"):
            # transforma path em nome de módulo: tools/cache.py → tools.cache e cache
            parts = rel_path.replace("/", ".").removesuffix(".py")
            py_modules.add(parts)
            py_modules.add(parts.split(".")[-1])  # nome simples

    for rel_path, info in files.items():
        internal: list[str] = []
        external: list[str] = []

        for imp in info["imports"]:
            if info["language"] == "python":
                is_internal = imp in py_modules or imp == "(relative)"
            else:
                # JS/TS: imports relativos começam com . ou ..
                is_internal = imp.startswith(".") or imp.startswith("/")

            if is_internal:
                internal.append(imp)
            else:
                external.append(imp)

        info["internal_deps"] = internal
        info["external_deps"] = external

    return files


def _build_summary(files: dict[str, dict]) -> dict:
    """Calcula métricas de dependências."""
    lang_counts: dict[str, int] = {}
    most_imported: dict[str, int] = {}

    for rel_path, info in files.items():
        lang = info["language"]
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        for imp in info["external_deps"]:
            most_imported[imp] = most_imported.get(imp, 0) + 1

    top_external = sorted(most_imported.items(), key=lambda x: -x[1])[:15]

    # Entry points: arquivos que ninguém importa internamente
    imported_modules: set[str] = set()
    for info in files.values():
        imported_modules.update(info["internal_deps"])

    entry_points = [
        p for p, info in files.items()
        if not (
            os.path.splitext(os.path.basename(p))[0] in imported_modules
            or p in imported_modules
        )
        and info["language"] == "python"
        and os.path.basename(p) in {"main.py", "app.py", "run.py", "cli.py", "server.py", "manage.py"}
    ]

    return {
        "files_analyzed": len(files),
        "by_language": lang_counts,
        "top_external_dependencies": [{"module": m, "used_by": c} for m, c in top_external],
        "likely_entry_points": entry_points,
    }


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def map_code_dependencies(language: str = "", file_path: str = "") -> str:
    """Mapeia dependências entre arquivos de código do repositório.

    Analisa imports estáticos (Python import/from, JS/TS import/require, Go import)
    e retorna: dependências internas (entre arquivos do repo), externas (bibliotecas),
    métricas por linguagem e possíveis entry points.

    Args:
        language: Filtra por linguagem ('python', 'typescript', 'javascript', 'go').
                  Se vazio, analisa todos os arquivos suportados.
        file_path: Retorna dependências de um arquivo específico
                   (ex: 'tools/subagents.py'). Se vazio, retorna visão geral.
    """
    _key = _cache.make_key("map_code_dependencies", language=language, file_path=file_path)
    if hit := _cache.get(_key):
        return hit

    project_root = _get_project_root()

    if not os.path.isdir(project_root):
        return json.dumps({
            "error": f"Diretório não encontrado: {project_root}",
            "hint": "Configure PROJECT_PATH para apontar para o repositório.",
        }, ensure_ascii=False, indent=2)

    all_files = _collect_files(project_root)
    all_files = _resolve_internal(all_files, project_root)

    if not all_files:
        result = json.dumps({
            "error": "Nenhum arquivo Python/JS/TS/Go encontrado.",
            "project_root": project_root,
        }, ensure_ascii=False, indent=2)
        return result

    # Filtro por arquivo específico
    if file_path:
        key = file_path.replace("\\", "/").lstrip("./")
        if key not in all_files:
            # Tenta busca parcial
            matches = [p for p in all_files if p.endswith(key) or key in p]
            if not matches:
                result = json.dumps({
                    "error": f"Arquivo '{file_path}' não encontrado.",
                    "available_files": sorted(all_files.keys()),
                }, ensure_ascii=False, indent=2)
                return result
            key = matches[0]

        result = json.dumps({
            "file": key,
            **all_files[key],
        }, ensure_ascii=False, indent=2)
        _cache.set(_key, result)
        return result

    # Filtro por linguagem
    if language:
        lang_key = language.lower()
        filtered = {p: v for p, v in all_files.items() if v["language"] == lang_key}
        if not filtered:
            result = json.dumps({
                "error": f"Nenhum arquivo '{language}' encontrado.",
                "available_languages": sorted({v["language"] for v in all_files.values()}),
            }, ensure_ascii=False, indent=2)
            return result
        all_files = filtered

    summary = _build_summary(all_files)

    result = json.dumps({
        "project_root": project_root,
        "summary": summary,
        "files": all_files,
    }, ensure_ascii=False, indent=2)
    _cache.set(_key, result)
    return result
