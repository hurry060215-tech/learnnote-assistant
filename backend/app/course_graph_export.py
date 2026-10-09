"""Capture a portable graph from current local sources; never repair the index."""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3

from . import courses
from .concept_identity import read_history
from .course_comparison import is_canonical_evidence, normalize_filters
from .graph_snapshot import MAX_BYTES, MAX_EVIDENCE, assemble_snapshot, digest, encoded, portable_evidence, safe_uri, verify_snapshot


def _task_ids(db, task_id):
    rows = db.execute("SELECT evidence_id FROM source_evidence WHERE task_id=? ORDER BY evidence_id LIMIT ?", (task_id, MAX_EVIDENCE + 1)).fetchall()
    if len(rows) > MAX_EVIDENCE:
        raise ValueError("graph_snapshot_too_large")
    return {row[0] for row in rows}


def _task_revision(task):
    # Public graph provenance must not fingerprint model options, private
    # connections, headers or credentials. Only source/eligibility state matters.
    identity = task.source_identity
    return digest({"id": task.id, "source_type": task.source_type, "mode": task.mode,
                   "source_uri": courses.task_material_source_uri(task), "status": task.status,
                   "source_identity": {key: getattr(identity, key) for key in ("platform", "platform_id", "resource_fingerprint", "media_sha256")},
                   "identity_uri": safe_uri(identity.page_url), "media_sha256": task.media_integrity.sha256,
                   "summary_source": task.summary_source, "review_required": bool(task.summary_diagnostics.get("review_required"))})


def _observed_task(task_id, observed):
    task = courses.get_task(task_id)
    revision = _task_revision(task)
    if observed.setdefault(task_id, revision) != revision:
        raise ValueError("course_changed_reload_required")
    return task


def _inspect(source: dict, db, observed_tasks: dict) -> tuple[dict | None, str, set[str], str | None]:
    """Recheck aliases against the live owner, not cached registration IDs."""
    if source["kind"] == "url":
        return None, "unresolved_url", set(), None
    try:
        if source["kind"] == "material":
            row = db.execute("SELECT * FROM library_materials WHERE material_id=?", (source["id"],)).fetchone()
            if row is None:
                return None, "missing", set(), None
            material = dict(row)
            task_id = material.get("linked_task_id")
            if task_id:
                task = _observed_task(task_id, observed_tasks)
                if material.get("source_type") != "video" or material.get("owns_evidence") != 0 or material.get("source_uri") != courses.task_material_source_uri(task):
                    return None, "excluded", set(), None
            else:
                if not material.get("owns_evidence") or material.get("source_uri") != f"local://materials/{source['id']}":
                    return None, "excluded", set(), None
                if len(material["evidence_ids_json"]) > MAX_BYTES:
                    raise ValueError("graph_snapshot_too_large")
                ids = json.loads(material["evidence_ids_json"])
                if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
                    raise ValueError("graph_snapshot_invalid")
                return {"kind": "material", "id": source["id"]}, "ready", set(ids), digest(material)
        else:
            task_id = source["id"]
            task = _observed_task(task_id, observed_tasks)
        if task.id != task_id or task.summary_source == "transcript-draft" or task.summary_diagnostics.get("review_required"):
            return None, "excluded", set(), None
        return {"kind": "task", "id": task_id}, "alias" if source["kind"] == "material" else "ready", _task_ids(db, task_id), observed_tasks[task_id]
    except FileNotFoundError:
        return None, "missing", set(), None


def _belongs(item: dict, owner: dict) -> bool:
    if owner["kind"] == "task":
        return item.get("task_id") == owner["id"]
    return not item.get("task_id") and (item.get("metadata") or {}).get("material_id") == owner["id"] and item.get("source_uri") == f"local://materials/{owner['id']}"


