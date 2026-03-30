"""Tool de domínio: Arquitetura do projeto analisado.

Lê os arquivos reais do projeto (dbt_project.yml, schema YAMLs, databricks.yml,
resources YAMLs e notebook do AI agent) em vez de retornar dados estáticos.
Funciona com qualquer projeto configurado via PROJECT_PATH.
"""

import json
import os
import re

import yaml
from langchain.tools import tool

from tools import cache as _cache
from tools.path_helpers import get_project_root as _get_project_root
from tools.path_helpers import find_dbt_root as _find_dbt_root
from tools.path_helpers import find_pipeline_root as _find_pipeline_root


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
# Leitores por módulo
# ---------------------------------------------------------------------------

def _read_dbt_module(dbt_root: str) -> dict:
    """Extrai info do módulo dbt: camadas, modelos, materialização."""
    yml_path = os.path.join(dbt_root, "dbt_project.yml")
    try:
        with open(yml_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return {}

    if not isinstance(config, dict):
        return {}

    project_name = config.get("name", "")
    version = config.get("version", "")
    layers_config = config.get("models", {}).get(project_name, {})
    models_root = os.path.join(dbt_root, "models")

    layers = []
    for layer_name, layer_cfg in layers_config.items():
        if not isinstance(layer_cfg, dict):
            continue
        layer_dir = os.path.join(models_root, layer_name)
        layer_models = []
        if os.path.isdir(layer_dir):
            for fname in os.listdir(layer_dir):
                if fname.endswith(".sql"):
                    layer_models.append(os.path.splitext(fname)[0])
        layers.append({
            "name": layer_name,
            "materialization": layer_cfg.get("+materialized"),
            "schema": layer_cfg.get("+schema"),
            "models": sorted(layer_models),
        })

    return {
        "name": project_name,
        "version": version,
        "type": "Data Engineering",
        "technology": "dbt Core",
        "architecture": "Medallion (Bronze → Silver → Gold)",
        "layers": layers,
    }


def _read_pipeline_module(pipeline_root: str) -> dict:
    """Extrai info do módulo de pipeline (DABs): bundle, targets, jobs."""
    bundle_path = os.path.join(pipeline_root, "databricks.yml")
    try:
        with open(bundle_path, encoding="utf-8") as f:
            bundle_config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return {}

    if not isinstance(bundle_config, dict):
        return {}

    bundle = bundle_config.get("bundle", {})
    targets = bundle_config.get("targets", {})

    resources_dir = os.path.join(pipeline_root, "resources")
    jobs = []
    if os.path.isdir(resources_dir):
        for fname in os.listdir(resources_dir):
            if not fname.endswith((".yml", ".yaml")):
                continue
            fpath = os.path.join(resources_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    resource = yaml.safe_load(f)
            except (OSError, yaml.YAMLError):
                continue
            if resource and "resources" in resource:
                for job_key, job_def in resource["resources"].get("jobs", {}).items():
                    schedule = job_def.get("schedule", {})
                    task_names = [t.get("task_key") for t in job_def.get("tasks", [])]
                    jobs.append({
                        "name": job_def.get("name", job_key),
                        "schedule": schedule.get("quartz_cron_expression"),
                        "timezone": schedule.get("timezone_id"),
                        "tasks": task_names,
                    })

    return {
        "name": bundle.get("name"),
        "type": "Orquestração",
        "technology": "Databricks Asset Bundles (DABs)",
        "targets": list(targets.keys()),
        "jobs": jobs,
    }


def _read_agent_module(notebook_path: str) -> dict:
    """Extrai info do AI agent a partir do notebook Jupyter."""
    try:
        with open(notebook_path, encoding="utf-8") as f:
            nb = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    all_source = "\n".join(
        "".join(cell.get("source", []))
        for cell in nb.get("cells", [])
    )

    llm_match = re.search(r'ChatDatabricks\s*\(\s*model\s*=\s*["\']([^"\']+)["\']', all_source)
    tools = re.findall(r'@tool\s+def\s+(\w+)', all_source)
    rl_match = re.search(r'"recursion_limit"\s*:\s*(\d+)', all_source)
    catalog_match = re.search(r'^CATALOG\s*=\s*["\']([^"\']+)["\']', all_source, re.MULTILINE)
    schema_match = re.search(r'^SCHEMA\s*=\s*["\']([^"\']+)["\']', all_source, re.MULTILINE)

    return {
        "name": os.path.splitext(os.path.basename(notebook_path))[0],
        "type": "AI/LLM Agent",
        "technology": "LangChain + LangGraph",
        "pattern": "ReAct (Reason + Act)",
        "llm": llm_match.group(1) if llm_match else None,
        "recursion_limit": int(rl_match.group(1)) if rl_match else None,
        "tools": tools,
        "data": {
            "catalog": catalog_match.group(1) if catalog_match else None,
            "schema": schema_match.group(1) if schema_match else None,
        },
        "observability": "MLflow" if "mlflow.langchain.autolog" in all_source else None,
    }


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def get_project_architecture() -> str:
    """Retorna o mapa completo da arquitetura do projeto analisado.

    Lê os arquivos reais do projeto:
    - dbt_project.yml → módulo dbt (camadas, modelos, materialização)
    - databricks.yml + resources/*.yml → pipeline/orquestração (jobs, schedule)
    - notebook .ipynb → AI agent (LLM, tools, pattern, observabilidade)

    Funciona com qualquer projeto configurado em PROJECT_PATH.
    """
    _key = _cache.make_key("get_project_architecture")
    if hit := _cache.get(_key):
        return hit

    project_root = _get_project_root()
    modules = []

    dbt_root = _find_dbt_root(project_root)
    if dbt_root:
        modules.append(_read_dbt_module(dbt_root))

    pipeline_root = _find_pipeline_root(project_root)
    if pipeline_root:
        modules.append(_read_pipeline_module(pipeline_root))

    notebook_path = _find_notebook(project_root)
    if notebook_path:
        modules.append(_read_agent_module(notebook_path))

    if not modules:
        return json.dumps({
            "error": "Nenhum módulo encontrado no projeto.",
            "project_root": project_root,
            "hint": "Configure PROJECT_PATH para apontar para o repositório do projeto.",
        }, ensure_ascii=False, indent=2)

    result = json.dumps({
        "project_root": os.path.basename(project_root),
        "modules_found": len(modules),
        "modules": modules,
    }, ensure_ascii=False, indent=2)
    _cache.set(_key, result)
    return result
