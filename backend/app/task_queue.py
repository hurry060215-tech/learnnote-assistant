"""Independent bounded heavy/light/download lanes with a local durable intent journal.

Credentials and browser request bodies stay in memory. After a restart, jobs
requiring that context are offered for explicit resume, never silently retried
without authentication or with a different model route.
"""
from __future__ import annotations

from concurrent.futures import Future
from contextlib import closing, ExitStack
from pathlib import Path
import sqlite3
import threading
import time
from typing import Callable

from .worker_lease import worker_lease
from .pipeline_timing import queued_callback
from .observability import record_task_event
from .queue_policy import LANES, lane_budgets
from .queue_controls import initialize_queue_schema, ordered_entries, queue_candidates

MAX_PENDING_TASKS = 24
LIGHT_TASK_KINDS = {"light", "summary", "local_light", "page_light"}
LANE_PENDING_LIMIT = 12


def task_lane(kind: str) -> str:
    if kind == "page_download":
        return "download"
    return "light" if kind in LIGHT_TASK_KINDS else "heavy"


class QueueFull(ValueError):
    pass


class LocalTaskQueue:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "task-queue.sqlite3"
        self.condition = threading.Condition(threading.RLock())
        self.jobs: dict[str, tuple[Callable, Future]] = {}
        self.observers: dict[str, Future] = {}
        self.generations: dict[str, str] = {}
        self.observer_generations: dict[str, str] = {}
        self.workers: dict[str, threading.Thread] = {}
        self.stopping = False
        self.closing = False
        self.concurrency = lane_budgets()
        with closing(self.connect()) as db:
            initialize_queue_schema(db)
            db.commit()

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def entries(self) -> list[dict]:
        with closing(self.connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY sequence")]

    def enqueue(self, task_id: str, kind: str, callback: Callable, *, requires_context: bool = False, generation: str = "") -> Future:
        with self.condition:
            if self.stopping or self.closing:
                raise RuntimeError("Task queue is stopping")
            if task_id in self.jobs:
                if self.generations.get(task_id, "") == generation:
                    return self.jobs[task_id][1]
                if (self._job_row(task_id) or {}).get("state") in {"queued", "running"}:
                    raise RuntimeError("Task generation is still active")
                previous = self.jobs.pop(task_id)[1]
                if not previous.running() and not previous.done():
                    previous.set_result(None)
            if task_id in self.observers and self.observer_generations.get(task_id, "") == generation:
                return self.observers[task_id]
            with closing(self.connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute("SELECT state,generation FROM jobs WHERE task_id=?", (task_id,)).fetchone()
                if existing and existing[0] in {"queued", "running"}:
                    if existing[1] != generation:
                        raise RuntimeError("Task generation is still active")
                    # Another process owns this intent. Observe it, never replace it.
                    future = Future()
                    self.observers[task_id] = future
                    self.observer_generations[task_id] = generation
                    threading.Thread(target=self._observe, args=(task_id, future, generation), daemon=True).start()
                    return future
                count = db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
                if count >= MAX_PENDING_TASKS:
                    raise QueueFull("任务队列已满，请等待任务完成后再提交。")
                kinds = db.execute("SELECT kind FROM jobs WHERE state IN ('queued','running')").fetchall()
                lane = task_lane(kind)
                if sum(task_lane(row[0]) == lane for row in kinds) >= LANE_PENDING_LIMIT:
                    raise QueueFull("此类任务的队列已满，其他类型任务仍可提交。")
                db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at,generation,callback_finished) VALUES (?,?,?,'queued',?,?,0) ON CONFLICT(task_id) DO UPDATE SET kind=excluded.kind, requires_context=excluded.requires_context, state='queued', updated_at=excluded.updated_at, generation=excluded.generation, cancel_operation_id='', callback_finished=0", (task_id, kind, int(requires_context), time.time(), generation))
                db.execute("DELETE FROM jobs WHERE state IN ('done','failed','cancelled') AND sequence NOT IN (SELECT sequence FROM jobs ORDER BY sequence DESC LIMIT 1000)")
                db.commit()
            future = Future()
            self.jobs[task_id] = (queued_callback(task_id, callback), future)
            self.generations[task_id] = generation
            try:
                record_task_event(task_id, "task_enqueued", phase="queue", status="queued")
            except Exception:
                pass  # The durable queue intent must still dispatch if optional logging fails.
            for slot in range(self.concurrency[lane]):
                worker_key = f"{lane}:{slot}"
                worker = self.workers.get(worker_key)
                if worker is None or not worker.is_alive():
                    worker = threading.Thread(target=self.run, args=(lane, slot), name=f"learnnote-task-queue-{worker_key}", daemon=True)
                    self.workers[worker_key] = worker
                    worker.start()
            self.condition.notify_all()
            return future

    def set_state(self, task_id: str, state: str, *, generation: str | None = None, callback_finished: bool | None = None):
        with closing(self.connect()) as db:
            where = "task_id=?" + (" AND generation=?" if generation is not None else "")
            args = [state, time.time(), callback_finished, task_id]
            if generation is not None:
                args.append(generation)
            db.execute(f"UPDATE jobs SET state=?,updated_at=?,callback_finished=? WHERE {where}", args)
            db.commit()

    def _observe(self, task_id, future, generation):
        # Cancelling an observer must not cancel another process's task.
        try:
            if not future.set_running_or_notify_cancel():
                return
            while not self.stopping:
                row = self._job_row(task_id)
                if not row or row.get("generation", "") != generation or row["state"] in {"done", "cancelled"}:
                    future.set_result(None)
                    return
                if row["state"] in {"failed", "waiting_context"}:
                    raise RuntimeError("Existing task requires recovery")
                time.sleep(.05)
            raise RuntimeError("Task queue is stopping")
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
        finally:
            with self.condition:
                if self.observers.get(task_id) is future:
                    self.observers.pop(task_id, None)
                    self.observer_generations.pop(task_id, None)

    def _claim(self, task_id, lane):
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            waiting = queue_candidates(db)
            first = next((row[0] for row in waiting if task_lane(row[1]) == lane), None)
            if first != task_id:
                return False
            changed = db.execute("UPDATE jobs SET state='running',updated_at=? WHERE task_id=? AND state='queued' AND generation=?", (time.time(), task_id, self.generations.get(task_id, ""))).rowcount
            db.commit()
            return bool(changed)

    def run(self, lane, slot=0):
        worker_key = f"{lane}:{slot}"
        while True:
            with self.condition:
                eligible = []
                for key, (_, future) in list(self.jobs.items()):
                    row = self._job_row(key) or {}
                    if row.get("generation", "") != self.generations.get(key, ""):
                        self.jobs.pop(key, None)
                        self.generations.pop(key, None)
                        if not future.running() and not future.done():
                            future.set_result(None)
                        continue
                    if task_lane(row.get("kind", "")) != lane:
                        continue
                    if row.get("state") == "queued":
                        eligible.append(key)
                    elif row.get("state") != "running" and not future.running():
                        self.jobs.pop(key, None)
                        self.generations.pop(key, None)
                        if not future.done():
                            future.set_result(None)
                rank = {row["task_id"]: index for index, row in enumerate(ordered_entries(self.entries()))}
                eligible.sort(key=lambda key: rank.get(key, len(rank)))
                if not eligible or self.stopping:
                    self.workers.pop(worker_key, None)
                    return
            # Waiting on another process is still queued and immediately cancellable.
            with worker_lease(self.root, blocking=False, lane=lane, slot=slot) as acquired:
                with self.condition:
                    task_id = next((key for key in eligible if key in self.jobs), None)
                    claimed = acquired and task_id and self._claim(task_id, lane)
                    if claimed:
                        callback, future = self.jobs[task_id]
                        generation = (self._job_row(task_id) or {}).get("generation", "")
                        if not future.set_running_or_notify_cancel():
                            self.jobs.pop(task_id, None)
                            self.generations.pop(task_id, None)
                            self.set_state(task_id, "cancelled", generation=generation, callback_finished=False)
                            continue
                if claimed:
                    try:
                        callback()
                        self.set_state(task_id, "done", generation=generation, callback_finished=True)
                    except Exception as exc:
                        try:
                            self.set_state(task_id, "failed", generation=generation, callback_finished=True)
                        except sqlite3.Error:
                            pass
                        failure = exc
                    else:
                        failure = None
                    finally:
                        with self.condition:
                            if self.jobs.get(task_id) == (callback, future):
                                self.jobs.pop(task_id, None)
                                self.generations.pop(task_id, None)
            if not claimed:
                # Never sleep while holding a slot needed by an older intent
                # in another process. Windows mutex reacquisition can starve it.
                with self.condition:
                    self.condition.wait(.05)
                continue
            if failure is not None:
                future.set_exception(failure)
            else:
                future.set_result(None)

    def _job_row(self, task_id: str) -> dict | None:
        with closing(self.connect()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM jobs WHERE task_id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    def stop(self, timeout: float = 10):
        with self.condition:
            self.closing = True
            workers = list(self.workers.values())
        deadline = time.monotonic() + timeout
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))
        self.stopping = True

    def cancel_pending(self, task_id: str) -> bool:
        with self.condition:
            with closing(self.connect()) as db:
                changed = db.execute("UPDATE jobs SET state='cancelled',updated_at=? WHERE task_id=? AND state='queued'", (time.time(), task_id)).rowcount
                db.commit()
            if not changed:
                return False
            job = self.jobs.pop(task_id, None)
            self.generations.pop(task_id, None)
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


