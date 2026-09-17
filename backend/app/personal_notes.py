"""User-authored annotations are separate local facts, never regenerated text."""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
import threading
from uuid import uuid4

from .config import DATA_DIR
from .storage import atomic_write_text, get_task
from .library import get_material, material_content

_lock = threading.RLock()


def source_key(kind: str, source_id: str) -> str:
    if kind == "material":
        return "material-" + str(get_material(source_id)["sha256"])
    if kind != "task":
        raise ValueError("invalid_source_kind")
    task = get_task(source_id)
    visited = {task.id}
    while task.source_task_id and task.source_task_id not in visited:
        try:
            task = get_task(task.source_task_id)
        except FileNotFoundError:
            return "task-" + task.source_task_id
        visited.add(task.id)
    return "task-" + task.id


def _path(kind: str, source_id: str) -> Path:
    key = source_key(kind, source_id)
    if not re.fullmatch(r"(?:task|material)-[A-Za-z0-9_-]+", key):
        raise ValueError("invalid_source_key")
    return DATA_DIR / "personal-notes" / f"{key}.json"


def _current_edition_revision(kind: str, source_id: str) -> str:
    """Read the current local edition revision without importing the router."""

    original = ""
    if kind == "task":
        task = get_task(source_id)
        source = Path(task.note_path or task.transcript_path or "")
        if source.is_file():
            original = source.read_text(encoding="utf-8")
    elif kind == "material":
        get_material(source_id)
        try:
            original = material_content(source_id)
        except (ValueError, FileNotFoundError, OSError):
            original = str(get_material(source_id).get("sha256") or "")
    edition = DATA_DIR / "user-editions" / f"{hashlib.sha256(f'{kind}:{source_id}'.encode()).hexdigest()}.json"
    if edition.is_file():
        try:
            value = json.loads(edition.read_text(encoding="utf-8"))
            if str(value.get("revision") or "").strip():
                return str(value["revision"])
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    return hashlib.sha256(original.encode("utf-8")).hexdigest() if original else ""


def list_annotations(kind: str, source_id: str) -> list[dict]:
    with _lock:
        path = _path(kind, source_id)
        if not path.is_file():
            return []
        items = json.loads(path.read_text(encoding="utf-8")).get("annotations", [])
        current_revision = _current_edition_revision(kind, source_id)
        result = [
            {**item, "anchor": item.get("anchor") if isinstance(item.get("anchor"), dict) else {}}
            for item in items
            if isinstance(item, dict)
        ]
        for item in result:
            anchor = item["anchor"]
            stored_revision = str(anchor.get("source_revision") or "")
            quote = str(item.get("quote") or anchor.get("selected_text") or "")
            if stored_revision or anchor:
                item["anchor_status"] = {
                    "stale": bool(stored_revision and current_revision and stored_revision != current_revision),
                    "repairable": bool(quote),
                    "current_revision": current_revision,
                }
        return result


def save_annotation(kind: str, source_id: str, text: str, quote: str = "", annotation_id: str = "", anchor: dict | None = None) -> dict:
    if not text.strip():
        raise ValueError("annotation_text_required")
    with _lock:
        items = list_annotations(kind, source_id)
        if annotation_id and not any(item["id"] == annotation_id for item in items):
            raise ValueError("annotation_not_found")
        if len(items) >= 500 and not annotation_id:
            raise ValueError("annotation_limit_reached")
        safe_anchor = {}
        for key in ("source_revision", "locator", "quote_hash", "selected_text"):
            value = anchor.get(key) if isinstance(anchor, dict) else ""
            if value:
                safe_anchor[key] = str(value)[:1000]
        item = {"id": annotation_id or uuid4().hex, "text": text.strip(), "quote": quote.strip(), "anchor": safe_anchor}
        items = [value for value in items if value["id"] != item["id"]]
        items.append(item)
        atomic_write_text(_path(kind, source_id), json.dumps({"schema_version": 1, "annotations": items}, ensure_ascii=False, indent=2))
        return item


def delete_annotation(kind: str, source_id: str, annotation_id: str):
    with _lock:
        items = list_annotations(kind, source_id)
        remaining = [item for item in items if item["id"] != annotation_id]
        atomic_write_text(_path(kind, source_id), json.dumps({"schema_version": 1, "annotations": remaining}, ensure_ascii=False, indent=2))
        return len(remaining) != len(items)


def annotation_markdown(kind: str, source_id: str) -> str:
    items = list_annotations(kind, source_id)
    if not items:
        return ""
    return "\n\n## 个人批注\n\n" + "\n\n".join((f"> {item['quote']}\n\n" if item["quote"] else "") + item["text"] for item in items)
