"""Published task reads stay responsive while the derived index is busy.

Event barriers, not latency thresholds, hold the relevant writer/reader phase.
The real manifest publication and file handles are used on Windows as well.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import main, storage
from app.models import TaskRecord


class ObservedManifestLock:
    def __init__(self, lock, thread_name, attempt_number=1):
        self.lock, self.thread_name, self.attempt_number = lock, thread_name, attempt_number
        self.attempts = 0
        self.attempted = threading.Event()

    def __enter__(self):
        if threading.current_thread().name == self.thread_name:
            self.attempts += 1
            if self.attempts == self.attempt_number:
                self.attempted.set()
        self.lock.acquire()
        return self

    def __exit__(self, *exc):
        self.lock.release()


class ManifestReadConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.tasks = self.root / "tasks"
        self.tasks.mkdir()
        self.stack.enter_context(patch.object(storage, "TASK_DIR", self.tasks))
        self.stack.enter_context(patch.object(storage, "DATA_DIR", self.root))

    def task(self, task_id, *, transcript=False):
        root = self.tasks / task_id
        root.mkdir()
        record = TaskRecord(id=task_id, source_type="local", title=f"Synthetic {task_id}",
                            status="success", created_at="2026-10-26", updated_at="2026-10-26")
        if transcript:
            target = root / "transcript.json"
            target.write_text(json.dumps({"full_text": "Synthetic retained caption", "segments": []}), encoding="utf-8")
            record.transcript_path = str(target)
        (root / "task.json").write_text(record.model_dump_json(), encoding="utf-8")
        return record

    def bytes_and_times(self):
        return {path.relative_to(self.tasks).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.tasks.rglob("*") if path.is_file()}

    def test_real_catalog_and_unrelated_transcript_finish_while_index_remains_held(self):
        writer = self.task("writer")
        reader = self.task("reader", transcript=True)
        entered, release = threading.Event(), threading.Event()

        def held_index(record, *, task_root):
            self.assertEqual(record.id, writer.id)
            entered.set()
            self.assertTrue(release.wait(5), "Test must release its held index")
            return True

        writer.title = "Synthetic fully published update"
        with patch.object(storage, "index_task", held_index), ThreadPoolExecutor(max_workers=3) as pool:
            pending = pool.submit(storage.save_task, writer)
            try:
                self.assertTrue(entered.wait(5))
                before = self.bytes_and_times()
                catalog = pool.submit(main.api_task_catalog).result(5)
                transcript = pool.submit(main.api_transcript, reader.id).result(5)
                self.assertFalse(pending.done(), "Reads must finish before the index is released")
                self.assertEqual(catalog["total"], 2)
                self.assertEqual(next(row["title"] for row in catalog["tasks"] if row["id"] == writer.id), writer.title)
                self.assertEqual(transcript["full_text"], "Synthetic retained caption")
                self.assertEqual(self.bytes_and_times(), before, "Read APIs must not mutate task files")
            finally:
                release.set()
            pending.result(5)

    def held_reader(self, target, opened, release):
        original = Path.read_text

        def read(path, *args, **kwargs):
            if path != target or threading.current_thread().name != "held-manifest-reader":
                return original(path, *args, **kwargs)
            with path.open("r", encoding="utf-8") as stream:
                opened.set()
                self.assertTrue(release.wait(5), "Test must close its held reader")
                return stream.read()

        return patch.object(Path, "read_text", read)

    def test_atomic_replacement_waits_until_real_reader_handle_is_closed(self):
        record = self.task("replace")
        target = self.tasks / record.id / "task.json"
        opened, release = threading.Event(), threading.Event()
        lock = ObservedManifestLock(storage._manifest_io_lock, "manifest-writer")

        def read():
            threading.current_thread().name = "held-manifest-reader"
            return storage.get_task(record.id)

        def write():
            threading.current_thread().name = "manifest-writer"
            storage.save_task(record.model_copy(update={"title": "Synthetic replacement"}))

        with patch.object(storage, "_manifest_io_lock", lock), self.held_reader(target, opened, release), \
                patch.object(storage, "index_task", return_value=True), ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(read)
            try:
                self.assertTrue(opened.wait(5))
                writing = pool.submit(write)
                self.assertTrue(lock.attempted.wait(5))
                self.assertFalse(writing.done(), "Windows replacement must not run against an open ordinary read handle")
            finally:
                release.set()
            self.assertEqual(reading.result(5).title, record.title)
            writing.result(5)  # Actual Path.replace must succeed, including on Windows.
        self.assertEqual(storage.get_task(record.id).title, "Synthetic replacement")

    def test_deletion_waits_for_reader_opened_after_index_cleanup_started(self):
        record = self.task("delete")
        root = self.tasks / record.id
        indexed, finish_cleanup, opened, release = (threading.Event() for _ in range(4))
        # The deletion's first manifest-lock entry reads eligibility; the second
        # protects removal after index cleanup, when another reader may be open.
        lock = ObservedManifestLock(storage._manifest_io_lock, "manifest-deleter", attempt_number=2)

        def remove_index(task_id):
            self.assertEqual(task_id, record.id)
            indexed.set()
            self.assertTrue(finish_cleanup.wait(5))
            return True

        def delete():
            threading.current_thread().name = "manifest-deleter"
            return storage.delete_task(record.id)

        def read():
            threading.current_thread().name = "held-manifest-reader"
            return storage.get_task(record.id)

        with patch.object(storage, "_manifest_io_lock", lock), self.held_reader(root / "task.json", opened, release), \
                patch.object(storage, "remove_task", remove_index), \
                patch.object(storage.assistant_records, "source_deletion", return_value=nullcontext()), \
                ThreadPoolExecutor(max_workers=2) as pool:
            deleting = pool.submit(delete)
            try:
                self.assertTrue(indexed.wait(5))
                reading = pool.submit(read)
                self.assertTrue(opened.wait(5))
                finish_cleanup.set()
                self.assertTrue(lock.attempted.wait(5))
                self.assertFalse(deleting.done())
                self.assertTrue((root / "task.json").is_file())
            finally:
                finish_cleanup.set()
                release.set()
            self.assertEqual(reading.result(5).id, record.id)
            self.assertEqual(deleting.result(5)["task_id"], record.id)
        self.assertFalse(root.exists())
        with self.assertRaises(FileNotFoundError):
            storage.get_task(record.id)


if __name__ == "__main__":
    unittest.main()
