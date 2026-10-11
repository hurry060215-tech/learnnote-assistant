"""Durable local admission controls; running tasks keep their checkpoints."""
from contextlib import closing
from pathlib import Path
import sqlite3
import time
import uuid

AGE_INTERVAL_SECONDS = 60


def _backup_legacy_queue(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    if not columns or {"priority", "generation", "cancel_operation_id", "callback_finished"}.issubset(columns):
        return
    filename = next((row[2] for row in db.execute("PRAGMA database_list") if row[1] == "main"), "")
    if not filename:
        return  # In-memory fixtures have no persistent database to migrate.
    source = Path(filename)
    backup = source.with_name(source.name + ".pre-control-" + uuid.uuid4().hex + ".bak")
    temporary = backup.with_suffix(".tmp")
    try:
        # SQLite's backup API includes committed WAL pages, unlike file copying.
        with closing(sqlite3.connect(temporary)) as target:
            db.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Queue migration backup failed integrity check")
        temporary.replace(backup)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_queue_schema(db):
    # Fail before any schema mutation when a recoverable snapshot cannot be made.
    if db.in_transaction:
        raise sqlite3.ProgrammingError("Queue migration requires an idle connection")
    _backup_legacy_queue(db)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS jobs (sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, requires_context INTEGER NOT NULL, state TEXT NOT NULL, updated_at REAL NOT NULL, priority INTEGER NOT NULL DEFAULT 0)")
        columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
        for name, definition in (("priority", "INTEGER NOT NULL DEFAULT 0"),
                                 ("generation", "TEXT NOT NULL DEFAULT ''"),
                                 ("cancel_operation_id", "TEXT NOT NULL DEFAULT ''"),
                                 ("callback_finished", "INTEGER")):
            if name not in columns:
                db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        db.execute("CREATE TABLE IF NOT EXISTS queue_settings (id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL)")
        db.execute("INSERT OR IGNORE INTO queue_settings VALUES(1,0)")
        db.commit()
    except Exception:
        db.rollback()
        raise


def ordered_entries(rows, now=None):
    now = time.time() if now is None else now
    def rank(row):
        age = max(0, int((now - float(row["updated_at"])) // AGE_INTERVAL_SECONDS)) if row["state"] == "queued" else 0
        return (-int(row.get("priority", 0)) - age, int(row["sequence"]))
    return sorted(rows, key=rank)


def queue_candidates(db):
    if db.execute("SELECT paused FROM queue_settings WHERE id=1").fetchone()[0]:
        return []
    rows = [dict(zip(("task_id", "kind", "priority", "updated_at", "sequence", "state"), row)) for row in
            db.execute("SELECT task_id,kind,priority,updated_at,sequence,state FROM jobs WHERE state='queued'")]
    return [(row["task_id"], row["kind"]) for row in ordered_entries(rows)]


def _connect(root):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "task-queue.sqlite3", timeout=30)
    initialize_queue_schema(db)
    return db


def queue_is_paused(root):
    with closing(_connect(root)) as db:
        return bool(db.execute("SELECT paused FROM queue_settings WHERE id=1").fetchone()[0])


def set_queue_paused(root, paused):
    with closing(_connect(root)) as db:
        db.execute("UPDATE queue_settings SET paused=? WHERE id=1", (int(bool(paused)),))
        db.commit()
    return {"paused": bool(paused), "running_tasks": "continue", "scope": "new admissions only"}


def set_task_priority(root, task_id, priority):
    if type(priority) is not int or not 0 <= priority <= 5:
        raise ValueError("Priority must be an integer from 0 through5")
    with closing(_connect(root)) as db:
        changed = db.execute("UPDATE jobs SET priority=? WHERE task_id=? AND state='queued'", (priority, task_id)).rowcount
        db.commit()
    if not changed:
        raise ValueError("Only a pending task can change priority")
    return {"task_id": task_id, "priority": priority, "aging_seconds_per_level": AGE_INTERVAL_SECONDS}
