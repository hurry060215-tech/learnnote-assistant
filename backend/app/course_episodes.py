"""Durable source-bound episode handoffs; no network/model calls.

Reserve before submission, then reconcile a lost browser acknowledgement from
persisted task manifests. Existing task endpoints retain scheduler ownership.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import re
import sqlite3

from .config import DATA_DIR, ensure_dirs
from .course_state import lock as _lock, read_course, require_current_course
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
        source = normalize_source_input(url)
        identity = task.source_identity
        return (normalize_source_input(task.page_url).url == source.url
                and (not identity.page_url or normalize_source_input(identity.page_url).url == source.url)
                and (not identity.platform or identity.platform == source.platform)
                and (not identity.platform_id or identity.platform_id == source.source_id))
    except (ValueError, TypeError):
        return False


def _same_url(left, right):
    try:
        return normalize_source_input(left).url == normalize_source_input(right).url
    except (ValueError, TypeError):
        return False


def _shareable(task):
    # Course batches currently submit whole videos in text mode. Do not merge
    # browser handoffs, local files, ranged work, or a different learning mode.
    return (bool(re.fullmatch(r"course-[a-f0-9]{40}", task.handoff_id))
            and task.source_type == "current_page" and task.mode == "video"
            and not task.learning_range and task.options.content_mode == "text"
            and not task.options.visual_understanding)


def _can_link(task, episode, *, bound=False):
    return (_same_source(task, episode["url"])
            and task.source_type == "current_page" and task.mode == "video" and not task.learning_range
            and (task.handoff_id == episode["handoff_id"] or _shareable(task)
                 or (bound and bool(re.fullmatch(r"course-[a-f0-9]{40}", task.handoff_id)))))


def _resolve_task(episode, linked, tasks, shared_links):
    if linked:
        try:
            task = get_task(linked)
        except FileNotFoundError:
            task = None
        if task:
            if task.id != linked or (episode["url"] and not _can_link(task, episode, bound=True)):
                raise ValueError("course_episode_identity_conflict")
            if episode["url"] and sum(item.handoff_id == task.handoff_id for item in tasks) > 1:
                raise ValueError("course_episode_identity_conflict")
            return task
    if not episode["url"]:
        return None
    # An exact legacy handoff remains authoritative; historical duplicates
    # with different handoffs are retained, never merged or removed.
    matches = [task for task in tasks if task.handoff_id == episode["handoff_id"]]
    if not matches:
        # list_tasks intentionally skips unreadable manifests. A known binding
        # to this source must still be checked before creating a replacement.
        for task_id in shared_links:
            try:
                shared = get_task(task_id)
            except FileNotFoundError:
                continue
            if shared.id != task_id or not _same_source(shared, episode["url"]):
                raise ValueError("course_episode_identity_conflict")
        matches = [task for task in tasks if _shareable(task) and _same_url(task.page_url, episode["url"])]
    if len(matches) > 1 or (matches and not _can_link(matches[0], episode)):
        raise ValueError("course_episode_identity_conflict")
    if matches and sum(task.handoff_id == matches[0].handoff_id for task in tasks) > 1:
        raise ValueError("course_episode_identity_conflict")
    if matches:
        # A parsed manifest may claim another task's ID. Resolve that ID back
        # through its own directory before projecting or authorizing deletion.
        # Do not silently skip an unreadable/mismatched candidate and create a
        # replacement: that would lose the original source identity.
        try:
            canonical = get_task(matches[0].id)
        except FileNotFoundError as exc:
            raise ValueError("course_episode_identity_conflict") from exc
        identity_fields = ("id", "created_at", "source_type", "page_url", "handoff_id", "mode", "learning_range")
        if any(getattr(canonical, key) != getattr(matches[0], key) for key in identity_fields) or not _can_link(canonical, episode):
            raise ValueError("course_episode_identity_conflict")
        return canonical
    return matches[0] if matches else None


def _projection(episode, task):
    return {**episode, "task_id": task.id, "status": task.status, "checkpoint": task.checkpoint,
            "progress": task.progress, "error_code": task.error_code, "retry_count": task.retry_count,
            "retryable": task.status in {"failed", "cancelled", "interrupted"},
            "resume_endpoint": f"/api/tasks/{task.id}/resume",
            "resource_budget_mb": task.options.resource_budget_mb, "content_mode": task.options.content_mode}


def course_episodes(course):
    episodes = [_episode(course["id"], source, index) for index, source in enumerate(course["sources"]) if source["kind"] in {"url", "task"}]
    rows = {}
    shared_links = {}
    path = DATA_DIR / "course-episodes.sqlite3"
    if path.exists():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            db.row_factory = sqlite3.Row
            rows = {row["episode_id"]: dict(row) for row in db.execute("SELECT * FROM course_episodes WHERE course_id=?", (course["id"],))}
            urls = [episode["url"] for episode in episodes if episode["url"]]
            if urls:
                placeholders = ",".join("?" for _ in urls)
                for row in db.execute(f"SELECT source_url,task_id FROM course_episodes WHERE source_url IN ({placeholders}) AND task_id<>''", urls):
                    shared_links.setdefault(row["source_url"], set()).add(row["task_id"])
    tasks = list_tasks(read_only=True) if any(item["url"] for item in episodes) else []
    result = []
    for episode in episodes:
        linked = rows.get(episode["episode_id"], {}).get("task_id") or episode["task_id"]
        row = rows.get(episode["episode_id"])
        try:
            if row and (row["source_url"] != episode["url"] or row["handoff_id"] != episode["handoff_id"]):
                raise ValueError("course_episode_identity_conflict")
            task = _resolve_task(episode, linked, tasks, shared_links.get(episode["url"], ()))
        except (ValueError, OSError) as exc:
            status = "identity_conflict" if str(exc) == "course_episode_identity_conflict" else "source_unreadable"
            result.append({**episode, "status": status, "task_id": "", "retryable": False})
            continue
        result.append(_projection(episode, task) if task else {**episode, "status": "source_missing" if linked else "pending", "task_id": "", "retryable": False})
    return result


def prepared_course_handoff(request):
    """Resolve a reserved course handoff under the caller's submission lock.

    Keep the existing UNIQUE per-course handoff rows and task manifests intact.
    The shared task, rather than a new alias table or changed ID, is the durable
    reuse identity. Ordinary current-page submissions retain their own rules.
    """
    path = DATA_DIR / "course-episodes.sqlite3"
    if not request.handoff_id.startswith("course-"):
        return False, None
    if not path.exists():
        raise ValueError("course_episode_identity_conflict")
    with _lock:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM course_episodes WHERE handoff_id=?", (request.handoff_id,)).fetchone()
        if row is None:
            # A removed course/reservation cannot turn a delayed course batch
            # into a fresh ordinary handoff after the user cancelled its scope.
            raise ValueError("course_episode_identity_conflict")
        if (request.page_url != row["source_url"] or request.mode != "video" or request.learning_range
                or request.options.content_mode != "text" or request.options.visual_understanding
                or request.resources or request.active_video or request.browser_subtitles or request.page_text
                or request.cookies or request.drm_detected or request.drm_signals):
            raise ValueError("course_episode_identity_conflict")
        course = read_course(DATA_DIR, row["course_id"])
        if course["paused"]:
            raise ValueError("course_paused")
        episode = next((item for item in course_episodes(course) if item["episode_id"] == row["episode_id"]), None)
        if episode is None or episode["handoff_id"] != request.handoff_id:
            raise ValueError("course_episode_identity_conflict")
        if episode["status"] in {"identity_conflict", "source_unreadable"}:
            raise ValueError("course_episode_identity_conflict")
        return True, get_task(episode["task_id"]) if episode["task_id"] else None


def _write_link(db, course_id, episode, task_id):
    db.execute("""INSERT INTO course_episodes(course_id,episode_id,source_url,handoff_id,task_id,updated_at)
        VALUES (?,?,?,?,?,?) ON CONFLICT(course_id,episode_id)
        DO UPDATE SET task_id=excluded.task_id,updated_at=excluded.updated_at""",
        (course_id, episode["episode_id"], episode["url"], episode["handoff_id"], task_id, datetime.now(timezone.utc).isoformat()))


def prepare_course_episode(course, episode_id):
    with _lock:
        require_current_course(DATA_DIR, course)
        return _prepare_course_episode(course, episode_id)


def _prepare_course_episode(course, episode_id):
    if course["paused"]:
        raise ValueError("course_paused")
    episode = next((item for item in course_episodes(course) if item["episode_id"] == episode_id), None)
    if episode is None:
        raise ValueError("course_episode_not_found")
    if episode["status"] in {"identity_conflict", "source_unreadable"}:
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
                    if not _can_link(current, episode, bound=True):
                        raise ValueError("course_episode_identity_conflict")
                    episode = _projection(episode, current)
            _write_link(db, course["id"], episode, episode["task_id"])
            db.commit()
    return {**episode, "prepared": True, "new_submission_required": not bool(episode["task_id"])}


def bind_course_episode(course, episode_id, task_id):
    with _lock:
        require_current_course(DATA_DIR, course)
        return _bind_course_episode(course, episode_id, task_id)


def _bind_course_episode(course, episode_id, task_id):
    episodes = course_episodes(course)
    episode = next((item for item in episodes if item["episode_id"] == episode_id), None)
    if episode is None:
        raise ValueError("course_episode_not_found")
    task = get_task(task_id)
    if episode["source_kind"] == "task":
        if episode["task_id"] != task.id:
            raise ValueError("course_episode_identity_conflict")
        return _projection(episode, task)
    if episode["status"] in {"identity_conflict", "source_unreadable"} or not _can_link(task, episode, bound=episode["task_id"] == task.id):
        raise ValueError("course_episode_identity_conflict")
    if episode["task_id"] and episode["task_id"] != task.id:
        raise ValueError("course_episode_already_bound")
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
