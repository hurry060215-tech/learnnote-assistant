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


def validate_catalog_version(connection: sqlite3.Connection) -> None:
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_meta'").fetchone():
        return  # Fresh and legacy evidence-only databases have no version yet.
    row = connection.execute("SELECT value FROM library_meta WHERE key='schema_version'").fetchone()
    if row is not None and row[0] not in {"1", "2", "3"}:
        raise CatalogUnavailable("catalog_current_schema_invalid")


def orphaned_sidecars(path: Path) -> list[str]:
    """An absent or empty main DB cannot authorize SQLite to discard its logs."""
    if path.is_symlink():
        return []  # Callers reject the database link before opening it.
    if path.exists() and path.stat().st_size:
        return []
    return [suffix for suffix in ("-wal", "-journal", "-shm")
            if (sidecar := path.with_name(path.name + suffix)).exists() or sidecar.is_symlink()]


def connect_catalog(path: Path, *, allow_missing: bool = False) -> sqlite3.Connection:
    guard = catalog_guard(path.parent)
    guard.__enter__()
    try:
        if path.is_symlink():
            raise CatalogUnavailable("catalog_path_unsafe")
        if orphaned_sidecars(path):
            raise CatalogUnavailable("catalog_sidecars_unresolved")
        if not allow_missing and (not path.exists() or not path.stat().st_size) and any(p.is_dir() for p in (path.parent / "materials").glob("*")):
            raise CatalogUnavailable("catalog_recovery_required")
        if path.exists():
            probe = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                validate_catalog_version(probe)
            finally:
                probe.close()
        connection = sqlite3.connect(path, timeout=30, factory=_GuardedConnection)
        connection._guard = guard
        return connection
    except BaseException:
        guard.__exit__(None, None, None)
        raise
