"""Local-only, bounded activation facts. No task contents or network transport."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import time

from . import APP_VERSION

RETENTION_SECONDS = 30 * 86400
MILESTONES = {"installed", "desktop_connected", "first_task_started", "first_task_succeeded"}
ERROR_CATEGORIES = {"connection", "download", "transcript", "model", "storage", "content", "other"}
FIELDS = tuple(sorted(MILESTONES)) + ("error_categories", "version")


@contextmanager
def database(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(root / "activation.sqlite3", timeout=5)) as db:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL)")
        db.execute("INSERT OR IGNORE INTO preferences VALUES(1,1)")
        db.execute("CREATE TABLE IF NOT EXISTS facts (name TEXT PRIMARY KEY, recorded REAL NOT NULL)")
        db.execute("DELETE FROM facts WHERE recorded < ?", (time.time() - RETENTION_SECONDS,))
        yield db
        db.commit()


def record(root: Path, name: str):
    if name not in MILESTONES and name not in {"error:" + value for value in ERROR_CATEGORIES}:
        raise ValueError("Unknown activation fact")
    # Diagnostics cannot make task execution or connection health fail.
    try:
        with database(root) as db:
            if db.execute("SELECT enabled FROM preferences WHERE id=1").fetchone()[0]:
                for value in ("installed", name):
                    db.execute("INSERT OR IGNORE INTO facts VALUES(?,?)", (value, time.time()))
    except (OSError, sqlite3.Error):
        pass


def error_category(code: str) -> str:
    code = str(code or "").lower()
    for category, prefixes in {
        "connection": ("connection", "pairing", "backend"), "download": ("download", "media_download"),
        "transcript": ("asr", "transcript", "subtitle"), "model": ("summary", "model", "provider", "llm"),
        "storage": ("disk", "storage", "upload"), "content": ("content", "note_quality", "encoding"),
    }.items():
        if code.startswith(prefixes):
            return category
    return "other"


def record_status(root: Path, status: str, code: str = ""):
    if status == "running":
        record(root, "first_task_started")
    elif status == "success":
        record(root, "first_task_succeeded")
    elif status == "failed":
        record(root, "error:" + error_category(code))


def snapshot(root: Path) -> dict:
    with database(root) as db:
        enabled = bool(db.execute("SELECT enabled FROM preferences WHERE id=1").fetchone()[0])
        facts = {row[0] for row in db.execute("SELECT name FROM facts")}
    return {"enabled": enabled, "retention_days": 30, "remote_transport": False,
            "fields": {**{key: key in facts for key in sorted(MILESTONES)},
                       "error_categories": sorted(value[6:] for value in facts if value.startswith("error:")),
                       "version": APP_VERSION}}


def set_enabled(root: Path, enabled: bool):
    with database(root) as db:
        db.execute("UPDATE preferences SET enabled=? WHERE id=1", (int(enabled),))
    if enabled:
        record(root, "installed")
    return snapshot(root)


def clear(root: Path):
    with database(root) as db:
        db.execute("DELETE FROM facts")
        db.execute("UPDATE preferences SET enabled=0 WHERE id=1")
    return snapshot(root)


def support_summary(root: Path, fields: list[str]) -> dict:
    if len(fields) != len(set(fields)) or any(field not in FIELDS for field in fields):
        raise ValueError("Only documented support fields can be exported")
    values = snapshot(root)["fields"]
    return {key: values[key] for key in fields}
