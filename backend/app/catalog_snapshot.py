"""Strict, read-only validation of an explicitly selected catalog snapshot."""
from __future__ import annotations

from contextlib import closing
import json
import hashlib
from pathlib import Path
import re
import sqlite3

from . import library
from .pdf_ocr_cache import read_ocr_cache

MATERIAL_COLUMNS = tuple("material_id schema_version title filename source_type content_type source_uri sha256 byte_size status linked_task_id anchor_count evidence_ids_json owns_evidence stored_path metadata_json created_at updated_at".split())
EVIDENCE_COLUMNS = tuple("evidence_id schema_version source_type title source_uri locator text task_id metadata_json created_at".split())
MAX_MATERIALS = 5000


def trusted_schema() -> dict[str, str]:
    with closing(sqlite3.connect(":memory:")) as db:
        library._ensure_schema(db)
        library.ensure_evidence_schema(db)
        return {name: sql for name, sql in db.execute("SELECT name,sql FROM sqlite_master WHERE name IN ('library_meta','library_materials','source_evidence','source_evidence_fts') OR name GLOB 'source_evidence_fts_*'")}


def validate_schema(db: sqlite3.Connection, code: str) -> None:
    if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
        raise ValueError(code)
    for name, expected in trusted_schema().items():
        actual = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if actual and " ".join(str(actual[0]).split()).casefold() != " ".join(expected.split()).casefold():
            raise ValueError(code)


def read_snapshot(path: Path) -> tuple[list[dict], dict[str, dict], str]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > library.LIBRARY_BACKUP_MAX_BYTES:
        raise ValueError("catalog_snapshot_invalid")
    digest = library._file_sha256(path)
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("catalog_snapshot_invalid")
            version = db.execute("SELECT value FROM library_meta WHERE key='schema_version'").fetchone()
            if not version or version[0] != str(library.LIBRARY_SCHEMA_VERSION):
                raise ValueError("catalog_snapshot_schema_invalid")
            validate_schema(db, "catalog_snapshot_schema_invalid")
            for table, columns in (("library_materials", MATERIAL_COLUMNS), ("source_evidence", EVIDENCE_COLUMNS)):
                found = tuple(row[1] for row in db.execute(f"PRAGMA table_info({table})"))
                if found != columns and not (table == "source_evidence" and not found):
                    raise ValueError("catalog_snapshot_schema_invalid")
            rows = [dict(row) for row in db.execute(f"SELECT * FROM library_materials LIMIT {MAX_MATERIALS + 1}")]
            evidence = [dict(row) for row in db.execute("SELECT * FROM source_evidence LIMIT 100001")] if found else []
            if len(rows) > MAX_MATERIALS or len(evidence) > 100000:
                raise ValueError("catalog_snapshot_too_large")
            for items, columns, integers in ((rows, MATERIAL_COLUMNS, {"schema_version", "byte_size", "anchor_count", "owns_evidence"}), (evidence, EVIDENCE_COLUMNS, {"schema_version"})):
                if any(type(row[k]) is not (int if k in integers else str) for row in items for k in columns):
                    raise ValueError("catalog_snapshot_metadata_invalid")
            if any(len(row["material_id"]) > 128 or len(row["title"]) > 500 for row in rows):
                raise ValueError("catalog_snapshot_metadata_invalid")
            return rows, {row["evidence_id"]: row for row in evidence}, digest
    except sqlite3.Error as exc:
        raise ValueError("catalog_snapshot_invalid") from exc


