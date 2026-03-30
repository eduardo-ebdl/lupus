"""Tool de domínio: Linhagem de dados do projeto analisado.

Lê os arquivos reais do projeto dbt (SQL + sources.yml + dbt_project.yml)
em vez de retornar dados estáticos. Extrai dependências a partir dos
padrões {{ ref() }} e {{ source() }} nos arquivos SQL.

Funciona com qualquer projeto dbt configurado via PROJECT_PATH.
"""

import json
import os
import re

import yaml
from langchain.tools import tool

from tools import cache as _cache
from tools.path_helpers import get_project_root as _get_project_root
from tools.path_helpers import find_dbt_root as _find_dbt_root


# ---------------------------------------------------------------------------
# Parsers de SQL e YAML
# ---------------------------------------------------------------------------

def _parse_refs(sql: str) -> list[str]:
    """Extrai modelos referenciados via {{ ref('...') }}."""
    return re.findall(r"\{\{\s*ref\(\s*['\"](\w+)['\"]\s*\)\s*\}\}", sql)


def _parse_sources(sql: str) -> list[tuple[str, str]]:
    """Extrai fontes referenciadas via {{ source('...', '...') }}."""
    return re.findall(
        r"\{\{\s*source\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]\s*\)\s*\}\}", sql
    )


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


def _read_sources(dbt_root: str) -> dict:
    """Lê sources.yml e retorna informações das fontes brutas."""
    sources_path = os.path.join(dbt_root, "models", "sources.yml")
    if not os.path.exists(sources_path):
        return {}
    try:
        with open(sources_path, encoding="utf-8") as f:
            schema = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return {}
    sources = {}
    for src in (schema or {}).get("sources", []):
        for table in src.get("tables", []):
            key = f"{src['name']}.{table['name']}"
            sources[key] = {
                "source": src["name"],
                "table": table["name"],
                "database": src.get("database", ""),
                "schema": src.get("schema", ""),
                "description": table.get("description", "").strip().strip('"'),
            }
    return sources


def _collect_models(models_root: str, materialization: dict) -> dict:
    """Percorre models/ e extrai dependências de cada arquivo SQL."""
    models = {}
    for root, _dirs, files in os.walk(models_root):
        for fname in files:
            if not fname.endswith(".sql"):
                continue
            model_name = os.path.splitext(fname)[0]
            layer = os.path.basename(root)
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    sql = f.read()
            except OSError:
                continue
            refs = _parse_refs(sql)
            src_refs = _parse_sources(sql)
            mat = materialization.get(layer, {})
            models[model_name] = {
                "layer": layer,
                "materialization": mat.get("materialized"),
                "schema": mat.get("schema"),
                "depends_on_models": refs,
                "depends_on_sources": [f"{s}.{t}" for s, t in src_refs],
            }
    return models


def _build_dependency_graph(models: dict) -> dict:
    """Constrói o grafo de dependências no formato {model: {depends_on, type, layer}}."""
    graph = {}
    for model_name, info in models.items():
        all_deps = info["depends_on_models"] + [
            s.split(".")[-1] for s in info["depends_on_sources"]
        ]
        graph[model_name] = {
            "depends_on": all_deps,
            "type": info["materialization"] or "unknown",
            "layer": info["layer"],
        }
    return graph


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool
def map_data_lineage(layer: str = "") -> str:
    """Mapeia o fluxo de dados (data lineage) lendo os arquivos reais do projeto.

    Extrai dependências entre modelos a partir dos arquivos SQL ({{ ref() }},
    {{ source() }}), materialização do dbt_project.yml e fontes do sources.yml.

    Funciona com qualquer projeto configurado em PROJECT_PATH.

    Args:
        layer: Camada específica para filtrar ('bronze', 'silver', 'gold').
               Se vazio, retorna o lineage completo com todos os modelos.
    """
    _key = _cache.make_key("map_data_lineage", layer=layer)
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
    materialization = _parse_materialization(dbt_root)
    raw_sources = _read_sources(dbt_root)
    models = _collect_models(models_root, materialization)
    dependency_graph = _build_dependency_graph(models)

    # Ordem das camadas para flow_direction
    ordered_layers = [
        l for l in ["bronze", "silver", "gold"]
        if any(m["layer"] == l for m in models.values())
    ]
    flow_direction = " → ".join(["raw"] + ordered_layers)

    result = {
        "dbt_project": os.path.basename(dbt_root),
        "raw_sources": raw_sources,
        "flow_direction": flow_direction,
        "models": models,
        "dependency_graph": dependency_graph,
    }

    if layer:
        key = layer.lower().strip()
        filtered_models = {k: v for k, v in models.items() if v["layer"] == key}
        if not filtered_models:
            return json.dumps({
                "error": f"Camada '{layer}' não encontrada.",
                "available_layers": sorted({m["layer"] for m in models.values()}),
            }, ensure_ascii=False, indent=2)
        filtered_graph = {k: v for k, v in dependency_graph.items() if k in filtered_models}
        result = json.dumps({
            "layer": key,
            "models": filtered_models,
            "dependency_graph": filtered_graph,
            "raw_sources": raw_sources,
            "flow_direction": flow_direction,
        }, ensure_ascii=False, indent=2)
        _cache.set(_key, result)
        return result

    result = json.dumps(result, ensure_ascii=False, indent=2)
    _cache.set(_key, result)
    return result
