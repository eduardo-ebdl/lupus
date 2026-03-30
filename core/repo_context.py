"""Dataclass que encapsula o estado do repositório ativo.

Substitui o uso direto de os.environ["PROJECT_PATH"] como fonte de verdade.
Toda informação sobre o repo atual (path, nome, timestamps, estado do RAG)
vive aqui. As tools leem deste objeto via ProjectContextManager.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RepoContext:
    """Estado de um repositório ativo."""

    path: str                          # Caminho absoluto do repo ativo
    name: str = ""                     # Nome do repo (basename do path)
    cloned_at: float | None = None     # Timestamp do clone (None = repo local)
    rag_indexed_path: str = ""         # Path que gerou o índice RAG atual
    cache_version: int = 0             # Incrementa a cada mudança de repo

    def __post_init__(self):
        if not self.name:
            self.name = Path(self.path).name if self.path else "nenhum"
        if self.cloned_at is None:
            self.cloned_at = time.time()

    def is_rag_synced(self) -> bool:
        """Retorna True se o índice RAG foi construído para o repo atual."""
        return bool(self.rag_indexed_path) and self.rag_indexed_path == self.path

    def invalidate_cache(self) -> None:
        """Incrementa versão do cache, sinalizando que dados mudaram."""
        self.cache_version += 1
