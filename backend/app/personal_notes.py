"""User-authored annotations are separate local facts, never regenerated text."""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from uuid import uuid4

from .config import DATA_DIR
from .storage import atomic_write_text, get_task
from .library import get_material, material_content
from .personal_anchors import KINDS, annotation_targets, digest, normalize_anchor, read_anchor_artifact, resolve_anchor, validate_new_anchor

from .personal_storage import lock as _lock, personal_transaction
from .personal_restore import _annotation_file, _edition_file, _read_existing, personal_restore_transaction


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
        try:
            original = read_anchor_artifact(source_id, task.note_path or task.transcript_path or "").replace("\r\n", "\n").replace("\r", "\n")
        except (OSError, UnicodeError):
            pass  # A damaged generated source must not hide personal text.
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
        targets = annotation_targets(kind, source_id)["targets"] if any(item["anchor"].get("kind") in KINDS for item in result) else []
        for item in result:
            item["revision"] = _annotation_revision(item)
            anchor = item["anchor"]
            if anchor.get("kind") in KINDS:
                item["anchor_status"] = resolve_anchor(anchor, targets)
                continue
            stored_revision = str(anchor.get("source_revision") or "")
            quote = str(item.get("quote") or anchor.get("selected_text") or "")
            if stored_revision or anchor:
                item["anchor_status"] = {
                    "stale": bool(stored_revision and stored_revision != current_revision),
                    "repairable": bool(quote),
                    "current_revision": current_revision,
                }
        return result


def _annotation_revision(item: dict) -> str:
    return digest({key: item.get(key, {} if key == "anchor" else "") for key in ("id", "text", "quote", "anchor")})


def _stored_items(items: list[dict]) -> list[dict]:
    return [{key: value for key, value in item.items() if key not in {"anchor_status", "revision"}} for item in items]


def save_annotation(kind: str, source_id: str, text: str, quote: str | None = None, annotation_id: str = "", anchor: dict | None = None,
                    revision: str = "", request_id: str = "") -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        raise ValueError("annotation_text_required")
    if quote is not None and (not isinstance(quote, str) or len(quote) > 1000):
        raise ValueError("annotation_quote_invalid")
    if request_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
        raise ValueError("annotation_request_id_invalid")
    with personal_transaction(DATA_DIR):
        items = list_annotations(kind, source_id)
        existing_item = next((item for item in items if item["id"] == annotation_id), None) if annotation_id else None
        if annotation_id and existing_item is None:
            raise ValueError("annotation_not_found")
        safe_anchor = normalize_anchor(anchor)
        if existing_item and not safe_anchor:
            safe_anchor = dict(existing_item.get("anchor") or {})
        saved_quote = quote if quote is not None else str((existing_item or {}).get("quote") or "")
        if request_id and not annotation_id:
            previous = next((item for item in items if item.get("request_id") == request_id), None)
            if previous:
                if any(previous.get(key) != value for key, value in (("text", text), ("quote", saved_quote), ("anchor", safe_anchor))):
                    raise ValueError("annotation_request_conflict")
                return previous
        if len(items) >= 500 and not annotation_id:
            raise ValueError("annotation_limit_reached")
        if existing_item and revision and revision != existing_item["revision"]:
            if all(existing_item.get(key) == value for key, value in (("text", text), ("quote", saved_quote), ("anchor", safe_anchor))):
                return existing_item  # Retrying an acknowledged edit is harmless.
            raise ValueError("annotation_revision_conflict")
        if not existing_item or safe_anchor != existing_item.get("anchor"):
            safe_anchor = validate_new_anchor(kind, source_id, safe_anchor)
        item = {"id": annotation_id or uuid4().hex, "text": text, "quote": saved_quote, "anchor": safe_anchor}
        if request_id or (existing_item or {}).get("request_id"):
            item["request_id"] = request_id or existing_item["request_id"]
        items = [value for value in items if value["id"] != item["id"]]
        items.append(item)
        atomic_write_text(_path(kind, source_id), json.dumps({"schema_version": 2, "annotations": _stored_items(items)}, ensure_ascii=False, indent=2))
        return {**item, "revision": _annotation_revision(item)}


def delete_annotation(kind: str, source_id: str, annotation_id: str):
    with personal_transaction(DATA_DIR):
        items = list_annotations(kind, source_id)
        remaining = [item for item in items if item["id"] != annotation_id]
        atomic_write_text(_path(kind, source_id), json.dumps({"schema_version": 2, "annotations": _stored_items(remaining)}, ensure_ascii=False, indent=2))
        return len(remaining) != len(items)


def annotation_markdown(kind: str, source_id: str) -> str:
    items = list_annotations(kind, source_id)
    if not items:
        return ""
    return "\n\n## 个人批注\n\n" + "\n\n".join((f"> {item['quote']}\n\n" if item["quote"] else "") + item["text"] for item in items)