def queue_status(root: Path, task_id: str) -> dict[str, object]:
    """Return a durable, privacy-safe queue snapshot for one task."""

    rows, paused = read_queue_entries(root)
    if rows and rows[0].get("state") == "unknown":
        return {"state": "unknown", "position": 0, "queued_count": 0, "running_count": 0, "kind": ""}
    entries = ordered_entries(rows)
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


def schedule_processing(background_tasks, function, task_id: str, *args, **kwargs):
    from .models import CurrentPageTaskRequest, TaskOptions
    from .storage import get_task, task_dir, update_task, mark_task_cancelled, task_state_transaction
    from .task_control_state import task_generation
    from fastapi import HTTPException
    from .processor_state import TaskCancelled

    queue = queue_for(task_dir(task_id).parent.parent)
    source = args[0] if args else None
    explicit_kind = kwargs.pop("_queue_kind", "")
    kind = explicit_kind or ("page" if isinstance(source, CurrentPageTaskRequest) else "local")
    options = source.options if kind == "page" else next((value for value in args if isinstance(value, TaskOptions)), None)
    needs_context = bool(options and options.llm_api_key)
    if kind == "page":
        needs_context = needs_context or bool(source.cookies or source.resources or source.page_text)
    if not explicit_kind:
        if isinstance(source, CurrentPageTaskRequest) and source.mode == "download_only":
            kind = "page_download"
        elif (isinstance(source, CurrentPageTaskRequest) and source.mode == "subtitle_only") or (options and options.content_mode == "subtitles"):
            kind = "page_light" if isinstance(source, CurrentPageTaskRequest) else "local_light"

    generation = task_generation(get_task(task_id))

    def work():
        try:
            task = get_task(task_id)
            if task_generation(task) != generation:
                return
            if task.cancel_requested or task.status == "cancelled":
                mark_task_cancelled(task_id)
                return
            function(task_id, *args, **kwargs)
            if get_task(task_id).cancel_requested:
                mark_task_cancelled(task_id, expected_generation=generation)
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
        with task_state_transaction():
            latest = get_task(task_id)
            if task_generation(latest) != generation:
                return
            if latest.cancel_requested:
                row = read_queue_job(queue.root, task_id)
                if row is None or (row.get("generation") != generation and row.get("state") in {"done", "failed", "cancelled", "waiting_context"}):
                    from .models import TaskCancellationReceipt, now_iso
                    receipt = latest.cancellation_receipt.model_copy(deep=True)
                    if receipt.generation != generation:
                        receipt = TaskCancellationReceipt(generation=generation, requested_at=latest.cancel_requested_at)
                    receipt.dispatch_prevented_at = now_iso()
                    update_task(task_id, status="cancelled", phase="cancelled", cancelled_at=now_iso(),
                                message="已在提交处理前取消，现有文件保留", cancellation_receipt=receipt)
                return
            future = queue.enqueue(task_id, kind, work, requires_context=needs_context, generation=generation)
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
    with ExitStack() as stack:
        for lane in LANES:
            for slot in range(4):
                if not stack.enter_context(worker_lease(root, blocking=False, lane=lane, slot=slot)):
                    return {"recovered": 0, "waiting_for_context": 0, "another_worker_active": 1}
        return _recover_processing(root)

