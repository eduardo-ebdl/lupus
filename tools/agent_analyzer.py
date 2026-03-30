"""Tool de domínio: Especificação das tools do AI Agent do projeto.

Lê o notebook real do AI agent (.ipynb) em vez de retornar dados estáticos.
Extrai configuração do LLM, definições das tools (@tool), data quality gate
e guardrails diretamente do código-fonte do notebook.

Funciona com qualquer projeto configurado via PROJECT_PATH.
"""

import json
import os
import re

from langchain.tools import tool

from tools import cache as _cache


# ---------------------------------------------------------------------------
# Helpers de descoberta de paths
# ---------------------------------------------------------------------------

def _get_project_root() -> str:
    """Retorna o root do projeto via ctx_manager (fonte centralizada)."""
    from core.context_manager import get_project_path
    return get_project_path()


def _find_notebook(project_root: str) -> str | None:
    """Encontra o notebook principal do AI agent (ignora arquivos de outputs)."""
    notebooks_dir = os.path.join(project_root, "ai_agent", "notebooks")
    if os.path.isdir(notebooks_dir):
        for fname in sorted(os.listdir(notebooks_dir)):
            if fname.endswith(".ipynb") and "outputs" not in fname:
                return os.path.join(notebooks_dir, fname)
    # Fallback: percorre o projeto inteiro (filtrando dirs irrelevantes)
    _skip = {"__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".git"}
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in _skip]
        for fname in sorted(files):
            if fname.endswith(".ipynb") and "outputs" not in fname:
                return os.path.join(root, fname)
    return None


# ---------------------------------------------------------------------------
# Parser do notebook
# ---------------------------------------------------------------------------

def _cell_source(cell: dict) -> str:
    """Retorna o source de uma célula como string."""
    src = cell.get("source", [])
    return "".join(src) if isinstance(src, list) else src


def _parse_notebook(notebook_path: str) -> dict:
    """Extrai a spec do AI agent a partir do notebook JSON."""
    try:
        with open(notebook_path, encoding="utf-8") as f:
            nb = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"error": f"Erro ao ler notebook: {e}"}

    all_source = "\n".join(_cell_source(c) for c in nb.get("cells", []))

    # LLM
    llm_match = re.search(
        r'ChatDatabricks\s*\(\s*model\s*=\s*["\']([^"\']+)["\']', all_source
    )

    # Recursion limit
    rl_match = re.search(r'"recursion_limit"\s*:\s*(\d+)', all_source)

    # Data config
    catalog_match = re.search(r'^CATALOG\s*=\s*["\']([^"\']+)["\']', all_source, re.MULTILINE)
    schema_match = re.search(r'^SCHEMA\s*=\s*["\']([^"\']+)["\']', all_source, re.MULTILINE)
    table_daily_match = re.search(r'TABLE_DAILY\s*=\s*f?"([^"]+)"', all_source)
    table_monthly_match = re.search(r'TABLE_MONTHLY\s*=\s*f?"([^"]+)"', all_source)

    # Tools (@tool decorated functions with docstring)
    tool_blocks = re.findall(
        r'@tool\s+def\s+(\w+)\s*\([^)]*\)\s*(?:->[^:]+)?:\s*"""(.*?)"""',
        all_source, re.DOTALL
    )
    tools = [
        {"name": name, "docstring": docstring.strip()}
        for name, docstring in tool_blocks
    ]

    # Quality gate — extrai regras da docstring da função
    qg_doc_match = re.search(
        r'def run_quality_gate\(\):\s+"""(.*?)"""', all_source, re.DOTALL
    )
    quality_rules = []
    if qg_doc_match:
        quality_rules = re.findall(r'\d+\.\s+(.+?)\.', qg_doc_match.group(1))

    # Guardrails — extrai títulos numerados do system_instructions
    gi_match = re.search(r'system_instructions\s*=\s*"""(.*?)"""', all_source, re.DOTALL)
    guardrails = []
    if gi_match:
        guardrails = re.findall(r'\d+\.\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕ][^\n:]+):', gi_match.group(1))

    # Observabilidade
    has_mlflow = bool(re.search(r'mlflow\.langchain\.autolog', all_source))
    exp_match = re.search(r'experiment_path\s*=\s*f?"([^"]+)"', all_source)

    return {
        "notebook": os.path.basename(notebook_path),
        "llm": {
            "model": llm_match.group(1) if llm_match else None,
            "provider": "Databricks-hosted (ChatDatabricks)",
            "framework": "LangChain + LangGraph",
        },
        "pattern": "ReAct (Reason + Act)",
        "recursion_limit": int(rl_match.group(1)) if rl_match else None,
        "data_config": {
            "catalog": catalog_match.group(1) if catalog_match else None,
            "schema": schema_match.group(1) if schema_match else None,
            "table_daily": table_daily_match.group(1) if table_daily_match else None,
            "table_monthly": table_monthly_match.group(1) if table_monthly_match else None,
        },
        "tools": tools,
        "quality_gate": {
            "description": "Validação de dados executada ANTES do agente rodar",
            "rules": quality_rules,
        },
        "guardrails": guardrails,
        "observability": {
            "mlflow_autolog": has_mlflow,
            "experiment_path": exp_match.group(1) if exp_match else None,
        },
    }


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def get_agent_tools_spec(tool_name: str = "") -> str:
    """Retorna a especificação completa das tools do AI Agent SRAG.

    Lê o notebook real do agente (.ipynb) e extrai: configuração do LLM,
    tools com docstrings, data quality gate, guardrails e observabilidade.

    Funciona com qualquer projeto configurado em PROJECT_PATH.

    Args:
        tool_name: Nome da tool específica para filtrar. Se vazio, retorna a spec completa.
    """
    _key = _cache.make_key("get_agent_tools_spec", tool_name=tool_name)
    if hit := _cache.get(_key):
        return hit

    project_root = _get_project_root()
    notebook_path = _find_notebook(project_root)

    if not notebook_path:
        return json.dumps({
            "error": "Notebook do AI agent não encontrado.",
            "project_root": project_root,
            "hint": "O notebook deve estar em ai_agent/notebooks/*.ipynb",
        }, ensure_ascii=False, indent=2)

    spec = _parse_notebook(notebook_path)
    spec["notebook_path"] = os.path.relpath(notebook_path, project_root).replace("\\", "/")

    if "error" in spec:
        return json.dumps(spec, ensure_ascii=False, indent=2)

    if tool_name:
        match = next((t for t in spec.get("tools", []) if t["name"] == tool_name), None)
        if match is None:
            return json.dumps({
                "error": f"Tool '{tool_name}' não encontrada.",
                "available_tools": [t["name"] for t in spec.get("tools", [])],
            }, ensure_ascii=False, indent=2)
        result = json.dumps(match, ensure_ascii=False, indent=2)
        _cache.set(_key, result)
        return result

    result = json.dumps(spec, ensure_ascii=False, indent=2)
    _cache.set(_key, result)
    return result
