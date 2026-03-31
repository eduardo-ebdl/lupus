"""Tool RAG: search_codebase — busca semântica híbrida no codebase indexado.

Complementa as domain tools:
- Domain tools  → dados estruturados e precisos (arquitetura, pipeline, dicionário)
- search_codebase → busca semântica em código sem saber o arquivo exato

Quando usar search_codebase ao invés de analyze_code:
- analyze_code: você sabe exatamente qual arquivo ler → leitura completa e precisa
- search_codebase: você não sabe onde está → encontra os trechos mais relevantes

Nota: o índice RAG é construído offline via scripts/build_rag_index.py e reflete
o repositório apontado por PROJECT_PATH no momento da indexação.
"""

import json
import os

from langchain.tools import tool

from core.context_manager import get_project_path

# Index path padrão — relativo ao diretório deste arquivo
_INDEX_DIR = os.path.join(os.path.dirname(__file__), "..", "rag", "index")

# Retriever singleton — carregado na primeira chamada (lazy loading)
_retriever = None

# Estado de sincronização com o repo ativo
_rag_synced = False
_indexed_path = ""


def on_repo_change(context) -> None:
    """Hook chamado pelo ProjectContextManager quando o repo muda.

    Marca o índice RAG como desatualizado se o repo mudou.
    """
    global _rag_synced, _retriever
    _retriever = None
    _rag_synced = (context.path == _indexed_path)


def mark_indexed(path: str) -> None:
    """Chamado após (re)construir o índice RAG para o repo dado."""
    global _indexed_path, _rag_synced
    _indexed_path = path
    _rag_synced = (path == get_project_path())


def _get_retriever():
    """Retorna o retriever, carregando do disco se necessário."""
    global _retriever
    if _retriever is None:
        from rag.retriever import get_retriever
        _retriever = get_retriever(os.path.normpath(_INDEX_DIR))
    return _retriever


@tool
def search_codebase(query: str, layer: str = "") -> str:
    """Busca semanticamente no código-fonte indexado do repositório usando RAG.

    Usa hybrid search (semântico + keyword + reranking) para encontrar os trechos
    de código mais relevantes à pergunta, mesmo sem saber o arquivo exato.

    Use quando:
    - O usuário perguntar sobre implementação sem mencionar um arquivo específico
    - Precisar encontrar onde um conceito, função ou variável está implementada
    - As domain tools não cobrirem o nível de detalhe pedido
    - A pergunta envolver termos técnicos específicos (nome de coluna, função, config)

    NÃO use quando:
    - O usuário pedir para ler um arquivo específico → use analyze_code
    - A pergunta for sobre arquitetura geral → use get_project_architecture ou discover_project
    - A pergunta for sobre pipeline/schedule → use analyze_pipeline_config

    Args:
        query: Descrição em linguagem natural do que buscar
               (ex: "como a idade é normalizada", "onde flag de óbito é criada",
                "configuração de liquid clustering", "cálculo de growth rate")
        layer: Filtro opcional por camada ou módulo do projeto indexado.
               Se vazio, busca em todo o codebase.
    """
    if not _rag_synced:
        return json.dumps({
            "warning": "O índice de busca foi construído para outro repositório"
                       f" ({_indexed_path or 'desconhecido'})."
                       " Os resultados podem ser incorretos."
                       " Use analyze_code para ler arquivos específicos.",
        }, ensure_ascii=False)

    try:
        retriever = _get_retriever()
    except FileNotFoundError as e:
        return json.dumps({
            "error": str(e),
            "hint": "Execute 'python scripts/build_rag_index.py' para gerar o índice RAG."
        }, ensure_ascii=False)

    response = retriever.search(query=query, k=5, layer=layer.strip().lower())
    return response.formatted
