"""Tool de domínio: Análise dinâmica de modelos dbt.

Lê os arquivos reais do projeto (SQL + schema YAML + dbt_project.yml)
em vez de retornar dados estáticos. Funciona com qualquer projeto dbt
configurado via PROJECT_PATH.
"""

import json
import os

import yaml
from langchain.tools import tool

from tools import cache as _cache
from tools.path_helpers import get_project_root as _get_project_root
from tools.path_helpers import find_dbt_root as _find_dbt_root


def _parse_materialization(dbt_root: str) -> dict:
    """Lê dbt_project.yml e retorna materialização por camada."""
    yml_path = os.path.join(dbt_root, "dbt_project.yml")
    try:
        with open(yml_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return {}

    if not isinstance(config, dict):
        return {}

    project_name = config.get("name", "")
    layers = config.get("models", {}).get(project_name, {})

    return {
        layer: {
            "materialized": cfg.get("+materialized") if isinstance(cfg, dict) else None,
            "schema": cfg.get("+schema") if isinstance(cfg, dict) else None,
        }
        for layer, cfg in layers.items()
        if isinstance(cfg, dict)
    }


def _find_sql_file(models_root: str, model_name: str) -> tuple[str | None, str | None]:
    """Percorre models/ e retorna (caminho_sql, camada) para o modelo."""
    for root, _dirs, files in os.walk(models_root):
        if f"{model_name}.sql" in files:
            layer = os.path.basename(root)
            return os.path.join(root, f"{model_name}.sql"), layer
    return None, None


def _find_schema_columns(layer_dir: str, model_name: str) -> dict:
    """Lê os schema YAMLs da camada e retorna a entrada do modelo.

    Aceita correspondência exata ou parcial (ex: yml com 'bronze_srag'
    documenta o modelo 'bronze_srag_data').
    """
    if not os.path.isdir(layer_dir):
        return {}

    for fname in os.listdir(layer_dir):
        if not fname.endswith((".yml", ".yaml")):
            continue
        fpath = os.path.join(layer_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                schema = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            continue

        for model in (schema or {}).get("models", []):
            yml_name = model.get("name", "")
            if yml_name == model_name or model_name.startswith(yml_name):
                return model
    return {}


def _list_models(models_root: str) -> list[str]:
    """Lista todos os modelos SQL disponíveis no projeto."""
    models = []
    if os.path.isdir(models_root):
        for root, _dirs, files in os.walk(models_root):
            for fname in files:
                if fname.endswith(".sql"):
                    models.append(os.path.splitext(fname)[0])
    return sorted(models)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def analyze_dbt_model(model_name: str) -> str:
    """Analisa um modelo dbt do projeto lendo os arquivos reais em disco.

    Retorna SQL completo, materialização (do dbt_project.yml), descrição
    e colunas documentadas com testes (dos schema YAMLs).

    Funciona com qualquer projeto configurado em PROJECT_PATH.

    Args:
        model_name: Nome do modelo (ex: 'bronze_srag_data', 'silver_srag_data',
                    'gold_srag_daily', 'gold_srag_monthly').
                    Sem extensão — apenas o nome do arquivo SQL.
    """
    _key = _cache.make_key("analyze_dbt_model", model_name=model_name)
    if hit := _cache.get(_key):
        return hit

    project_root = _get_project_root()
    dbt_root = _find_dbt_root(project_root)

    if not dbt_root:
        return json.dumps({
            "error": "dbt_project.yml não encontrado.",
            "project_root": project_root,
            "hint": "Configure PROJECT_PATH para apontar para o repositório do projeto.",
        }, ensure_ascii=False, indent=2)

    models_root = os.path.join(dbt_root, "models")
    sql_path, layer = _find_sql_file(models_root, model_name)

    if not sql_path:
        return json.dumps({
            "error": f"Modelo '{model_name}' não encontrado.",
            "available_models": _list_models(models_root),
            "dbt_root": dbt_root,
        }, ensure_ascii=False, indent=2)

    # SQL real
    with open(sql_path, encoding="utf-8") as f:
        sql_content = f.read()

    # Materialização do dbt_project.yml
    mat = _parse_materialization(dbt_root).get(layer, {})

    # Colunas e testes do schema YAML
    layer_dir = os.path.join(models_root, layer)
    schema_entry = _find_schema_columns(layer_dir, model_name)

    documented_columns = [
        {
            "name": col["name"],
            "description": col.get("description", "").strip().strip('"'),
            "tests": [
                t if isinstance(t, str) else list(t.keys())[0]
                for t in col.get("data_tests", col.get("tests", []))
            ],
        }
        for col in schema_entry.get("columns", [])
    ]

    result = {
        "model": model_name,
        "layer": layer,
        "sql_file": os.path.relpath(sql_path, project_root).replace("\\", "/"),
        "materialization": mat.get("materialized"),
        "schema": mat.get("schema"),
        "description": schema_entry.get("description", "").strip().strip('"'),
        "sql": sql_content,
        "documented_columns": documented_columns,
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    _cache.set(_key, output)
    return output
