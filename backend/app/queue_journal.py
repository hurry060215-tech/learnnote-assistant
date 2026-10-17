"""Durable queue evidence and cancellation independent of live workers.

Reads never initialize a database or schema. Cancellation competes with worker
claims through the existing SQLite row, including when no queue is cached.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import time

from .queue_controls import ordered_entries
from .queue_policy import LANE_PENDING_LIMIT, lane_budgets, task_lane


def read_queue_entries(root: Path) -> tuple[list[dict], bool | None]:
    """Read durable evidence without creating a queue, schema, directory or worker."""
    path = Path(root) / "task-queue.sqlite3"
    if not path.exists():
        return [], None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY sequence")]
            for row in rows:
                if not {"task_id", "sequence", "kind", "state", "updated_at"}.issubset(row) or row["state"] not in {
                        "queued", "running", "done", "failed", "cancelled", "recovering", "waiting_context"}:
                    return [{"state": "unknown"}], None
            try:
                setting = db.execute("SELECT paused FROM queue_settings WHERE id=1").fetchone()
                paused = bool(setting[0]) if setting else None
            except sqlite3.Error:
                paused = None
            return rows, paused
    except sqlite3.Error:
        return [{"state": "unknown"}], None


def read_queue_job(root: Path, task_id: str) -> dict | None:
    rows, _ = read_queue_entries(root)
    if rows and rows[0].get("state") == "unknown":
        return rows[0]
    return next((row for row in rows if row.get("task_id") == task_id), None)


def cancel_queued_processing(root: Path, task_id: str, *, expected_generation: str | None = None,
                             operation_id: str = "") -> bool:
    # Do not depend on this process owning a callback/cache. The queued->running
    # claim and queued->cancelled cancellation compete in the same SQLite row.
    path = Path(root) / "task-queue.sqlite3"
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=30)) as db:
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if expected_generation is not None and "generation" not in columns:
                return False  # Legacy evidence cannot identify the attempted generation.
            if expected_generation is None:
                changed = db.execute("UPDATE jobs SET state='cancelled',updated_at=? WHERE task_id=? AND state='queued'",
                                     (time.time(), task_id)).rowcount
            else:
                changed = db.execute("UPDATE jobs SET state='cancelled',updated_at=?,cancel_operation_id=?,callback_finished=0 WHERE task_id=? AND state='queued' AND generation=?",
                                     (time.time(), operation_id, task_id, expected_generation)).rowcount
            db.commit()
            return bool(changed)
    except sqlite3.Error:
        return False


def read_queue_snapshot(root: Path) -> tuple[list[dict], bool | None]:
    """Read and order once; callers own this request-local, nonmutating value."""
    rows, paused = read_queue_entries(root)
    return (rows if rows and rows[0].get("state") == "unknown" else ordered_entries(rows)), paused


def queue_status(root: Path, task_id: str) -> dict[str, object]:
    """Return a durable, privacy-safe queue snapshot for one task."""
    return queue_status_from_snapshot(read_queue_snapshot(root), task_id)


def queue_status_from_snapshot(snapshot: tuple[list[dict], bool | None], task_id: str) -> dict[str, object]:
    """Pure projection; no queue read, initialization, repair or row mutation."""
    entries, paused = snapshot
    if entries and entries[0].get("state") == "unknown":
        return {"state": "unknown", "position": 0, "queued_count": 0, "running_count": 0, "kind": ""}
    active = [row for row in entries if row["state"] in {"queued", "running", "recovering"}]
    current = next((row for row in active if row["task_id"] == task_id), None)
    if current is None:
        return {
            "state": next((row["state"] for row in entries if row["task_id"] == task_id), "none"),
            "position": 0,
            "queued_count": sum(row["state"] == "queued" for row in active),
            "running_count": sum(row["state"] == "running" for row in active),
            "kind": next((row["kind"] for row in entries if row["task_id"] == task_id), ""),
        }
    position = (1 + sum(row["state"] == "queued" and task_lane(row["kind"]) == task_lane(current["kind"]) for row in active[:active.index(current)])) if current["state"] == "queued" else 0
    return {
        "state": current["state"],
        "position": position,
        "queued_count": sum(row["state"] == "queued" for row in active),
        "running_count": sum(row["state"] == "running" for row in active),
        "kind": current["kind"],
        "lane": task_lane(current["kind"]),
        "lane_pending_limit": LANE_PENDING_LIMIT,
        "lane_concurrency": lane_budgets()[task_lane(current["kind"])],
        "lane_budgets": dict(lane_budgets()),
        "paused": paused,
        "priority": current.get("priority", 0),
    }
