"""Indexer: chunking semântico do codebase + geração de embeddings + FAISS.

Estratégia de chunking por unidade semântica (não por tamanho fixo):
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

# Extensões indexadas e as que devem ser ignoradas
INDEXED_EXTENSIONS = {".sql", ".yml", ".yaml", ".md", ".ipynb"}
IGNORED_PATTERNS = {
    "requirements.txt", "LICENSE", ".env", ".env.example",
    "srag_agent_v1_outputs.ipynb",  # só outputs, sem código limpo
}


def _detect_layer(file_path: str) -> str:
    """Detecta a camada/módulo com base no caminho do arquivo."""
    p = file_path.replace("\\", "/").lower()
    if "models/bronze" in p or "/bronze/" in p:
        return "bronze"
    if "models/silver" in p or "/silver/" in p:
        return "silver"
    if "models/gold" in p or "/gold/" in p:
        return "gold"
    if "ai_agent" in p:
        return "ai_agent"
    if "agent_srag_pipeline" in p or "pipeline" in p:
        return "pipeline"
    return "root"


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

            if ext == ".sql":
                chunks.extend(_chunk_sql(full_path, rel_path))
            elif ext in {".yml", ".yaml"}:
                chunks.extend(_chunk_yml(full_path, rel_path))
            elif ext == ".ipynb":
                chunks.extend(_chunk_notebook(full_path, rel_path))
            elif ext == ".md":
                chunks.extend(_chunk_markdown(full_path, rel_path))

    return chunks


def build_faiss_index(chunks: list[dict], model_name: str = EMBEDDING_MODEL) -> tuple[Any, list[dict]]:
    """Gera embeddings e constrói índice FAISS (IndexFlatIP com vetores normalizados = cosine similarity).

    Retorna (faiss_index, chunks_com_embedding_id).
    """
    print(f"Carregando modelo de embeddings: {model_name}")
    model = SentenceTransformer(model_name)

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

    # Prepara metadados com repo_id para fallback automático por mismatch
    metadata = {
        "chunks": chunks,
        "repo_id": _compute_repo_id(repo_path) if repo_path else None,
    }

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Índice salvo em: {index_path}")
    print(f"Metadados salvos em: {metadata_path}")
    if repo_path:
        print(f"Repositório: {os.path.abspath(repo_path)}")
