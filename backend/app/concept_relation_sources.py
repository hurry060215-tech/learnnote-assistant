"""Read-only full-library/course source capture for local relation candidates."""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3

from . import courses
from .catalog_guard import orphaned_sidecars, validate_catalog_version
from .concept_identity import read_history
from .concept_relations import MAX_ROWS, MAX_TEXT, MAX_CHARACTERS, build_relations
from .concept_relation_snapshot import verify_relation_snapshot
from .course_comparison import is_canonical_evidence, time_bounds
from .course_graph_export import _belongs, _inspect, _task_revision
from .graph_snapshot import digest, encoded, portable_evidence

MAX_SOURCES = 1000
MAX_METADATA = 16_000
MAX_BYTES = 20_000_000
FORMAT = "learnnote.cited-relations"


def _library_sources(db):
    tasks = db.execute("SELECT DISTINCT task_id FROM source_evidence WHERE task_id<>'' LIMIT ?", (MAX_SOURCES + 1,)).fetchall()
    if len(tasks) > MAX_SOURCES:
        raise ValueError("concept_relations_too_large")
    sources = [{"kind": "task", "id": row[0], "title": ""} for row in tasks]
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='library_materials'").fetchone():
        materials = db.execute("SELECT material_id,substr(title,1,501) FROM library_materials WHERE linked_task_id='' AND owns_evidence=1 LIMIT ?", (MAX_SOURCES + 1,)).fetchall()
        sources.extend({"kind": "material", "id": row[0], "title": row[1]} for row in materials)
    if len(sources) > MAX_SOURCES:
        raise ValueError("concept_relations_too_large")
    return sorted(sources, key=lambda row: (row["kind"], row["id"]))


def _source_identity_keys(owner, db):
    keys = [digest(["owner", owner])]
    if owner["kind"] == "material":
        material = db.execute("SELECT sha256 FROM library_materials WHERE material_id=?", (owner["id"],)).fetchone()
        if material and material[0]:
            keys.append(digest(["content", material[0]]))
        return keys
    task = courses.get_task(owner["id"])
    checksum = task.media_integrity.sha256 or task.source_identity.media_sha256
    if checksum:
        keys.append(digest(["content", checksum]))
    keys.append(digest(["origin", courses.task_material_source_uri(task)]))
    return keys


def _identity_components(identities):
    # Shared page origins OR content hashes join transitively. Choosing only a
    # hash would miss an alias of the same page whose media hash is unavailable.
    parents = {}
    def root(key):
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key
    for keys in identities.values():
        for key in keys[1:]:
            a, b = root(keys[0]), root(key)
            parents[max(a, b)] = min(a, b)
    return {owner: root(keys[0]) for owner, keys in identities.items()}


