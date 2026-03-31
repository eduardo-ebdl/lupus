"""Indexer: chunking semântico do codebase + geração de embeddings + FAISS.

Estratégia de chunking por unidade semântica (não por tamanho fixo):
- .py   → 1 função/classe = 1 chunk (split por def/class de top-level)
- .sql  → 1 arquivo = 1 chunk (cada model dbt é uma unidade coesa)
- .yml  → 1 arquivo = 1 chunk (configs são pequenos e interdependentes)
- .ipynb → 1 cell de código = 1 chunk (células pip install são ignoradas)
- .md   → 1 seção (##) = 1 chunk
"""

import hashlib
import json
import os
import re
from typing import Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

# Modelo local, sem custo de API — 80MB, 384 dims, ótimo para código + texto
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Tamanho máximo de um chunk Python em chars (evita chunks gigantes de arquivos grandes)
_MAX_PYTHON_CHUNK_CHARS = 4000

# Extensões indexadas e as que devem ser ignoradas
INDEXED_EXTENSIONS = {".py", ".sql", ".yml", ".yaml", ".md", ".ipynb"}
IGNORED_PATTERNS = {
    "requirements.txt", "LICENSE", ".env", ".env.example",
    "srag_agent_v1_outputs.ipynb",  # só outputs, sem código limpo
}


def _detect_layer(file_path: str) -> str:
    """Detecta a camada/módulo com base no caminho do arquivo.

    Suporta tanto nomenclatura específica de projetos dbt (bronze/silver/gold)
    quanto estrutura genérica de projetos Python.
    """
    p = file_path.replace("\\", "/").lower()
    # Camadas dbt / Medallion Architecture
    if "models/bronze" in p or "/bronze/" in p:
        return "bronze"
    if "models/silver" in p or "/silver/" in p:
        return "silver"
    if "models/gold" in p or "/gold/" in p:
        return "gold"
    # Módulos genéricos de projetos Python
    if "/tests/" in p or "/test_" in p or p.startswith("test_"):
        return "tests"
    if "/api/" in p or "/routes/" in p or "/endpoints/" in p:
        return "api"
    if "/core/" in p:
        return "core"
    if "/tools/" in p:
        return "tools"
    if "/rag/" in p:
        return "rag"
    if "/scripts/" in p:
        return "scripts"
    if "/models/" in p:
        return "models"
    if "/utils/" in p or "/helpers/" in p:
        return "utils"
    # Projetos específicos do srag_agent
    if "ai_agent" in p:
        return "ai_agent"
    if "agent_srag_pipeline" in p or "pipeline" in p:
        return "pipeline"
    return "root"


def _chunk_python(file_path: str, rel_path: str) -> list[dict]:
    """Python: 1 função/classe top-level = 1 chunk.

    Divide por definitões de função e classe que começam na coluna 0
    (top-level, sem indentação). Docstrings do módulo são incluídas
    no primeiro chunk como contexto.
    """
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return []

    if not content.strip():
        return []

    # Divide por definitões top-level (sem indentação)
    parts = re.split(r"\n(?=(?:def |class |async def )\w)", content)
    layer = _detect_layer(rel_path)
    chunks = []

    for i, part in enumerate(parts):
        part = part.strip()
        if len(part) < 20:  # descarta fragmentos muito curtos
            continue
        # Trunca chunks muito grandes para não explodir o índice
        if len(part) > _MAX_PYTHON_CHUNK_CHARS:
            part = part[:_MAX_PYTHON_CHUNK_CHARS] + "\n# [truncado]"
        chunks.append({
            "content": part,
            "file_path": rel_path,
            "file_type": "py",
            "layer": layer,
            "model_name": None,
            "chunk_type": "python_function",
            "chunk_index": i,
        })

    # Fallback: arquivo inteiro como um chunk (para arquivos sem defs)
    if not chunks:
        chunk_content = content.strip()[:_MAX_PYTHON_CHUNK_CHARS]
        chunks.append({
            "content": chunk_content,
            "file_path": rel_path,
            "file_type": "py",
            "layer": layer,
            "model_name": None,
            "chunk_type": "python_module",
            "chunk_index": 0,
        })

    return chunks


