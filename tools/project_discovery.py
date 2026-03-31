"""Tool de descoberta: mapeia a estrutura e tecnologias do projeto analisado.

Detecta o que existe em PROJECT_PATH (dbt, DABs, notebooks, Python, Node.js,
Go, Java, Terraform, Kubernetes, etc.) e retorna quais domain tools fazem sentido
usar. Deve ser chamada antes de qualquer outra tool quando a pergunta envolver o
projeto como um todo.
"""

import json
import os

from langchain.tools import tool


_SKIP_WALK_DIRS = {
    "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git", ".hg", ".svn",
}


def _get_project_root() -> str:
    """Retorna o root do projeto via ctx_manager (fonte centralizada)."""
    from core.context_manager import get_project_path
    return get_project_path()


def _find_file(root: str, filename: str, max_depth: int = 3) -> str | None:
    """Procura um arquivo pelo nome até max_depth níveis de profundidade."""
    for dirpath, _dirs, files in os.walk(root):
        _dirs[:] = [d for d in _dirs if d not in _SKIP_WALK_DIRS]
        if filename in files:
            return dirpath
        depth = len(os.path.relpath(dirpath, root).split(os.sep))
        if depth >= max_depth:
            _dirs.clear()
    return None


def _count_files(root: str, extension: str) -> int:
    """Conta arquivos com determinada extensão no projeto."""
    count = 0
    for _root, _dirs, files in os.walk(root):
        _dirs[:] = [d for d in _dirs if d not in _SKIP_WALK_DIRS]
        count += sum(1 for f in files if f.endswith(extension))
    return count


def _detect_node(root: str) -> dict:
    """Detecta Node.js e identifica o framework frontend via package.json."""
    pkg_dir = _find_file(root, "package.json")
    if not pkg_dir:
        return {"found": False}

    pkg_path = os.path.join(pkg_dir, "package.json")
    try:
        with open(pkg_path, encoding="utf-8") as f:
            pkg = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return {"found": True, "framework": None}

    all_deps = {
        **pkg.get("dependencies", {}),
        **pkg.get("devDependencies", {}),
    }

    framework = None
    if "next" in all_deps:
        framework = "Next.js"
    elif "nuxt" in all_deps:
        framework = "Nuxt.js"
    elif "react" in all_deps:
        framework = "React"
    elif "vue" in all_deps:
        framework = "Vue"
    elif "@angular/core" in all_deps:
        framework = "Angular"
    elif "svelte" in all_deps:
        framework = "Svelte"

    return {
        "found": True,
        "framework": framework,
        "location": os.path.relpath(pkg_dir, root).replace("\\", "/"),
    }


