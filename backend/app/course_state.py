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
    course = json.loads(course_path(data_dir, course_id).read_text(encoding="utf-8"))
    # A manifest cannot redirect a reviewed operation to another collection or
    # smuggle an unchecked filesystem identity through its persisted sources.
    if (not isinstance(course, dict) or course.get("id") != course_id
            or type(course.get("schema_version")) is not int or course["schema_version"] != 1
            or not isinstance(course.get("title"), str)
            or type(course.get("paused")) is not bool
            or type(course.get("revision")) is not int or course["revision"] < 1
            or not isinstance(course.get("sources"), list) or len(course["sources"]) > 200):
        raise ValueError("course_manifest_invalid")
    for source in course["sources"]:
        if (not isinstance(source, dict) or not isinstance(source.get("kind"), str)
                or source["kind"] not in {"task", "material", "url"}
                or not isinstance(source.get("title"), str)):
            raise ValueError("course_manifest_invalid")
        identity = source.get("url") if source["kind"] == "url" else source.get("id")
        if (not isinstance(identity, str) or not identity
                or (source["kind"] == "url" and len(identity) > 4096)
                or (source["kind"] != "url" and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity))):
            raise ValueError("course_manifest_invalid")
    return course


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
