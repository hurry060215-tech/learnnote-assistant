from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from .config import DATA_DIR, TASK_DIR, TEMP_DIR, ensure_dirs
from .models import TaskRecord


LIBRARY_SCHEMA_VERSION = 1
LIBRARY_BACKUP_MAX_BYTES = 128 * 1024 * 1024
_lock = threading.RLock()


def _db_path() -> Path:
    return DATA_DIR / "library.sqlite3"


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value or ""))
        if not parsed.scheme or not parsed.netloc:
            return str(value or "")[:300]
        keep = {"v", "p", "list", "index", "courseId", "clazzid", "knowledgeId", "chapterId", "objectid"}
        query = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True) if key in keep]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(sorted(query)), ""))[:500]
    except (TypeError, ValueError):
        return str(value or "")[:300]


def _read_text(value: str, limit: int = 1_000_000) -> str:
    if not value:
        return ""
    try:
        path = Path(value)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except (OSError, ValueError):
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
          content TEXT NOT NULL
        );
        INSERT OR REPLACE INTO library_meta(key, value) VALUES ('schema_version', '1');
        """
    )
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
                                              created_at, updated_at, note_path, media_path, content)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                      title=excluded.title, source=excluded.source, source_type=excluded.source_type,
                      mode=excluded.mode, status=excluded.status, checkpoint=excluded.checkpoint,
                      created_at=excluded.created_at, updated_at=excluded.updated_at,
                      note_path=excluded.note_path, media_path=excluded.media_path, content=excluded.content
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
                return True
            finally:
                connection.close()
    except (OSError, sqlite3.Error):
        return False


def remove_task(task_id: str) -> bool:
    try:
        with _lock:
            connection, fts_available = _connect()
            try:
                connection.execute("DELETE FROM library_tasks WHERE task_id = ?", (task_id,))
                if fts_available:
                    connection.execute("DELETE FROM library_tasks_fts WHERE task_id = ?", (task_id,))
                connection.commit()
                return True
            finally:
                connection.close()
    except sqlite3.Error:
        return False


def rebuild_index() -> dict[str, int | str]:
    indexed = 0
    skipped = 0
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
                    return [dict(row) for row in rows]
            if term:
                like = f"%{str(query).strip()}%"
                rows = connection.execute(
                    "SELECT * FROM library_tasks WHERE title LIKE ? OR source LIKE ? OR content LIKE ? ORDER BY updated_at DESC LIMIT ?",
                    (like, like, like, limit),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM library_tasks ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()


def library_status() -> dict[str, object]:
    with _lock:
        connection, fts_available = _connect()
        try:
            count = int(connection.execute("SELECT COUNT(*) FROM library_tasks").fetchone()[0])
            path = _db_path()
            return {
                "schema_version": LIBRARY_SCHEMA_VERSION,
                "indexed_task_count": count,
                "fts_available": fts_available,
                "path": str(path),
                "bytes": path.stat().st_size if path.exists() else 0,
            }
        finally:
            connection.close()


def backup_library() -> Path:
    """Create a SQLite-consistent local backup outside the live database file."""
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
    return target


def restore_library(backup_path: Path) -> dict[str, object]:
    """Validate and atomically restore an uploaded SQLite index."""
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
            table = source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'library_tasks'"
            ).fetchone()
        finally:
            source.close()
    except sqlite3.Error as exc:
        raise ValueError("library_backup_invalid") from exc
    if integrity.lower() != "ok" or not schema or str(schema[0]) != str(LIBRARY_SCHEMA_VERSION) or not table:
        raise ValueError("library_backup_schema_mismatch")

    ensure_dirs()
    target = _db_path()
    temporary = TEMP_DIR / f"library-restore-{uuid4().hex}.sqlite3"
    with _lock:
        source = sqlite3.connect(candidate)
        destination = sqlite3.connect(temporary)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()
        temporary.replace(target)
    return library_status()
