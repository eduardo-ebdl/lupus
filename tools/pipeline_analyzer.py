"""Tool de domínio: Configuração do pipeline de orquestração.

Lê os YAMLs reais do Databricks Asset Bundles (DABs) em vez de retornar
dados estáticos. Funciona com qualquer projeto configurado via PROJECT_PATH.
"""

import json
import os

import yaml
from langchain.tools import tool

from tools import cache as _cache
from tools.path_helpers import get_project_root as _get_project_root
from tools.path_helpers import find_pipeline_root as _find_pipeline_root


def _collect_jobs(pipeline_root: str) -> dict:
    """Percorre resources/ e coleta todas as definições de jobs dos YAMLs."""
    jobs = {}
    resources_dir = os.path.join(pipeline_root, "resources")
    if not os.path.isdir(resources_dir):
        return jobs

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
            jobs.update(resource["resources"].get("jobs", {}))
    return jobs


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def analyze_pipeline_config() -> str:
    """Retorna a configuração completa do pipeline de orquestração do projeto.

    Lê os YAMLs reais do Databricks Asset Bundles (DABs):
    schedule, tasks, dependências, targets (dev/prod), variáveis e permissões.

    Funciona com qualquer projeto configurado em PROJECT_PATH.
    """
    _key = _cache.make_key("analyze_pipeline_config")
    if hit := _cache.get(_key):
        return hit

    project_root = _get_project_root()
    pipeline_root = _find_pipeline_root(project_root)

    if not pipeline_root:
        return json.dumps({
            "error": "databricks.yml não encontrado.",
            "project_root": project_root,
            "hint": "Configure PROJECT_PATH para apontar para o repositório do projeto.",
        }, ensure_ascii=False, indent=2)

    # Lê databricks.yml (bundle principal)
    bundle_path = os.path.join(pipeline_root, "databricks.yml")
    try:
        with open(bundle_path, encoding="utf-8") as f:
            bundle_config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        return json.dumps({"error": f"Erro ao ler databricks.yml: {e}"}, ensure_ascii=False, indent=2)

    if not isinstance(bundle_config, dict):
        return json.dumps({"error": "databricks.yml vazio ou inválido."}, ensure_ascii=False, indent=2)

    bundle = bundle_config.get("bundle", {})
    variables = bundle_config.get("variables", {})
    targets = bundle_config.get("targets", {})

    # Lê jobs dos resources YAMLs
    raw_jobs = _collect_jobs(pipeline_root)

    # Estrutura os jobs de forma legível
    jobs = []
    for job_key, job_def in raw_jobs.items():
        schedule = job_def.get("schedule", {})

        tasks = []
        for task in job_def.get("tasks", []):
            nb = task.get("notebook_task", {})
            tasks.append({
                "key": task.get("task_key"),
                "type": "notebook_task" if nb else "unknown",
                "notebook": nb.get("notebook_path"),
                "parameters": nb.get("base_parameters", {}),
                "depends_on": [d["task_key"] for d in task.get("depends_on", [])],
            })

        dependencies = []
        for env in job_def.get("environments", []):
            dependencies.extend(env.get("spec", {}).get("dependencies", []))

        jobs.append({
            "name": job_def.get("name", job_key),
            "schedule": {
                "cron_expression": schedule.get("quartz_cron_expression"),
                "timezone": schedule.get("timezone_id"),
            },
            "tasks": tasks,
            "python_dependencies": dependencies,
            "email_on_failure": job_def.get("email_notifications", {}).get("on_failure"),
        })

    result = {
        "bundle_name": bundle.get("name"),
        "bundle_uuid": bundle.get("uuid"),
        "bundle_file": os.path.relpath(bundle_path, project_root).replace("\\", "/"),
        "variables": {
            k: {"description": v.get("description"), "default": v.get("default")}
            for k, v in variables.items()
        },
        "targets": {
            name: {
                "mode": target.get("mode"),
                "is_default": target.get("default", False),
                "workspace_host": target.get("workspace", {}).get("host"),
                "root_path": target.get("workspace", {}).get("root_path"),
                "variables": target.get("variables", {}),
                "permissions": target.get("permissions", []),
            }
            for name, target in targets.items()
        },
        "jobs": jobs,
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    _cache.set(_key, output)
    return output
