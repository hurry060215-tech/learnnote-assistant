"""Narrow catalog projection for explicit desktop data-directory moves.

SQLite is opened only on private copies of the complete stopped snapshot family.
The only DML is UPDATE of enumerated path slots. Every other SQL value, table,
index, schema definition, and row count must survive exactly. No backend imports,
model calls, source connections, or automatic schema upgrades are involved.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile

from .data_migration_paths import JsonDocument, ReferenceMappingError, _digest, _path_values


CATALOG_SCHEMA_SQL = """
CREATE TABLE library_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE library_tasks (
  task_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  source TEXT NOT NULL,
  source_type TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  checkpoint TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  note_path TEXT NOT NULL,
  media_path TEXT NOT NULL,
  fingerprint TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL
);
CREATE TABLE library_materials (
  material_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL,
  title TEXT NOT NULL,
  filename TEXT NOT NULL,
  source_type TEXT NOT NULL,
  content_type TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  byte_size INTEGER NOT NULL,
  status TEXT NOT NULL,
  linked_task_id TEXT NOT NULL,
  anchor_count INTEGER NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  owns_evidence INTEGER NOT NULL,
  stored_path TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX library_materials_updated_idx ON library_materials(updated_at DESC);
CREATE INDEX library_materials_task_idx ON library_materials(linked_task_id);
"""
EVIDENCE_SCHEMA_SQL = """
CREATE TABLE source_evidence (
  evidence_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL,
  source_type TEXT NOT NULL,
  title TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  locator TEXT NOT NULL,
  text TEXT NOT NULL,
  task_id TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX source_evidence_task_idx ON source_evidence(task_id);
"""
PROJECTION_REVISION_SQL = """
CREATE TABLE task_projection_revisions (
  task_id TEXT PRIMARY KEY,
  signature TEXT NOT NULL
);
"""
_FTS = {
    "library_tasks_fts": "CREATE VIRTUAL TABLE library_tasks_fts USING fts5(task_id UNINDEXED, title, source, content)",
    "source_evidence_fts": "CREATE VIRTUAL TABLE source_evidence_fts USING fts5(evidence_id UNINDEXED, title, source_uri, locator, text)",
}
_FAMILY = ("library.sqlite3", "library.sqlite3-wal", "library.sqlite3-shm", "library.sqlite3-journal")
_MATERIAL_COLUMNS = "material_id schema_version title filename source_type content_type source_uri sha256 byte_size status linked_task_id anchor_count evidence_ids_json owns_evidence stored_path metadata_json created_at updated_at".split()
_TASK_COLUMNS = "task_id title source source_type mode status checkpoint created_at updated_at note_path media_path fingerprint content".split()


def _normalize(sql):
    if sql is None:
        return None
    text = " ".join(str(sql).split()).casefold()
    return text.replace("( ", "(").replace(" )", ")")


def _schema(db):
    return {row[1]: (row[0], row[2], _normalize(row[3])) for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name")}


def _validate_schema(db):
    if db.execute("PRAGMA user_version").fetchone()[0] != 0 or db.execute("PRAGMA application_id").fetchone()[0] != 0:
        raise ReferenceMappingError("unsupported_catalog_user_version")
    actual = _schema(db)
    if any(value[0] in {"view", "trigger"} for value in actual.values()):
        raise ReferenceMappingError("unsupported_catalog_schema")
    with closing(sqlite3.connect(":memory:")) as trusted:
        trusted.executescript(CATALOG_SCHEMA_SQL)
        if "source_evidence" in actual:
            trusted.executescript(EVIDENCE_SCHEMA_SQL)
        if "task_projection_revisions" in actual:
            trusted.executescript(PROJECTION_REVISION_SQL)
        for name, sql in _FTS.items():
            if name in actual:
                if name == "source_evidence_fts" and "source_evidence" not in actual:
                    raise ReferenceMappingError("unsupported_catalog_schema")
                trusted.execute(sql)
        expected = _schema(trusted)
        if actual != expected:
            raise ReferenceMappingError("unsupported_catalog_schema")
    version = db.execute("SELECT value FROM library_meta WHERE key='schema_version'").fetchone()
    if version is None or version[0] != "3":
        raise ReferenceMappingError("unsupported_catalog_schema_version")
    return actual


def _value(item):
    if item is None:
        return ["null", None]
    if type(item) is int:
        return ["int", str(item)]
    if type(item) is float:
        return ["float", item.hex()]
    if isinstance(item, bytes):
        return ["blob", item.hex()]
    if isinstance(item, str):
        return ["text", item]
    raise ReferenceMappingError("unsupported_catalog_value")


def _serialized_row(row):
    return json.dumps([_value(item) for item in row], ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _snapshot(db):
    result = {}
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        # Names have already matched the trusted schema. Quote regardless.
        columns = tuple(row[1] for row in db.execute(f'PRAGMA table_info("{name}")'))
        rows = [tuple(row) for row in db.execute(f'SELECT * FROM "{name}"')]
        result[name] = (columns, rows)
    return result


def _proof(snapshot, *, mask_paths=False):
    result = {}
    for name, (columns, rows) in snapshot.items():
        encoded = []
        for row in rows:
            values = list(row)
            if mask_paths and name == "library_tasks":
                for field in ("note_path", "media_path"):
                    values[columns.index(field)] = "__MIGRATION_REFERENCE__"
            if mask_paths and name == "library_materials":
                values[columns.index("stored_path")] = "__MIGRATION_REFERENCE__"
                index = columns.index("metadata_json")
                document = JsonDocument(values[index].encode("utf-8"))
                if isinstance(document.value, dict) and isinstance(document.value.get("ocr_path"), str):
                    values[index] = document.replace({("ocr_path",): "__MIGRATION_REFERENCE__"}).decode("utf-8")
            encoded.append(_serialized_row(values))
        payload = b"\n".join(sorted(encoded))
        result[name] = {"row_count": len(rows), "values_sha256": _digest(payload)}
    return result


def _safe_filename(name):
    # Mirror the producer's canonicalization without importing library/config or
    # probing a user path. Reject noncanonical names rather than repairing them.
    if not isinstance(name, str) or not name or PurePosixPath(name).name != name:
        return False
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._") or "material"
    suffix = PurePosixPath(normalized).suffix
    if len(suffix) > 20:
        suffix = ""
    stem = normalized[:-len(suffix)] if suffix else normalized
    stem = stem[:180 - len(suffix)]
    while len(stem.encode("utf-8")) > 200 - len(suffix.encode("utf-8")):
        stem = stem[:-1]
    normalized = (stem.rstrip(" ._") or "material") + suffix
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if PurePosixPath(normalized).stem.upper() in reserved:
        normalized = "_" + normalized
    return name == normalized


def _map_material_path(context, value, key, basename, *, location):
    if not isinstance(value, str) or not value:
        raise ReferenceMappingError("missing_material_reference", location)
    relative = context.relative_reference(value)
    expected = ("materials", key, basename)
    if relative != expected:
        raise ReferenceMappingError("material_ownership_mismatch", location)
    context.read("/".join(expected))
    return str(context.destination.joinpath(*expected))


def _catalog_edits(context, before):
    updates = []
    if "source_evidence" in before:
        evidence_columns, evidence_rows = before["source_evidence"]
        for row in evidence_rows:
            metadata = row[evidence_columns.index("metadata_json")]
            if not isinstance(metadata, str):
                raise ReferenceMappingError("invalid_evidence_metadata")
            document = JsonDocument(metadata.encode("utf-8"))
            if not isinstance(document.value, dict) or any(_path_values(document.value)):
                raise ReferenceMappingError("unsupported_evidence_reference")
    columns, rows = before["library_tasks"]
    for values in sorted(rows, key=lambda item: item[0]):
        row = dict(zip(columns, values))
        if any(not isinstance(value, str) for value in values):
            raise ReferenceMappingError("invalid_catalog_task_row")
        task_id = row["task_id"]
        if task_id not in context.tasks:
            raise ReferenceMappingError("catalog_task_manifest_missing", task_id)
        task = context.tasks[task_id]
        for field in ("note_path", "media_path"):
            value = row[field]
            permitted = [task.get(field, "")]
            if field == "media_path":
                permitted.append(task.get("source_media_path", ""))
            if value and value not in permitted:
                raise ReferenceMappingError("catalog_task_pointer_mismatch", task_id)
            changed = context.map_task(value, task_id, field, f"library.sqlite3#{task_id}/{field}")
            if changed != value:
                edit = {"file": "library.sqlite3", "table": "library_tasks", "key": {"task_id": task_id},
                        "column": field, "before": value, "after": changed}
                updates.append(edit)
                context.changes.append(edit)
    columns, rows = before["library_materials"]
    integers = {"schema_version", "byte_size", "anchor_count", "owns_evidence"}
    for values in sorted(rows, key=lambda item: item[0]):
        row = dict(zip(columns, values))
        if any(type(row[key]) is not (int if key in integers else str) for key in columns):
            raise ReferenceMappingError("invalid_catalog_material_row")
        key, name = row["material_id"], row["filename"]
        if not re.fullmatch(r"[a-f0-9]{32}", key) or row["schema_version"] != 1 or row["owns_evidence"] not in {0, 1}:
            raise ReferenceMappingError("invalid_material_identity", key)
        document = JsonDocument(row["metadata_json"].encode("utf-8"))
        metadata = document.value
        if not isinstance(metadata, dict):
            raise ReferenceMappingError("invalid_material_metadata", key)
        for pointer, value in _path_values(metadata):
            if pointer != ("ocr_path",) or not isinstance(value, str):
                raise ReferenceMappingError("unsupported_material_reference", key)
        if not row["stored_path"]:
            # Existing-task registration deliberately owns no separate original.
            if (row["source_type"] != "video" or row["owns_evidence"] != 0 or row["linked_task_id"] not in context.tasks
                    or metadata.get("registration") != "existing_task" or metadata.get("ocr_path")):
                raise ReferenceMappingError("material_original_unproven", key)
            continue
        if (not _safe_filename(name) or row["source_type"] not in {"text", "markdown", "webpage", "pdf"}
                or row["linked_task_id"] or row["source_uri"] != f"local://materials/{key}"):
            raise ReferenceMappingError("material_original_unproven", key)
        original = context.read(f"materials/{key}/{name}")
        if len(original) != row["byte_size"] or _digest(original) != row["sha256"]:
            raise ReferenceMappingError("material_original_changed", key)
        changed = _map_material_path(context, row["stored_path"], key, name, location=key + "/stored_path")
        if changed != row["stored_path"]:
            edit = {"file": "library.sqlite3", "table": "library_materials", "key": {"material_id": key},
                    "column": "stored_path", "before": row["stored_path"], "after": changed}
            updates.append(edit)
            context.changes.append(edit)
        if metadata.get("ocr_path"):
            value = metadata["ocr_path"]
            relative = context.relative_reference(value)
            if not relative or len(relative) != 3 or not re.fullmatch(r"ocr(?:-[a-f0-9]{64})?\.json", relative[-1]):
                raise ReferenceMappingError("invalid_material_ocr_basename", key)
            changed = _map_material_path(context, value, key, relative[-1], location=key + "/ocr_path")
            if changed != value:
                rewritten = document.replace({("ocr_path",): changed}).decode("utf-8")
                updates.append({"file": "library.sqlite3", "table": "library_materials", "key": {"material_id": key},
                                "column": "metadata_json", "before": row["metadata_json"], "after": rewritten})
                context.changes.append({"file": "library.sqlite3", "table": "library_materials", "key": {"material_id": key},
                                        "column": "metadata_json", "json_pointer": "/ocr_path", "before": value, "after": changed})
    return updates


def _updated_snapshot(before, edits):
    expected = {name: (columns, list(rows)) for name, (columns, rows) in before.items()}
    for edit in edits:
        columns, rows = expected[edit["table"]]
        key, identifier = next(iter(edit["key"].items()))
        found = 0
        for index, row in enumerate(rows):
            if row[columns.index(key)] == identifier:
                values = list(row)
                if values[columns.index(edit["column"])] != edit["before"]:
                    raise ReferenceMappingError("catalog_row_changed")
                values[columns.index(edit["column"])] = edit["after"]
                rows[index] = tuple(values)
                found += 1
        if found != 1:
            raise ReferenceMappingError("catalog_row_changed")
    return expected


def plan_catalog(context):
    # Even a disposable copy can retain an absolute super-journal reference.
    # SQLite hot-journal recovery may follow/delete that external file, so no
    # rollback journal is ever opened here. Only WAL consolidation is approved.
    if "library.sqlite3-journal" in context.inventory:
        raise ReferenceMappingError("catalog_rollback_recovery_required")
    family = [name for name in _FAMILY if name in context.inventory]
    if not family:
        if any(name.startswith("materials/") for name in context.inventory):
            raise ReferenceMappingError("catalog_original_missing")
        return {}, {}, []
    if "library.sqlite3" not in family or context.inventory["library.sqlite3"]["size"] == 0:
        raise ReferenceMappingError("catalog_family_incomplete")
    original_hashes = {name: context.inventory[name]["sha256"] for name in family}
    try:
        with tempfile.TemporaryDirectory(prefix="learnnote-catalog-mapping-") as temporary:
            directory = Path(temporary)
            for name in family:
                (directory / name).write_bytes(context.read(name))
            path = directory / "library.sqlite3"
            with closing(sqlite3.connect(path, timeout=0)) as db:
                db.execute("PRAGMA trusted_schema=OFF")
                schema = _validate_schema(db)
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ReferenceMappingError("catalog_integrity_failed")
                before = _snapshot(db)
                edits = _catalog_edits(context, before)
                expected = _updated_snapshot(before, edits)
                db.execute("BEGIN IMMEDIATE")
                for edit in edits:
                    key, identifier = next(iter(edit["key"].items()))
                    cursor = db.execute(f'UPDATE "{edit["table"]}" SET "{edit["column"]}"=? WHERE "{key}"=? AND "{edit["column"]}"=?',
                                        (edit["after"], identifier, edit["before"]))
                    if cursor.rowcount != 1:
                        raise ReferenceMappingError("catalog_row_changed")
                after = _snapshot(db)
                if _proof(after) != _proof(expected) or _proof(before, mask_paths=True) != _proof(after, mask_paths=True) or _schema(db) != schema:
                    raise ReferenceMappingError("catalog_nonpath_values_changed")
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ReferenceMappingError("catalog_integrity_failed")
                db.commit()
                checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint and checkpoint[0] != 0:
                    raise ReferenceMappingError("catalog_checkpoint_failed")
                if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                    raise ReferenceMappingError("catalog_checkpoint_failed")
            # Reopen the finished, sidecar-free image to verify persisted values.
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
                db.execute("PRAGMA trusted_schema=OFF")
                if (_validate_schema(db) != schema or _proof(_snapshot(db)) != _proof(expected)
                        or db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]):
                    raise ReferenceMappingError("catalog_persisted_validation_failed")
            output = path.read_bytes()
    except sqlite3.Error as exc:
        raise ReferenceMappingError("catalog_validation_failed") from exc
    removed = [name for name in family if name != "library.sqlite3"]
    # An untouched DELETE-mode DB remains byte-for-byte unchanged if SQLite did
    # not need recovery; a WAL family is intentionally consolidated in staging.
    outputs = {}
    if _digest(output) != context.inventory["library.sqlite3"]["sha256"]:
        outputs["library.sqlite3"] = output
        context.files.append({"path": "library.sqlite3", "original_sha256": original_hashes["library.sqlite3"],
                              "result_sha256": _digest(output), "result_size": len(output), "operation": "replace"})
    for name in removed:
        context.files.append({"path": name, "original_sha256": original_hashes[name], "result_sha256": None,
                              "result_size": 0, "operation": "remove_consolidated_sidecar"})
    proof = {"integrity_before": "ok", "integrity_after": "ok", "user_version": 0,
             "original_family_sha256": original_hashes, "result_sha256": _digest(output),
             "tables_before": _proof(before), "tables_after": _proof(after),
             "nonpath_before": _proof(before, mask_paths=True), "nonpath_after": _proof(after, mask_paths=True)}
    return proof, outputs, removed
