"""One damaged task cannot prevent app startup or unrelated intent recovery."""
from contextlib import ExitStack, closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main, storage
from app.task_control_state import task_generation
from app.task_queue import queue_for, recover_processing


class RecoveryManifestErrorTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name, value in (("TASK_DIR", self.root / "tasks"), ("DATA_DIR", self.root),
                            ("ensure_dirs", lambda: None), ("index_task", lambda *a, **k: True),
                            ("record_task_event", lambda *a, **k: None),
                            ("record_status", lambda *a, **k: None)):
            self.stack.enter_context(patch.object(storage, name, value))
        self.stack.enter_context(patch("app.task_queue.record_task_event"))
        self.stack.enter_context(patch.object(main, "DATA_DIR", self.root))
        self.stack.enter_context(patch.object(main, "record_activation"))
        self.stack.enter_context(patch.object(main, "cleanup_expired_staged_uploads"))
        # Exercise the real lifespan and route without consulting user settings.
        self.stack.enter_context(patch.object(main, "health_payload", return_value={"ok": True}))
        self.queue = queue_for(self.root)
        self.addCleanup(self.queue.stop)

    def intent(self, *, state="queued", operation_id=""):
        task = storage.create_task("local", "Synthetic retained task")
        generation = task_generation(task)
        with closing(self.queue.connect()) as db:
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at,generation,"
                       "callback_finished,owner_id,cancel_operation_id) VALUES (?,'summary',0,?,0,?,0,'',?)",
                       (task.id, state, generation, operation_id))
            db.commit()
        return task

    def startup_recovers_healthy(self, healthy):
        completed = threading.Event()

        def process(task_id, options):
            self.assertEqual(task_id, healthy.id, "Invalid task must never be processed")
            storage.update_task(task_id, status="success", phase="completed")
            completed.set()

        with patch("app.processor.process_saved_transcript_task", side_effect=process) as callback:
            with TestClient(main.app) as client:
                self.assertEqual(client.get("/health").json(), {"ok": True})
                self.assertTrue(completed.wait(5), "Healthy queued task must recover after an invalid entry")
            callback.assert_called_once()
        self.assertEqual(storage.get_task(healthy.id).status, "success")
        self.assertEqual(self.queue._job_row(healthy.id)["state"], "done")

    def assert_attention(self, task, before):
        row = self.queue._job_row(task.id)
        self.assertEqual(row["state"], "waiting_context")
        self.assertEqual(row["generation"], task_generation(task))
        self.assertEqual(row["callback_finished"], 0)
        path = storage.task_file(task.id)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_lifespan_isolates_malformed_schema_identity_and_encoding_without_repairing_bytes(self):
        damaged = []
        for payload in (b'{"synthetic-secret":', b'{}', b'true', b'{"schema_version":[]}',
                        b'{"schema_version":1e309}', b'\xff\xfe', None):
            task = self.intent()
            if payload is None:
                payload = task.model_copy(update={"id": "another-owner"}).model_dump_json().encode()
            path = storage.task_file(task.id)
            path.write_bytes(payload)
            damaged.append((task, (path.read_bytes(), path.stat().st_mtime_ns)))
        healthy = self.intent()
        with self.assertLogs("app.task_recovery", level="WARNING") as warnings:
            self.startup_recovers_healthy(healthy)
        self.assertEqual(len(warnings.records), len(damaged))
        self.assertNotIn("synthetic-secret", "\n".join(warnings.output))
        self.assertNotIn(str(self.root), "\n".join(warnings.output))
        for task, before in damaged:
            self.assert_attention(task, before)

    def test_unreadable_manifest_does_not_block_healthy_recovery(self):
        damaged, healthy = self.intent(), self.intent()
        path = storage.task_file(damaged.id)
        before = path.read_bytes(), path.stat().st_mtime_ns
        read = storage.get_task

        def unreadable(task_id):
            if task_id == damaged.id:
                raise PermissionError("synthetic-secret inaccessible path")
            return read(task_id)

        with patch.object(storage, "get_task", side_effect=unreadable), \
                self.assertLogs("app.task_recovery", level="WARNING") as warnings:
            self.startup_recovers_healthy(healthy)
        self.assert_attention(damaged, before)
        self.assertNotIn("synthetic-secret", "\n".join(warnings.output))

    def test_cancel_receipt_survives_invalid_manifest_without_claiming_acknowledgement(self):
        damaged = self.intent(state="cancelled", operation_id="synthetic-cancel-receipt")
        path = storage.task_file(damaged.id)
        path.write_text("{invalid", encoding="utf-8")
        before = path.read_bytes(), path.stat().st_mtime_ns
        healthy = self.intent()
        with self.assertLogs("app.task_recovery", level="WARNING"):
            self.startup_recovers_healthy(healthy)
        self.assert_attention(damaged, before)
        self.assertEqual(self.queue._job_row(damaged.id)["cancel_operation_id"], "synthetic-cancel-receipt")

    def test_journal_update_error_is_not_swallowed_as_a_bad_manifest(self):
        damaged = self.intent()
        storage.task_file(damaged.id).write_text("{invalid", encoding="utf-8")
        with patch.object(self.queue, "set_state", side_effect=sqlite3.DatabaseError("journal failure")):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "journal failure"):
                recover_processing(self.root)
        self.assertEqual(self.queue._job_row(damaged.id)["state"], "queued")

    def test_overflow_schema_is_skipped_only_by_non_strict_catalog_reads(self):
        task = storage.create_task("local", "Synthetic overflowing schema")
        path = storage.task_file(task.id)
        path.write_text('{"schema_version":1e309}', encoding="utf-8")
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(storage.list_tasks_snapshot(), [])
        with self.assertRaises(OverflowError):
            storage.list_tasks_snapshot(strict=True)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_unjournaled_snapshot_read_race_preserves_manifest_and_does_not_abort(self):
        task = storage.create_task("local", "Synthetic cancellation", mode="local")
        task = storage.update_task(task.id, status="cancelling", cancel_requested=True)
        path = storage.task_file(task.id)
        before = path.read_bytes(), path.stat().st_mtime_ns
        with patch.object(storage, "list_tasks_snapshot", return_value=[task]), \
                patch.object(storage, "get_task", side_effect=json.JSONDecodeError("invalid", "", 0)), \
                self.assertLogs("app.task_recovery", level="WARNING"):
            result = recover_processing(self.root)
        self.assertEqual(result, {"recovered": 0, "waiting_for_context": 1})
        self.assertEqual(self.queue.entries(), [])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