def export_personal_data() -> dict[str, list[dict]]:
    """Export all recognized personal content or fail without a partial backup."""
    result = {"annotations": [], "editions": []}
    total_bytes = 0
    with personal_transaction(DATA_DIR):
        for folder, pattern, kind in (
            ("personal-notes", r"(?:task|material)-[A-Za-z0-9_-]+", "annotations"),
            ("user-editions", r"[a-f0-9]{64}", "editions"),
        ):
            root = DATA_DIR / folder
            if root.is_symlink() or (root.exists() and not root.is_dir()):
                raise ValueError("personal_backup_target_unsafe")
            paths = sorted(path for path in root.iterdir() if path.suffix == ".json") if root.exists() else []
            for path in paths:
                if not re.fullmatch(pattern, path.stem):
                    continue  # Files outside the defined personal-record namespace.
                if len(result[kind]) >= 100_000:
                    raise ValueError("personal_backup_limit_exceeded")
                content = _read_existing(path)
                if content is None:
                    raise ValueError("personal_backup_target_changed")
                total_bytes += len(content)
                if total_bytes > 100_000_000:
                    raise ValueError("personal_backup_too_large")
                if kind == "annotations":
                    value = _annotation_file(content, path.stem, validate_personal_data)
                    result[kind].append({"key": path.stem, "items": value["annotations"]})
                else:
                    _edition_file(content, path.stem, validate_personal_data)
                    value = json.loads(content.decode("utf-8"))
                    result[kind].append({"key": path.stem, "value": {
                        "text": value["text"], "revision": value["revision"], "edited": value["edited"],
                    }})
        validate_personal_data(result)
    return result


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
    annotation_keys: set[str] = set()
    total_text = 0
    for group in raw_annotations:
        if not isinstance(group, dict):
            raise ValueError("personal_backup_annotation_group_invalid")
        key = str(group.get("key") or "")
        items = group.get("items")
        if key in annotation_keys or not re.fullmatch(r"(?:task|material)-[A-Za-z0-9_-]+", key) or not isinstance(items, list) or len(items) > 500:
            raise ValueError("personal_backup_annotation_group_invalid")
        annotation_keys.add(key)
        safe_items = []
        seen_ids: set[str] = set()
        for raw in items:
            if not isinstance(raw, dict):
                raise ValueError("personal_backup_annotation_invalid")
            annotation_id = raw.get("id")
            text = raw.get("text", "")
            quote = raw.get("quote", "")
            anchor = raw.get("anchor", {})
            if not isinstance(anchor, dict):
                raise ValueError("personal_backup_annotation_invalid")
            if (not isinstance(annotation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", annotation_id) or annotation_id in seen_ids
                    or not isinstance(text, str) or not isinstance(quote, str) or not text.strip() or len(text) > 8000 or len(quote) > 1000):
                raise ValueError("personal_backup_annotation_invalid")
            seen_ids.add(annotation_id)
            total_text += len(text) + len(quote)
            safe_anchor = normalize_anchor(anchor)
            saved = {"id": annotation_id, "text": text, "quote": quote, "anchor": safe_anchor}
            if raw.get("request_id"):
                if not isinstance(raw["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", raw["request_id"]):
                    raise ValueError("personal_backup_annotation_invalid")
                saved["request_id"] = raw["request_id"]
            safe_items.append(saved)
        annotations.append({"key": key, "items": safe_items})

    editions = []
    edition_keys: set[str] = set()
    for raw in raw_editions:
        if not isinstance(raw, dict) or not isinstance(raw.get("value"), dict):
            raise ValueError("personal_backup_edition_invalid")
        key = str(raw.get("key") or "")
        text = raw["value"].get("text")
        revision = str(raw["value"].get("revision") or "")
        if key in edition_keys or not re.fullmatch(r"[a-f0-9]{64}", key) or not isinstance(text, str) or len(text) > 5_000_000:
            raise ValueError("personal_backup_edition_invalid")
        edition_keys.add(key)
        expected_revision = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if revision != expected_revision:
            raise ValueError("personal_backup_edition_revision_invalid")
        total_text += len(text)
        editions.append({"key": key, "value": {"text": text, "revision": revision, "edited": bool(raw["value"].get("edited"))}})
    if total_text > 100_000_000:
        raise ValueError("personal_backup_too_large")
    return {"annotations": annotations, "editions": editions}


def prepare_personal_restore(payload: dict):
    """Validate destinations and retain the transaction until study commits."""
    return personal_restore_transaction(DATA_DIR, validate_personal_data(payload), validate_personal_data, atomic_write_text)


def restore_personal_data(payload: dict) -> dict[str, int]:
    """Merge missing notes; a rejected or failed batch preserves local content."""
    with prepare_personal_restore(payload) as plan:
        plan.apply()
        return plan.counts
