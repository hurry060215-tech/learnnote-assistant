"""Exact, read-only anchor resolution; never guess a replacement by similarity."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from contextlib import contextmanager

from .claims import CLAIM_SCHEMA_VERSION
from .storage import get_task, task_dir
from .task_artifacts import owned_task_artifact

KINDS = {"claim", "transcript", "visual"}
TEXT_FIELDS = ("source_revision", "locator", "quote_hash", "selected_text",
               "kind", "source_task_id", "claim_id", "evidence_id", "window_id", "target_hash")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def normalize_anchor(anchor: dict | None) -> dict:
    if not isinstance(anchor, dict):
        return {}
    result = {}
    for key in TEXT_FIELDS:
        value = anchor.get(key)
        if value is not None and value != "":
            if not isinstance(value, str) or len(value) > 1000:
                raise ValueError("annotation_anchor_invalid")
            result[key] = value
    kind = result.get("kind")
    if kind and kind not in KINDS | {"quote"}:
        raise ValueError("annotation_anchor_kind_invalid")
    for key in ("start", "end"):
        if key in anchor:
            value = anchor[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("annotation_anchor_range_invalid")
            result[key] = value
    if kind in {"transcript", "visual"}:
        if "start" not in result or "end" not in result or result["end"] < result["start"]:
            raise ValueError("annotation_anchor_range_invalid")
    if kind in KINDS and (not result.get("target_hash") or not result.get("source_task_id") or not result.get("source_revision")
                         or not result.get("claim_id" if kind == "claim" else "evidence_id")):
        raise ValueError("annotation_anchor_target_required")
    return result


MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


@contextmanager
def _opened_artifact(task_id: str, value: str, directory: str = ""):
    """Check ownership, then bind validation and size limits to one descriptor."""
    source = None
    try:
        path = owned_task_artifact(task_id, value, directory=directory)
        if path is not None:
            expected = path.lstat()
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
            source = os.fdopen(descriptor, "rb")
            actual = os.fstat(source.fileno())
            if (not stat.S_ISREG(actual.st_mode) or actual.st_size > MAX_ARTIFACT_BYTES
                    or (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino)
                    or owned_task_artifact(task_id, value, directory=directory) != path):
                source.close()
                source = None
    except OSError:
        if source is not None:
            source.close()
        source = None
    try:
        yield source
    finally:
        if source is not None:
            source.close()


def read_anchor_artifact(task_id: str, value: str) -> str:
    with _opened_artifact(task_id, value) as source:
        if source is None:
            return ""
        content = source.read(MAX_ARTIFACT_BYTES + 1)
    return content.decode("utf-8") if len(content) <= MAX_ARTIFACT_BYTES else ""


def _grid_hash(task_id: str, value: str) -> str:
    if not str(value).lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return ""
    result, total = hashlib.sha256(), 0
    with _opened_artifact(task_id, value, "grids") as source:
        if source is None:
            return ""
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                return ""
            result.update(chunk)
    return result.hexdigest()


def _family_root(source_id: str) -> str:
    visited = set()
    while source_id:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", source_id) or source_id in visited or len(visited) >= 100:
            raise ValueError("invalid_annotation_lineage")
        visited.add(source_id)
        try:
            task = get_task(source_id)
        except FileNotFoundError:
            return source_id  # A surviving child's explicit parent link remains evidence.
        if task.id != source_id:
            raise ValueError("invalid_annotation_lineage")
        if not task.source_task_id:
            return source_id
        source_id = task.source_task_id
    raise ValueError("invalid_annotation_lineage")


def _related(left: str, right: str) -> bool:
    if left == right:
        return True
    try:
        return _family_root(left) == _family_root(right)
    except (ValueError, OSError):
        return False


def annotation_targets(kind: str, source_id: str) -> dict:
    """Only current generated claims and extant source artifacts are selectable."""
    if kind != "task":
        return {"targets": []}
    task = get_task(source_id)
    targets = []
    try:
        # Generated claim maps use normalized note newlines. Personal text is
        # stored in JSON and never passes through this source-only projection.
        note = read_anchor_artifact(source_id, task.note_path).replace("\r\n", "\n").replace("\r", "\n")
        source_revision = hashlib.sha256(note.encode("utf-8")).hexdigest() if note else ""
        mapped = json.loads(read_anchor_artifact(source_id, str(task_dir(source_id) / "claim_evidence_map.json")) or "{}")
        if (isinstance(mapped, dict) and mapped.get("schema_version") == CLAIM_SCHEMA_VERSION
                and mapped.get("source_revision") == source_revision):
            for claim in mapped.get("claims", []):
                text = claim.get("text", "")
                if not isinstance(text, str) or not text or not claim.get("claim_id"):
                    continue
                targets.append({"label": text[:160], "anchor": {
                    "kind": "claim", "source_task_id": source_id, "claim_id": claim["claim_id"],
                    "source_revision": source_revision, "target_hash": digest(["claim", text]),
                    "selected_text": text[:1000],
                }})
    except (OSError, ValueError, TypeError, AttributeError):
        pass  # Unreadable generated evidence cannot invalidate the personal file.
    for evidence_kind, path, array_key in (("transcript", task.transcript_path, "segments"),
                                           ("visual", task.visual_index_path, "windows")):
        try:
            payload = json.loads(read_anchor_artifact(source_id, path) or "{}")
            artifact_revision = digest(payload)
            for index, item in enumerate(payload.get(array_key, [])):
                if not isinstance(item, dict):
                    continue
                start, end = item.get("start"), item.get("end")
                if any(isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 for value in (start, end)) or end < start:
                    continue
                text = str(item.get("text") or item.get("summary") or item.get("visual_summary") or item.get("transcript_excerpt") or "")
                window_id = str(item.get("id") or "")
                fingerprint = [evidence_kind, float(start), float(end), text]
                if evidence_kind == "visual":
                    # Window numbering alone cannot prove that the frames survived.
                    grid_hash = _grid_hash(source_id, item.get("grid_path") or "")
                    if not window_id or not grid_hash:
                        continue
                    fingerprint.append(grid_hash)
                elif not text.strip():
                    continue
                anchor = {"kind": evidence_kind, "source_task_id": source_id,
                          "evidence_id": f"task-{source_id}-{evidence_kind}-{window_id if evidence_kind == 'visual' else f'{index:05d}'}",
                          "start": start, "end": end, "target_hash": digest(fingerprint),
                          "source_revision": artifact_revision, "selected_text": text[:1000],
                          "locator": f"{start:g}–{end:g}s"}
                if evidence_kind == "visual":
                    anchor["window_id"] = window_id
                targets.append({"label": f"{anchor['locator']} · {text[:120] or window_id}", "anchor": anchor})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return {"targets": targets}


def resolve_anchor(anchor: dict, targets: list[dict]) -> dict:
    source = str(anchor.get("source_task_id") or "")
    owners = {str(item["anchor"].get("source_task_id") or "") for item in targets}
    related = {owner for owner in owners if _related(source, owner)}
    candidates = [item["anchor"] for item in targets if item["anchor"].get("source_task_id") in related and item["anchor"].get("kind") == anchor.get("kind")
                  and item["anchor"].get("target_hash") == anchor.get("target_hash")]
    identity = "claim_id" if anchor.get("kind") == "claim" else "evidence_id"
    exact = [item for item in candidates if item.get(identity) == anchor.get(identity)
             and item.get("source_task_id") == anchor.get("source_task_id")]
    # Unchanged artifact revision makes its occurrence ID meaningful. Changed
    # revisions require one unique exact match even if an ordinal ID repeats.
    unchanged = exact and exact[0].get("source_revision") == anchor.get("source_revision")
    if len(exact) == 1 and unchanged:
        resolution, selected = "exact", exact[0]
    elif len(candidates) == 1:
        resolution, selected = "migrated", candidates[0]
    else:
        return {"stale": True, "repairable": True, "resolution": "orphaned",
                "reason": "ambiguous_target" if candidates else "target_missing_or_changed"}
    return {"stale": False, "repairable": True, "resolution": resolution,
            "resolved_anchor": selected}


def validate_new_anchor(kind: str, source_id: str, anchor: dict) -> dict:
    if anchor.get("kind") not in KINDS:
        return anchor
    if kind != "task":
        raise ValueError("annotation_anchor_source_invalid")
    # A selection made before regeneration must be reviewed, not silently saved.
    result = resolve_anchor(anchor, annotation_targets(kind, source_id)["targets"])
    if result["resolution"] != "exact":
        raise ValueError("annotation_anchor_stale")
    return normalize_anchor(result["resolved_anchor"])
