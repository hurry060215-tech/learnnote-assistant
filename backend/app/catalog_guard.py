"""Serialize catalog access, including recovery publication, across app processes."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import threading

_mutex = threading.RLock()
_local = threading.local()


class CatalogUnavailable(sqlite3.DatabaseError):
    pass


@contextmanager
def catalog_guard(root: Path):
    # Keep the lock file: unlinking it could give two processes different locks.
    key = str(root.resolve())
    with _mutex:
        held = getattr(_local, "held", {})
        if key in held:
            yield
            return
        root.mkdir(parents=True, exist_ok=True)
        if (root / ".library-access.lock").is_symlink():
            raise CatalogUnavailable("catalog_path_unsafe")
        handle = (root / ".library-access.lock").open("a+b")
        locked = False
        try:
            if os.name == "nt":
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
            held[key] = True
            _local.held = held
            yield
        except OSError as exc:
            if not locked:
                raise CatalogUnavailable("catalog_busy") from exc
            raise
        finally:
            held.pop(key, None)
            if locked:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


class _GuardedConnection(sqlite3.Connection):
    _guard = None

    def close(self):
        try:
            super().close()
        finally:
            if self._guard is not None:
                guard, self._guard = self._guard, None
                guard.__exit__(None, None, None)


def connect_catalog(path: Path, *, allow_missing: bool = False) -> sqlite3.Connection:
    guard = catalog_guard(path.parent)
    guard.__enter__()
    try:
        if path.is_symlink():
            raise CatalogUnavailable("catalog_path_unsafe")
        if not allow_missing and not path.exists() and any(p.is_dir() for p in (path.parent / "materials").glob("*")):
            raise CatalogUnavailable("catalog_recovery_required")
        connection = sqlite3.connect(path, timeout=30, factory=_GuardedConnection)
        connection._guard = guard
        return connection
    except BaseException:
        guard.__exit__(None, None, None)
        raise