def capture_graph_snapshot(course_id: str, query: str, revision: int, **filters) -> dict:
    filters = normalize_filters(**filters)
    with courses._lock:
        course = courses.get_course(course_id)
        if course["revision"] != revision:
            raise ValueError("course_changed_reload_required")
        history = read_history(course_id)
        # The ordinary library getters may initialize schemas. This path must
        # never create or repair a disposable catalog as a side effect of export.
        with closing(sqlite3.connect((courses.DATA_DIR / "library.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            return _capture(course, history, query, filters, db)


def _capture(course: dict, history: dict, query: str, filters: dict, db) -> dict:
    course_id = course["id"]
    resolved = courses._evidence_sources(course, read_only=True)
    sources, candidates, observed_tasks = [], {}, {}
    for position, original in enumerate(course["sources"]):
        reference = {key: original.get(key, "") for key in ("kind", "id", "url", "title")}
        reference["url"] = safe_uri(reference["url"])
        source = resolved[position]
        owner, status, ids, owner_revision = _inspect(source, db, observed_tasks)
        entry = {"position": position, "reference": reference,
                 "resolved_source": {key: source[key] for key in ("kind", "id", "title")} if source["kind"] != "url" else None,
                 "canonical_owner": owner, "owner_revision": owner_revision, "status": status, "evidence_ids": [], "missing_evidence_ids": [], "excluded_evidence_ids": [],
                 "reference_fingerprint": digest(original), "redacted_fields": ["url"] if original.get("url", "") != reference["url"] else []}
        sources.append(entry)
        for evidence_id in sorted(ids):
            candidates.setdefault(evidence_id, []).append(entry)
        if len(candidates) > MAX_EVIDENCE:
            raise ValueError("graph_snapshot_too_large")
    evidence, found, size = [], set(), 0
    ids = list(candidates)
    for start in range(0, len(ids), 10):
        batch = ids[start:start + 10]
        placeholders = ",".join("?" for _ in batch)
        rows = db.execute(f"SELECT * FROM source_evidence WHERE evidence_id IN ({placeholders})", batch).fetchall()
        by_id = {row["evidence_id"]: row for row in rows}
        for key in batch:
            if key not in by_id:
                continue
            item = dict(by_id[key])
            item["metadata"] = json.loads(item.pop("metadata_json"))
            if not isinstance(item["metadata"], dict):
                raise ValueError("graph_snapshot_invalid")
            key = item["evidence_id"]
            if key not in candidates or key in found:
                continue
            found.add(key)
            accepted = []
            for entry in candidates[key]:
                allowed = is_canonical_evidence(item) and _belongs(item, entry["canonical_owner"])
                entry["evidence_ids" if allowed else "excluded_evidence_ids"].append(key)
                if allowed:
                    accepted.append(entry)
            if accepted:
                entry = accepted[0]
                record = portable_evidence({**item, "course_source": entry["resolved_source"]}, entry["canonical_owner"])
                size += len(encoded(record))
                if size > MAX_BYTES:
                    raise ValueError("graph_snapshot_too_large")
                evidence.append(record)
    for key in candidates.keys() - found:
        for entry in candidates[key]:
            entry["missing_evidence_ids"].append(key)
    for entry in sources:
        for key in ("evidence_ids", "missing_evidence_ids", "excluded_evidence_ids"):
            entry[key].sort()
        if entry["status"] in {"ready", "alias"} and not entry["evidence_ids"]:
            entry["status"] = "unindexed"
    # All catalog facts have been captured consistently. Release the read lock
    # before bounded graph work so a concurrent index writer need not wait for it.
    db.rollback()
    portable_course = {key: course[key] for key in ("schema_version", "id", "title", "paused", "revision")}
    portable_course["sources"] = [entry["reference"] for entry in sources]
    snapshot = assemble_snapshot(portable_course, sources, evidence, history, query, filters)
    # Do not offer a download that this version could not reconstruct itself.
    verify_snapshot(snapshot)
    # SQLite reads share one transaction; task manifests are separate files.
    # Recheck only the task versions used in this capture, after graph assembly.
    try:
        stable_tasks = all(_task_revision(courses.get_task(key)) == revision for key, revision in observed_tasks.items())
    except FileNotFoundError:
        stable_tasks = False
    if not stable_tasks or courses.get_course(course_id) != course or read_history(course_id) != history or courses._evidence_sources(course, read_only=True) != resolved:
        raise ValueError("course_changed_reload_required")
    return snapshot
