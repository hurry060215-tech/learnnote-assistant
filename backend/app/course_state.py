"""Course manifest identity and a short, process-safe mutation transaction."""
from contextlib import contextmanager
import json
import re
import threading

from .worker_lease import worker_lease, has_worker_lease

_lock = threading.RLock()


def course_read_lock():
    """Share the in-process writer lock without creating files on a read path."""
    return _lock


def course_path(data_dir, course_id):
    if not re.fullmatch(r"[a-f0-9]{32}", course_id):
        raise ValueError("invalid_course_id")
    return data_dir / "courses" / f"{course_id}.json"


def read_course(data_dir, course_id):
    return json.loads(course_path(data_dir, course_id).read_text(encoding="utf-8"))


@contextmanager
def course_transaction(data_dir):
    with _lock:
        directory = data_dir / "course-state-locks"
        if directory.is_symlink():
            raise ValueError("course_lock_unavailable")
        directory.mkdir(parents=True, exist_ok=True)
        if has_worker_lease(directory, "heavy"):
            yield
            return
        with worker_lease(directory) as acquired:
            if not acquired:
                raise ValueError("course_busy")
            yield
