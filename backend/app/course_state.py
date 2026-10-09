"""Shared manifest identity and lock for course edits, bindings and deletion."""
import json
import re
import threading

lock = threading.RLock()


def course_path(root, course_id):
    if not re.fullmatch(r"[a-f0-9]{32}", course_id):
        raise ValueError("invalid_course_id")
    return root / "courses" / f"{course_id}.json"


def read_course(root, course_id):
    return json.loads(course_path(root, course_id).read_text(encoding="utf-8"))


def require_current_course(root, course):
    if read_course(root, course["id"]) != course:
        raise ValueError("course_changed_reload_required")
