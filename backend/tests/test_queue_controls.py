from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.queue_controls import ordered_entries, queue_is_paused, set_queue_paused, set_task_priority
from app.task_queue import LocalTaskQueue, queue_status, schedule_processing
from app.routers import queue as routes


class QueueControlTests(unittest.TestCase):
    def test_explicit_caption_summary_uses_light_lane_without_asr_fallback(self):
        from app.models import CurrentPageTaskRequest, TaskOptions, TaskRecord
        from fastapi import BackgroundTasks
        from unittest.mock import MagicMock
        request = CurrentPageTaskRequest(mode="subtitle_only", page_url="https://example.test/reference",
                                         options=TaskOptions(content_mode="text", visual_understanding=False))
        queue = MagicMock()
        task = TaskRecord(id="caption", title="fixture", source_type="current_page", created_at="fixed", updated_at="fixed")
        with patch("app.task_queue.queue_for", return_value=queue), patch("app.storage.task_dir", return_value=self.root / "tasks" / "caption"), \
                patch("app.storage.TASK_DIR", self.root / "tasks"), patch("app.storage.get_task", return_value=task):
            schedule_processing(BackgroundTasks(), lambda *args: None, "caption", request)
        self.assertEqual(queue.enqueue.call_args.args[1], "page_light")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.queues = []

    def tearDown(self):
        set_queue_paused(self.root, False)
        for queue in self.queues:
            queue.stop()

    def queue(self):
        queue = LocalTaskQueue(self.root); self.queues.append(queue); return queue

    def test_existing_journal_migrates_without_losing_intents(self):
        with closing(sqlite3.connect(self.root / "task-queue.sqlite3")) as db:
            db.execute("CREATE TABLE jobs(sequence INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT UNIQUE,kind TEXT,requires_context INTEGER,state TEXT,updated_at REAL)")
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES('saved','local',0,'queued',1)"); db.commit()
        queue = self.queue()
        self.assertEqual(queue.entries()[0]["task_id"], "saved")
        self.assertEqual(queue.entries()[0]["priority"], 0)

    def test_legacy_queue_migration_backs_up_committed_wal_and_remains_old_reader_compatible(self):
        path = self.root / "task-queue.sqlite3"
        with closing(sqlite3.connect(path)) as original:
            original.execute("PRAGMA journal_mode=WAL")
            original.execute("PRAGMA wal_autocheckpoint=0")
            original.execute("CREATE TABLE jobs(sequence INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT UNIQUE,kind TEXT,requires_context INTEGER,state TEXT,updated_at REAL)")
            original.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES('wal-row','local',0,'queued',1)")
            original.commit()
            self.assertTrue(path.with_name(path.name + "-wal").is_file())
            queue = self.queue()
            backups = list(self.root.glob("task-queue.sqlite3.pre-control-*.bak"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute("SELECT task_id,state FROM jobs").fetchall(), [("wal-row", "queued")])
                self.assertNotIn("generation", {row[1] for row in backup.execute("PRAGMA table_info(jobs)")})
            # The prior version's select/insert shape still works after migration.
            with closing(queue.connect()) as current:
                self.assertEqual(current.execute("SELECT task_id,kind,requires_context,state,updated_at FROM jobs").fetchall(), [("wal-row", "local", 0, "queued", 1)])
                current.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES('old-writer','local',0,'queued',2)")
                current.commit()
            self.assertEqual(len(queue.entries()), 2)
            self.queue()
            self.assertEqual(list(self.root.glob("task-queue.sqlite3.pre-control-*.bak")), backups)

    def test_backup_and_schema_failure_leave_original_queue_readable(self):
        from app.queue_controls import initialize_queue_schema
        path = self.root / "task-queue.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE jobs(sequence INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT UNIQUE,kind TEXT,requires_context INTEGER,state TEXT,updated_at REAL)")
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES('retained','local',0,'queued',1)")
            db.commit()
            columns = db.execute("PRAGMA table_info(jobs)").fetchall()
            with patch("app.queue_controls._backup_legacy_queue", side_effect=OSError("synthetic storage failure")):
                with self.assertRaises(OSError):
                    initialize_queue_schema(db)
            self.assertEqual(db.execute("PRAGMA table_info(jobs)").fetchall(), columns)
            db.set_authorizer(lambda action, first, *args: sqlite3.SQLITE_DENY
                              if action == sqlite3.SQLITE_CREATE_TABLE and first == "queue_settings" else sqlite3.SQLITE_OK)
            with self.assertRaises(sqlite3.DatabaseError):
                initialize_queue_schema(db)
            db.set_authorizer(None)
            self.assertEqual(db.execute("PRAGMA table_info(jobs)").fetchall(), columns)
            self.assertEqual(db.execute("SELECT task_id,state FROM jobs").fetchall(), [("retained", "queued")])
            self.assertEqual(len(list(self.root.glob("task-queue.sqlite3.pre-control-*.bak"))), 1)

    def test_pause_survives_new_instance_and_does_not_lose_jobs(self):
        set_queue_paused(self.root, True)
        first, second = self.queue(), self.queue()
        ran = []
        futures = [(first if i % 2 else second).enqueue(str(i), "local", lambda i=i: ran.append(i)) for i in range(5)]
        time.sleep(.15)
        self.assertEqual(ran, []); self.assertTrue(queue_is_paused(self.root))
        self.assertTrue(first.cancel_pending("4"))
        set_queue_paused(self.root, False)
        for future in futures: future.result(5)
        self.assertEqual(ran, [0, 1, 2, 3])
        self.assertEqual(first.entries()[-1]["state"], "cancelled")

    def test_running_work_continues_but_following_admission_pauses(self):
        queue = self.queue(); started, release, second_started = threading.Event(), threading.Event(), threading.Event()
        first = queue.enqueue("active", "local", lambda: (started.set(), release.wait(3)))
        self.assertTrue(started.wait(2))
        try:
            set_queue_paused(self.root, True)
            second = queue.enqueue("next", "local", second_started.set)
            release.set(); first.result(3)
            self.assertFalse(second_started.wait(.15))
            set_queue_paused(self.root, False); second.result(3)
        finally:
            release.set()

    def test_priority_selects_later_owned_job_without_deadlock(self):
        set_queue_paused(self.root, True)
        queue = self.queue(); order = []
        futures = [queue.enqueue(str(i), "local", lambda i=i: order.append(i)) for i in range(5)]
        set_task_priority(self.root, "3", 5)
        snapshot = queue_status(self.root, "3")
        self.assertEqual(snapshot["position"], 1); self.assertTrue(snapshot["paused"])
        set_queue_paused(self.root, False)
        for future in futures: future.result(5)
        self.assertEqual(order, [3, 0, 1, 2, 4])
        with self.assertRaises(ValueError): set_task_priority(self.root, "3", 0)

    def test_aging_prevents_new_high_priority_work_starving_older_intent(self):
        rows = [dict(task_id="new", priority=5, updated_at=1000, sequence=2, state="queued"),
                dict(task_id="old", priority=0, updated_at=600, sequence=1, state="queued")]
        self.assertEqual(ordered_entries(rows, now=1000)[0]["task_id"], "old")

    def test_controls_are_strict_and_reject_nonpending_ids(self):
        app = FastAPI(); app.include_router(routes.router)
        with patch.object(routes, "DATA_DIR", self.root), TestClient(app) as client:
            self.assertEqual(client.put("/api/queue/pause", json={"paused": "false"}).status_code, 422)
            self.assertTrue(client.put("/api/queue/pause", json={"paused": True}).json()["paused"])
            self.assertEqual(client.put("/api/queue/tasks/missing/priority", json={"priority": 5}).status_code, 409)
            for value in (-1, 6, True):
                self.assertEqual(client.put("/api/queue/tasks/missing/priority", json={"priority": value}).status_code, 422)
