from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import TASK_DIR, ensure_dirs


EVENT_SCHEMA_VERSION = 1
_lock = threading.RLock()
_SECRET_KEY_RE = re.compile(r"cookie|authorization|token|signature|secret|password|api[_-]?key|request[_-]?body|signed[_-]?url", re.I)


def _safe_value(value: Any, key: str = "") -> Any:
    if _SECRET_KEY_RE.search(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(name): _safe_value(item, str(name)) for name, item in value.items() if not _SECRET_KEY_RE.search(str(name))}
    if isinstance(value, list):
        return [_safe_value(item, key) for item in value[:32]]
    text = str(value) if value is not None else ""
    if re.search(r"https?://", text, re.I):
        return re.sub(r"([?&](?:token|sign|signature|auth|expires|expires_at|key)=[^&#\s]+)", "<redacted>", text, flags=re.I)
    return value


def events_path(task_id: str) -> Path:
    return (TASK_DIR / task_id / "events.jsonl").resolve()


def record_task_event(
    task_id: str,
    event: str,
    *,
    phase: str = "",
    status: str = "",
    error_code: str = "",
    message: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": str(event)[:80],
        "phase": str(phase)[:80],
        "status": str(status)[:40],
        "error_code": str(error_code)[:120],
        "message": str(message)[:500],
        "details": _safe_value(details or {}),
    }
    target = events_path(task_id)
    task_root = TASK_DIR.resolve()
    if task_root not in target.parents:
        raise ValueError("invalid_task_path")
    ensure_dirs()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def read_task_events(task_id: str, limit: int = 500) -> list[dict[str, Any]]:
    path = events_path(task_id)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(int(limit or 500), 2000)):]
    except OSError:
        return []
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def redacted_support_manifest(task_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "bundle_type": "support-package",
        "task_id": task_id,
        "event_count": len(events),
        "privacy": {
            "cookies": False,
            "authorization": False,
            "request_bodies": False,
            "signed_urls": False,
            "course_content": False,
        },
    }
