from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from .config import DATA_DIR, TASK_DIR, TEMP_DIR, ensure_dirs
from .models import TaskRecord
from .knowledge import add_evidence, clear_task_evidence, evidence_for_task, extract_import_text, remove_evidence, remove_task_evidence
from .text_cleanup import TextDecodingError, read_canonical_text


LIBRARY_SCHEMA_VERSION = 3
MATERIAL_SCHEMA_VERSION = 1
LIBRARY_BACKUP_MAX_BYTES = 128 * 1024 * 1024
MATERIAL_IMPORT_MAX_BYTES = 32 * 1024 * 1024
MATERIAL_MAX_ANCHORS = 1000
SUPPORTED_DOCUMENT_SUFFIXES = {".pdf", ".md", ".markdown", ".html", ".htm", ".txt"}
SUPPORTED_LOCAL_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}
_lock = threading.RLock()


def _db_path() -> Path:
    return DATA_DIR / "library.sqlite3"


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value or ""))
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return ""
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".localhost", ".local", ".lan", ".internal", ".home", ".corp")):
            return ""
        try:
            if not ipaddress.ip_address(hostname).is_global:
                return ""
        except ValueError:
            pass
        keep = {"v", "p", "list", "index", "courseId", "clazzid", "knowledgeId", "chapterId", "objectid"}
        query = [
            (str(key)[:40], str(item)[:200])
            for key, item in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=100)
            if key in keep
        ]
        port = f":{parsed.port}" if parsed.port else ""
        return urlunsplit((parsed.scheme.lower(), hostname + port, parsed.path[:1000], urlencode(sorted(query)), ""))[:1200]
    except (TypeError, ValueError):
        return ""


def _read_text(value: str, limit: int = 1_000_000) -> str:
    if not value:
        return ""
    try:
        path = Path(value)
        if not path.is_file():
            return ""
        return read_canonical_text(path).text[:limit]
    except (OSError, ValueError, TextDecodingError):
        return ""


