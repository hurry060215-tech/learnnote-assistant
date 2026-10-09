"""Review course deletion against current local identities; never delete implicitly."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from . import courses, storage, library
from .course_episodes import course_episodes


def _task_references(course):
    """Include resolved URL handoffs and task-backed library aliases."""
    ids = {source["id"] for source in course["sources"] if source["kind"] == "task"}
    episodes = course_episodes(course)
    if any(item["status"] in {"identity_conflict", "source_unreadable"} for item in episodes):
        raise ValueError("course_episode_identity_conflict")
    ids.update(item["task_id"] for item in episodes if item.get("task_id"))
    material_ids = {source["id"] for source in course["sources"] if source["kind"] == "material"}
    if material_ids:
        # The regular material getter initializes/migrates its index. A review
        # must not write even when the user will immediately press Cancel.
        with closing(sqlite3.connect(library._db_path().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            placeholders = ",".join("?" for _ in material_ids)
            rows = db.execute(f"SELECT material_id,linked_task_id FROM library_materials WHERE material_id IN ({placeholders})", tuple(material_ids)).fetchall()
        if {row[0] for row in rows} != material_ids:
            raise ValueError("course_material_unavailable")
        ids.update(row[1] for row in rows if row[1])
    return ids


def _busy_tasks():
    path = courses.DATA_DIR / "task-queue.sqlite3"
    if not path.exists():
        return set()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        return {row[0] for row in db.execute("SELECT task_id FROM jobs WHERE state IN ('queued','running','recovering')")}


def _dependency_owners():
    """Protect source media/evidence still needed by any retained task."""
    owners = set()
    root = storage.TASK_DIR.resolve()
    for path in storage.TASK_DIR.glob("*/task.json"):
        task = storage.get_task(path.parent.name)
        if task.id != path.parent.name:
            raise ValueError("task_identity_conflict")
        if task.source_task_id and task.source_task_id != task.id:
            owners.add(task.source_task_id)
        for key, value in task.model_dump().items():
            if key.endswith("_path") and isinstance(value, str) and value:
                resolved = Path(value).resolve()
                if resolved.is_relative_to(root):
                    relative = resolved.relative_to(root)
                    if relative.parts and relative.parts[0] != task.id:
                        owners.add(relative.parts[0])
    return owners


def _preview(course_id):
    course = courses.get_course(course_id)
    episodes = course_episodes(course)
    shared = set()
    references_verified = True
    for path in (courses.DATA_DIR / "courses").glob("*.json"):
        if path.stem == course_id:
            continue
        try:
            shared.update(_task_references(courses.get_course(path.stem)))
        except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
            # An unreadable course may own a selected task. Do not guess.
            references_verified = False
    try:
        busy = _busy_tasks()
        dependency_owners = _dependency_owners()
    except (ValueError, OSError, sqlite3.Error):
        busy = set()
        dependency_owners = set()
        references_verified = False
    tasks = {}
    unlinked = []
    identities = []
    for episode in episodes:
        task_id = episode.get("source_id") if episode["source_kind"] == "task" else episode.get("task_id")
        if not task_id:
            unlinked.append({"episode_id": episode["episode_id"], "title": episode["title"], "status": episode["status"]})
            continue
        if task_id in tasks:
            continue
        reason = ""
        title = episode["title"]
        task_status = "source_missing"
        try:
            task = storage.get_task(task_id)
            title, task_status = task.title, task.status
            if task.id != task_id:
                reason = "identity_conflict"
            identities.append({"id": task.id, "created_at": task.created_at, "updated_at": task.updated_at, "page_url": task.page_url,
                               "handoff_id": task.handoff_id, "source_type": task.source_type,
                               "source_media_path": task.source_media_path})
        except FileNotFoundError:
            reason = "source_missing"
        except (OSError, ValueError):
            reason = "source_unreadable"
        if not reason:
            reason = ("shared_task" if task_id in shared else
                      "dependent_task" if task_id in dependency_owners else
                      "active_task" if task_status in {"queued", "running", "cancelling"} else
                      "busy_task" if task_id in busy else
                      "references_unavailable" if not references_verified else "")
        tasks[task_id] = {"task_id": task_id, "title": title, "status": task_status,
                          "eligible": not bool(reason), "reason": reason}
    snapshot = {"course": course, "tasks": list(tasks.values()), "unlinked": unlinked, "identities": identities}
    token = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"course_id": course_id, "title": course["title"], "revision": course["revision"],
            "snapshot": token, "tasks": list(tasks.values()), "unlinked": unlinked,
            "material_count": sum(source["kind"] == "material" for source in course["sources"])}


def preview_course_deletion(course_id):
    with courses._lock, storage._lock:
        return _preview(course_id)


def delete_reviewed_course(course_id, *, revision, snapshot, task_ids):
    # Same lock order as course saves/bindings. Task transitions cannot race the
    # eligibility check; course saves/binds cannot create new shared references.
    with courses._lock, storage._lock:
        preview = _preview(course_id)
        if preview["revision"] != revision or preview["snapshot"] != snapshot:
            raise ValueError("course_deletion_changed_reload_required")
        selected = list(dict.fromkeys(task_ids))
        allowed = {item["task_id"] for item in preview["tasks"] if item["eligible"]}
        if not set(selected).issubset(allowed):
            raise ValueError("course_deletion_ineligible_task")
        outcomes = []
        for task_id in selected:
            try:
                result = storage.delete_task(task_id)
                outcomes.append({"task_id": task_id, "deleted": True, "reclaimed_bytes": result["reclaimed_bytes"]})
            except Exception as exc:
                # Filesystem/index deletion is not an atomic transaction. Keep
                # the course for review/retry and report every attempted task.
                present = storage.task_file(task_id).exists()
                code = "task_cleanup_failed"
                if str(exc) == "active_task":
                    code = "active_task"
                elif str(exc) == "task_index_cleanup_failed":
                    code = "task_index_cleanup_failed"
                outcomes.append({"task_id": task_id, "deleted": not present, "error": code})
        course_deleted = False
        error = ""
        if not any(item.get("error") for item in outcomes):
            try:
                courses.delete_course(course_id)
                course_deleted = True
            except (OSError, ValueError, sqlite3.Error):
                course_deleted = not courses._path(course_id).exists()
                error = "course_cleanup_failed"
        else:
            error = "child_cleanup_incomplete"
        deleted = [item["task_id"] for item in outcomes if item["deleted"]]
        return {"deleted": course_deleted, "sources_deleted": bool(deleted), "deleted_task_ids": deleted,
                "task_outcomes": outcomes, "error": error}
