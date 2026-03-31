"""Cache simples com TTL para domain tools.

Evita I/O repetido de arquivos em conversas longas.
A chave de cache inclui PROJECT_PATH — troca de repositório invalida automaticamente.
"""

import hashlib
import threading
import time

from core.context_manager import get_project_path

_TTL_SECONDS = 300  # 5 minutos
_store: dict[str, tuple[float, str]] = {}  # key → (timestamp, result)
_lock = threading.RLock()
_last_purge_time = time.time()  # Timestamp do último purge


def make_key(func_name: str, **kwargs) -> str:
    """Gera chave de cache baseada na função, PROJECT_PATH e argumentos."""
    project_path = get_project_path()
    raw = f"{func_name}:{project_path}:{sorted(kwargs.items())}"
    return hashlib.md5(raw.encode()).hexdigest()


def get(key: str) -> str | None:
    """Retorna valor em cache se ainda válido, None se expirado ou ausente."""
    with _lock:
        if key in _store:
            timestamp, value = _store[key]
            if time.time() - timestamp < _TTL_SECONDS:
                return value
            del _store[key]
        return None


def set(key: str, value: str) -> None:
    """Armazena resultado no cache."""
    global _last_purge_time
    with _lock:
        _store[key] = (time.time(), value)
        # Limpa entradas expiradas periodicamente (a cada 20 escritas OU a cada 5 minutos)
        if len(_store) % 20 == 0 or time.time() - _last_purge_time > _TTL_SECONDS:
            _purge_expired()
            _last_purge_time = time.time()


def _purge_expired() -> None:
    """Remove entradas expiradas do cache. Deve ser chamada com _lock adquirido."""
    now = time.time()
    expired = [k for k, (ts, _) in _store.items() if now - ts >= _TTL_SECONDS]
    for k in expired:
        del _store[k]


def clear() -> None:
    """Limpa todo o cache — útil quando PROJECT_PATH muda em runtime."""
    with _lock:
        _store.clear()


def on_repo_change(context) -> None:
    """Hook chamado pelo ProjectContextManager quando o repo muda."""
    clear()


def stats() -> dict:
    """Retorna estatísticas do cache para debug."""
    with _lock:
        now = time.time()
        valid = sum(1 for ts, _ in _store.values() if now - ts < _TTL_SECONDS)
        return {
            "total_entries": len(_store),
            "valid_entries": valid,
            "expired_entries": len(_store) - valid,
            "ttl_seconds": _TTL_SECONDS,
        }
