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
from .queue_policy import LANES, LANE_PENDING_LIMIT, LIGHT_TASK_KINDS, QueueFull, lane_budgets, task_lane
from .queue_journal import cancel_queued_processing, queue_status, read_queue_entries, read_queue_job
from .queue_controls import initialize_queue_schema, ordered_entries, queue_candidates
from .queue_ownership import QueueOwner, owner_is_alive

MAX_PENDING_TASKS = 24


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
        self.recovery_lanes: set[str] = set()
        self.recovery_worker = None
        self.last_recovery_probe: dict[str, float] = {}
        with closing(self.connect()) as db:
            initialize_queue_schema(db)
            db.commit()
        self.owner = None

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def entries(self) -> list[dict]:
        with closing(self.connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY sequence")]

    def enqueue(self, task_id: str, kind: str, callback: Callable, *, requires_context: bool = False, generation: str = "", recovery: bool = False) -> Future:
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
            # Recovery must create an owned callback even when this process was
            # already observing the same intent in another process. Keep that
            # observer watching the journal; its running Future cannot be reused
            # as the newly queued callback's Future.
            if not recovery and task_id in self.observers and self.observer_generations.get(task_id, "") == generation:
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
                if self.owner is None:
                    self.owner = QueueOwner(self.root)
                db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at,generation,callback_finished,owner_id) VALUES (?,?,?,'queued',?,?,0,?) ON CONFLICT(task_id) DO UPDATE SET kind=excluded.kind, requires_context=excluded.requires_context, state='queued', updated_at=excluded.updated_at, generation=excluded.generation, cancel_operation_id='', callback_finished=0, owner_id=excluded.owner_id", (task_id, kind, int(requires_context), time.time(), generation, self.owner.id))
                db.execute("DELETE FROM jobs WHERE state IN ('done','failed','cancelled') AND sequence NOT IN (SELECT sequence FROM jobs ORDER BY sequence DESC LIMIT 1000)")
                db.commit()
            future = Future()
            self.jobs[task_id] = (queued_callback(task_id, callback, recovery=recovery), future)
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
                self.probe_orphans(task_lane(row["kind"]))
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
                    if not self.jobs or (self.stopping and not self.workers):
                        self._close_owner()
                    return
            # Waiting on another process is still queued and immediately cancellable.
            with worker_lease(self.root, blocking=False, lane=lane, slot=slot) as acquired:
                with self.condition:
                    task_id = next((key for key in eligible if key in self.jobs), None)
                    claimed = acquired and not self.stopping and task_id and self._claim(task_id, lane)
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
                            if not self.jobs:
                                self._close_owner()
            if not claimed:
                # Never sleep while holding a slot needed by an older intent
                # in another process. Windows mutex reacquisition can starve it.
                with self.condition:
                    self.condition.wait(.05)
                self.probe_orphans(lane)
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

    def _close_owner(self):
        if self.owner is not None:
            self.owner.close()
            self.owner = None

    def probe_orphans(self, lane):
        with self.condition:
            if self.closing or time.monotonic() - self.last_recovery_probe.get(lane, 0) < .5:
                return
            self.last_recovery_probe[lane] = time.monotonic()
        if any(task_lane(row["kind"]) == lane and row["state"] in {"queued", "running", "recovering"}
               and not owner_is_alive(self.root, row.get("owner_id", "")) for row in self.entries()):
            self.request_recovery({lane})

    def request_recovery(self, lanes):
        with self.condition:
            if self.closing or self.stopping:
                return
            self.recovery_lanes.update(lanes)
            if self.recovery_worker is None or not self.recovery_worker.is_alive():
                self.recovery_worker = threading.Thread(target=self._retry_recovery,
                    name="learnnote-queue-recovery", daemon=True)
                self.recovery_worker.start()
            self.condition.notify_all()

    def _retry_recovery(self):
        while True:
            with self.condition:
                if self.closing or not self.recovery_lanes:
                    self.recovery_worker = None
                    return
                lanes = self.recovery_lanes.copy()
                self.recovery_lanes.clear()
            try:
                _, busy = _recover_lanes(self, lanes)
            except Exception:
                busy = lanes  # A transient journal/manifest error cannot erase intent.
            with self.condition:
                self.recovery_lanes.update(busy)
                if self.recovery_lanes and not self.closing:
                    self.condition.wait(.5)

    def stop(self, timeout: float = 10):
        with self.condition:
            self.closing = True
            workers = list(self.workers.values())
            self.condition.notify_all()
            if self.recovery_worker:
                workers.append(self.recovery_worker)
        deadline = time.monotonic() + timeout
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))
        with self.condition:
            self.stopping = True
            if not any(future.running() for _, future in self.jobs.values()):
                self._close_owner()
            self.condition.notify_all()

    def cancel_pending(self, task_id: str) -> bool:
        with self.condition:
            with closing(self.connect()) as db:
                changed = db.execute("UPDATE jobs SET state='cancelled',updated_at=? WHERE task_id=? AND state='queued'", (time.time(), task_id)).rowcount
                db.commit()
            if not changed:
                return False
            job = self.jobs.pop(task_id, None)
            self.generations.pop(task_id, None)
            if not self.jobs:
                self._close_owner()
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


def schedule_processing(background_tasks, function, task_id: str, *args, **kwargs):
    from .storage import task_dir
    from .task_dispatch import dispatch_processing
    queue = queue_for(task_dir(task_id).parent.parent)
    return dispatch_processing(queue, background_tasks, function, task_id, *args, **kwargs)


def recover_processing(root: Path) -> dict[str, int]:
    queue = queue_for(root)
    result, busy = _recover_lanes(queue, LANES)
    if busy:
        queue.request_recovery(busy)
        result["another_worker_active"] = 1
    return result


def _recover_lanes(queue, lanes):
    available, busy = [], set()
    with ExitStack() as leases:
        for lane in lanes:
            lane_leases = ExitStack()
            for slot in range(4):
                if not lane_leases.enter_context(worker_lease(queue.root, blocking=False, lane=lane, slot=slot)):
                    lane_leases.close()
                    busy.add(lane)
                    break
            else:
                leases.enter_context(lane_leases)
                available.append(lane)
        result = _recover_processing(queue.root, queue=queue, lanes=available,
                                     reconcile_unjournaled=set(available) == set(LANES), waiting_lanes=busy)
    return result, busy


def _recover_processing(root: Path, *, queue=None, lanes=LANES, reconcile_unjournaled=True, waiting_lanes=None) -> dict[str, int]:
    from .task_recovery import recover_intents
    from .range_learning import process_range_task
    return recover_intents(queue or queue_for(root), lanes=lanes,
                           reconcile_unjournaled=reconcile_unjournaled, process_range_task=process_range_task,
                           waiting_lanes=waiting_lanes)
