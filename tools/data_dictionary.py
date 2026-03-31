"""Tool de domínio: Dicionário de dados do projeto analisado.

Lê os schema YAMLs reais de cada camada dbt em vez de retornar dados estáticos.
Funciona com qualquer projeto dbt configurado via PROJECT_PATH.
"""

import json
import os

import yaml
from langchain.tools import tool

from tools import cache as _cache
from tools.path_helpers import get_project_root as _get_project_root, find_dbt_root as _find_dbt_root


def _collect_models_from_yaml(yaml_path: str, layer: str) -> list[dict]:
    """Lê um schema YAML e retorna a lista de modelos documentados."""
    try:
        with open(yaml_path, encoding="utf-8") as f:
            schema = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return []

    models = []
    for model in (schema or {}).get("models", []):
        model_name = model.get("name", "")
        if not model_name:
            continue
        columns = []
        for col in model.get("columns", []):
            tests = [
                t if isinstance(t, str) else list(t.keys())[0]
                for t in col.get("data_tests", col.get("tests", []))
            ]
            columns.append({
                "name": col["name"],
                "description": col.get("description", "").strip().strip('"'),
                "tests": tests,
            })
        models.append({
            "model": model_name,
            "layer": layer,
            "description": model.get("description", "").strip().strip('"'),
            "columns": columns,
        })
    return models


def _build_dictionary(models_root: str) -> dict:
    """Percorre models/ e coleta todos os modelos documentados via schema YAMLs."""
    result = {}
    if not os.path.isdir(models_root):
        return result

    for layer_name in sorted(os.listdir(models_root)):
        layer_dir = os.path.join(models_root, layer_name)
        if not os.path.isdir(layer_dir):
            continue
        for fname in os.listdir(layer_dir):
            if not fname.endswith((".yml", ".yaml")):
                continue
            fpath = os.path.join(layer_dir, fname)
            for entry in _collect_models_from_yaml(fpath, layer_name):
                result[entry["model"]] = entry

    return result


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def get_data_dictionary(layer: str = "") -> str:
    """Retorna o dicionário de dados do projeto com colunas, descrições e testes.

    Lê os schema YAMLs reais do projeto dbt. Cada modelo tem nome, camada,
    descrição e lista de colunas documentadas com seus testes de qualidade.

    Funciona com qualquer projeto configurado em PROJECT_PATH.

    Args:
        layer: Filtra por camada ('bronze', 'silver', 'gold') ou por nome exato
               de modelo ('gold_srag_daily', 'gold_srag_monthly').
               Se vazio, retorna o dicionário completo de todos os modelos.
    """
    _key = _cache.make_key("get_data_dictionary", layer=layer)
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
    dictionary = _build_dictionary(models_root)

    if not dictionary:
        return json.dumps({
            "error": "Nenhum modelo com schema YAML encontrado.",
            "models_root": models_root,
        }, ensure_ascii=False, indent=2)

    if layer:
        key = layer.lower().strip()
        # Correspondência exata por nome de modelo
        if key in dictionary:
            result = json.dumps({key: dictionary[key]}, ensure_ascii=False, indent=2)
            _cache.set(_key, result)
            return result
        # Filtro por camada (ex: 'gold' retorna gold_srag_daily + gold_srag_monthly)
        filtered = {k: v for k, v in dictionary.items() if v["layer"] == key}
        if filtered:
            result = json.dumps(filtered, ensure_ascii=False, indent=2)
            _cache.set(_key, result)
            return result
        return json.dumps({
            "error": f"Camada ou modelo '{layer}' não encontrado.",
            "available": list(dictionary.keys()),
        }, ensure_ascii=False, indent=2)

    result = json.dumps(dictionary, ensure_ascii=False, indent=2)
    _cache.set(_key, result)
    return result
