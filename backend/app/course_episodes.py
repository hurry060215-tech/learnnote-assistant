"""Durable source-bound episode handoffs; no network/model calls.

Reserve before submission, then reconcile a lost browser acknowledgement from
persisted task manifests. Existing task endpoints retain scheduler ownership.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import sqlite3

from .config import DATA_DIR, ensure_dirs
from .source_input import normalize_source_input
from .storage import get_task, list_tasks


def _connect():
    ensure_dirs()
    db = sqlite3.connect(DATA_DIR / "course-episodes.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS course_episodes (
        course_id TEXT NOT NULL, episode_id TEXT NOT NULL, source_url TEXT NOT NULL,
        handoff_id TEXT NOT NULL, task_id TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
        PRIMARY KEY(course_id,episode_id), UNIQUE(handoff_id))""")
    db.commit()
    return db


def _episode(course_id, source, position):
    key = f"{source['kind']}:{source.get('url') if source['kind'] == 'url' else source.get('id')}"
    url = source.get("url", "") if source["kind"] == "url" else ""
    return {"episode_id": hashlib.sha256(key.encode()).hexdigest()[:24], "position": position,
            "source_kind": source["kind"], "source_id": source.get("id", ""), "url": url,
            "title": source.get("title", ""),
            "handoff_id": "course-" + hashlib.sha256(f"{course_id}:{url}".encode()).hexdigest()[:40] if url else "",
            "task_id": source.get("id", "") if source["kind"] == "task" else ""}


def _same_source(task, url):
    try:
        return normalize_source_input(task.page_url).url == normalize_source_input(url).url
    except (ValueError, TypeError):
        return False


def _projection(episode, task):
    return {**episode, "task_id": task.id, "status": task.status, "checkpoint": task.checkpoint,
            "progress": task.progress, "error_code": task.error_code, "retry_count": task.retry_count,
            "retryable": task.status in {"failed", "cancelled", "interrupted"},
            "resume_endpoint": f"/api/tasks/{task.id}/resume",
            "resource_budget_mb": task.options.resource_budget_mb, "content_mode": task.options.content_mode}


def course_episodes(course, *, read_only=False):
    episodes = [_episode(course["id"], source, index) for index, source in enumerate(course["sources"]) if source["kind"] in {"url", "task"}]
    path = DATA_DIR / "course-episodes.sqlite3"
    rows = {}
    if not read_only or path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) if read_only else _connect()) as db:
            db.row_factory = sqlite3.Row
            rows = {row["episode_id"]: dict(row) for row in db.execute("SELECT * FROM course_episodes WHERE course_id=?", (course["id"],))}
    by_handoff = {}
    if any(item["url"] and not rows.get(item["episode_id"], {}).get("task_id") for item in episodes):
        for task in list_tasks():
            if task.handoff_id:
                by_handoff.setdefault(task.handoff_id, []).append(task)
    result = []
    for episode in episodes:
        linked = rows.get(episode["episode_id"], {}).get("task_id") or episode["task_id"]
        task = None
        if linked:
            try:
                task = get_task(linked)
            except FileNotFoundError:
                pass
        matches = by_handoff.get(episode["handoff_id"], []) if not task else []
        conflict = task and episode["url"] and (task.handoff_id != episode["handoff_id"] or not _same_source(task, episode["url"]))
        if conflict or len(matches) > 1 or (matches and not _same_source(matches[0], episode["url"])):
            result.append({**episode, "status": "identity_conflict", "task_id": "", "retryable": False})
            continue
        task = task or (matches[0] if matches else None)
        result.append(_projection(episode, task) if task else {**episode, "status": "source_missing" if linked else "pending", "task_id": "", "retryable": False})
    return result


def _write_link(db, course_id, episode, task_id):
    db.execute("""INSERT INTO course_episodes(course_id,episode_id,source_url,handoff_id,task_id,updated_at)
        VALUES (?,?,?,?,?,?) ON CONFLICT(course_id,episode_id)
        DO UPDATE SET task_id=excluded.task_id,updated_at=excluded.updated_at""",
        (course_id, episode["episode_id"], episode["url"], episode["handoff_id"], task_id, datetime.now(timezone.utc).isoformat()))


def prepare_course_episode(course, episode_id):
    if course["paused"]:
        raise ValueError("course_paused")
    episode = next((item for item in course_episodes(course) if item["episode_id"] == episode_id), None)
    if episode is None:
        raise ValueError("course_episode_not_found")
    if episode["status"] == "identity_conflict":
        raise ValueError("course_episode_identity_conflict")
    if episode["source_kind"] == "url":
        with closing(_connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT task_id FROM course_episodes WHERE course_id=? AND episode_id=?", (course["id"], episode_id)).fetchone()
            # A slow prepare must not erase a bind committed after its read.
            if row and row["task_id"] and not episode["task_id"]:
                try:
                    current = get_task(row["task_id"])
                except FileNotFoundError:
                    pass
                else:
                    if current.handoff_id != episode["handoff_id"] or not _same_source(current, episode["url"]):
                        raise ValueError("course_episode_identity_conflict")
                    episode = _projection(episode, current)
            _write_link(db, course["id"], episode, episode["task_id"])
            db.commit()
    return {**episode, "prepared": True, "new_submission_required": not bool(episode["task_id"])}


def bind_course_episode(course, episode_id, task_id):
    episodes = [_episode(course["id"], source, index) for index, source in enumerate(course["sources"]) if source["kind"] in {"url", "task"}]
    episode = next((item for item in episodes if item["episode_id"] == episode_id), None)
    if episode is None:
        raise ValueError("course_episode_not_found")
    task = get_task(task_id)
    if episode["source_kind"] == "task":
        if episode["task_id"] != task.id:
            raise ValueError("course_episode_identity_conflict")
        return _projection(episode, task)
    if task.handoff_id != episode["handoff_id"] or not _same_source(task, episode["url"]):
        raise ValueError("course_episode_identity_conflict")
    with closing(_connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT task_id FROM course_episodes WHERE course_id=? AND episode_id=?", (course["id"], episode_id)).fetchone()
        if row and row["task_id"] and row["task_id"] != task.id:
            try:
                get_task(row["task_id"])
            except FileNotFoundError:
                pass
            else:
                raise ValueError("course_episode_already_bound")
        _write_link(db, course["id"], episode, task.id)
        db.commit()
    return _projection(episode, task)


def clear_course_episode_links(course_id):
    if not (DATA_DIR / "course-episodes.sqlite3").exists():
        return
    with closing(_connect()) as db:
        db.execute("DELETE FROM course_episodes WHERE course_id=?", (course_id,))
        db.commit()
