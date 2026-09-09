"""Bounded single-worker task execution with a local durable intent journal.

Credentials and browser request bodies stay in memory. After a restart, jobs
requiring that context are offered for explicit resume, never silently retried
without authentication or with a different model route.
"""
from __future__ import annotations

from concurrent.futures import Future
from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time
from typing import Callable

from .worker_lease import worker_lease

MAX_PENDING_TASKS = 24


class QueueFull(ValueError):
    pass


class LocalTaskQueue:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "task-queue.sqlite3"
        self.condition = threading.Condition(threading.RLock())
        self.jobs: dict[str, tuple[Callable, Future]] = {}
        self.worker: threading.Thread | None = None
        self.stopping = False
        with closing(self.connect()) as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, requires_context INTEGER NOT NULL, state TEXT NOT NULL, updated_at REAL NOT NULL)")
            db.commit()

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def entries(self) -> list[dict]:
        with closing(self.connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY sequence")]

    def enqueue(self, task_id: str, kind: str, callback: Callable, *, requires_context: bool = False) -> Future:
        with self.condition:
            if self.stopping:
                raise RuntimeError("Task queue is stopping")
            if task_id in self.jobs:
                return self.jobs[task_id][1]
            with closing(self.connect()) as db:
                count = db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
                if count >= MAX_PENDING_TASKS:
                    raise QueueFull("任务队列已满，请等待任务完成后再提交。")
                db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES (?,?,?,'queued',?) ON CONFLICT(task_id) DO UPDATE SET kind=excluded.kind, requires_context=excluded.requires_context, state='queued', updated_at=excluded.updated_at", (task_id, kind, int(requires_context), time.time()))
                db.execute("DELETE FROM jobs WHERE state IN ('done','failed','cancelled') AND sequence NOT IN (SELECT sequence FROM jobs ORDER BY sequence DESC LIMIT 1000)")
                db.commit()
            future = Future()
            self.jobs[task_id] = (callback, future)
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self.run, name="learnnote-task-queue", daemon=True)
                self.worker.start()
            self.condition.notify_all()
            return future

    def set_state(self, task_id: str, state: str):
        with closing(self.connect()) as db:
            db.execute("UPDATE jobs SET state=?,updated_at=? WHERE task_id=?", (state, time.time(), task_id))
            db.commit()

    def run(self):
        while True:
            with self.condition:
                if not self.jobs or self.stopping:
                    self.worker = None
                    return
                task_id = next(iter(self.jobs))
                callback, future = self.jobs[task_id]
                if not future.set_running_or_notify_cancel():
                    self.jobs.pop(task_id, None)
                    self.set_state(task_id, "cancelled")
                    continue
                try:
                    self.set_state(task_id, "running")
                except Exception as exc:
                    self.jobs.pop(task_id, None)
                    future.set_exception(exc)
                    continue
            try:
                with worker_lease(self.root):
                    callback()
                self.set_state(task_id, "done")
            except Exception as exc:
                try:
                    self.set_state(task_id, "failed")
                except sqlite3.Error:
                    pass
                failure = exc
            else:
                failure = None
            finally:
                with self.condition:
                    self.jobs.pop(task_id, None)
            if failure is not None:
                future.set_exception(failure)
            else:
                future.set_result(None)

    def stop(self, timeout: float = 10):
        with self.condition:
            self.stopping = True
            worker = self.worker
        if worker:
            worker.join(timeout)

    def cancel_pending(self, task_id: str) -> bool:
        with self.condition:
            with closing(self.connect()) as db:
                row = db.execute("SELECT state FROM jobs WHERE task_id=?", (task_id,)).fetchone()
            if row is None or row[0] != "queued":
                return False
            self.set_state(task_id, "cancelled")
            job = self.jobs.pop(task_id, None)
            if job:
                if not job[1].done():
                    job[1].set_result(None)
            return True


_queues: dict[Path, LocalTaskQueue] = {}
_lock = threading.RLock()


def queue_for(root: Path) -> LocalTaskQueue:
    key = Path(root).resolve()
    with _lock:
        current = _queues.get(key)
        if current is None or current.stopping:
            current = _queues[key] = LocalTaskQueue(key)
        return current


def cancel_queued_processing(root: Path, task_id: str) -> bool:
    with _lock:
        queue = _queues.get(Path(root).resolve())
    return queue.cancel_pending(task_id) if queue else False


