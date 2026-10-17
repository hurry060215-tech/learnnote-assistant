"""Request-local facts retain full task projections and fresh file ownership."""
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from app import main, storage, queue_journal
from app.models import TaskRecord
from app.task_artifacts import public_summary_task
from app.task_projection_evidence import TaskProjectionEvidence


class TaskProjectionEvidenceTests(unittest.TestCase):
    def task(self, task_id="projection01"):
        return TaskRecord(id=task_id, source_type="local", title="Full source", status="success",
                          created_at="2026-10-17", updated_at="2026-10-17")

    def facts(self, task, **overrides):
        readers = dict(media_path=Mock(return_value=Path("media.mp4")),
                       media_signature=Mock(return_value="mp4"), non_video=Mock(return_value=False))
        readers.update(overrides)
        return TaskProjectionEvidence(task, **readers), readers

    def test_fact_readers_run_once_per_owned_task_and_fresh_object_reads_again(self):
        task = public_summary_task(self.task())
        facts, readers = self.facts(task)
        for _ in range(3):
            self.assertEqual(facts.media_validation(task), ("verified", "mp4"))
            self.assertEqual(facts.media_path(task), Path("media.mp4"))
        for reader in readers.values():
            reader.assert_called_once()
        fresh = TaskProjectionEvidence(task, **readers)
        fresh.media_validation(task)
        self.assertTrue(all(reader.call_count == 2 for reader in readers.values()))

    def test_same_id_foreign_snapshot_and_changed_generation_are_rejected(self):
        task = public_summary_task(self.task())
        facts, readers = self.facts(task)
        for other in (self.task("projection02"), task.model_copy()):
            with self.assertRaisesRegex(ValueError, "task_projection_evidence_mismatch"):
                facts.media_path(other)
        task.retry_count += 1
        with self.assertRaisesRegex(ValueError, "task_projection_evidence_mismatch"):
            facts.media_validation(task)
        self.assertTrue(all(not reader.called for reader in readers.values()))

    def test_missing_media_is_consistent_and_changed_path_is_rejected(self):
        task = self.task()
        facts, readers = self.facts(task, media_path=Mock(return_value=None))
        for _ in range(2):
            self.assertEqual(facts.media_validation(task), ("missing", ""))
        readers["media_path"].assert_called_once()
        readers["media_signature"].assert_not_called()
        task.source_media_path = "different-media.mp4"
        with self.assertRaisesRegex(ValueError, "task_projection_evidence_mismatch"):
            facts.media_path(task)


class TaskPayloadProjectionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "tasks"
        self.root.mkdir()
        self.stack.enter_context(patch.object(storage, "TASK_DIR", self.root))
        self.stack.enter_context(patch.object(main, "TASK_DIR", self.root))
        self.stack.enter_context(patch.object(storage, "ensure_dirs", return_value=None))

    def record(self, task_id="projection01"):
        root = self.root / task_id
        root.mkdir()
        transcript = {"source": "browser-subtitle", "segments": [
            {"start": start, "end": start + 30, "text": f"Complete source cue at {start} seconds."}
            for start in range(0, 10800, 30)]}
        (root / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
        (root / "note.md").write_text("# Full source\n\nRetained source note.", encoding="utf-8")
        task = TaskRecord(id=task_id, source_type="local", title="Full source", mode="subtitle_only",
                          status="success", created_at="2026-10-17", updated_at="2026-10-17",
                          transcript_path=str(root / "transcript.json"), note_path=str(root / "note.md"))
        (root / "task.json").write_text(task.model_dump_json(), encoding="utf-8")
        return task

    def test_full_list_reuses_media_and_queue_without_changing_transcript_reads(self):
        tasks = [self.record("projection01"), self.record("projection02")]
        with patch.object(main, "read_transcript", wraps=main.read_transcript) as transcript, \
             patch.object(main, "task_media_path", wraps=main.task_media_path) as media, \
             patch.object(queue_journal, "read_queue_entries", wraps=queue_journal.read_queue_entries) as queue:
            payload = main.api_list_tasks()
        self.assertEqual(transcript.call_count, 8)
        self.assertEqual(media.call_count, 2)
        queue.assert_called_once()
        self.assertEqual({item["id"] for item in payload["tasks"]}, {item.id for item in tasks})
        for item in payload["tasks"]:
            self.assertEqual(item["evidence_quality"]["browser_subtitle_cue_count"], 360)
            self.assertEqual(item["reuse"]["transcript_source"], "browser-subtitle")
            self.assertIn("qa", item)
            self.assertIn("audit", item)
            self.assertIn("claim_evidence", item)
            self.assertIn("artifact_status", item)

    def test_next_request_observes_changed_transcript_and_missing_artifact(self):
        task = self.record()
        before = main.task_payload(task)
        path = self.root / task.id / "transcript.json"
        path.write_text(json.dumps({"source": "asr", "segments": []}), encoding="utf-8")
        changed = main.task_payload(task)
        self.assertEqual(before["reuse"]["transcript_source"], "browser-subtitle")
        self.assertEqual(changed["reuse"]["transcript_source"], "asr")
        path.unlink()
        missing = main.task_payload(task)
        self.assertFalse(missing["reuse"]["transcript_ready"])
        self.assertEqual(missing["reuse"]["transcript_source"], "")
        self.assertIn("transcript_path", missing["artifact_status"]["path_diagnostics"])

    def test_replacement_and_deletion_between_requests_revalidate_media(self):
        task = self.record()
        media = self.root / task.id / "media.mp4"
        media.write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(64))
        task.media_path = str(media)
        storage.task_file(task.id).write_text(task.model_dump_json(), encoding="utf-8")
        self.assertEqual(main.task_payload(task)["reuse"]["media_validation"], "verified")
        media.write_bytes(b"<html>not video</html>")
        self.assertEqual(main.task_payload(task)["reuse"]["media_validation"], "invalid")
        media.unlink()
        self.assertEqual(main.task_payload(task)["reuse"]["media_validation"], "missing")

    def test_cancel_during_blocked_projection_is_not_blocked_or_rewritten(self):
        task = self.record()
        with patch.object(storage, "index_task"), patch.object(storage, "record_task_event"), patch.object(storage, "record_status"):
            task = storage.update_task(task.id, status="running", phase="summarizing")
            entered, release = threading.Event(), threading.Event()
            caller = threading.get_ident()
            original = main.task_media_path
            def held(record):
                if threading.get_ident() != caller and not entered.is_set():
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("Projection was not released")
                return original(record)
            with patch.object(main, "task_media_path", side_effect=held), ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(main.api_list_tasks)
                try:
                    self.assertTrue(entered.wait(5))
                    cancelled = main.api_cancel_task(task.id)["task"]
                    self.assertTrue(cancelled["cancel_requested"])
                    self.assertEqual(cancelled["status"], "cancelling")
                finally:
                    release.set()
                pending.result(5)
            latest = main.api_list_tasks()["tasks"][0]
            self.assertTrue(latest["cancel_requested"])
            self.assertEqual(latest["status"], "cancelling")
            self.assertEqual(latest["control_generation"], cancelled["control_generation"])

    def test_public_summary_ownership_preserves_original_diagnostics(self):
        task = self.record()
        task.summary_warning = "provider detail https://example.test/?token=SECRET"
        original = task.model_dump(mode="json")
        main.task_payload(task)
        self.assertEqual(task.model_dump(mode="json"), original)

    def test_queue_snapshot_is_read_only_and_next_request_observes_changes(self):
        rows = [{"task_id": "one", "sequence": 1, "kind": "page", "state": "running", "updated_at": 1},
                {"task_id": "two", "sequence": 2, "kind": "page", "state": "queued", "updated_at": 1}]
        original = json.loads(json.dumps(rows))
        with patch.object(queue_journal, "read_queue_entries", return_value=(rows, True)) as read:
            snapshot = queue_journal.read_queue_snapshot(self.root.parent)
            first = queue_journal.queue_status_from_snapshot(snapshot, "two")
            second = queue_journal.queue_status_from_snapshot(snapshot, "one")
            read.assert_called_once()
        self.assertTrue(first["paused"])
        self.assertEqual((first["position"], first["queued_count"], first["running_count"]), (1, 1, 1))
        self.assertEqual(second["state"], "running")
        self.assertEqual(rows, original)
        with patch.object(queue_journal, "read_queue_entries", return_value=([{**rows[0], "state": "cancelled"}], False)):
            self.assertEqual(queue_journal.queue_status(self.root.parent, "one")["state"], "cancelled")
        self.assertEqual(queue_journal.queue_status_from_snapshot(snapshot, "one")["state"], "running")
        self.assertEqual(queue_journal.queue_status_from_snapshot(([{"state": "unknown"}], None), "one"),
                         {"state": "unknown", "position": 0, "queued_count": 0, "running_count": 0, "kind": ""})