def _ensure_schema(connection: sqlite3.Connection) -> bool:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS library_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS library_tasks (
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
        CREATE TABLE IF NOT EXISTS library_materials (
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
        CREATE INDEX IF NOT EXISTS library_materials_updated_idx
          ON library_materials(updated_at DESC);
        CREATE INDEX IF NOT EXISTS library_materials_task_idx
          ON library_materials(linked_task_id);
        INSERT OR REPLACE INTO library_meta(key, value) VALUES ('schema_version', '3');
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(library_tasks)").fetchall()}
    if "fingerprint" not in columns:
        connection.execute("ALTER TABLE library_tasks ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''")
        connection.commit()
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS library_tasks_fts USING fts5(task_id UNINDEXED, title, source, content)"
        )
        return True
    except sqlite3.OperationalError:
        return False


def _connect() -> tuple[sqlite3.Connection, bool]:
    ensure_dirs()
    connection = sqlite3.connect(_db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    fts_available = _ensure_schema(connection)
    return connection, fts_available


def index_task(record: TaskRecord) -> bool:
    """Best-effort indexing; task JSON remains the source of truth if SQLite is unavailable."""
    note = _read_text(record.note_path)
    transcript = _read_text(record.transcript_path)
    source = _safe_url(record.page_url)
    content = "\n".join(part for part in (record.title, source, note, transcript) if part)
    try:
        with _lock:
            connection, fts_available = _connect()
            try:
                connection.execute(
                    """
                    INSERT INTO library_tasks(task_id, title, source, source_type, mode, status, checkpoint,
                                              created_at, updated_at, note_path, media_path, fingerprint, content)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                      title=excluded.title, source=excluded.source, source_type=excluded.source_type,
                      mode=excluded.mode, status=excluded.status, checkpoint=excluded.checkpoint,
                      created_at=excluded.created_at, updated_at=excluded.updated_at,
                      note_path=excluded.note_path, media_path=excluded.media_path,
                      fingerprint=excluded.fingerprint, content=excluded.content
                    """,
                    (
                        record.id,
                        record.title,
                        source,
                        record.source_type,
                        record.mode,
                        record.status,
                        record.checkpoint,
                        record.created_at,
                        record.updated_at,
                        record.note_path,
                        record.media_path or record.source_media_path,
                        record.source_identity.media_sha256,
                        content,
                    ),
                )
                if fts_available:
                    connection.execute("DELETE FROM library_tasks_fts WHERE task_id = ?", (record.id,))
                    connection.execute(
                        "INSERT INTO library_tasks_fts(task_id, title, source, content) VALUES (?, ?, ?, ?)",
                        (record.id, record.title, source, content),
                    )
                connection.commit()
                indexed = True
            finally:
                connection.close()
        if indexed:
            # Keep the task directory as the source of truth while exposing a
            # citation-ready projection for local retrieval.
            remove_task_evidence(record.id)
            if note:
                add_evidence(record_to_evidence(record, note, "note"))
            if transcript:
                transcript_items = transcript_evidence(record, transcript)
                for item in transcript_items:
                    add_evidence(item)
        return indexed
    except (OSError, sqlite3.Error):
        return False


def record_to_evidence(record: TaskRecord, text: str, kind: str):
    from .models import SourceEvidence

    return SourceEvidence(
        evidence_id=f"task-{record.id}-{kind}",
        source_type="video" if kind == "transcript" else "task",
        title=record.title,
        source_uri=_safe_url(record.page_url),
        locator="transcript" if kind == "transcript" else "note",
        text=text,
        task_id=record.id,
        metadata={"kind": kind, "checkpoint": record.checkpoint},
    )


def transcript_evidence(record: TaskRecord, raw: str):
    from .models import SourceEvidence

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = {}
    segments = payload.get("segments") if isinstance(payload, dict) else []
    items = []
    for index, segment in enumerate(segments or []):
        if not isinstance(segment, dict) or not str(segment.get("text") or "").strip():
            continue
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or start)
        items.append(SourceEvidence(
            evidence_id=f"task-{record.id}-transcript-{index:05d}",
            source_type="video",
            title=record.title,
            source_uri=_safe_url(record.page_url),
            locator=f"{start:.1f}-{end:.1f}s",
            text=str(segment.get("text") or ""),
            task_id=record.id,
            metadata={"kind": "transcript", "start": start, "end": end},
        ))
    return items or [record_to_evidence(record, raw, "transcript")]


def remove_task(task_id: str) -> bool:
    evidence_ids = [
        str(item.get("evidence_id") or "")
        for item in evidence_for_task(task_id, limit=2000)
        if str(item.get("evidence_id") or "")
    ]
    try:
        with _lock:
            connection, fts_available = _connect()
            try:
                connection.execute("DELETE FROM library_tasks WHERE task_id = ?", (task_id,))
                connection.execute("DELETE FROM library_materials WHERE linked_task_id = ?", (task_id,))
                if fts_available:
                    connection.execute("DELETE FROM library_tasks_fts WHERE task_id = ?", (task_id,))
                connection.commit()
            finally:
                connection.close()
        from .community import clear_community_context
        from .study import remove_cards_for_evidence

        remove_cards_for_evidence(evidence_ids)
        clear_community_context(task_id)
        remove_task_evidence(task_id)
        return True
    except sqlite3.Error:
        return False


def rebuild_index() -> dict[str, int | str]:
    with _lock:
        connection, fts_available = _connect()
        try:
            connection.execute("DELETE FROM library_tasks")
            if fts_available:
                connection.execute("DELETE FROM library_tasks_fts")
            connection.commit()
        finally:
            connection.close()
    indexed = 0
    skipped = 0
    clear_task_evidence()
    for path in sorted(TASK_DIR.glob("*/task.json")):
        try:
            record = TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            skipped += 1
            continue
        indexed += int(index_task(record))
    return {"status": "pass", "indexed": indexed, "skipped": skipped, "schema_version": LIBRARY_SCHEMA_VERSION}


def _search_term(value: str) -> str:
    tokens = [re.sub(r"[^\w\u4e00-\u9fff.-]+", " ", part).strip() for part in str(value or "").split()]
    return " AND ".join(f'"{token.replace(chr(34), "")}"' for token in tokens if token)


def search_library(query: str = "", limit: int = 50) -> list[dict[str, object]]:
    limit = max(1, min(int(limit or 50), 200))
    with _lock:
        connection, fts_available = _connect()
        try:
            term = _search_term(query)
            if term and fts_available:
                rows = connection.execute(
                    """
                    SELECT t.* FROM library_tasks_fts f
                    JOIN library_tasks t ON t.task_id = f.task_id
                    WHERE library_tasks_fts MATCH ?
                    ORDER BY t.updated_at DESC LIMIT ?
                    """,
                    (term, limit),
                ).fetchall()
                if rows:
                    return [_library_search_result(row, query) for row in rows]
            if term:
                like = f"%{str(query).strip()}%"
                rows = connection.execute(
                    "SELECT * FROM library_tasks WHERE title LIKE ? OR source LIKE ? OR content LIKE ? ORDER BY updated_at DESC LIMIT ?",
                    (like, like, like, limit),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM library_tasks ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
            return [_library_search_result(row, query) for row in rows]
        finally:
            connection.close()


def library_status() -> dict[str, object]:
    with _lock:
        connection, fts_available = _connect()
        try:
            count = int(connection.execute("SELECT COUNT(*) FROM library_tasks").fetchone()[0])
            material_count = int(connection.execute("SELECT COUNT(*) FROM library_materials").fetchone()[0])
            path = _db_path()
            return {
                "schema_version": LIBRARY_SCHEMA_VERSION,
                "indexed_task_count": count,
                "material_count": material_count,
                "fts_available": fts_available,
                "path": str(path),
                "bytes": path.stat().st_size if path.exists() else 0,
            }
        finally:
            connection.close()


def duplicate_groups() -> list[dict[str, object]]:
    """Return media-fingerprint groups that can be reviewed before cleanup."""
    with _lock:
        connection, _ = _connect()
        try:
            rows = connection.execute(
                """SELECT fingerprint, COUNT(*) AS count, GROUP_CONCAT(task_id) AS task_ids
                   FROM library_tasks
                   WHERE fingerprint != ''
                   GROUP BY fingerprint HAVING COUNT(*) > 1
                   ORDER BY count DESC"""
            ).fetchall()
            return [
                {"fingerprint": row["fingerprint"], "count": int(row["count"]), "task_ids": str(row["task_ids"] or "").split(",")}
                for row in rows
            ]
        finally:
            connection.close()


def backup_library() -> Path:
    """Create a SQLite-consistent index snapshot (not a full data backup)."""
    export_dir = DATA_DIR / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = export_dir / f"learnnote-library-{stamp}-{uuid4().hex[:8]}.sqlite3"
    with _lock:
        source, _ = _connect()
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()
    snapshots = sorted(
        (
            path for path in export_dir.glob("learnnote-library-*.sqlite3")
            if re.fullmatch(r"learnnote-library-\d{8}-\d{6}-[0-9a-f]{8}\.sqlite3", path.name)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale in snapshots[10:]:
        try:
            stale.unlink()
        except OSError:
            continue
    return target


def restore_library(backup_path: Path) -> dict[str, object]:
    """Logically migrate a validated task index into a fresh local database."""
    candidate = Path(backup_path).resolve()
    if not candidate.is_file():
        raise ValueError("library_backup_missing")
    if candidate.stat().st_size > LIBRARY_BACKUP_MAX_BYTES:
        raise ValueError("library_backup_too_large")
    try:
        source = sqlite3.connect(candidate)
        try:
            integrity = str(source.execute("PRAGMA integrity_check").fetchone()[0])
            schema = source.execute(
                "SELECT value FROM library_meta WHERE key = 'schema_version'"
            ).fetchone()
            table = source.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'library_tasks'").fetchone()
            columns = {str(row[1]) for row in source.execute("PRAGMA table_info(library_tasks)").fetchall()}
            objects = source.execute(
                "SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view') AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        finally:
            source.close()
    except sqlite3.Error as exc:
        raise ValueError("library_backup_invalid") from exc
    required_columns = {
        "task_id", "title", "source", "source_type", "mode", "status",
        "created_at", "updated_at", "note_path", "media_path", "content",
    }
    if (
        integrity.lower() != "ok"
        or not schema
        or str(schema[0]) not in {"1", "2", str(LIBRARY_SCHEMA_VERSION)}
        or not table
        or not required_columns.issubset(columns)
        or objects
    ):
        raise ValueError("library_backup_schema_mismatch")

    ensure_dirs()
    target = _db_path()
    temporary = TEMP_DIR / f"library-restore-{uuid4().hex}.sqlite3"
    rollback_created = False
    try:
        with _lock:
            source = sqlite3.connect(candidate)
            source.row_factory = sqlite3.Row
            destination = sqlite3.connect(temporary)
            destination.row_factory = sqlite3.Row
            try:
                fts_available = _ensure_schema(destination)
                checkpoint_expr = "checkpoint" if "checkpoint" in columns else "'' AS checkpoint"
                fingerprint_expr = "fingerprint" if "fingerprint" in columns else "'' AS fingerprint"
                rows = source.execute(
                    f"""SELECT task_id, title, source, source_type, mode, status, {checkpoint_expr},
                               created_at, updated_at, note_path, media_path, {fingerprint_expr}, content
                        FROM library_tasks LIMIT 100001"""
                ).fetchall()
                if len(rows) > 100000:
                    raise ValueError("library_backup_too_many_rows")
                for row in rows:
                    values = (
                        str(row["task_id"] or "")[:128],
                        str(row["title"] or "")[:500],
                        _safe_url(str(row["source"] or "")),
                        str(row["source_type"] or "")[:40],
                        str(row["mode"] or "")[:40],
                        str(row["status"] or "")[:40],
                        str(row["checkpoint"] or "")[:80],
                        str(row["created_at"] or "")[:80],
                        str(row["updated_at"] or "")[:80],
                        "",
                        "",
                        str(row["fingerprint"] or "")[:160],
                        str(row["content"] or "")[:2_000_000],
                    )
                    if not values[0]:
                        raise ValueError("library_backup_invalid_row")
                    destination.execute(
                        """INSERT INTO library_tasks(task_id, title, source, source_type, mode, status, checkpoint,
                                                     created_at, updated_at, note_path, media_path, fingerprint, content)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        values,
                    )
                    if fts_available:
                        destination.execute(
                            "INSERT INTO library_tasks_fts(task_id, title, source, content) VALUES (?, ?, ?, ?)",
                            (values[0], values[1], values[2], values[12]),
                        )
                destination.commit()
                if str(destination.execute("PRAGMA integrity_check").fetchone()[0]).lower() != "ok":
                    raise ValueError("library_backup_invalid")
            finally:
                destination.close()
                source.close()

            if target.is_file():
                export_dir = DATA_DIR / "exports"
                export_dir.mkdir(parents=True, exist_ok=True)
                rollback = export_dir / f"learnnote-library-pre-restore-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.sqlite3"
                live = sqlite3.connect(target)
                snapshot = sqlite3.connect(rollback)
                try:
                    live.backup(snapshot)
                    snapshot.commit()
                    rollback_created = True
                finally:
                    snapshot.close()
                    live.close()
            temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    status = library_status()
    status.update({"backup_scope": "task_index_only", "rollback_snapshot_created": rollback_created})
    return status


def material_capabilities() -> dict[str, object]:
    return {
        "schema_version": MATERIAL_SCHEMA_VERSION,
        "document_import": {
            "endpoint": "/api/library/materials/import",
            "suffixes": sorted(SUPPORTED_DOCUMENT_SUFFIXES),
            "max_bytes": MATERIAL_IMPORT_MAX_BYTES,
            "anchors": ["pdf_page", "document_section", "paragraph"],
        },
        "local_video": {
            "upload_endpoint": "/api/tasks/local",
            "register_endpoint": "/api/library/materials/register-task/{task_id}",
            "suffixes": sorted(SUPPORTED_LOCAL_VIDEO_SUFFIXES),
            "duplicates_media": False,
            "anchor_source": "task transcript and visual evidence",
        },
        "privacy": {
            "storage": "local-only",
            "accounts_required": False,
            "telemetry": False,
            "remote_ocr": False,
        },
    }


def _material_row(row: sqlite3.Row, *, deduplicated: bool = False) -> dict[str, object]:
    try:
        evidence_ids = json.loads(row["evidence_ids_json"] or "[]")
    except (TypeError, ValueError):
        evidence_ids = []
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, ValueError):
        metadata = {}
    material_id = str(row["material_id"] or "")[:128]
    expected_file = (DATA_DIR / "materials" / material_id / _safe_material_filename(str(row["filename"] or "material"))).resolve()
    material_root = (DATA_DIR / "materials" / material_id).resolve()
    stored_locally = bool(expected_file.parent == material_root and expected_file.is_file())
    return {
        "material_id": material_id,
        "schema_version": int(row["schema_version"]),
        "title": row["title"],
        "filename": row["filename"],
        "source_type": row["source_type"],
        "content_type": row["content_type"],
        "source_uri": row["source_uri"],
        "sha256": row["sha256"],
        "byte_size": int(row["byte_size"]),
        "status": row["status"],
        "linked_task_id": row["linked_task_id"],
        "anchor_count": int(row["anchor_count"]),
        "evidence_ids": evidence_ids if isinstance(evidence_ids, list) else [],
        "owns_evidence": bool(row["owns_evidence"]),
        "stored_locally": stored_locally,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deduplicated": bool(deduplicated),
    }


def list_materials(limit: int = 100, source_type: str = "") -> list[dict[str, object]]:
    cap = max(1, min(int(limit or 100), 500))
    with _lock:
        connection, _ = _connect()
        try:
            if source_type:
                rows = connection.execute(
                    "SELECT * FROM library_materials WHERE source_type = ? ORDER BY updated_at DESC LIMIT ?",
                    (str(source_type)[:40], cap),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM library_materials ORDER BY updated_at DESC LIMIT ?",
                    (cap,),
                ).fetchall()
        finally:
            connection.close()
    return [_material_row(row) for row in rows]


def _library_search_result(row: sqlite3.Row, query: str = "") -> dict[str, object]:
    content = " ".join(str(row["content"] or "").split())
    needle = str(query or "").strip().casefold()
    start = max(0, content.casefold().find(needle) - 90) if needle and needle in content.casefold() else 0
    snippet = content[start : start + 320]
    if start:
        snippet = "…" + snippet
    if start + 320 < len(content):
        snippet += "…"
    return {
        "task_id": row["task_id"],
        "title": row["title"],
        "source": row["source"],
        "source_type": row["source_type"],
        "mode": row["mode"],
        "status": row["status"],
        "checkpoint": row["checkpoint"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "snippet": snippet,
    }


def get_material(material_id: str) -> dict[str, object]:
    with _lock:
        connection, _ = _connect()
        try:
            row = connection.execute(
                "SELECT * FROM library_materials WHERE material_id = ?",
                (str(material_id or "")[:128],),
            ).fetchone()
        finally:
            connection.close()
    if row is None:
        raise ValueError("material_not_found")
    return _material_row(row)


def delete_material(material_id: str) -> dict[str, object]:
    """Permanently remove one app-owned material and only its own evidence."""

    material_key = str(material_id or "")[:128]
    with _lock:
        connection, _ = _connect()
        try:
            row = connection.execute("SELECT * FROM library_materials WHERE material_id = ?", (material_key,)).fetchone()
        finally:
            connection.close()
    if row is None:
        raise ValueError("material_not_found")
    try:
        evidence_ids = [str(value) for value in json.loads(row["evidence_ids_json"] or "[]") if str(value)]
    except (TypeError, ValueError):
        evidence_ids = []

    owns_evidence = bool(row["owns_evidence"])
    if owns_evidence:
        material_root = (DATA_DIR / "materials").resolve()
        owned_root = (material_root / material_key).resolve()
        if owned_root.parent != material_root:
            raise ValueError("invalid_material_path")
        filename = _safe_material_filename(str(row["filename"] or "material"))
        owned_file = (owned_root / filename).resolve()
        if owned_file.parent != owned_root:
            raise ValueError("invalid_material_path")
        if owned_file.is_file():
            owned_file.unlink()
        if owned_root.is_dir():
            try:
                owned_root.rmdir()
            except OSError:
                # Never widen deletion to unknown files in a recovered folder.
                pass

    with _lock:
        connection, _ = _connect()
        try:
            connection.execute("DELETE FROM library_materials WHERE material_id = ?", (material_key,))
            connection.commit()
        finally:
            connection.close()
    if owns_evidence:
        for evidence_id in evidence_ids:
            remove_evidence(evidence_id)
    return {
        "material_id": material_key,
        "deleted": True,
        "deleted_evidence_count": len(evidence_ids) if owns_evidence else 0,
    }


def _safe_material_filename(filename: str) -> str:
    name = Path(str(filename or "material")).name
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", name).strip(" ._")
    name = (name or "material")[:180]
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{index}" for index in range(1, 10)), *(f"LPT{index}" for index in range(1, 10))}
    if Path(name).stem.upper() in reserved:
        name = f"_{name}"
    return name


def _split_long_section(text: str, max_chars: int = 6000) -> list[str]:
    normalized = "\n".join(line.rstrip() for line in str(text or "").splitlines()).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    remaining = normalized
    while len(remaining) > max_chars:
        split_at = max(
            remaining.rfind("\n\n", 0, max_chars),
            remaining.rfind("。", 0, max_chars),
            remaining.rfind(". ", 0, max_chars),
        )
        if split_at < max_chars // 3:
            split_at = max_chars
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _material_sections(filename: str, content: bytes, content_type: str) -> tuple[str, list[tuple[str, str]], dict[str, object]]:
    text, evidence_source_type = extract_import_text(filename, content, content_type)
    suffix = Path(filename).suffix.lower()
    sections: list[tuple[str, str]] = []
    metadata: dict[str, object] = {"extraction": "local", "ocr_performed": False}
    if suffix == ".pdf" or evidence_source_type == "pdf":
        pieces = re.split(r"(?m)^\[第\s+(\d+)\s+页\]\s*$", text)
        if len(pieces) > 1:
            for index in range(1, len(pieces), 2):
                page_number = pieces[index]
                page_text = pieces[index + 1] if index + 1 < len(pieces) else ""
                for part_index, chunk in enumerate(_split_long_section(page_text), start=1):
                    locator = f"page {page_number}"
                    if part_index > 1:
                        locator += f" part {part_index}"
                    sections.append((locator, chunk))
                    if len(sections) > MATERIAL_MAX_ANCHORS:
                        raise ValueError("material_anchor_limit_exceeded")
        metadata["anchor_type"] = "pdf_page"
        metadata["ocr_required"] = not bool(sections)
    else:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
        heading = ""
        ordinal = 0
        for paragraph in paragraphs:
            first_line = paragraph.splitlines()[0].strip()
            if suffix in {".md", ".markdown"} and first_line.startswith("#"):
                heading = first_line.lstrip("#").strip()[:180]
            for chunk in _split_long_section(paragraph):
                ordinal += 1
                locator = f"section {ordinal}"
                if heading:
                    locator += f" · {heading}"
                sections.append((locator, chunk))
                if len(sections) > MATERIAL_MAX_ANCHORS:
                    raise ValueError("material_anchor_limit_exceeded")
        metadata["anchor_type"] = "document_section"
    if not sections:
        raise ValueError("material_no_extractable_text")
    return evidence_source_type, sections, metadata


def _find_material_by_sha(connection: sqlite3.Connection, digest: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM library_materials WHERE sha256 = ?", (digest,)).fetchone()


def import_document_material(filename: str, content: bytes, content_type: str = "") -> dict[str, object]:
    safe_name = _safe_material_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
        if suffix in SUPPORTED_LOCAL_VIDEO_SUFFIXES or str(content_type or "").lower().startswith("video/"):
            raise ValueError("local_video_use_task_upload")
        raise ValueError("material_type_unsupported")
    if not content:
        raise ValueError("material_file_empty")
    if len(content) > MATERIAL_IMPORT_MAX_BYTES:
        raise ValueError("material_file_too_large")
    digest = hashlib.sha256(content).hexdigest()
    with _lock:
        connection, _ = _connect()
        try:
            existing = _find_material_by_sha(connection, digest)
        finally:
            connection.close()
    if existing is not None:
        return _material_row(existing, deduplicated=True)

    evidence_source_type, sections, metadata = _material_sections(safe_name, content, content_type)
    material_id = uuid4().hex
    source_uri = f"local://materials/{material_id}"
    title = Path(safe_name).stem[:500] or "本地学习资料"
    material_dir = DATA_DIR / "materials" / material_id
    stored_path = material_dir / safe_name
    temporary = material_dir / f".{safe_name}.{uuid4().hex}.tmp"
    try:
        material_dir.mkdir(parents=True, exist_ok=False)
        temporary.write_bytes(content)
        temporary.replace(stored_path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        try:
            material_dir.rmdir()
        except OSError:
            pass
        raise ValueError("material_storage_failed") from exc

    evidence_ids: list[str] = []
    try:
        for index, (locator, text) in enumerate(sections, start=1):
            evidence_id = f"material-{material_id}-{index:04d}"
            stored = add_evidence(record_to_material_evidence(
                evidence_id=evidence_id,
                source_type=evidence_source_type,
                title=title,
                source_uri=source_uri,
                locator=locator,
                text=text,
                material_id=material_id,
                filename=safe_name,
            ))
            evidence_ids.append(stored.evidence_id)
    except Exception:
        for evidence_id in evidence_ids:
            remove_evidence(evidence_id)
        stored_path.unlink(missing_ok=True)
        try:
            material_dir.rmdir()
        except OSError:
            pass
        raise
    now = datetime.now(timezone.utc).isoformat()
    record_source_type = "text" if suffix == ".txt" else evidence_source_type
    metadata.update({"suffix": suffix, "original_filename": safe_name})
    try:
        with _lock:
            connection, _ = _connect()
            try:
                existing = _find_material_by_sha(connection, digest)
                if existing is not None:
                    for evidence_id in evidence_ids:
                        remove_evidence(evidence_id)
                    temporary.unlink(missing_ok=True)
                    stored_path.unlink(missing_ok=True)
                    try:
                        material_dir.rmdir()
                    except OSError:
                        pass
                    return _material_row(existing, deduplicated=True)
                connection.execute(
                    """INSERT INTO library_materials
                       (material_id, schema_version, title, filename, source_type, content_type,
                        source_uri, sha256, byte_size, status, linked_task_id, anchor_count,
                        evidence_ids_json, owns_evidence, stored_path, metadata_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, 1, ?, ?, ?, ?)""",
                    (
                        material_id,
                        MATERIAL_SCHEMA_VERSION,
                        title,
                        safe_name,
                        record_source_type,
                        str(content_type or "")[:200],
                        source_uri,
                        digest,
                        len(content),
                        "ready",
                        len(evidence_ids),
                        json.dumps(evidence_ids, ensure_ascii=False),
                        str(stored_path),
                        json.dumps(metadata, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                connection.commit()
                row = connection.execute("SELECT * FROM library_materials WHERE material_id = ?", (material_id,)).fetchone()
            finally:
                connection.close()
    except Exception:
        for evidence_id in evidence_ids:
            remove_evidence(evidence_id)
        stored_path.unlink(missing_ok=True)
        try:
            material_dir.rmdir()
        except OSError:
            pass
        raise
    return _material_row(row)


def record_to_material_evidence(
    *,
    evidence_id: str,
    source_type: str,
    title: str,
    source_uri: str,
    locator: str,
    text: str,
    material_id: str,
    filename: str,
):
    from .models import SourceEvidence

    allowed_source_type = source_type if source_type in {"video", "pdf", "markdown", "webpage", "task"} else "task"
    return SourceEvidence(
        evidence_id=evidence_id,
        source_type=allowed_source_type,
        title=title,
        source_uri=source_uri,
        locator=locator,
        text=text,
        metadata={"kind": "material", "material_id": material_id, "filename": filename},
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register_task_material(record: TaskRecord) -> dict[str, object]:
    media_path = Path(record.media_path or record.source_media_path) if (record.media_path or record.source_media_path) else None
    digest = str(record.source_identity.media_sha256 or "").strip()
    if not digest and media_path and media_path.is_file():
        digest = _file_sha256(media_path)
    if not digest:
        digest = hashlib.sha256(f"task\0{record.id}".encode("utf-8")).hexdigest()
    with _lock:
        connection, _ = _connect()
        try:
            existing = _find_material_by_sha(connection, digest)
        finally:
            connection.close()
    if existing is not None:
        return _material_row(existing, deduplicated=True)

    from .knowledge import evidence_for_task

    anchors = evidence_for_task(record.id, limit=500)
    evidence_ids = [str(item.get("evidence_id") or "") for item in anchors if item.get("evidence_id")]
    material_id = uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    source_uri = _safe_url(record.page_url) or f"local://tasks/{record.id}"
    filename = media_path.name if media_path else ""
    status = "ready" if record.status == "success" else ("failed" if record.status == "failed" else "processing")
    metadata = {
        "registration": "existing_task",
        "task_status": record.status,
        "task_checkpoint": record.checkpoint,
        "original_media_duplicated": False,
    }
    with _lock:
        connection, _ = _connect()
        try:
            connection.execute(
                """INSERT INTO library_materials
                   (material_id, schema_version, title, filename, source_type, content_type,
                    source_uri, sha256, byte_size, status, linked_task_id, anchor_count,
                    evidence_ids_json, owns_evidence, stored_path, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?, ?)""",
                (
                    material_id,
                    MATERIAL_SCHEMA_VERSION,
                    record.title[:500],
                    filename[:180],
                    "video/*",
                    source_uri,
                    digest,
                    media_path.stat().st_size if media_path and media_path.is_file() else 0,
                    status,
                    record.id,
                    len(evidence_ids),
                    json.dumps(evidence_ids, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM library_materials WHERE material_id = ?", (material_id,)).fetchone()
        finally:
            connection.close()
    return _material_row(row)


def material_anchors(material_id: str, limit: int = 500) -> list[dict[str, object]]:
    material = get_material(material_id)
    evidence_ids = [str(item) for item in material["evidence_ids"] if str(item)]
    if not evidence_ids:
        return []
    cap = max(1, min(int(limit or 500), 1000))
    selected = evidence_ids[:cap]
    placeholders = ",".join("?" for _ in selected)
    connection = sqlite3.connect(_db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            f"SELECT * FROM source_evidence WHERE evidence_id IN ({placeholders})",
            tuple(selected),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        connection.close()
    by_id = {row["evidence_id"]: row for row in rows}
    result: list[dict[str, object]] = []
    for evidence_id in selected:
        row = by_id.get(evidence_id)
        if row is None:
            continue
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        result.append({
            "evidence_id": row["evidence_id"],
            "source_type": row["source_type"],
            "title": row["title"],
            "source_uri": row["source_uri"],
            "locator": row["locator"],
            "text": row["text"],
            "task_id": row["task_id"],
            "metadata": metadata,
        })
    return result
