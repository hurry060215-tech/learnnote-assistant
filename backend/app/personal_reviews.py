"""Explicit local whole-note review records, independent of AI verification."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from .personal_review_records import review_key, validate_review
from uuid import uuid4

from .personal_anchors import digest
from .personal_restore import _object, _read_existing
from .personal_storage import personal_transaction
from .storage import atomic_write_text

ABSENT_REVISION = digest(["personal-review", "absent"])
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class ReviewConflict(ValueError):
    pass


def _read(root: Path, kind: str, source_id: str):
    key = review_key(kind, source_id)
    path = root / "personal-reviews" / f"{key}.json"
    raw = _read_existing(path)
    return path, validate_review(_object(raw), key) if raw is not None else None


def _context(reader):
    # A missing/corrupt source must not hide the stored record or prevent revoke.
    try:
        return reader()
    except (OSError, ValueError, OverflowError, RecursionError):
        return {"context_revision": None, "note_revision": None, "can_mark": False,
            "source_scope": "reading_only", "source_labels": [],
            "scope_detail": "当前笔记或来源无法安全读取；旧记录未改动，可撤销后恢复来源再核对。"}


def _project(record, context):
    status = "unmarked"
    if record:
        status = ("current" if context.get("can_mark") and record["context_revision"] == context["context_revision"] else "stale") if record["state"] == "marked" else record["state"]
    return {**context, "status": status, "review_revision": record["revision"] if record else ABSENT_REVISION,
        "checked_at": record["checked_at"] if record else None}


def read_review(root: Path, kind: str, source_id: str, reader) -> dict:
    with personal_transaction(root):
        _, record = _read(root, kind, source_id)
        return _project(record, _context(reader))


def change_review(root: Path, kind: str, source_id: str, reader, *, action: str,
                  expected_context_revision: str, expected_review_revision: str, request_id: str) -> dict:
    if action not in {"mark", "revoke"} or not _ID.fullmatch(request_id):
        raise ValueError("personal_review_request_invalid")
    with personal_transaction(root):
        path, record = _read(root, kind, source_id)
        context = _context(reader)
        request_digest = digest([action, expected_context_revision, expected_review_revision])
        receipts = record["receipts"] if record else []
        for receipt in receipts:
            if receipt["id"] == request_id:
                if receipt["digest"] != request_digest:
                    raise ReviewConflict("personal_review_request_conflict")
                return {**_project(record, context), "replayed": True}
        if expected_review_revision != (record["revision"] if record else ABSENT_REVISION):
            raise ReviewConflict("personal_review_changed")
        if action == "mark" and (not context["can_mark"] or expected_context_revision != context["context_revision"]):
            raise ReviewConflict("personal_review_context_changed")
        if action == "revoke" and record is None:
            raise ReviewConflict("personal_review_missing")
        # Sources do not all share the personal write lock. Require another
        # matching read before persisting and derive status again after writing.
        if action == "mark" and _context(reader) != context:
            raise ReviewConflict("personal_review_context_changed")
        now = datetime.now(timezone.utc).isoformat()
        value = {"schema_version": 1, "kind": kind, "source_id": source_id,
            "state": "marked" if action == "mark" else "revoked",
            "context_revision": context["context_revision"] if action == "mark" else record["context_revision"],
            "revision": digest([uuid4().hex]), "checked_at": now if action == "mark" else record["checked_at"],
            "updated_at": now, "receipts": (receipts + [{"id": request_id, "digest": request_digest}])[-32:]}
        validate_review(value, path.stem)
        atomic_write_text(path, json.dumps(value, ensure_ascii=False))
        return _project(value, _context(reader))
