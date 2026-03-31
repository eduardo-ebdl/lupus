"""Tool de integração: clona repositórios GitHub e configura PROJECT_PATH.

Permite que o agente analise qualquer repositório público sem configuração manual.
Usa git clone via subprocess, atualiza PROJECT_PATH no processo atual e limpa
o cache das domain tools para forçar re-leitura do novo repositório.
"""

import json
import logging
import os
import shutil
import stat
import subprocess

from langchain.tools import tool

logger = logging.getLogger(__name__)

from core.context_manager import ctx_manager


def _force_remove_readonly(func, path, exc_info):
    """Windows: git marca arquivos .git/ como read-only — remove o atributo antes."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _repo_name_from_url(url: str) -> str:
    """Extrai o nome do repositório da URL."""
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repo"


def _is_git_available() -> bool:
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            check=True,
            timeout=10,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@tool
def clone_repository(url: str, branch: str = "") -> str:
    """Clona um repositório GitHub e configura o agente para analisá-lo.

    Executa git clone, atualiza PROJECT_PATH automaticamente e retorna
    um sumário do repositório clonado (tecnologias, estrutura, tools sugeridas).

    Após chamar essa tool, todas as outras tools (analyze_dbt_model,
    map_data_lineage, etc.) passam a analisar o repositório recém-clonado.

    Args:
        url: URL do repositório GitHub
             (ex: 'https://github.com/dbt-labs/jaffle_shop').
        branch: Branch específica para clonar. Se vazio, usa o branch padrão.
    """
    url = url.strip()
    if not url:
        return json.dumps({"error": "URL do repositório não informada."}, ensure_ascii=False)

    if not (url.startswith("https://") or url.startswith("git@")):
        return json.dumps({
            "error": "URL inválida. Use HTTPS (https://github.com/...) ou SSH (git@github.com:...).",
            "url": url,
        }, ensure_ascii=False)

    if not _is_git_available():
        return json.dumps({
            "error": "git não encontrado no PATH.",
            "hint": "Instale o Git e certifique-se de que está no PATH do sistema.",
        }, ensure_ascii=False, indent=2)

    repo_name = _repo_name_from_url(url)

    # Diretório de destino: ~/lupus-repos/<repo_name>
    repos_base = os.path.join(os.path.expanduser("~"), "lupus-repos")
    dest_dir = os.path.join(repos_base, repo_name)

    # Limpa TODOS os repos clonados anteriormente (mantém apenas 1 ativo)
    if os.path.isdir(repos_base):
        for entry in os.listdir(repos_base):
            entry_path = os.path.join(repos_base, entry)
            if os.path.isdir(entry_path):
                try:
                    shutil.rmtree(entry_path, onerror=_force_remove_readonly)
                except OSError as e:
                    logger.warning("Falha ao limpar repo anterior %s: %s", entry_path, e)

    os.makedirs(repos_base, exist_ok=True)

    # Monta o comando git clone
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, dest_dir]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({
            "error": "Timeout ao clonar o repositório (120s).",
            "url": url,
            "hint": "Verifique se a URL está correta e o repositório é público.",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Erro ao executar git clone: {e}"}, ensure_ascii=False)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        return json.dumps({
            "error": "git clone falhou.",
            "url": url,
            "stderr": stderr,
            "hint": "Verifique se a URL está correta e o repositório é público.",
        }, ensure_ascii=False, indent=2)

    # Atualiza o repo ativo — dispara hooks (cache, RAG, middleware)
    ctx_manager.set_repo(dest_dir)

    # Importa aqui para evitar circular import no módulo
    from tools.project_discovery import discover_project
    summary = discover_project.invoke({})

    return json.dumps({
        "status": "ok",
        "repository": repo_name,
        "url": url,
        "cloned_to": dest_dir,
        "project_path_updated": dest_dir,
        "message": (
            f"Repositório '{repo_name}' clonado com sucesso. "
            "PROJECT_PATH atualizado. Todas as domain tools agora analisam este repositório."
        ),
        "discovery": json.loads(summary),
    }, ensure_ascii=False, indent=2)
