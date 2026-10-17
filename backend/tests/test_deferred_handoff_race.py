"""Concurrent real task admission/list contracts, without provider or media work."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import main, storage
from app.models import CurrentPageTaskRequest, TaskOptions


class DeferredHandoffRaceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "tasks"
        for name in ("app.storage.TASK_DIR", "app.observability.TASK_DIR", "app.main.TASK_DIR"):
            self.stack.enter_context(patch(name, root))
        self.stack.enter_context(patch("app.storage.ensure_dirs", lambda: None))
        self.stack.enter_context(patch("app.main.task_payload", lambda task, *, queue_snapshot=None: task.model_dump(mode="json")))
        self.stack.enter_context(patch("app.main.require_ready_note_model", lambda options: None))
        self.stack.enter_context(patch.dict(main._deferred_handoffs, {}, clear=True))
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.queue_root = root.parent.resolve()
        self.addCleanup(self.stop_owned_queue)
        self.request = CurrentPageTaskRequest(page_url="https://example.test/reference", title="Synthetic handoff",
            options=TaskOptions(content_mode="text", use_saved_connection=False))
        self.task = storage.create_task("current_page", self.request.title, self.request.page_url, options=self.request.options)
        storage.update_task(self.task.id, awaiting_confirmation=True)
        main._deferred_handoffs[self.task.id] = self.request

    def stop_owned_queue(self):
        from app import task_queue
        with task_queue._lock:
            owned = task_queue._queues.get(self.queue_root)
        if owned is None:
            return
        workers = list(owned.workers.values())
        try:
            owned.stop(timeout=5)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(owned.jobs, {})
            self.assertEqual(owned.observers, {})
        finally:
            with task_queue._lock:
                if task_queue._queues.get(self.queue_root) is owned:
                    task_queue._queues.pop(self.queue_root)

    def test_list_snapshot_before_real_start_cannot_expire_admitted_task(self):
        captured, release = threading.Event(), threading.Event()
        held, finish = threading.Event(), threading.Event()
        def delayed_snapshot():
            records = [storage.get_task(self.task.id)]
            captured.set()
            if not release.wait(5):
                raise AssertionError("test did not release captured task snapshot")
            return records
        def processing(task_id, request):
            storage.update_task(task_id, status="running", phase="summarizing")
            held.set()
            if not finish.wait(5):
                raise AssertionError("test did not release held processing")
        with patch("app.main.list_tasks", delayed_snapshot), patch("app.main.process_current_page_task", processing), ThreadPoolExecutor(2) as pool:
            pending = pool.submit(self.client.get, "/api/tasks")
            try:
                self.assertTrue(captured.wait(5))
                started = pool.submit(self.client.post, f"/api/tasks/{self.task.id}/start", json=self.request.options.model_dump())
                self.assertTrue(held.wait(5))
                with main._deferred_handoffs_lock:
                    self.assertNotIn(self.task.id, main._deferred_handoffs)
                self.assertEqual(storage.get_task(self.task.id).status, "running")
                release.set()
                response = pending.result(5)
                self.assertEqual(response.status_code, 200, response.text)
                current = storage.get_task(self.task.id)
                self.assertEqual((current.status, current.error_code), ("running", ""))
                self.assertFalse(current.awaiting_confirmation)
                self.assertEqual(response.json()["tasks"][0]["status"], "running")
                from app.queue_journal import read_queue_job
                row = read_queue_job(storage.TASK_DIR.parent, self.task.id)
                self.assertEqual(row["state"], "running")
                self.assertFalse(row["callback_finished"])
            finally:
                release.set()
                finish.set()
            admitted = started.result(5)
            self.assertEqual(admitted.status_code, 200, admitted.text)

    def test_live_and_genuinely_lost_handoffs_keep_distinct_outcomes(self):
        live = main.expire_deferred_handoff(self.task.id)
        self.assertTrue(live.awaiting_confirmation)
        self.assertEqual((live.status, live.error_code), ("queued", ""))
        main._deferred_handoffs.pop(self.task.id)
        lost = main.expire_deferred_handoff(self.task.id)
        self.assertEqual((lost.status, lost.error_code), ("failed", "handoff_expired"))
        self.assertFalse(lost.awaiting_confirmation)
        self.assertEqual(main.expire_deferred_handoff(self.task.id).updated_at, lost.updated_at)

    def test_stale_list_preserves_cancelled_completed_and_deleted_current_state(self):
        stale = storage.get_task(self.task.id)
        main._deferred_handoffs.pop(self.task.id)
        for status in ("cancelled", "success", "failed"):
            with self.subTest(status=status):
                current = storage.update_task(self.task.id, status=status, phase="completed" if status == "success" else status,
                    awaiting_confirmation=False, error_code="original_outcome")
                with patch("app.main.list_tasks", return_value=[stale]):
                    listed = self.client.get("/api/tasks")
                self.assertEqual(listed.status_code, 200, listed.text)
                self.assertEqual(listed.json()["tasks"][0]["status"], status)
                self.assertEqual(storage.get_task(self.task.id).updated_at, current.updated_at)
                self.assertEqual(storage.get_task(self.task.id).error_code, "original_outcome")
        storage.task_file(self.task.id).unlink()
        with patch("app.main.list_tasks", return_value=[stale]):
            response = self.client.get("/api/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["tasks"], [])
        self.assertFalse(storage.task_file(self.task.id).exists())

    def test_recaptured_handoff_is_rechecked_when_older_expiry_candidate_arrives(self):
        stale = storage.get_task(self.task.id)
        replacement = self.request.model_copy(update={"title": "Freshly reviewed source"})
        main._deferred_handoffs[self.task.id] = replacement
        with patch("app.main.list_tasks", return_value=[stale]):
            response = self.client.get("/api/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["tasks"][0]["status"], "queued")
        self.assertTrue(response.json()["tasks"][0]["awaiting_confirmation"])
        self.assertIs(main._deferred_handoffs[self.task.id], replacement)
