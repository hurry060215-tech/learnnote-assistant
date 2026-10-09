"""Local, user-authored keyword groups; never a claim of semantic equivalence.

The evidence index is disposable. These versioned choices and their previous
snapshots are not: missing/changed citations stay unresolved until reviewed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading

from .config import DATA_DIR
from .storage import atomic_write_text

_lock = threading.RLock()
UNASSIGNED = "unassigned"
MAX_EVENTS = 1000
MAX_HISTORY_BYTES = 20_000_000


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evidence_fingerprint(item: dict) -> str:
    anchor = {key: (item.get("metadata") or {}).get(key) for key in ("start", "end", "window_id", "frame_timestamp", "page", "page_index", "material_id")}
    return _digest({**{key: item.get(key, "") for key in ("evidence_id", "source_type", "source_uri", "task_id", "locator", "text")}, "anchor": anchor})


def _path(course_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", course_id):
        raise ValueError("invalid_course_id")
    return DATA_DIR / "concept-identities" / f"{course_id}.json"


def validate_history(value: dict, course_id: str) -> dict:
    try:
        if set(value) != {"schema_version", "course_id", "events"} or value["schema_version"] != 1 or value["course_id"] != course_id:
            raise ValueError
        events = value["events"]
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise ValueError
        seen = set()
        for revision, event in enumerate(events):
            if set(event) != {"id", "request", "references"} or not re.fullmatch(r"[a-f0-9]{32}", event["id"]) or event["id"] in seen:
                raise ValueError
            seen.add(event["id"])
            request = event["request"]
            if set(request) != {"action", "term", "label", "evidence_ids", "group_ids", "revision", "course_revision", "scope_revision"}:
                raise ValueError
            if request["action"] not in {"split", "merge"} or not isinstance(request["term"], str) or not 1 <= len(request["term"]) <= 200 or request["term"] != request["term"].strip().casefold():
                raise ValueError
            if not isinstance(request["label"], str) or not request["label"].strip() or len(request["label"]) > 120:
                raise ValueError
            if any(type(request[key]) is not int or request[key] < 0 for key in ("revision", "course_revision")) or not re.fullmatch(r"[a-f0-9]{64}", request["scope_revision"]):
                raise ValueError
            if request["revision"] != revision or request["course_revision"] < 1:
                raise ValueError
            for key in ("evidence_ids", "group_ids"):
                ids = request[key]
                if not isinstance(ids, list) or len(ids) > 1000 or len(set(ids)) != len(ids) or any(not isinstance(i, str) or not 1 <= len(i) <= 128 for i in ids):
                    raise ValueError
            refs = event["references"]
            if not isinstance(refs, dict) or not 1 <= len(refs) <= 1000 or any(not isinstance(key, str) or not 1 <= len(key) <= 128 or not re.fullmatch(r"[a-f0-9]{64}", fingerprint) for key, fingerprint in refs.items()):
                raise ValueError
            if request["action"] == "split":
                if request["group_ids"] or set(request["evidence_ids"]) != set(refs):
                    raise ValueError
            elif request["evidence_ids"] or len(request["group_ids"]) < 2:
                raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("concept_history_invalid") from exc
    return value


def read_history(course_id: str) -> dict:
    path = _path(course_id)
    try:
        # Bind the type, advertised size and actual bytes to one descriptor.
        # Replacement/growth after fstat cannot bypass the bounded read.
        with path.open("rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_HISTORY_BYTES:
                raise ValueError
            raw = handle.read(MAX_HISTORY_BYTES + 1)
        if len(raw) > MAX_HISTORY_BYTES:
            raise ValueError
        return validate_history(json.loads(raw.decode("utf-8")), course_id)
    except FileNotFoundError:
        return {"schema_version": 1, "course_id": course_id, "events": []}
    except (ValueError, UnicodeError) as exc:
        # Never reset damaged user choices or silently call them unassigned.
        raise ValueError("concept_history_invalid") from exc


def _save(previous: dict, current: dict) -> None:
    # No formatting newlines: the shared text writer uses platform newlines,
    # so compact JSON keeps the byte cap exact on Windows as well as Linux.
    encoded = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode()) > MAX_HISTORY_BYTES or len(current["events"]) > MAX_EVENTS:
        raise ValueError("concept_history_limit")
    path = _path(current["course_id"])
    if path.exists():
        backup = path.parent / "history" / current["course_id"] / f"{len(previous['events']):04d}-{_digest(previous)}.json"
        if not backup.exists():
            atomic_write_text(backup, json.dumps(previous, ensure_ascii=False, separators=(",", ":")))
    atomic_write_text(path, encoded)


def assignments(history: dict, term: str) -> dict:
    result = {}
    for event in history["events"]:
        if event["request"]["term"] == term:
            for evidence_id, fingerprint in event["references"].items():
                result[evidence_id] = {"id": event["id"], "label": event["request"]["label"], "fingerprint": fingerprint}
    return result


def term_scope(evidence: list[dict], term: str) -> dict:
    return {item["evidence_id"]: evidence_fingerprint(item) for item in evidence if term in str(item.get("text") or "").casefold()}


def identity_groups(history: dict, evidence: list[dict], term: str) -> dict:
    scope = term_scope(evidence, term)
    chosen = assignments(history, term)
    groups = {}
    for evidence_id in dict.fromkeys([*scope, *chosen]):
        selected = chosen.get(evidence_id)
        group_id = selected["id"] if selected else UNASSIGNED
        group = groups.setdefault(group_id, {"id": group_id, "label": selected["label"] if selected else "未区分含义", "evidence_ids": [], "unresolved_ids": []})
        resolved = evidence_id in scope and (not selected or selected["fingerprint"] == scope[evidence_id])
        group["evidence_ids" if resolved else "unresolved_ids"].append(evidence_id)
    return {"term": term, "scope_revision": _digest(scope), "groups": list(groups.values())}


def identity_key(item: dict, chosen: dict) -> str | None:
    selected = chosen.get(item["evidence_id"])
    if selected and selected["fingerprint"] != evidence_fingerprint(item):
        return None
    return selected["id"] if selected else UNASSIGNED


def edit_identity(course_id: str, course_revision: int, evidence: list[dict], request_id: str, request: dict) -> dict:
    with _lock:
        history = read_history(course_id)
        previous = next((event for event in history["events"] if event["id"] == request_id), None)
        if previous:
            if previous["request"] != request:
                raise ValueError("concept_request_conflict")
            return {"revision": len(history["events"]), "replayed": True}
        if len(history["events"]) != request["revision"] or course_revision != request["course_revision"]:
            raise ValueError("concept_changed_reload_required")
        term = request["term"]
        view = identity_groups(history, evidence, term)
        if view["scope_revision"] != request["scope_revision"]:
            raise ValueError("concept_evidence_changed_reload_required")
        scope = term_scope(evidence, term)
        if request["action"] == "split":
            ids = request["evidence_ids"]
            if request["group_ids"] or not ids or any(key not in scope for key in ids):
                raise ValueError("concept_evidence_outside_scope")
        else:
            selected = [group for group in view["groups"] if group["id"] in request["group_ids"]]
            if request["evidence_ids"] or len(selected) < 2 or len(selected) != len(request["group_ids"]):
                raise ValueError("concept_merge_groups_required")
            if any(group["unresolved_ids"] for group in selected):
                raise ValueError("concept_evidence_unresolved")
            ids = [key for group in selected for key in group["evidence_ids"]]
        if len(ids) > 1000 or len(history["events"]) >= MAX_EVENTS:
            raise ValueError("concept_history_limit")
        event = {"id": request_id, "request": request, "references": {key: scope[key] for key in ids}}
        updated = {**history, "events": [*history["events"], event]}
        validate_history(updated, course_id)
        _save(history, updated)
        return {"revision": len(updated["events"]), "replayed": False}


def restore_history(course_id: str, backup: dict, revision: int) -> dict:
    incoming = validate_history(backup, course_id)
    with _lock:
        current = read_history(course_id)
        # An older prefix is an idempotent no-op, never a rollback of later edits.
        common = min(len(current["events"]), len(incoming["events"]))
        if current["events"][:common] != incoming["events"][:common]:
            raise ValueError("concept_backup_conflict")
        if len(incoming["events"]) <= len(current["events"]):
            return {"revision": len(current["events"]), "restored": 0}
        if revision != len(current["events"]):
            raise ValueError("concept_changed_reload_required")
        _save(current, incoming)
        return {"revision": len(incoming["events"]), "restored": len(incoming["events"]) - len(current["events"])}