def capture_relations(*, course_id="", revision=None, query="", **filters):
    path = courses.DATA_DIR / "library.sqlite3"
    if path.is_symlink() or orphaned_sidecars(path) or not path.is_file():
        raise ValueError("concept_relation_index_unavailable")
    initial_stat = path.stat()
    with courses.course_read_lock(), closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        validate_catalog_version(db)
        version = db.execute("PRAGMA data_version").fetchone()[0]
        db.execute("BEGIN")
        course = courses.get_course(course_id) if course_id else None
        if course and course["revision"] != revision:
            raise ValueError("course_changed_reload_required")
        history = read_history(course_id) if course else {"schema_version": 1, "course_id": "0" * 32, "events": []}
        sources = courses._evidence_sources(course, read_only=True) if course else _library_sources(db)
        if len(sources) > MAX_SOURCES:
            raise ValueError("concept_relations_too_large")
        evidence, members, candidates, observed, identities = [], [], {}, {}, {}
        for source in sources:
            owner, status, ids, owner_revision = _inspect(source, db, observed)
            member = {"source": {key: source.get(key, "") for key in ("kind", "id", "title")}, "status": status,
                      "canonical_owner": owner, "owner_revision": owner_revision, "eligible": 0, "excluded": 0, "missing": 0}
            members.append(member)
            if not owner:
                continue
            identity_key = (owner["kind"], owner["id"])
            if identity_key not in identities:
                identities[identity_key] = _source_identity_keys(owner, db)
            for key in sorted(ids):
                candidates.setdefault(key, []).append(member)
            if len(candidates) > MAX_ROWS:
                raise ValueError("concept_relations_too_large")
        identities = _identity_components(identities)
        total = 0
        ids = sorted(candidates)
        for offset in range(0, len(ids), 100):
            batch = ids[offset:offset + 100]
            fields = f"evidence_id,schema_version,source_type,substr(title,1,501) AS title,substr(source_uri,1,4097) AS source_uri,substr(locator,1,301) AS locator,task_id,length(text) AS characters,substr(text,1,{MAX_TEXT + 1}) AS text,substr(metadata_json,1,{MAX_METADATA + 1}) AS metadata_json"
            rows = db.execute(f"SELECT {fields} FROM source_evidence WHERE evidence_id IN ({','.join('?' for _ in batch)})", batch)
            found = set()
            for raw in rows:
                item = dict(raw)
                found.add(item["evidence_id"])
                if item.pop("characters") > MAX_TEXT or len(item["metadata_json"]) > MAX_METADATA:
                    raise ValueError("concept_relations_too_large")
                if any(len(item[field]) > limit for field, limit in (("title", 500), ("source_uri", 4096), ("locator", 300), ("evidence_id", 128), ("task_id", 128))):
                    raise ValueError("concept_relation_index_unavailable")
                item["metadata"] = json.loads(item.pop("metadata_json"))
                if not isinstance(item["metadata"], dict):
                    raise ValueError("concept_relation_index_unavailable")
                accepted = []
                for member in candidates[item["evidence_id"]]:
                    owner = member["canonical_owner"]
                    valid = (_belongs(item, owner) and is_canonical_evidence(item)
                             and item["metadata"].get("kind", "") in {"", "transcript", "subtitle", "frame", "visual", "ocr", "material"}
                             and (owner["kind"] != "task" or time_bounds(item) is not None))
                    member["eligible" if valid else "excluded"] += 1
                    if valid:
                        accepted.append(member)
                if not accepted:
                    continue
                member = accepted[0]
                owner = member["canonical_owner"]
                item["course_source"] = {"kind": owner["kind"], "id": owner["id"], "title": item["title"]}
                row = portable_evidence(item, owner)
                row["source_identity"] = identities[(owner["kind"], owner["id"])]
                # Cover the additional identity field in the portable digest.
                row["snapshot_fingerprint"] = digest({key: value for key, value in row.items() if key != "snapshot_fingerprint"})
                evidence.append(row)
                total += len(item["text"])
                if total > MAX_CHARACTERS:
                    raise ValueError("concept_relations_too_large")
            for key in set(batch) - found:
                for member in candidates[key]:
                    member["missing"] += 1
        scope = {"kind": "course", "id": course_id, "revision": revision, "title": course["title"]} if course else {"kind": "library"}
        evidence.sort(key=lambda row: row["evidence_id"])
        graph = build_relations(evidence, history, query=query, **filters)
        snapshot = {"format": FORMAT, "schema_version": 1, "scope": scope, "members": members, "evidence": evidence,
                    "history": history, "graph": graph, "provenance": "Local indexed sources only. Digests prove internal consistency, not source authenticity or truth. Text and titles are retained; URLs and metadata use the existing graph export redaction policy."}
        snapshot["digest"] = digest(snapshot)
        if len(encoded(snapshot)) > MAX_BYTES:
            raise ValueError("concept_relations_too_large")
        verify_relation_snapshot(snapshot)
        db.rollback()
        try:
            stable = all(_task_revision(courses.get_task(key)) == value for key, value in observed.items())
        except FileNotFoundError:
            stable = False
        if course and (courses.get_course(course_id) != course or read_history(course_id) != history or courses._evidence_sources(course, read_only=True) != sources):
            stable = False
        final_stat = path.stat()
        if not stable or version != db.execute("PRAGMA data_version").fetchone()[0] or (initial_stat.st_dev, initial_stat.st_ino) != (final_stat.st_dev, final_stat.st_ino):
            raise ValueError("concept_relations_changed_reload_required")
        return snapshot
