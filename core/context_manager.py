"""Gerenciador centralizado do contexto do repositório ativo.

Singleton que controla todo o estado do repo. Toda mudança de repositório
DEVE passar por ctx_manager.set_repo() — é o único ponto de entrada.

Hooks registrados são disparados automaticamente quando o repo muda,
garantindo que cache, RAG, e middleware se mantenham sincronizados.

Uso:
    from core.context_manager import ctx_manager

    # Ler estado atual
    path = ctx_manager.path
    name = ctx_manager.name

    # Mudar repo (dispara hooks)
    ctx_manager.set_repo("/caminho/para/novo/repo")

    # Registrar hook
    ctx_manager.register_hook(minha_funcao)
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from core.repo_context import RepoContext

logger = logging.getLogger(__name__)

# Type alias para hooks: recebem o novo RepoContext
RepoChangeHook = Callable[[RepoContext], None]


class ProjectContextManager:
    """Singleton que gerencia o RepoContext e dispara ações quando o repo muda."""

    _instance: ProjectContextManager | None = None

    def __new__(cls) -> ProjectContextManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._context = None
            cls._instance._hooks: list[RepoChangeHook] = []
            cls._instance._repo_change_count = 0
        return cls._instance

    @property
    def context(self) -> RepoContext | None:
        """RepoContext atual ou None se nenhum repo está ativo."""
        return self._context

    @property
    def path(self) -> str:
        """Caminho do repo ativo. String vazia se nenhum repo."""
        return self._context.path if self._context else ""

    @property
    def name(self) -> str:
        """Nome do repo ativo. 'nenhum' se nenhum repo."""
        return self._context.name if self._context else "nenhum"

    @property
    def repo_change_count(self) -> int:
        """Contador de mudanças de repo. Usado pelo main loop para detectar mudanças."""
        return self._repo_change_count

    def set_repo(self, path: str) -> None:
        """Atualiza o repo ativo. Dispara todos os hooks registrados.

        ÚNICO ponto de entrada para mudança de repo.

        Args:
            path: Caminho absoluto do novo repositório.
        """
        old_path = self._context.path if self._context else None
        self._context = RepoContext(path=path)
        self._repo_change_count += 1

        # Retrocompatibilidade — tools que ainda leiam os.environ diretamente
        os.environ["PROJECT_PATH"] = path

        logger.info("Repo alterado: %s -> %s", old_path, path)

        for hook in self._hooks:
            try:
                hook(self._context)
            except Exception as e:
                logger.error("Erro no hook %s: %s", getattr(hook, "__name__", hook), e)

    def register_hook(self, fn: RepoChangeHook) -> None:
        """Registra função chamada quando o repo mudar.

        Hooks são chamados na ordem de registro.
        Assinatura: fn(context: RepoContext) -> None
        """
        self._hooks.append(fn)

    def init_from_env(self, default_path: str = "") -> None:
        """Inicializa a partir do PROJECT_PATH existente (startup).

        Não dispara hooks — é a configuração inicial, não uma mudança.
        """
        path = os.environ.get("PROJECT_PATH", default_path)
        if path:
            self._context = RepoContext(path=path)
            os.environ["PROJECT_PATH"] = path


def get_project_path() -> str:
    """Retorna o caminho do repo ativo. Fonte única de verdade.

    Substitui os.environ.get("PROJECT_PATH") e _get_project_root() nas tools.
    Fallback para os.environ por segurança durante migração.
    """
    if ctx_manager.path:
        return ctx_manager.path
    return os.environ.get("PROJECT_PATH", "")


# Instância global — importar este objeto, não instanciar nova classe
ctx_manager = ProjectContextManager()
