"""OS-held callback ownership, independent of occupied processing slots.

The journal stores an opaque instance ID, never a callback or credential. A
process death releases its file lock; elapsed time and PIDs are not evidence.
"""
from pathlib import Path
import os
import re
import uuid


def _lock(handle, acquire):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), (fcntl.LOCK_EX | fcntl.LOCK_NB) if acquire else fcntl.LOCK_UN)


class QueueOwner:
    def __init__(self, root: Path):
        self.id = uuid.uuid4().hex
        directory = Path(root) / ".queue-owners"
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (self.id + ".lock")
        self.handle = self.path.open("x+b")
        try:
            self.handle.write(b"1")
            self.handle.flush()
            _lock(self.handle, True)
        except BaseException:
            self.handle.close()
            self.path.unlink(missing_ok=True)
            raise

    def close(self):
        if self.handle is None:
            return
        handle, self.handle = self.handle, None
        try:
            _lock(handle, False)
        finally:
            handle.close()
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass  # An unlocked residual file never establishes ownership.


def owner_is_alive(root: Path, owner_id: str) -> bool:
    if not owner_id:
        return False  # Legacy rows are recovered only under worker leases.
    if not re.fullmatch(r"[0-9a-f]{32}", owner_id):
        return True  # Unknown ownership must not authorize stealing a callback.
    path = Path(root) / ".queue-owners" / (owner_id + ".lock")
    try:
        if path.is_symlink():
            return True
        with path.open("r+b") as handle:
            try:
                _lock(handle, True)
            except OSError:
                return True
            _lock(handle, False)
            return False
    except FileNotFoundError:
        return False
    except OSError:
        return True
