from concurrent.futures import ThreadPoolExecutor
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
from app.models import TaskRecord
from app.task_control import cancel_task_generation, read_task_control, task_generation, TaskControlConflict
from app.task_queue import LocalTaskQueue, queue_status, recover_processing
from app.queue_controls import set_queue_paused


def _process_progress(root, task_id, ready, release):
    storage.TASK_DIR = Path(root) / "tasks"
    with patch.object(storage, "index_task"), patch.object(storage, "record_task_event"), patch.object(storage, "record_status"):
        with storage.task_state_transaction():
            ready.set()
            release.wait(5)
            storage.update_task(task_id, progress=40)


class TaskControlTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for key, value in (("TASK_DIR", self.root / "tasks"), ("ensure_dirs", lambda: None),
                           ("index_task", lambda task: None), ("record_task_event", lambda *a, **k: None),
                           ("record_status", lambda *a, **k: None)):
            self.stack.enter_context(patch.object(storage, key, value))
        self.stack.enter_context(patch("app.task_queue.record_task_event"))
        self.queues = []
        self.release = threading.Event()
        self.addCleanup(self.stop_queues)

    def stop_queues(self):
        self.release.set()
        for queue in self.queues:
            queue.stop()

    def task(self, **changes):
        task = storage.create_task("local", "Synthetic fixture")
        if changes:
            task = storage.update_task(task.id, **changes)
        return task

    def queue(self):
        queue = LocalTaskQueue(self.root)
        self.queues.append(queue)
        return queue

    def cancel(self, task, operation="cancel-op"):
        return cancel_task_generation(task.id, expected_generation=task_generation(task), operation_id=operation)

    def test_generation_is_frozen_for_progress_enrichment_and_changes_on_retry(self):
        task = self.task(status="failed")
        generation = task_generation(task)
        task = storage.update_task(task.id, progress=45, mode="subtitle_only",
                                   source_identity=task.source_identity.model_copy(update={"media_sha256": "synthetic"}))
        self.assertEqual(task_generation(task), generation)
        retry = storage.admit_task_retry(task.id, expected_generation=generation)
        self.assertNotEqual(task_generation(retry), generation)
        self.assertEqual(retry.retry_count, 1)

    def test_queue_cas_without_cached_queue_prevents_callback_and_preserves_files(self):
        task = self.task()
        note = storage.task_file(task.id).with_name("note.md")
        note.write_text("fixture", encoding="utf-8")
        queue = self.queue()
        set_queue_paused(self.root, True)
        called = threading.Event()
        future = queue.enqueue(task.id, "local", called.set, generation=task_generation(task))
        result = self.cancel(task)
        future.result(3)
        self.assertTrue(result["queued_job_cancelled"])
        self.assertFalse(result["worker_acknowledged"])
        self.assertFalse(result["callback_finished"])
        self.assertFalse(called.is_set())
        self.assertEqual(note.read_text(encoding="utf-8"), "fixture")
        self.assertEqual(storage.get_task(task.id).status, "cancelled")

    def test_queue_claim_before_manifest_update_is_only_requested_until_ack_and_return(self):
        task = self.task()
        started, ack, finish = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        def callback():
            started.set()
            self.release.wait(5)
            storage.mark_task_cancelled(task.id)
            ack.set()
            finish.wait(5)
        future = self.queue().enqueue(task.id, "local", callback, generation=task_generation(task))
        self.assertTrue(started.wait(3))
        self.assertEqual(storage.get_task(task.id).status, "queued")
        result = self.cancel(task)
        self.assertEqual(result["status"], "cancelling")
        self.assertTrue(result["cancellation_requested"])
        self.assertFalse(result["queued_job_cancelled"])
        self.assertFalse(result["worker_acknowledged"])
        self.assertFalse(result["callback_finished"])
        self.release.set()
        self.assertTrue(ack.wait(3))
        result = read_task_control(task.id)
        self.assertTrue(result["worker_acknowledged"])
        self.assertFalse(result["callback_finished"])
        finish.set()
        future.result(3)
        self.assertTrue(read_task_control(task.id)["callback_finished"])

    def test_old_cancellation_cannot_mutate_retry_and_receipt_proves_old_operation(self):
        task = self.task()
        queue = self.queue()
        set_queue_paused(self.root, True)
        queue.enqueue(task.id, "local", lambda: None, generation=task_generation(task))
        self.cancel(task)
        retry = storage.admit_task_retry(task.id, expected_generation=task_generation(task))
        before = storage.task_file(task.id).read_bytes()
        replay = self.cancel(task)
        self.assertTrue(replay["operation_applied"])
        self.assertEqual(replay["applied_generation"], task_generation(task))
        self.assertEqual(replay["generation"], task_generation(retry))
        self.assertFalse(replay["cancellation_requested"])
        with self.assertRaisesRegex(TaskControlConflict, "stale_generation"):
            self.cancel(task, "another-operation")
        self.assertEqual(storage.task_file(task.id).read_bytes(), before)

    def test_pending_cancellation_preserves_the_first_operation_receipt(self):
        task = self.task()
        self.cancel(task)
        before = storage.task_file(task.id).read_bytes()
        with self.assertRaisesRegex(TaskControlConflict, "cancellation_pending"):
            self.cancel(task, "later-operation")
        self.assertEqual(storage.task_file(task.id).read_bytes(), before)
        self.assertEqual(storage.request_task_cancel(task.id).cancellation_receipt.operation_id, "cancel-op")

    def test_retry_enqueue_replaces_old_generation_pending_cache(self):
        task = self.task()
        queue = self.queue()
        set_queue_paused(self.root, True)
        with queue.condition:
            old = queue.enqueue(task.id, "local", lambda: self.fail("Old callback ran"), generation=task_generation(task))
            self.cancel(task)
            retry = storage.admit_task_retry(task.id, expected_generation=task_generation(task))
            called = threading.Event()
            new = queue.enqueue(task.id, "local", called.set, generation=task_generation(retry))
            self.assertIsNot(old, new)
        set_queue_paused(self.root, False)
        new.result(3)
        old.result(3)
        self.assertTrue(called.is_set())
        self.assertEqual(queue.entries()[0]["generation"], task_generation(retry))

    def test_another_queue_cannot_claim_a_retry_with_its_old_callback(self):
        from app.worker_lease import worker_lease
        task = self.task()
        first, second = self.queue(), self.queue()
        old_called, new_called = threading.Event(), threading.Event()
        with worker_lease(self.root):
            old = first.enqueue(task.id, "local", old_called.set, generation=task_generation(task))
            self.cancel(task)
            retry = storage.admit_task_retry(task.id, expected_generation=task_generation(task))
            new = second.enqueue(task.id, "local", new_called.set, generation=task_generation(retry))
        old.result(3)
        new.result(3)
        self.assertFalse(old_called.is_set())
        self.assertTrue(new_called.is_set())

    def test_replacement_in_another_lane_releases_the_old_cached_future(self):
        for old_kind, new_kind in (("summary", "local"), ("local", "summary")):
            with self.subTest(old_kind=old_kind):
                task = self.task()
                first, second = self.queue(), self.queue()
                set_queue_paused(self.root, True)
                called = threading.Event()
                with first.condition:
                    old = first.enqueue(task.id, old_kind, lambda: self.fail("Old callback ran"), generation=task_generation(task))
                    self.cancel(task)
                    retry = storage.admit_task_retry(task.id, expected_generation=task_generation(task))
                    new = second.enqueue(task.id, new_kind, called.set, generation=task_generation(retry))
                    set_queue_paused(self.root, False)
                new.result(3)
                old.result(3)
                self.assertTrue(called.is_set())
                self.assertNotIn(task.id, first.jobs)

    def test_concurrent_resume_admits_one_and_old_running_row_blocks_new_generation(self):
        task = self.task(status="failed", phase="failed")
        barrier = threading.Barrier(2)
        def resume():
            barrier.wait(3)
            try:
                return storage.admit_task_retry(task.id, expected_generation=task_generation(task)).retry_count
            except TaskControlConflict as exc:
                return exc.code
        with ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(lambda _: resume(), range(2)))
        self.assertEqual(outcomes.count(1), 1)
        self.assertEqual(outcomes.count("stale_generation"), 1)
        other = self.task(status="cancelled")
        queue = self.queue()
        with closing(queue.connect()) as db:
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at,generation) VALUES (?,'local',0,'running',0,'old-generation')", (other.id,))
            db.commit()
        with self.assertRaisesRegex(TaskControlConflict, "task_still_running"):
            storage.admit_task_retry(other.id, expected_generation=task_generation(other))
        with self.assertRaisesRegex(TaskControlConflict, "task_still_running"):
            storage.admit_task_retry(other.id, expected_generation=task_generation(other), clone=True)

    def test_all_same_id_routes_admit_only_one_concurrent_request(self):
        from fastapi import BackgroundTasks, HTTPException
        from app import main, screen_subtitle_routes
        from app.models import TaskOptions, TranscriptResult, ScreenSubtitleSettings
        from app.task_control import admit_retry
        options = TaskOptions(content_mode="text", visual_understanding=False)
        for route in ("summary", "media", "screen"):
            with self.subTest(route=route):
                task = self.task(status="failed", options=options)
                media = storage.task_file(task.id).with_name("fixture.mp4")
                media.write_bytes(b"synthetic-media")
                transcript = media.with_name("transcript.json")
                transcript.write_text(TranscriptResult(full_text="synthetic saved transcript").model_dump_json(), encoding="utf-8")
                changes = {"media_path": str(media)}
                if route == "summary":
                    changes["transcript_path"] = str(transcript)
                if route == "screen":
                    changes.update(mode="screen_subtitles", options=options.model_copy(update={"screen_subtitles": ScreenSubtitleSettings()}))
                storage.update_task(task.id, **changes)
                barrier = threading.Barrier(2)
                def final_admission(source, **kwargs):
                    barrier.wait(3)
                    return admit_retry(source, **kwargs)
                def invoke():
                    try:
                        if route == "summary":
                            return main.retry_summary(task.id, BackgroundTasks(), None)
                        if route == "media":
                            return main.resume_task_from_checkpoint(task.id, BackgroundTasks(), None)
                        return screen_subtitle_routes.resume_screen_subtitles(task.id, BackgroundTasks())
                    except HTTPException as exc:
                        return exc.status_code
                with patch("app.task_control.admit_retry", side_effect=final_admission), \
                     patch.object(main, "require_ready_note_model"), patch.object(main, "_snapshot_before_retry"), \
                     patch.object(main, "task_payload", side_effect=lambda task: task.model_dump()), \
                     patch.object(screen_subtitle_routes, "require_ready_note_model"), \
                     patch.object(main, "schedule_processing") as schedule, \
                     patch.object(screen_subtitle_routes, "schedule_processing") as screen_schedule, \
                     ThreadPoolExecutor(2) as pool:
                    outcomes = list(pool.map(lambda _: invoke(), range(2)))
                    self.assertEqual(sum(isinstance(value, dict) for value in outcomes), 1)
                    self.assertEqual(outcomes.count(409), 1)
                    self.assertEqual(schedule.call_count + screen_schedule.call_count, 1)
                self.assertEqual(storage.get_task(task.id).retry_count, 1)

    def test_delayed_clone_retry_cannot_regress_newer_same_id_generations(self):
        from fastapi import BackgroundTasks, HTTPException
        from app import main
        task = self.task(status="failed", phase="failed")
        observed, release = threading.Event(), threading.Event()
        media = storage.task_file(task.id).with_name("fixture.mp4")
        media.write_bytes(b"synthetic media")
        def delayed_media_path(_):
            observed.set()
            release.wait(5)
            return media
        def clone():
            try:
                return main.api_retry_task(task.id, BackgroundTasks(), None)
            except HTTPException as exc:
                return exc.status_code, exc.detail["code"]
        with patch.object(main, "task_media_path", side_effect=delayed_media_path), \
             patch.object(main, "create_from_existing_media") as create_clone, ThreadPoolExecutor(1) as pool:
            pending = pool.submit(clone)
            try:
                self.assertTrue(observed.wait(3))
                first = storage.admit_task_retry(task.id, expected_generation=task_generation(task))
                storage.update_task(task.id, status="failed", phase="failed")
                second = storage.admit_task_retry(task.id, expected_generation=task_generation(first))
                storage.update_task(task.id, status="failed", phase="failed")
                before = storage.task_file(task.id).read_bytes()
                release.set()
                self.assertEqual(pending.result(3), (409, "stale_generation"))
                create_clone.assert_not_called()
                self.assertEqual(storage.task_file(task.id).read_bytes(), before)
                self.assertEqual(storage.get_task(task.id).retry_count, 2)
                self.assertEqual(task_generation(storage.get_task(task.id)), task_generation(second))
            finally:
                release.set()

    def test_clone_retry_preserves_terminal_source_and_increments_current_counter(self):
        from fastapi import BackgroundTasks
        from app import main
        task = self.task(status="failed", phase="failed")
        with patch.object(main, "task_media_path", return_value=self.root / "synthetic.mp4"), \
             patch.object(main, "create_from_existing_media", return_value={"task_id": "new-clone"}) as clone:
            result = main.api_retry_task(task.id, BackgroundTasks(), None)
        self.assertEqual(result["task_id"], "new-clone")
        clone.assert_called_once()
        source = storage.get_task(task.id)
        self.assertEqual(source.status, "failed")
        self.assertEqual(source.retry_count, 1)
        self.assertNotEqual(task_generation(source), task_generation(task))

    def test_concurrent_progress_and_stale_reconciliation_preserve_cancellation(self):
        task = self.task()
        stale = task.model_copy(update={"updated_at": "2000-01-01T00:00:00+00:00"})
        self.cancel(task)
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(storage.update_task, task.id, progress=60, status="running", cancel_requested=False),
                       pool.submit(storage.reconcile_stale_tasks, [stale])]
            for future in futures:
                future.result(3)
        latest = storage.get_task(task.id)
        self.assertTrue(latest.cancel_requested)
        self.assertEqual(latest.status, "cancelling")
        self.assertEqual(latest.cancellation_receipt.operation_id, "cancel-op")
        self.assertFalse(read_task_control(task.id)["worker_acknowledged"])

    def test_cross_process_update_and_cancel_share_state_transaction(self):
        task = self.task()
        ctx = multiprocessing.get_context("spawn")
        ready, release = ctx.Event(), ctx.Event()
        child = ctx.Process(target=_process_progress, args=(str(self.root), task.id, ready, release))
        child.start()
        try:
            self.assertTrue(ready.wait(5))
            with ThreadPoolExecutor(1) as pool:
                cancelled = pool.submit(self.cancel, task)
                release.set()
                cancelled.result(5)
            child.join(5)
            self.assertEqual(child.exitcode, 0)
            latest = storage.get_task(task.id)
            self.assertTrue(latest.cancel_requested)
            self.assertEqual(latest.progress, 40)
        finally:
            release.set()
            if child.is_alive():
                child.terminate()
                child.join(3)

    def test_receipt_replay_completes_a_cancel_request_interrupted_before_queue_cas(self):
        task = self.task()
        queue = self.queue()
        set_queue_paused(self.root, True)
        future = queue.enqueue(task.id, "local", lambda: self.fail("Cancelled callback ran"), generation=task_generation(task))
        with patch("app.task_queue.cancel_queued_processing", side_effect=OSError("interrupted before CAS")):
            with self.assertRaises(OSError):
                self.cancel(task)
        self.assertEqual(read_task_control(task.id)["queue_state"], "queued")
        result = self.cancel(task)
        self.assertTrue(result["queued_job_cancelled"])
        self.assertEqual(result["status"], "cancelled")
        future.result(3)
        self.assertEqual(storage.admit_task_retry(task.id, expected_generation=task_generation(task)).retry_count, 1)

    def test_receipt_recovers_crash_after_queue_cas_before_manifest_completion(self):
        task = self.task()
        queue = self.queue()
        set_queue_paused(self.root, True)
        queue.enqueue(task.id, "local", lambda: self.fail("Cancelled callback ran"), generation=task_generation(task))
        update = storage.update_task
        def fail_second(task_id, **changes):
            if changes.get("status") == "cancelled":
                raise OSError("synthetic interrupted commit")
            return update(task_id, **changes)
        with patch.object(storage, "update_task", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.cancel(task)
        before = storage.task_file(task.id).read_bytes()
        self.assertTrue(read_task_control(task.id)["queued_job_cancelled"])
        self.assertEqual(storage.task_file(task.id).read_bytes(), before)
        result = self.cancel(task)
        self.assertTrue(result["operation_applied"])
        self.assertTrue(result["queued_job_cancelled"])
        self.assertFalse(result["worker_acknowledged"])
        self.assertEqual(result["status"], "cancelled")
        retry = storage.admit_task_retry(task.id, expected_generation=task_generation(task))
        self.assertEqual(retry.retry_count, 1)

    def test_cancel_before_enqueue_prevents_dispatch_and_allows_retry(self):
        from fastapi import BackgroundTasks
        from app.task_queue import schedule_processing, queue_for
        task = self.task()
        self.cancel(task)
        called = threading.Event()
        schedule_processing(BackgroundTasks(), lambda _: called.set(), task.id)
        self.queues.append(queue_for(self.root))
        result = read_task_control(task.id)
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(result["dispatch_prevented"])
        self.assertFalse(result["queued_job_cancelled"])
        self.assertFalse(result["worker_acknowledged"])
        self.assertFalse(result["callback_finished"])
        self.assertFalse(called.is_set())
        self.assertEqual(storage.admit_task_retry(task.id, expected_generation=task_generation(task)).retry_count, 1)

    def test_restart_closes_cancel_request_with_no_dispatch_row_without_inventing_ack(self):
        task = self.task()
        self.cancel(task)
        recover_processing(self.root)
        result = read_task_control(task.id)
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(result["recovery_stopped"])
        self.assertFalse(result["worker_acknowledged"])
        self.assertFalse(result["dispatch_prevented"])
        self.assertIsNone(result["callback_finished"])
        self.assertEqual(storage.admit_task_retry(task.id, expected_generation=task_generation(task)).retry_count, 1)

    def test_restart_finishes_manifest_after_durable_queue_cas(self):
        task = self.task()
        queue = self.queue()
        set_queue_paused(self.root, True)
        queue.enqueue(task.id, "local", lambda: self.fail("Cancelled callback ran"), generation=task_generation(task))
        result = self.cancel(task)
        # A crash left only the first manifest commit, but the queue CAS survived.
        payload = json.loads(storage.task_file(task.id).read_text(encoding="utf-8"))
        payload.update(status="cancelling", phase="cancelling", cancelled_at="")
        payload["cancellation_receipt"]["queued_cancelled_at"] = ""
        storage.task_file(task.id).write_text(json.dumps(payload), encoding="utf-8")
        queue.stop()
        recover_processing(self.root)
        self.assertEqual(storage.get_task(task.id).status, "cancelled")
        self.assertTrue(read_task_control(task.id)["queued_job_cancelled"])
        self.assertFalse(read_task_control(task.id)["worker_acknowledged"])
        self.assertEqual(storage.admit_task_retry(task.id, expected_generation=task_generation(task)).retry_count, 1)

    def test_restart_reuses_generation_and_honors_persisted_cancellation(self):
        task = self.task(status="running", cancel_requested=True, phase="cancelling")
        generation = task_generation(task)
        queue = self.queue()
        with closing(queue.connect()) as db:
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at,generation) VALUES (?,'local',0,'running',0,?)", (task.id, generation))
            db.commit()
        with patch("app.processor.process_local_video_task") as callback:
            result = recover_processing(self.root)
        self.assertEqual(result["recovered"], 0)
        callback.assert_not_called()
        self.assertEqual(task_generation(storage.get_task(task.id)), generation)
        self.assertTrue(storage.get_task(task.id).cancel_requested)
        self.assertIsNone(read_task_control(task.id)["callback_finished"])
        self.assertFalse(read_task_control(task.id)["worker_acknowledged"])

    def test_recovery_snapshot_cannot_overwrite_an_admitted_replacement(self):
        task = self.task()
        media = storage.task_file(task.id).with_name("fixture.mp4")
        media.write_bytes(b"synthetic media")
        task = storage.update_task(task.id, source_media_path=str(media))
        first, second = self.queue(), self.queue()
        with closing(first.connect()) as db:
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at,generation) VALUES (?,'local',0,'queued',0,?)", (task.id, task_generation(task)))
            db.commit()
        entries = first.entries
        called = threading.Event()
        replacement = []
        def snapshot_then_replace():
            snapshot = entries()
            self.cancel(task)
            retry = storage.admit_task_retry(task.id, expected_generation=task_generation(task))
            replacement.append(second.enqueue(task.id, "local", called.set, generation=task_generation(retry)))
            return snapshot
        with patch("app.task_queue.queue_for", return_value=first), patch.object(first, "entries", side_effect=snapshot_then_replace):
            result = recover_processing(self.root)
        self.assertEqual(result["recovered"], 0)
        replacement[0].result(3)
        self.assertTrue(called.is_set())
        self.assertEqual(first.entries()[0]["generation"], task_generation(storage.get_task(task.id)))

    def test_restart_continues_an_interrupted_recovery_in_same_generation(self):
        task = self.task()
        media = storage.task_file(task.id).with_name("fixture.mp4")
        media.write_bytes(b"synthetic media")
        task = storage.update_task(task.id, source_media_path=str(media))
        queue = self.queue()
        with closing(queue.connect()) as db:
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at,generation) VALUES (?,'local',0,'recovering',0,?)", (task.id, task_generation(task)))
            db.commit()
        called = threading.Event()
        with patch("app.task_queue.queue_for", return_value=queue), patch("app.processor.process_local_video_task", side_effect=lambda *a, **k: called.set()):
            result = recover_processing(self.root)
            self.assertTrue(called.wait(3))
            queue.stop()
        self.assertEqual(result["recovered"], 1)
        self.assertEqual(task_generation(storage.get_task(task.id)), task_generation(task))

    def test_read_only_status_and_snapshots_preserve_all_bytes_and_do_not_create_database(self):
        task = self.task(title="", status="running")
        path = storage.task_file(task.id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["updated_at"] = "2000-01-01T00:00:00+00:00"
        path.write_text(json.dumps(payload), encoding="utf-8")
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(storage.list_tasks_snapshot()[0].status, "running")
        self.assertEqual(read_task_control(task.id)["queue_state"], "none")
        self.assertEqual(queue_status(self.root, task.id)["state"], "none")
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.root / "task-queue.sqlite3").exists())
        (self.root / "task-queue.sqlite3").write_bytes(b"corrupt fixture")
        before = (self.root / "task-queue.sqlite3").read_bytes()
        self.assertEqual(read_task_control(task.id)["queue_state"], "unknown")
        self.assertIsNone(read_task_control(task.id)["callback_finished"])
        self.assertEqual((self.root / "task-queue.sqlite3").read_bytes(), before)

    def test_elapsed_cancellation_does_not_claim_worker_acknowledgment(self):
        task = self.task()
        self.cancel(task)
        future = datetime.now(timezone.utc) + timedelta(days=1)
        [latest] = storage.reconcile_stale_tasks([task], now=future)
        self.assertEqual(latest.status, "cancelling")
        self.assertFalse(read_task_control(task.id)["worker_acknowledged"])

    def test_deferred_task_requires_existing_route_cleanup(self):
        task = self.task(awaiting_confirmation=True)
        before = storage.task_file(task.id).read_bytes()
        with self.assertRaisesRegex(TaskControlConflict, "deferred_task"):
            self.cancel(task)
        self.assertEqual(storage.task_file(task.id).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