def _recover_processing(root: Path) -> dict[str, int]:
    from .storage import get_task, update_task, mark_task_cancelled, task_state_transaction, mark_task_recovery_stopped, list_tasks_snapshot, TASK_DIR
    from .task_control_state import task_generation
    from .processor import process_local_video_task, process_current_page_task
    from .models import CurrentPageTaskRequest

    queue = queue_for(root)
    recovered = waiting = 0
    for snapshot in queue.entries():
        with task_state_transaction():
            row = queue._job_row(snapshot["task_id"])
            if row is None or row.get("generation", "") != snapshot.get("generation", ""):
                continue  # A retry admitted after the recovery snapshot owns its new intent.
            if row["task_id"] in queue.jobs:
                continue
            if row["state"] == "cancelled" and row.get("cancel_operation_id") and row.get("generation"):
                from .storage import cancel_task_generation
                from .task_control_state import TaskControlConflict
                try:
                    cancel_task_generation(row["task_id"], expected_generation=row["generation"],
                                           operation_id=row["cancel_operation_id"])
                except (FileNotFoundError, TaskControlConflict):
                    pass
                continue
            if row["state"] not in {"queued", "running", "recovering"}:
                continue
            try:
                task = get_task(row["task_id"])
            except FileNotFoundError:
                queue.set_state(row["task_id"], "cancelled", generation=row.get("generation", ""))
                continue
            if row.get("generation") and row["generation"] != task_generation(task):
                queue.set_state(task.id, "cancelled", generation=row["generation"])
                continue
            if task.cancel_requested:
                # Owning every worker lease proves no callback is executing, but
                # recovery is not evidence that the original worker acknowledged.
                mark_task_recovery_stopped(task.id)
                queue.set_state(task.id, "cancelled", generation=row.get("generation", ""))
                continue
            if task.status in {"success", "failed", "cancelled"}:
                queue.set_state(task.id, "done", generation=row.get("generation", ""))
                continue
            if row["requires_context"]:
                queue.set_state(task.id, "waiting_context", generation=row.get("generation", ""))
                update_task(task.id, status="failed", phase="failed", error_code="resume_context_required", message="进度已保存；请重新确认模型或从原网页发送，以恢复需要登录信息的任务。")
                waiting += 1
                continue
            if row["kind"] == "summary":
                from .processor import process_saved_transcript_task
                callback = lambda task=task: process_saved_transcript_task(task.id, task.options)
            elif row["kind"] in {"local", "range", "local_light", "screen_ocr"} or (row["kind"] == "light" and task.source_type == "local"):
                path = Path(task.source_media_path or task.media_path or "")
                if not path.is_file() or not path.resolve().is_relative_to(Path(root).resolve()):
                    queue.set_state(task.id, "waiting_context", generation=row.get("generation", ""))
                    update_task(task.id, status="failed", phase="failed", error_code="resume_source_required", message="原媒体不在当前数据目录，请重新选择原文件恢复。")
                    waiting += 1
                    continue
                if row["kind"] == "screen_ocr":
                    from .screen_subtitle_tasks import process_screen_subtitle_task
                    callback = lambda task=task, path=path: process_screen_subtitle_task(task.id, path, task.options)
                elif row["kind"] == "range":
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
                    learning_range=task.learning_range, drm_detected=task.drm_detected, drm_signals=task.drm_signals)
                callback = lambda task=task, request=request: process_current_page_task(task.id, request)
            # Reset the orphaned lease before re-enqueueing the original task ID.
            queue.set_state(task.id, "recovering", generation=row.get("generation", ""))
            generation = task_generation(task)
            def recover_work(callback=callback, task_id=task.id, generation=generation):
                latest = get_task(task_id)
                if task_generation(latest) != generation:
                    return
                if latest.cancel_requested:
                    mark_task_cancelled(task_id, expected_generation=generation)
                    return
                callback()
                if get_task(task_id).cancel_requested:
                    mark_task_cancelled(task_id, expected_generation=generation)
            queue.enqueue(task.id, row["kind"], recover_work, generation=generation)
            recovered += 1
    if TASK_DIR.parent.resolve() == Path(root).resolve():
        for snapshot in list_tasks_snapshot():
            if snapshot.status != "cancelling" or not snapshot.cancel_requested or snapshot.awaiting_confirmation:
                continue
            with task_state_transaction():
                task = get_task(snapshot.id)
                if task.status == "cancelling" and task.cancel_requested and read_queue_job(root, task.id) is None:
                    # The worker leases prove stopped now; an absent journal row
                    # cannot establish whether an earlier callback ever returned.
                    mark_task_recovery_stopped(task.id)
    return {"recovered": recovered, "waiting_for_context": waiting}
