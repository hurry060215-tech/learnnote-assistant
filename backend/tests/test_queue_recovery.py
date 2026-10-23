"""Real leases/journal regressions; media and provider execution are fixtures."""
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import storage
from app.queue_controls import set_queue_paused
from app.queue_ownership import owner_is_alive
from app.task_control_state import task_generation
from app.task_queue import LocalTaskQueue, queue_for, recover_processing


def _isolated_storage(root):
    stack = ExitStack()
    for name, value in (("TASK_DIR", Path(root) / "tasks"), ("ensure_dirs", lambda: None),
                        ("index_task", lambda *_a, **_k: None),
                        ("record_task_event", lambda *_a, **_k: None),
                        ("record_status", lambda *_a, **_k: None)):
        stack.enter_context(patch.object(storage, name, value))
    stack.enter_context(patch("app.task_queue.record_task_event"))
    return stack


def _paused_owner(root, task_id, generation, requires_context, ready, release, executed):
    with _isolated_storage(root):
        queue = LocalTaskQueue(Path(root))
        secret = "synthetic-credential-kept-in-callback-only"
        future = queue.enqueue(task_id, "local", lambda: executed.set() if secret else None,
                               generation=generation, requires_context=requires_context)
        ready.set()
        if release.wait(20):
            set_queue_paused(Path(root), False)
            future.result(5)
            queue.stop()


def _simultaneous_recovery(root, ready, start):
    with _isolated_storage(root):
        def process(task_id, *_args, **_kwargs):
            with closing(sqlite3.connect(Path(root) / "executions.sqlite3")) as db:
                db.execute("CREATE TABLE IF NOT EXISTS executions(task_id TEXT)")
                db.execute("INSERT INTO executions VALUES(?)", (task_id,))
                db.commit()
            storage.update_task(task_id, status="success", phase="completed")
        with patch("app.processor.process_local_video_task", side_effect=process):
            ready.set()
            if not start.wait(10):
                raise RuntimeError("recovery fixture did not start")
            recover_processing(Path(root))
            queue_for(Path(root)).stop()


class QueueRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(_isolated_storage(self.root))
        self.queues = []
        self.releases = []
        self.processes = []
        self.addCleanup(self.close_workers)

    def close_workers(self):
        for release in self.releases:
            release.set()
        set_queue_paused(self.root, False)
        for process in self.processes:
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)
        for queue in self.queues:
            queue.stop()
        queue_for(self.root).stop()

    def queue(self):
        queue = LocalTaskQueue(self.root)
        self.queues.append(queue)
        return queue

    def task(self):
        task = storage.create_task("local", "Synthetic recovery")
        media = storage.task_file(task.id).with_name("fixture.mp4")
        media.write_bytes(b"fixture-only; the processing callback is replaced")
        return storage.update_task(task.id, source_media_path=str(media))

    def orphan(self, queue, task, kind="local"):
        with closing(queue.connect()) as db:
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at,generation) "
                       "VALUES (?,?,0,'queued',0,?)", (task.id, kind, task_generation(task)))
            db.commit()

    def complete(self, task_id, *_args, **_kwargs):
        storage.update_task(task_id, status="success", phase="completed")

    def test_paused_seven_hour_task_listing_is_one_read_and_cannot_consume_intent(self):
        task = self.task()
        path = storage.task_file(task.id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        path.write_text(json.dumps(payload), encoding="utf-8")
        queue = queue_for(self.root)
        self.orphan(queue, task)
        set_queue_paused(self.root, True)
        before = path.read_bytes(), path.stat().st_mtime_ns
        with patch.object(storage, "get_task", wraps=storage.get_task) as reads, \
                patch.object(storage, "task_state_transaction", side_effect=AssertionError("read acquired write transaction")):
            [listed] = storage.list_tasks()
        self.assertEqual(reads.call_count, 1)
        self.assertEqual(listed.status, "queued")
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        with patch("app.processor.process_local_video_task", side_effect=self.complete) as process:
            self.assertEqual(recover_processing(self.root)["recovered"], 1)
            self.assertEqual(queue.entries()[0]["state"], "queued")
            process.assert_not_called()
            set_queue_paused(self.root, False)
            queue.stop()
        self.assertEqual(storage.get_task(task.id).status, "success")

    def test_busy_other_lane_does_not_prevent_orphan_recovery(self):
        first, second = self.queue(), queue_for(self.root)
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        active = first.enqueue("active-light", "light", lambda: (started.set(), release.wait(5)))
        self.assertTrue(started.wait(2))
        task = self.task()
        self.orphan(first, task)
        reached = threading.Event()
        with patch("app.processor.process_local_video_task", side_effect=lambda *a, **k: (self.complete(*a, **k), reached.set())):
            result = recover_processing(self.root)
            self.assertEqual(result["recovered"], 1)
            self.assertTrue(reached.wait(2))
            self.assertFalse(active.done())
            release.set()
            active.result(3)
            second.stop()

    def test_busy_same_lane_retries_recovery_after_owner_finishes(self):
        first, second = self.queue(), queue_for(self.root)
        started, release, recovered = threading.Event(), threading.Event(), threading.Event()
        self.releases.append(release)
        active = first.enqueue("active-heavy", "local", lambda: (started.set(), release.wait(5)))
        self.assertTrue(started.wait(2))
        task = self.task()
        self.orphan(first, task)
        order = []
        def resume(*args, **kwargs):
            self.complete(*args, **kwargs)
            order.append("recovered")
            recovered.set()
        with patch("app.processor.process_local_video_task", side_effect=resume):
            self.assertEqual(recover_processing(self.root)["another_worker_active"], 1)
            later = second.enqueue("later", "local", lambda: order.append("later"))
            release.set()
            active.result(3)
            self.assertTrue(recovered.wait(4))
            later.result(4)
        self.assertEqual(order, ["recovered", "later"])

    def test_worker_recovers_an_orphan_that_appears_after_startup(self):
        queue = queue_for(self.root)
        self.assertEqual(recover_processing(self.root)["recovered"], 0)
        task = self.task()
        self.orphan(queue, task)
        order = []
        with patch("app.processor.process_local_video_task", side_effect=lambda *a, **k: (self.complete(*a, **k), order.append("orphan"))):
            later = queue.enqueue("later", "local", lambda: order.append("later"))
            later.result(5)
        self.assertEqual(order, ["orphan", "later"])

    def owner_process(self, task, requires_context):
        context = multiprocessing.get_context("spawn")
        ready, release, executed = context.Event(), context.Event(), context.Event()
        self.releases.append(release)
        set_queue_paused(self.root, True)
        process = context.Process(target=_paused_owner,
            args=(str(self.root), task.id, task_generation(task), requires_context, ready, release, executed))
        self.processes.append(process)
        process.start()
        self.assertTrue(ready.wait(10))
        return process, release, executed

    def test_another_process_cannot_steal_paused_credential_callback(self):
        task = self.task()
        process, release, executed = self.owner_process(task, True)
        before = storage.task_file(task.id).read_bytes()
        with patch("app.processor.process_local_video_task") as callback:
            self.assertEqual(recover_processing(self.root), {"recovered": 0, "waiting_for_context": 0, "another_worker_active": 1})
            callback.assert_not_called()
        self.assertEqual(storage.task_file(task.id).read_bytes(), before)
        row = queue_for(self.root).entries()[0]
        self.assertTrue(owner_is_alive(self.root, row["owner_id"]))
        self.assertEqual(row["state"], "queued")
        self.assertNotIn(b"synthetic-credential-kept-in-callback-only", (self.root / "task-queue.sqlite3").read_bytes())
        release.set()
        self.assertTrue(executed.wait(5))
        process.join(5)
        self.assertEqual(process.exitcode, 0)

    def test_owner_process_death_releases_local_job_for_same_generation_recovery(self):
        task = self.task()
        process, release, executed = self.owner_process(task, False)
        row = queue_for(self.root).entries()[0]
        self.releases.remove(release)  # Do not touch synchronization objects held by a killed process.
        process.terminate()
        process.join(5)
        self.assertFalse(owner_is_alive(self.root, row["owner_id"]))
        set_queue_paused(self.root, False)
        with patch("app.processor.process_local_video_task", side_effect=self.complete) as callback:
            self.assertEqual(recover_processing(self.root)["recovered"], 1)
            queue_for(self.root).stop()
            callback.assert_called_once()
        self.assertFalse(executed.is_set())
        self.assertEqual(storage.get_task(task.id).status, "success")
        self.assertEqual(queue_for(self.root).entries()[0]["generation"], row["generation"])

    def test_watching_foreign_owner_recovers_after_death_without_new_submission(self):
        task = self.task()
        process, release, _ = self.owner_process(task, False)
        reached = threading.Event()
        with patch("app.processor.process_local_video_task", side_effect=lambda *a, **k: (self.complete(*a, **k), reached.set())):
            self.assertEqual(recover_processing(self.root)["another_worker_active"], 1)
            self.releases.remove(release)
            process.terminate()
            process.join(5)
            set_queue_paused(self.root, False)
            self.assertTrue(reached.wait(5))
        self.assertEqual(storage.get_task(task.id).status, "success")

    def test_dead_credential_owner_requires_new_context_and_never_calls_processor(self):
        task = self.task()
        process, release, _ = self.owner_process(task, True)
        self.releases.remove(release)
        process.terminate()
        process.join(5)
        with patch("app.processor.process_local_video_task") as callback:
            self.assertEqual(recover_processing(self.root)["waiting_for_context"], 1)
            callback.assert_not_called()
        self.assertEqual(storage.get_task(task.id).error_code, "resume_context_required")
        self.assertEqual(queue_for(self.root).entries()[0]["state"], "waiting_context")

    def test_two_recovery_processes_execute_orphan_once(self):
        task = self.task()
        self.orphan(self.queue(), task)
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        ready = [context.Event(), context.Event()]
        for event in ready:
            process = context.Process(target=_simultaneous_recovery, args=(str(self.root), event, start))
            self.processes.append(process)
            process.start()
        self.assertTrue(all(event.wait(10) for event in ready))
        start.set()
        for process in self.processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        with closing(sqlite3.connect(self.root / "executions.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT task_id FROM executions").fetchall(), [(task.id,)])
        self.assertEqual(storage.get_task(task.id).status, "success")


if __name__ == "__main__":
    unittest.main()