def safe_source(root: Path, material_id: str, filename: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", material_id) or filename != library._safe_material_filename(filename):
        raise ValueError("catalog_identity_invalid")
    base = root / "materials"
    folder = base / material_id
    path = folder / filename
    if any(p.is_symlink() for p in (base, folder, path)) or path.resolve().parent != folder or folder.resolve().parent != base:
        raise ValueError("catalog_source_path_unsafe")
    if not path.is_file():
        raise ValueError("catalog_original_missing")
    if path.stat().st_size > library.MATERIAL_IMPORT_MAX_BYTES:
        raise ValueError("catalog_source_too_large")
    return path


def validate_material(root: Path, row: dict, evidence: dict[str, dict]) -> tuple[dict, list[dict]]:
    integers = {"schema_version", "byte_size", "anchor_count", "owns_evidence"}
    if any(type(row[key]) is not (int if key in integers else str) for key in MATERIAL_COLUMNS):
        raise ValueError("catalog_metadata_invalid")
    if row["schema_version"] != 1 or row["source_type"] not in {"text", "markdown", "webpage", "pdf"} or row["linked_task_id"]:
        raise ValueError("catalog_document_required")
    if row["owns_evidence"] not in (0, 1) or row["status"] not in {"ready", "ocr_required", "ocr_partial"}:
        raise ValueError("catalog_metadata_invalid")
    if len(row["title"]) > 500 or len(row["metadata_json"]) > 20000 or len(row["evidence_ids_json"]) > 150000:
        raise ValueError("catalog_metadata_invalid")
    key, filename = row["material_id"], row["filename"]
    path = safe_source(root, key, filename)
    if row["source_uri"] != f"local://materials/{key}" or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"]):
        raise ValueError("catalog_identity_invalid")
    raw = path.read_bytes()
    if len(raw) != row["byte_size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ValueError("catalog_original_changed")
    try:
        metadata, ids = json.loads(row["metadata_json"]), json.loads(row["evidence_ids_json"])
        if not isinstance(metadata, dict) or not isinstance(ids, list) or len(ids) > library.MATERIAL_MAX_ANCHORS:
            raise ValueError
        if any(not isinstance(item, str) or not re.fullmatch(f"material-{key}-(?:[0-9]{{4}}|ocr-[0-9]{{4}}|redecoded-[a-f0-9]{{12}}-[0-9]{{4}})", item) for item in ids):
            raise ValueError
        if len(set(ids)) != len(ids) or len(ids) != row["anchor_count"] or (ids and not row["owns_evidence"]):
            raise ValueError
        if metadata.get("raw_sha256") != row["sha256"] or metadata.get("raw_byte_count") != len(raw) or not re.fullmatch(r"[a-f0-9]{64}", str(metadata.get("source_revision", ""))):
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValueError("catalog_metadata_invalid") from exc
    if metadata.get("ocr_performed"):
        name = str(metadata.get("ocr_path") or "ocr.json").replace("\\", "/").rsplit("/", 1)[-1]
        if not re.fullmatch(r"ocr(?:-[a-f0-9]{64})?\.json", name) or (path.parent / name).is_symlink():
            raise ValueError("catalog_cache_invalid")
        try:
            cached = read_ocr_cache({"metadata": metadata}, path.parent)
            sections = [(f"page {p['page']}", p["text"]) for p in cached["pages"] if p["text"]]
        except (ValueError, TypeError) as exc:
            raise ValueError("catalog_cache_invalid") from exc
        source_type = "pdf"
    else:
        encoding = metadata.get("decoding_hint") or ""
        if not isinstance(encoding, str) or len(encoding) > 40:
            raise ValueError("catalog_metadata_invalid")
        source_type, sections, decoded = library._material_sections(filename, raw, row["content_type"], encoding=encoding, preserve_original=False)
        if decoded.get("source_revision") != metadata["source_revision"] or decoded.get("encoding") != metadata.get("encoding"):
            raise ValueError("catalog_revision_changed")
    if len(sections) != len(ids):
        raise ValueError("catalog_identity_invalid")
    if not ids and row["status"] != "ocr_required" and not metadata.get("ocr_performed"):
        raise ValueError("catalog_evidence_missing")
    items = []
    for identifier, (locator, text) in zip(ids, sections):
        item = evidence.get(identifier)
        if item is None:
            raise ValueError("catalog_evidence_missing")
        if any(type(item[c]) is not (int if c == "schema_version" else str) for c in EVIDENCE_COLUMNS):
            raise ValueError("catalog_evidence_invalid")
        if item["schema_version"] != 1 or len(item["metadata_json"]) > 20000:
            raise ValueError("catalog_evidence_invalid")
        expected_type = source_type if source_type in {"pdf", "markdown", "webpage"} else "task"
        if (item["task_id"] or item["source_uri"] != row["source_uri"] or item["source_type"] != expected_type
                or item["title"] != row["title"] or item["locator"] != locator or item["text"] != text):
            raise ValueError("catalog_evidence_conflict")
        try:
            info = json.loads(item["metadata_json"])
            if not isinstance(info, dict) or info.get("material_id") != key or info.get("kind") != "material" or info.get("filename") != filename:
                raise ValueError
            if info.get("source_revision") != hashlib.sha256(text.encode()).hexdigest():
                raise ValueError
            if not metadata.get("ocr_performed") and any(info.get(k) != metadata.get(k) for k in ("raw_sha256", "encoding")):
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise ValueError("catalog_evidence_conflict") from exc
        items.append(item)
    return {**row, "stored_path": str(path)}, items


def equivalent(left: dict, right: dict, columns: tuple) -> bool:
    for key in columns:
        if key == "stored_path":
            continue  # Location may change when the data folder is moved.
        a, b = left.get(key), right.get(key)
        if key.endswith("_json"):
            try:
                a, b = json.loads(a), json.loads(b)
            except (ValueError, TypeError):
                return False
        if a != b:
            return False
    return True