def schedule_processing(background_tasks, function, task_id: str, *args, **kwargs):
    from .models import CurrentPageTaskRequest, TaskOptions
    from .storage import get_task, task_dir, update_task, mark_task_cancelled
    from fastapi import HTTPException
    from .processor_state import TaskCancelled

    queue = queue_for(task_dir(task_id).parent.parent)
    source = args[0] if args else None
    kind = kwargs.pop("_queue_kind", "") or ("page" if isinstance(source, CurrentPageTaskRequest) else "local")
    options = source.options if kind == "page" else next((value for value in args if isinstance(value, TaskOptions)), None)
    needs_context = bool(options and options.llm_api_key)
    if kind == "page":
        needs_context = needs_context or bool(source.cookies or source.resources or source.page_text)

    def work():
        try:
            task = get_task(task_id)
            if task.cancel_requested or task.status == "cancelled":
                mark_task_cancelled(task_id)
                return
            function(task_id, *args, **kwargs)
        except FileNotFoundError:
            return  # Deleting an unstarted task also cancels its queued work.
        except TaskCancelled:
            mark_task_cancelled(task_id)
            return
        except Exception:
            latest = get_task(task_id)
            if latest.cancel_requested or latest.status == "cancelled":
                mark_task_cancelled(task_id)
                return
            update_task(task_id, status="failed", phase="failed", error_code="queued_task_failed", message="处理失败，已保留本地进度，请查看诊断后恢复。")
            raise

    try:
        future = queue.enqueue(task_id, kind, work, requires_context=needs_context)
    except QueueFull as exc:
        update_task(task_id, status="failed", phase="failed", error_code="task_queue_full", message=str(exc))
        raise HTTPException(status_code=429, detail={"code": "task_queue_full", "message": str(exc)}) from exc

    def wait_for_result():
        try:
            future.result()
        except Exception:
            pass  # Failure is persisted on the task and displayed by the UI.
    # The worker owns execution; this preserves response-lifecycle compatibility
    # for existing clients and tests without owning the processing lifetime.
    background_tasks.add_task(wait_for_result)


def recover_processing(root: Path) -> dict[str, int]:
    with worker_lease(root, blocking=False) as acquired:
        if not acquired:
            return {"recovered": 0, "waiting_for_context": 0, "another_worker_active": 1}
        return _recover_processing(root)


def _recover_processing(root: Path) -> dict[str, int]:
    from .storage import get_task, update_task, mark_task_cancelled
    from .processor import process_local_video_task, process_current_page_task
    from .models import CurrentPageTaskRequest

    queue = queue_for(root)
    recovered = waiting = 0
    for row in queue.entries():
        if row["task_id"] in queue.jobs:
            continue
        if row["state"] not in {"queued", "running"}:
            continue
        try:
            task = get_task(row["task_id"])
        except FileNotFoundError:
            queue.set_state(row["task_id"], "cancelled")
            continue
        if task.cancel_requested:
            mark_task_cancelled(task.id)
            queue.set_state(task.id, "cancelled")
            continue
        if task.status in {"success", "failed", "cancelled"}:
            queue.set_state(task.id, "done")
            continue
        if row["requires_context"]:
            queue.set_state(task.id, "waiting_context")
            update_task(task.id, status="failed", phase="failed", error_code="resume_context_required", message="进度已保存；请重新确认模型或从原网页发送，以恢复需要登录信息的任务。")
            waiting += 1
            continue
        if row["kind"] == "summary":
            from .processor import process_saved_transcript_task
            callback = lambda task=task: process_saved_transcript_task(task.id, task.options)
        elif row["kind"] in {"local", "range"}:
            path = Path(task.source_media_path or task.media_path or "")
            if not path.is_file() or not path.resolve().is_relative_to(Path(root).resolve()):
                queue.set_state(task.id, "waiting_context")
                update_task(task.id, status="failed", phase="failed", error_code="resume_source_required", message="原媒体不在当前数据目录，请重新选择原文件恢复。")
                waiting += 1
                continue
            if row["kind"] == "range":
                from .range_learning import process_range_task
                callback = lambda task=task, path=path: process_range_task(task.id, path, task.title, task.options)
            else:
                callback = lambda task=task, path=path: process_local_video_task(
                    task.id, path, task.title, task.options, page_url=task.page_url,
                    browser_subtitles=task.browser_subtitles,
                    subtitle_path=Path(task.subtitle_path) if task.subtitle_path else None,
                    subtitle_source="browser-subtitle" if task.browser_subtitles else "page-subtitle")
        else:
            request = CurrentPageTaskRequest(page_url=task.page_url, title=task.title, options=task.options,
                mode=task.mode, browser_subtitles=task.browser_subtitles, active_video=task.active_video,
                drm_detected=task.drm_detected, drm_signals=task.drm_signals)
            callback = lambda task=task, request=request: process_current_page_task(task.id, request)
        # Reset the orphaned lease before re-enqueueing the original task ID.
        queue.set_state(task.id, "recovering")
        queue.enqueue(task.id, row["kind"], callback)
        recovered += 1
    return {"recovered": recovered, "waiting_for_context": waiting}
