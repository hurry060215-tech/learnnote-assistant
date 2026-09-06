from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.task_queue import LocalTaskQueue, QueueFull
from app.task_queue import recover_processing, queue_for
from app.models import TaskRecord
from contextlib import closing
import sqlite3


class TaskQueueTests(unittest.TestCase):
    def test_cancelled_future_does_not_execute_or_stop_later_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = LocalTaskQueue(Path(directory))
            started, release = threading.Event(), threading.Event()
            def hold():
                started.set()
                release.wait(3)
            first = queue.enqueue("active", "local", hold)
            self.assertTrue(started.wait(2))
            self.assertFalse(first.cancel())
            pending = queue.enqueue("cancelled", "local", lambda: self.fail("Cancelled callback ran"))
            self.assertTrue(pending.cancel())
            last = queue.enqueue("last", "local", lambda: None)
            release.set()
            first.result(5)
            last.result(5)
            queue.stop()
            self.assertEqual(queue.entries()[1]["state"], "cancelled")
            with self.assertRaisesRegex(RuntimeError, "stopping"):
                queue.enqueue("stopped", "local", lambda: None)

    def test_two_queue_instances_share_the_heavy_worker_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            first_queue = LocalTaskQueue(Path(directory))
            second_queue = LocalTaskQueue(Path(directory))
            started = threading.Event()
            release = threading.Event()
            overlap = threading.Event()
            def first_work():
                started.set()
                release.wait(3)
            first = first_queue.enqueue("first", "local", first_work)
            self.assertTrue(started.wait(2))
            second = second_queue.enqueue("second", "local", overlap.set)
            self.assertFalse(overlap.wait(.1))
            release.set()
            first.result(5)
            second.result(5)
            first_queue.stop()
            second_queue.stop()
    def test_restart_restores_local_intent_but_requests_ephemeral_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "video.mp4"
            media.write_bytes(b"fixture")
            queue = LocalTaskQueue(root)
            with closing(sqlite3.connect(queue.path)) as db:
                db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES ('local','local',0,'running',0), ('private','page',1,'queued',0)")
                db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES ('cancelled','local',0,'running',0)")
                db.commit()
            records = {key: TaskRecord(id=key, title="任务", source_type="local", source_media_path=str(media), created_at="2026-09-06", updated_at="2026-09-06", status="running") for key in ("local", "private")}
            records["cancelled"] = records["local"].model_copy(update={"id": "cancelled", "cancel_requested": True, "status": "cancelling"})
            with patch("app.storage.get_task", side_effect=records.__getitem__), patch("app.storage.update_task") as update, patch("app.storage.mark_task_cancelled") as cancel, patch("app.processor.process_local_video_task") as process:
                result = recover_processing(root)
                queue_for(root).stop()
                self.assertEqual(result, {"recovered": 1, "waiting_for_context": 1})
                process.assert_called_once()
                self.assertEqual(update.call_args.kwargs["error_code"], "resume_context_required")
                cancel.assert_called_once_with("cancelled")

    def test_cancel_pending_releases_capacity_without_waiting_for_active_job(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = LocalTaskQueue(Path(directory))
            release = threading.Event()
            first = queue.enqueue("active", "local", lambda: release.wait(3))
            second = queue.enqueue("pending", "local", lambda: self.fail("Cancelled work ran"))
            self.assertTrue(queue.cancel_pending("pending"))
            self.assertIsNone(second.result(.1))
            release.set()
            first.result(5)
            queue.stop()

    def test_five_jobs_run_once_and_never_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = LocalTaskQueue(Path(directory))
            active = 0
            peak = 0
            order = []
            release = threading.Event()
            def work(index):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                release.wait(3)
                order.append(index)
                active -= 1
            futures = [queue.enqueue(str(i), "local", lambda i=i: work(i)) for i in range(5)]
            self.assertIs(queue.enqueue("0", "local", lambda: self.fail("duplicate")), futures[0])
            release.set()
            for future in futures:
                future.result(5)
            queue.stop()
            self.assertEqual(peak, 1)
            self.assertEqual(order, list(range(5)))
            self.assertTrue(all(row["state"] == "done" for row in queue.entries()))

    def test_backpressure_and_failed_job_do_not_stall_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = LocalTaskQueue(Path(directory))
            release = threading.Event()
            with patch("app.task_queue.MAX_PENDING_TASKS", 1):
                first = queue.enqueue("first", "local", lambda: release.wait(3))
                with self.assertRaises(QueueFull):
                    queue.enqueue("over-limit", "local", lambda: None)
                release.set()
                first.result(5)
            def fail():
                raise RuntimeError("fixture")
            future = queue.enqueue("failed", "local", fail)
            with self.assertRaises(RuntimeError):
                future.result(5)
            queue.enqueue("after-failure", "local", lambda: None).result(5)
            queue.stop()
            self.assertEqual(queue.entries()[-1]["state"], "done")

    def test_journal_is_durable_and_never_serializes_callback_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = LocalTaskQueue(root)
            secret = "private-cookie-do-not-store"
            queue.enqueue("job", "page", lambda: bool(secret), requires_context=True).result(5)
            queue.stop()
            restored = LocalTaskQueue(root)
            self.assertEqual(restored.entries()[0]["requires_context"], 1)
            self.assertNotIn(secret.encode(), restored.path.read_bytes())
            restored.stop()


if __name__ == "__main__":
    unittest.main()
