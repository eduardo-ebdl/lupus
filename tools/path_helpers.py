"""Helpers compartilhados para descoberta de paths no repositório.

Centraliza funções duplicadas entre architecture.py, dbt_analyzer.py,
lineage.py e pipeline_analyzer.py.
"""

import os


def get_project_root() -> str:
    """Retorna o root do projeto via ctx_manager (fonte centralizada)."""
    from core.context_manager import get_project_path
    return get_project_path()


def find_dbt_root(project_root: str) -> str | None:
    """Encontra o diretório onde dbt_project.yml está.

    Suporta dois layouts:
    - dbt_project.yml na raiz do projeto
    - dbt_project.yml em um subdiretório (ex: srag_agent/srag_agent/)
    """
    if os.path.exists(os.path.join(project_root, "dbt_project.yml")):
        return project_root
    try:
        for name in os.listdir(project_root):
            sub = os.path.join(project_root, name)
            if os.path.isdir(sub) and os.path.exists(os.path.join(sub, "dbt_project.yml")):
                return sub
    except OSError:
        pass
    return None


def find_pipeline_root(project_root: str) -> str | None:
    """Encontra o diretório onde databricks.yml está.

    Suporta dois layouts:
    - databricks.yml na raiz do projeto
    - databricks.yml em um subdiretório (ex: agent_srag_pipeline/)
    """
    if os.path.exists(os.path.join(project_root, "databricks.yml")):
        return project_root
    try:
        for name in os.listdir(project_root):
            sub = os.path.join(project_root, name)
            if os.path.isdir(sub) and os.path.exists(os.path.join(sub, "databricks.yml")):
                return sub
    except OSError:
        pass
    return None
