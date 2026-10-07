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
        existing_item = next((item for item in items if item["id"] == annotation_id), None) if annotation_id else None
        if annotation_id and existing_item is None:
            raise ValueError("annotation_not_found")
        if len(items) >= 500 and not annotation_id:
            raise ValueError("annotation_limit_reached")
        safe_anchor = {}
        for key in ("source_revision", "locator", "quote_hash", "selected_text"):
            value = anchor.get(key) if isinstance(anchor, dict) else ""
            if value:
                safe_anchor[key] = str(value)[:1000]
        if existing_item and not safe_anchor:
            safe_anchor = dict(existing_item.get("anchor") or {})
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


def export_personal_data() -> dict[str, list[dict]]:
    """Export only user-authored annotations and note editions for a local backup."""

    annotations = []
    notes_root = DATA_DIR / "personal-notes"
    if notes_root.is_dir():
        for path in sorted(notes_root.glob("*.json")):
            key = path.stem
            if not re.fullmatch(r"(?:task|material)-[A-Za-z0-9_-]+", key):
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                items = value.get("annotations") if isinstance(value, dict) else None
                if isinstance(items, list):
                    annotations.append({"key": key, "items": items})
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue

    editions = []
    editions_root = DATA_DIR / "user-editions"
    if editions_root.is_dir():
        for path in sorted(editions_root.glob("*.json")):
            if not re.fullmatch(r"[a-f0-9]{64}", path.stem):
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                text = value.get("text") if isinstance(value, dict) else None
                revision = str(value.get("revision") or "") if isinstance(value, dict) else ""
                if isinstance(text, str) and len(text) <= 5_000_000 and revision == hashlib.sha256(text.encode("utf-8")).hexdigest():
                    editions.append({"key": path.stem, "value": {"text": text, "revision": revision, "edited": bool(value.get("edited"))}})
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
    return {"annotations": annotations, "editions": editions}


def validate_personal_data(payload: dict) -> dict[str, list[dict]]:
    if not isinstance(payload, dict):
        raise ValueError("personal_backup_invalid")
    raw_annotations = payload.get("annotations", [])
    raw_editions = payload.get("editions", [])
    if not isinstance(raw_annotations, list) or not isinstance(raw_editions, list):
        raise ValueError("personal_backup_invalid")
    if len(raw_annotations) > 100_000 or len(raw_editions) > 100_000:
        raise ValueError("personal_backup_limit_exceeded")

    annotations = []
    total_text = 0
    for group in raw_annotations:
        if not isinstance(group, dict):
            raise ValueError("personal_backup_annotation_group_invalid")
        key = str(group.get("key") or "")
        items = group.get("items")
        if not re.fullmatch(r"(?:task|material)-[A-Za-z0-9_-]+", key) or not isinstance(items, list) or len(items) > 500:
            raise ValueError("personal_backup_annotation_group_invalid")
        safe_items = []
        seen_ids: set[str] = set()
        for raw in items:
            if not isinstance(raw, dict):
                raise ValueError("personal_backup_annotation_invalid")
            annotation_id = str(raw.get("id") or "")
            text = str(raw.get("text") or "").strip()
            quote = str(raw.get("quote") or "").strip()
            anchor = raw.get("anchor") if isinstance(raw.get("anchor"), dict) else {}
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", annotation_id) or annotation_id in seen_ids or not text or len(text) > 8000 or len(quote) > 1000:
                raise ValueError("personal_backup_annotation_invalid")
            seen_ids.add(annotation_id)
            total_text += len(text) + len(quote)
            safe_anchor = {key: str(anchor[key])[:1000] for key in ("source_revision", "locator", "quote_hash", "selected_text") if anchor.get(key)}
            safe_items.append({"id": annotation_id, "text": text, "quote": quote, "anchor": safe_anchor})
        annotations.append({"key": key, "items": safe_items})

    editions = []
    for raw in raw_editions:
        if not isinstance(raw, dict) or not isinstance(raw.get("value"), dict):
            raise ValueError("personal_backup_edition_invalid")
        key = str(raw.get("key") or "")
        text = raw["value"].get("text")
        revision = str(raw["value"].get("revision") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", key) or not isinstance(text, str) or len(text) > 5_000_000:
            raise ValueError("personal_backup_edition_invalid")
        expected_revision = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if revision != expected_revision:
            raise ValueError("personal_backup_edition_revision_invalid")
        total_text += len(text)
        editions.append({"key": key, "value": {"text": text, "revision": revision, "edited": bool(raw["value"].get("edited"))}})
    if total_text > 100_000_000:
        raise ValueError("personal_backup_too_large")
    return {"annotations": annotations, "editions": editions}


def restore_personal_data(payload: dict) -> dict[str, int]:
    """Merge missing local user notes without overwriting current edits."""

    snapshot = validate_personal_data(payload)
    restored_annotations = restored_editions = 0
    with _lock:
        notes_root = DATA_DIR / "personal-notes"
        for group in snapshot["annotations"]:
            path = notes_root / f"{group['key']}.json"
            existing: list[dict] = []
            if path.is_file():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    existing = [item for item in value.get("annotations", []) if isinstance(item, dict)] if isinstance(value, dict) else []
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    continue
            ids = {str(item.get("id") or "") for item in existing}
            additions = [item for item in group["items"] if item["id"] not in ids]
            if additions:
                if len(existing) + len(additions) > 500:
                    raise ValueError("personal_annotation_limit_reached")
                atomic_write_text(path, json.dumps({"schema_version": 1, "annotations": existing + additions}, ensure_ascii=False, indent=2))
                restored_annotations += len(additions)

        editions_root = DATA_DIR / "user-editions"
        for item in snapshot["editions"]:
            path = editions_root / f"{item['key']}.json"
            if path.exists():
                continue
            atomic_write_text(path, json.dumps(item["value"], ensure_ascii=False))
            restored_editions += 1
    return {"restored_annotations": restored_annotations, "restored_editions": restored_editions}