def _detect_python_framework(root: str) -> str | None:
    """Detecta framework Python web (Django, FastAPI, Flask, etc.)."""
    # Django: sempre tem manage.py na raiz
    if os.path.exists(os.path.join(root, "manage.py")):
        return "Django"

    # FastAPI / Flask: checa imports em app.py ou main.py
    from config import MAX_CONTEXT_BYTES
    max_read = max(2000, MAX_CONTEXT_BYTES // 4)  # 1/4 do limite, mínimo 2KB
    for entry_file in ("app.py", "main.py", "server.py", "wsgi.py", "asgi.py"):
        candidate = os.path.join(root, entry_file)
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8", errors="ignore") as f:
                    content = f.read(max_read)
                if "fastapi" in content.lower():
                    return "FastAPI"
                if "flask" in content.lower():
                    return "Flask"
            except OSError:
                pass

    return None


def _detect_kubernetes(root: str) -> bool:
    """Detecta manifests Kubernetes (YAML com kind: Deployment/Service/etc.)."""
    from config import MAX_CONTEXT_BYTES
    max_read = max(500, MAX_CONTEXT_BYTES // 16)  # 1/16 do limite, mínimo 500B
    k8s_kinds = {
        "Deployment", "Service", "Pod", "StatefulSet", "DaemonSet",
        "Ingress", "ConfigMap", "Secret", "Namespace", "Job",
    }
    for dirpath, _dirs, files in os.walk(root):
        _dirs[:] = [d for d in _dirs if d not in _SKIP_WALK_DIRS]
        for fname in files:
            if not (fname.endswith(".yml") or fname.endswith(".yaml")):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    content = f.read(max_read)
                if any(f"kind: {k}" in content for k in k8s_kinds):
                    return True
            except OSError:
                pass
    return False


def _detect_data_files(root: str) -> dict:
    """Conta arquivos de dados locais no repositório."""
    counts = {
        "csv": _count_files(root, ".csv"),
        "parquet": _count_files(root, ".parquet"),
        "json_data": 0,
        "excel": _count_files(root, ".xlsx") + _count_files(root, ".xls"),
        "sqlite": _count_files(root, ".db") + _count_files(root, ".sqlite"),
    }
    # JSON de dados (exclui configs/package.json/etc. em raiz)
    for dirpath, _dirs, files in os.walk(root):
        _dirs[:] = [d for d in _dirs if d not in _SKIP_WALK_DIRS]
        rel = os.path.relpath(dirpath, root)
        if rel != ".":  # ignora JSONs da raiz (configs)
            counts["json_data"] += sum(1 for f in files if f.endswith(".json"))

    total = sum(counts.values())
    return {"found": total > 0, "counts": counts}


@tool
def discover_project() -> str:
    """Descobre a estrutura e tecnologias do projeto em PROJECT_PATH.

    Detecta tecnologias presentes (dbt, Databricks Asset Bundles, Jupyter,
    Python/frameworks web, Node.js/frontend, Go, Java, Terraform, Kubernetes,
    Docker, arquivos de dados locais) e indica quais tools usar.

    Use como ponto de partida quando a pergunta for sobre a estrutura,
    arquitetura ou capacidades gerais do projeto.
    """
    project_root = _get_project_root()

    if not os.path.isdir(project_root):
        return json.dumps({
            "error": f"Diretório não encontrado: {project_root}",
            "hint": "Configure PROJECT_PATH para apontar para o repositório.",
        }, ensure_ascii=False, indent=2)

    # --- Detecções ---

    dbt_dir = _find_file(project_root, "dbt_project.yml")
    databricks_dir = _find_file(project_root, "databricks.yml")

    notebooks = []
    for dirpath, _dirs, files in os.walk(project_root):
        _dirs[:] = [d for d in _dirs if d not in _SKIP_WALK_DIRS]
        for f in files:
            if f.endswith(".ipynb") and "outputs" not in f:
                notebooks.append(
                    os.path.relpath(os.path.join(dirpath, f), project_root).replace("\\", "/")
                )

    py_count = _count_files(project_root, ".py")
    has_requirements = (
        os.path.exists(os.path.join(project_root, "requirements.txt"))
        or _find_file(project_root, "pyproject.toml") is not None
        or _find_file(project_root, "setup.py") is not None
    )
    py_framework = _detect_python_framework(project_root) if py_count > 0 else None

    node_info = _detect_node(project_root)

    go_dir = _find_file(project_root, "go.mod")
    java_dir = (
        _find_file(project_root, "pom.xml")
        or _find_file(project_root, "build.gradle")
    )
    tf_count = _count_files(project_root, ".tf")
    has_k8s = _detect_kubernetes(project_root)
    has_docker = (
        _find_file(project_root, "Dockerfile") is not None
        or _find_file(project_root, "docker-compose.yml") is not None
        or _find_file(project_root, "docker-compose.yaml") is not None
    )
    has_git = os.path.isdir(os.path.join(project_root, ".git"))
    data_files = _detect_data_files(project_root)

    sql_count = _count_files(project_root, ".sql")
    yml_count = _count_files(project_root, ".yml") + _count_files(project_root, ".yaml")

    # --- Tools sugeridas ---
    suggested_tools = [
        "discover_project",
        "explore_repository",
        "analyze_code",
        "search_codebase",
        "suggest_improvements",
    ]

    if dbt_dir:
        suggested_tools += ["analyze_dbt_model", "get_data_dictionary", "map_data_lineage"]
    if databricks_dir:
        suggested_tools.append("analyze_pipeline_config")
    if notebooks:
        suggested_tools.append("get_agent_tools_spec")
    if dbt_dir or databricks_dir or notebooks:
        suggested_tools.insert(0, "get_project_architecture")
    if data_files["found"]:
        suggested_tools.append("read_data_file")

    # --- Monta resultado ---
    technologies = {
        "dbt": {
            "found": dbt_dir is not None,
            "location": os.path.relpath(dbt_dir, project_root).replace("\\", "/") if dbt_dir else None,
        },
        "databricks_asset_bundles": {
            "found": databricks_dir is not None,
            "location": os.path.relpath(databricks_dir, project_root).replace("\\", "/") if databricks_dir else None,
        },
        "jupyter_notebooks": {
            "found": len(notebooks) > 0,
            "files": notebooks,
        },
        "python": {
            "found": py_count > 0,
            "file_count": py_count,
            "has_requirements": has_requirements,
            "framework": py_framework,
        },
        "nodejs": {
            **node_info,
        },
        "go": {
            "found": go_dir is not None,
            "location": os.path.relpath(go_dir, project_root).replace("\\", "/") if go_dir else None,
        },
        "java": {
            "found": java_dir is not None,
            "location": os.path.relpath(java_dir, project_root).replace("\\", "/") if java_dir else None,
        },
        "terraform": {
            "found": tf_count > 0,
            "file_count": tf_count,
        },
        "kubernetes": {"found": has_k8s},
        "docker": {"found": has_docker},
        "git": {"found": has_git},
        "local_data_files": data_files,
    }

    file_summary = {
        "sql_files": sql_count,
        "python_files": py_count,
        "yaml_files": yml_count,
        "notebooks": len(notebooks),
    }

    return json.dumps({
        "project_root": project_root,
        "technologies": technologies,
        "file_summary": file_summary,
        "suggested_tools": suggested_tools,
    }, ensure_ascii=False, indent=2)
