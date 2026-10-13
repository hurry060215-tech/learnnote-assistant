"""Strict portable records for explicit personal whole-note review actions."""
from datetime import datetime
import hashlib
import re
from uuid import uuid4
from .personal_anchors import digest

_HASH = re.compile(r"[a-f0-9]{64}")
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

def review_key(kind: str, source_id: str) -> str:
    if kind not in {"task", "material"} or not _ID.fullmatch(source_id):
        raise ValueError("personal_review_source_invalid")
    return hashlib.sha256(f"{kind}:{source_id}".encode()).hexdigest()


def validate_review(value: dict, key: str) -> dict:
    """Fail closed on damaged/future records; never normalize personal preimages."""
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("personal_review_schema_unsupported")
    if set(value) != {"schema_version", "kind", "source_id", "state", "context_revision", "revision", "checked_at", "updated_at", "receipts"}:
        raise ValueError("personal_review_invalid")
    if (not isinstance(value["kind"], str) or not isinstance(value["source_id"], str)
            or review_key(value["kind"], value["source_id"]) != key
            or value["state"] not in ("marked", "revoked", "imported")):
        raise ValueError("personal_review_invalid")
    for field in ("context_revision", "revision"):
        if not isinstance(value[field], str) or not _HASH.fullmatch(value[field]):
            raise ValueError("personal_review_invalid")
    for field in ("checked_at", "updated_at"):
        if not isinstance(value[field], str) or not 1 <= len(value[field]) <= 64:
            raise ValueError("personal_review_invalid")
        try:
            stamp = datetime.fromisoformat(value[field])
            if stamp.tzinfo is None:
                raise ValueError("timezone_required")
        except ValueError as exc:
            raise ValueError("personal_review_invalid") from exc
    receipts = value["receipts"]
    if not isinstance(receipts, list) or len(receipts) > 32:
        raise ValueError("personal_review_invalid")
    seen = set()
    for item in receipts:
        if (not isinstance(item, dict) or set(item) != {"id", "digest"}
                or not isinstance(item["id"], str) or not _ID.fullmatch(item["id"])
                or item["id"] in seen or not isinstance(item["digest"], str) or not _HASH.fullmatch(item["digest"])):
            raise ValueError("personal_review_invalid")
        seen.add(item["id"])
    return value


def imported_review(value: dict) -> dict:
    """A backup does not establish the current operator's personal endorsement."""
    return {**value, "state": "revoked" if value["state"] == "revoked" else "imported",
        "revision": digest(["imported", uuid4().hex]), "receipts": []}


