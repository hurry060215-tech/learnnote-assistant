"""Shared local serialization for personal annotations, editions and restore."""
from contextlib import contextmanager
from pathlib import Path
import threading

from .worker_lease import has_worker_lease, worker_lease

lock = threading.RLock()


RECOVERY_MESSAGE = "恢复状态暂时无法确认，已停止后续写入。请先保留数据目录 personal-state/restore-pending 中的恢复副本并核对记录。"


class PersonalStorageError(ValueError):
    """A bounded local storage condition; callers can show a safe message."""


class PersonalRecoveryRequired(PersonalStorageError):
    """Original local copies exist and must be inspected before another write."""

    def __init__(self):
        super().__init__("personal_restore_recovery_required")


def state_root(data_dir: Path) -> Path:
    root = data_dir / "personal-state"
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise PersonalStorageError("personal_storage_unavailable")
    return root


@contextmanager
def personal_transaction(data_dir: Path):
    """Use one lock order for manual edits, assistant edits and backup restore."""
    with lock:
        root = state_root(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        lease_file = root / "worker.lock"
        if lease_file.is_symlink() or (lease_file.exists() and not lease_file.is_file()):
            raise PersonalStorageError("personal_storage_unavailable")
        if has_worker_lease(root, "heavy"):
            yield
            return
        with worker_lease(root) as acquired:
            if not acquired:
                raise PersonalStorageError("personal_storage_busy")
            pending = root / "restore-pending"
            if pending.exists() or pending.is_symlink():
                raise PersonalRecoveryRequired()
            yield