def _chunk_sql(file_path: str, rel_path: str) -> list[dict]:
    """SQL: arquivo inteiro = 1 chunk."""
    with open(file_path, encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []
    model_name = os.path.splitext(os.path.basename(file_path))[0]
    return [{
        "content": content,
        "file_path": rel_path,
        "file_type": "sql",
        "layer": _detect_layer(rel_path),
        "model_name": model_name,
        "chunk_type": "sql_model",
        "chunk_index": 0,
    }]


def _chunk_yml(file_path: str, rel_path: str) -> list[dict]:
    """YAML: arquivo inteiro = 1 chunk."""
    with open(file_path, encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []
    return [{
        "content": content,
        "file_path": rel_path,
        "file_type": "yml",
        "layer": _detect_layer(rel_path),
        "model_name": None,
        "chunk_type": "yml_config",
        "chunk_index": 0,
    }]


def _chunk_notebook(file_path: str, rel_path: str) -> list[dict]:
    """Notebook: 1 célula de código = 1 chunk. Ignora pip install e células vazias.
    Células markdown precedentes são incluídas como contexto do chunk seguinte.
    """
    with open(file_path, encoding="utf-8") as f:
        nb = json.load(f)

    chunks = []
    pending_markdown = ""
    layer = _detect_layer(rel_path)

    for i, cell in enumerate(nb.get("cells", [])):
        source = "".join(cell.get("source", []))
        if not source.strip():
            continue

        if cell["cell_type"] == "markdown":
            pending_markdown = source.strip()
            continue

        if cell["cell_type"] == "code":
            # Ignora células de instalação de pacotes
            if source.strip().startswith("%pip") or source.strip().startswith("!pip"):
                pending_markdown = ""
                continue

            content = source.strip()
            if pending_markdown:
                content = f"# {pending_markdown}\n\n{content}"
                pending_markdown = ""

            chunks.append({
                "content": content,
                "file_path": rel_path,
                "file_type": "ipynb",
                "layer": layer,
                "model_name": None,
                "chunk_type": "notebook_cell",
                "chunk_index": len(chunks),
            })

    return chunks


def _chunk_markdown(file_path: str, rel_path: str) -> list[dict]:
    """Markdown: 1 seção (##) = 1 chunk. Seção inicial (antes do primeiro ##) = 1 chunk."""
    with open(file_path, encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []

    # Divide por headers ##
    sections = re.split(r"\n(?=## )", content)
    chunks = []
    layer = _detect_layer(rel_path)

    for i, section in enumerate(sections):
        section = section.strip()
        if len(section) < 30:  # seções muito curtas não agregam valor
            continue
        chunks.append({
            "content": section,
            "file_path": rel_path,
            "file_type": "md",
            "layer": layer,
            "model_name": None,
            "chunk_type": "markdown_section",
            "chunk_index": i,
        })

    return chunks


def collect_chunks(srag_root: str) -> list[dict]:
    """Percorre o srag_agent/ e gera todos os chunks indexáveis."""
    chunks = []
    base = os.path.abspath(srag_root)

    for root, dirs, files in os.walk(base):
        # Ignora diretórios irrelevantes
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".ipynb_checkpoints", "artifacts"}]

        for fname in sorted(files):
            if fname in IGNORED_PATTERNS:
                continue

            ext = os.path.splitext(fname)[1].lower()
            if ext not in INDEXED_EXTENSIONS:
                continue

            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, base).replace("\\", "/")

            if ext == ".py":
                chunks.extend(_chunk_python(full_path, rel_path))
            elif ext == ".sql":
                chunks.extend(_chunk_sql(full_path, rel_path))
            elif ext in {".yml", ".yaml"}:
                chunks.extend(_chunk_yml(full_path, rel_path))
            elif ext == ".ipynb":
                chunks.extend(_chunk_notebook(full_path, rel_path))
            elif ext == ".md":
                chunks.extend(_chunk_markdown(full_path, rel_path))

    return chunks


def _load_sentence_transformer(model_name: str, timeout_seconds: int = 300) -> SentenceTransformer:
    """Carrega SentenceTransformer com timeout para downloads do HuggingFace.

    HuggingFace downloads podem travar indefinidamente em conexões ruins.
    Este wrapper detecta timeouts longos e falha com mensagem clara.

    Args:
        model_name: Nome do modelo (ex: 'all-MiniLM-L6-v2')
        timeout_seconds: Timeout em segundos (padrão: 5 min)

    Raises:
        TimeoutError: Se o carregamento exceder o timeout
    """
    import threading
    result = None
    exception = None

    def load():
        nonlocal result, exception
        try:
            result = SentenceTransformer(model_name)
        except Exception as e:
            exception = e

    thread = threading.Thread(target=load, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        raise TimeoutError(
            f"Carregamento de modelo '{model_name}' expirou após {timeout_seconds}s.\n"
            f"Possíveis causas:\n"
            f"  • Conexão de internet lenta ou instável\n"
            f"  • HuggingFace hub indisponível\n"
            f"Solução: tente novamente em alguns minutos."
        )

    if exception:
        raise exception

    return result


def build_faiss_index(chunks: list[dict], model_name: str = EMBEDDING_MODEL) -> tuple[Any, list[dict]]:
    """Gera embeddings e constrói índice FAISS (IndexFlatIP com vetores normalizados = cosine similarity).

    Retorna (faiss_index, chunks_com_embedding_id).
    """
    print(f"Carregando modelo de embeddings: {model_name}")
    model = _load_sentence_transformer(model_name)

    texts = [c["content"] for c in chunks]
    print(f"Gerando embeddings para {len(texts)} chunks...")
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)

    # Normaliza para cosine similarity via produto interno
    faiss.normalize_L2(embeddings)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    print(f"Índice FAISS construído: {index.ntotal} vetores, {dim} dimensões")
    return index, chunks


def _compute_repo_id(repo_path: str) -> str:
    """Calcula hash do caminho absoluto do repositório para detecção de mismatch."""
    abs_path = os.path.abspath(repo_path)
    return hashlib.sha256(abs_path.encode()).hexdigest()[:16]


def save_index(index: Any, chunks: list[dict], output_dir: str, repo_path: str = "") -> None:
    """Salva o índice FAISS e os metadados em disco.

    Args:
        index: Índice FAISS construído
        chunks: Lista de chunks com metadados
        output_dir: Diretório onde salvar os arquivos
        repo_path: Caminho do repositório para detectar mismatches (se vazio, não salva repo_id)
    """
    os.makedirs(output_dir, exist_ok=True)

    index_path = os.path.join(output_dir, "srag.index")
    metadata_path = os.path.join(output_dir, "srag_metadata.json")

    faiss.write_index(index, index_path)

    # Prepara metadados com repo_id e repo_path para fallback automático por mismatch
    metadata = {
        "chunks": chunks,
        "repo_id": _compute_repo_id(repo_path) if repo_path else None,
        "repo_path": os.path.abspath(repo_path) if repo_path else None,
    }

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Índice salvo em: {index_path}")
    print(f"Metadados salvos em: {metadata_path}")
    if repo_path:
        print(f"Repositório: {os.path.abspath(repo_path)}")
