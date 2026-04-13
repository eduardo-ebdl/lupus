"""Pipeline de indexação RAG — roda uma vez offline.

Uso:
    python scripts/build_rag_index.py

O índice é salvo em rag/index/ (gitignored).
Execute novamente sempre que o repositório alvo mudar.

Requer: PROJECT_PATH configurado no .env ou variável de ambiente.
"""

import os
import sys
import time

# Path setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from rag.indexer import collect_chunks, build_faiss_index, save_index
from core.context_manager import get_project_path

REPO_ROOT = get_project_path()
INDEX_DIR = os.path.join(PROJECT_ROOT, "rag", "index")


def main():
    print("=" * 60)
    print("LUPUS — RAG INDEX BUILDER")
    print("=" * 60)

    # Validar que repositório foi configurado
    if not REPO_ROOT:
        print("ERRO: Nenhum repositório configurado!")
        print("Configure PROJECT_PATH no .env ou via variável de ambiente.")
        sys.exit(1)

    print(f"Repositório: {REPO_ROOT}")
    print(f"Índice: {INDEX_DIR}")
    print()

    start = time.time()

    # 1. Coleta e chunking
    print("[ 1/3 ] Coletando e chunking arquivos...")
    chunks = collect_chunks(REPO_ROOT)

    if not chunks:
        print("ERRO: Nenhum chunk gerado. Verifique se o repositório existe e tem arquivos.")
        sys.exit(1)

    # Estatísticas de chunking
    by_type = {}
    by_layer = {}
    for c in chunks:
        by_type[c["chunk_type"]] = by_type.get(c["chunk_type"], 0) + 1
        by_layer[c["layer"]] = by_layer.get(c["layer"], 0) + 1

    print(f"  Total de chunks: {len(chunks)}")
    print(f"  Por tipo:  {by_type}")
    print(f"  Por camada: {by_layer}")
    print()

    # 2. Embeddings + FAISS
    print("[ 2/3 ] Gerando embeddings e construindo índice FAISS...")
    index, chunks = build_faiss_index(chunks)
    print()

    # 3. Salvar
    print("[ 3/3 ] Salvando índice em disco...")
    save_index(index, chunks, INDEX_DIR, repo_path=REPO_ROOT)

    elapsed = time.time() - start
    total_chars = sum(len(c["content"]) for c in chunks)

    print()
    print("=" * 60)
    print("CONCLUÍDO")
    print("=" * 60)
    print(f"  Chunks indexados : {len(chunks)}")
    print(f"  Total de chars   : {total_chars:,}")
    print(f"  Tempo total      : {elapsed:.1f}s")
    print()
    print("Para usar o RAG, inicie o chat normalmente:")
    print("  python main.py")


if __name__ == "__main__":
    main()
