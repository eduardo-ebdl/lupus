"""Tool composta: clona e analisa repositório completo em uma única chamada.

Resolve o problema do ReAct agent (Gemini) que para após cada tool call
em vez de encadear múltiplas tools automaticamente. Ao consolidar clone +
exploração + leitura de arquivos em uma única tool, o agente recebe todo
o contexto necessário para gerar a análise completa.
"""

import json
import os

from langchain.tools import tool

from tools.github_integration import clone_repository
from tools.repository_explorer import explore_repository
from tools.code_dependencies import map_code_dependencies


def _get_project_root() -> str:
    """Retorna o root do projeto via ctx_manager (fonte centralizada)."""
    from core.context_manager import get_project_path
    return get_project_path()


def _read_file_safe(project_root: str, file_path: str, max_chars: int = 3000) -> str | None:
    """Lê um arquivo do repositório com limite de caracteres."""
    full_path = os.path.normpath(os.path.join(project_root, file_path))
    norm_root = os.path.normpath(project_root)
    try:
        if os.path.commonpath([full_path, norm_root]) != norm_root:
            return None
    except ValueError:
        return None
    try:
        with open(full_path, encoding="utf-8", errors="ignore") as f:
            return f.read(max_chars)
    except Exception:
        return None


@tool
def analyze_full_repository(url: str, branch: str = "") -> str:
    """Clona e analisa completamente um repositório GitHub em uma única chamada.

    Executa automaticamente: clone → exploração da estrutura → leitura dos
    arquivos de código → mapeamento de dependências. Retorna análise consolidada
    com todo o contexto necessário para responder sobre o repositório.

    Use SEMPRE que o usuário enviar uma URL de repositório para análise.
    NÃO use clone_repository diretamente — esta tool já inclui o clone.

    Args:
        url: URL do repositório GitHub (ex: 'https://github.com/user/repo').
        branch: Branch específica para clonar. Se vazio, usa o branch padrão.
    """
    # 1. Clone + discover (já executa discover_project internamente)
    clone_raw = clone_repository.invoke({"url": url, "branch": branch})
    clone_data = json.loads(clone_raw)
    if "error" in clone_data:
        return clone_raw

    project_root = _get_project_root()

    # 2. Explore — estrutura completa do repositório
    explore_raw = explore_repository.invoke({"max_depth": 3})
    explore_data = json.loads(explore_raw)

    # 3. Map dependencies entre arquivos de código
    try:
        deps_raw = map_code_dependencies.invoke({})
        deps_data = json.loads(deps_raw)
    except Exception:
        deps_data = {"note": "dependências não disponíveis"}  # falha silenciosa intencional: deps são enriquecimento opcional

    # 4. Lê todos os arquivos de código e config (I/O direto, sem LLM)
    all_files = explore_data.get("files", [])
    readable_types = {
        "python", "javascript", "typescript", "sql", "config",
        "markdown", "docker", "shell",
    }

    file_contents: dict[str, str] = {}
    total_chars = 0
    max_total_chars = 15_000  # Gemini repete conteúdo com contexto muito grande — 15K é o limite seguro testado

    # Prioriza key files, depois código
    key_files = explore_data.get("key_files", [])
    code_files = [f["path"] for f in all_files if f.get("type") in readable_types]
    ordered_files = key_files + [f for f in code_files if f not in key_files]

    for fpath in ordered_files:
        if total_chars >= max_total_chars:
            break
        content = _read_file_safe(project_root, fpath)
        if content:
            file_contents[fpath] = content
            total_chars += len(content)

    return json.dumps({
        "status": "analysis_complete",
        "repository": clone_data.get("repository"),
        "url": clone_data.get("url"),
        "cloned_to": clone_data.get("cloned_to"),
        "discovery": clone_data.get("discovery"),
        "structure": {
            "total_files": explore_data.get("total_files"),
            "type_summary": explore_data.get("type_summary"),
            "key_files": explore_data.get("key_files"),
            "directories": explore_data.get("directories"),
        },
        "dependencies_summary": deps_data.get("summary", deps_data),
        "file_contents": file_contents,
        "files_read": len(file_contents),
    }, ensure_ascii=False, indent=2)
