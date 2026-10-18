import hashlib
import json
import os
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import generated_draft_reader as reader, personal_anchors, personal_reviews, storage
from app.models import TranscriptResult, TranscriptSegment
from app.pipeline_progress import start_pipeline_attempt, write_progressive_draft
from app.routers import notes


class GeneratedDraftReaderTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("storage", "library", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        for module in ("storage", "library", "knowledge", "routers.notes"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        self.stack.enter_context(patch("app.storage.ensure_dirs"))
        self.task = storage.create_task("local", "Transcript draft fixture")
        self.work = storage.TASK_DIR / self.task.id
        self.transcript = TranscriptResult(source="fixture", full_text="Exact transcript. 中文。",
            segments=[TranscriptSegment(start=0, end=10, text="Exact transcript. 中文。")])
        transcript_path = storage.write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        storage.update_task(self.task.id, status="running", transcript_path=str(transcript_path))
        self.attempt = start_pipeline_attempt(self.task.id)
        self.note = write_progressive_draft(self.task.id, self.task.title, self.transcript, expected_attempt_id=self.attempt)
        self.publish()
        app = FastAPI()
        app.include_router(notes.notes_router)
        self.client = self.stack.enter_context(TestClient(app))

    def publish(self):
        self.task = storage.update_task(self.task.id, note_path=str(self.note), summary_source="transcript-draft")

    def get(self):
        return notes.get_edition("task", self.task.id, True, self.task.control_generation)

    def rejected(self, reason=None):
        with self.assertRaises(HTTPException) as caught:
            self.get()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["code"], "reader_snapshot_unavailable")
        if reason:
            self.assertEqual(caught.exception.detail["reason"], reason)

    @unittest.skipUnless(os.name == "nt", "Windows file-sharing contract")
    def test_windows_opt_in_read_allows_atomic_replace_while_original_opener_blocks(self):
        for name in ("task.json", "pipeline_metrics.json", "draft.md", "transcript.json"):
            path = self.work / name
            before = path.read_bytes()
            with self.subTest(name=name):
                with personal_anchors._opened_artifact(self.task.id, str(path)) as stream:
                    self.assertIsNotNone(stream)
                    with self.assertRaises(PermissionError):
                        storage.atomic_write_text(path, "replacement")
                    self.assertEqual(stream.read(), before)
                self.assertEqual(path.read_bytes(), before)
                with personal_anchors._opened_artifact(self.task.id, str(path), share_delete=True) as stream:
                    self.assertIsNotNone(stream)
                    storage.atomic_write_text(path, "replacement")
                    self.assertEqual(stream.read(), before)
                    self.assertFalse(os.get_inheritable(stream.fileno()))
                self.assertEqual(path.read_bytes(), b"replacement")
                path.write_bytes(before)

    def test_publication_replaced_during_open_read_is_rejected_as_conflict(self):
        original, replaced = reader._opened_artifact, False
        @contextmanager
        def replacing(task_id, value, **kwargs):
            nonlocal replaced
            self.assertIs(kwargs.get("share_delete"), True)
            with original(task_id, value, **kwargs) as stream:
                if Path(value).name == "pipeline_metrics.json" and not replaced:
                    self.assertIsNotNone(stream)
                    replaced = True
                    metrics = json.loads(Path(value).read_bytes())
                    metrics["draft"]["sequence"] += 1
                    current = next(item for item in metrics["attempts"] if item["attempt_id"] == metrics["current_attempt_id"])
                    current["draft"] = dict(metrics["draft"])
                    storage.write_json(task_id, "pipeline_metrics.json", metrics)
                yield stream
        with patch.object(reader, "_opened_artifact", replacing):
            self.rejected("snapshot_changed")
        self.assertTrue(replaced)

    def test_http_contract_and_ordinary_response_are_independent(self):
        response = self.client.get(f"/api/tasks/editions/task/{self.task.id}",
            params={"reader_snapshot": "true", "expected_generation": self.task.control_generation})
        self.assertEqual(response.status_code, 200)
        value = response.json()
        self.assertEqual(value["revision"], hashlib.sha256(value["text"].encode()).hexdigest())
        self.assertEqual(value["reader_snapshot"]["body_revision"], value["revision"])
        self.assertEqual(value["reader_snapshot"]["attempt_id"], self.attempt)
        self.assertEqual(value["reader_snapshot"]["source_revision"], reader.draft_source_revision(self.task, self.transcript))
        self.assertFalse(value["reader_snapshot"]["verified"])
        ordinary = notes.get_edition("task", self.task.id)
        self.assertEqual(ordinary, {key: value[key] for key in ("text", "revision", "edited")})

    def test_reader_never_uses_locked_readers_or_mutators(self):
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with patch("app.storage.get_task", side_effect=AssertionError("locked read")), \
                patch("app.storage.read_json", side_effect=AssertionError("locked JSON")), \
                patch("app.storage.atomic_write_text", side_effect=AssertionError("write")), \
                patch("app.storage.index_task", side_effect=AssertionError("index")):
            self.assertTrue(self.get()["text"])
        self.assertEqual(before, {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_index_and_personal_review_convoy_does_not_block_explicit_reader(self):
        storage.update_task(self.task.id, note_path="", summary_source="")
        entered, release, reviewing = threading.Event(), threading.Event(), threading.Event()
        index, context = storage.index_task, personal_reviews._context
        def held_index(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("index barrier not released")
            return index(*args, **kwargs)
        def review_context(*args):
            reviewing.set()
            return context(*args)
        with patch("app.storage.index_task", held_index), patch("app.personal_reviews._context", review_context), \
                ThreadPoolExecutor(max_workers=3) as pool:
            writer = pool.submit(storage.update_task, self.task.id, message="Controlled progress")
            self.assertTrue(entered.wait(2))
            review = pool.submit(notes.get_personal_review, "task", self.task.id)
            try:
                self.assertTrue(reviewing.wait(2))
                self.assertFalse(review.done())
                fast = pool.submit(self.get)
                self.assertTrue(fast.result(timeout=2)["reader_snapshot"]["provisional"])
                self.assertFalse(writer.done())
                self.assertFalse(review.done())
            finally:
                release.set()
            writer.result(timeout=2)
            self.assertEqual(review.result(timeout=2)["status"], "unmarked")

    def test_retry_retained_pointer_is_not_rebound_to_old_attempt(self):
        self.task = storage.update_task(self.task.id, retry_count=self.task.retry_count + 1)
        self.assertEqual(self.task.note_path, str(self.note))
        self.rejected("publication_unavailable")
        start_pipeline_attempt(self.task.id)
        self.rejected("publication_unavailable")

    def test_initial_pre_pointer_is_provisional_then_committed(self):
        storage.update_task(self.task.id, note_path="", summary_source="")
        self.assertTrue(self.get()["reader_snapshot"]["provisional"])
        self.assertEqual(notes.get_edition("task", self.task.id)["text"], "")
        self.publish()
        self.assertFalse(self.get()["reader_snapshot"]["provisional"])

    def test_provisional_rejects_retries_later_attempts_and_conflicting_pointers(self):
        storage.update_task(self.task.id, note_path="", summary_source="transcript-draft")
        self.rejected("task_ineligible")
        storage.update_task(self.task.id, note_path="", summary_source="")
        start_pipeline_attempt(self.task.id)
        self.rejected("publication_unavailable")
        self.task = storage.update_task(self.task.id, retry_count=1)
        self.rejected("task_ineligible")
        self.task = storage.update_task(self.task.id, retry_count=0, note_path=str(self.work / "note.md"))
        self.rejected("task_ineligible")

    def test_nonempty_missing_draft_pointer_does_not_become_provisional(self):
        self.note.unlink()
        self.rejected("artifact_unavailable")

    def test_source_change_while_writing_does_not_acquire_a_witness(self):
        self.attempt = start_pipeline_attempt(self.task.id)
        original_write = storage.atomic_write_text
        def changing(path, text):
            original_write(path, text)
            if path == self.note:
                storage.update_task(self.task.id, page_url="https://example.invalid/replaced")
        with patch("app.pipeline_progress.atomic_write_text", changing):
            write_progressive_draft(self.task.id, self.task.title, self.transcript, expected_attempt_id=self.attempt)
        self.rejected("publication_unavailable")

    def test_body_or_source_replacement_rejects_without_stale_fallback(self):
        original = self.note.read_bytes()
        storage.atomic_write_text(self.note, "# Wrong attempt\n")
        self.rejected("publication_mismatch")
        self.note.write_bytes(original)
        changed = self.transcript.model_copy(update={"full_text": "Changed transcript"})
        storage.write_json(self.task.id, "transcript.json", changed.model_dump(mode="json"))
        self.rejected("publication_mismatch")

    def test_source_identity_change_with_frozen_generation_rejects(self):
        for fields in ({"learning_range": {"start": 5, "end": 10}}, {"page_url": "https://example.invalid/changed"},
                       {"source_task_id": "other-owner"}):
            with self.subTest(fields=fields):
                storage.update_task(self.task.id, **fields)
                self.assertEqual(storage.get_task(self.task.id).control_generation, self.task.control_generation)
                self.rejected("publication_mismatch")
                storage.update_task(self.task.id, **{key: getattr(self.task, key) for key in fields})

    def test_late_replacement_during_read_is_rejected(self):
        original_read, replaced = reader._read, False
        def replacing(task_id, path):
            nonlocal replaced
            value = original_read(task_id, path)
            if path == self.note and not replaced:
                replaced = True
                storage.atomic_write_text(path, "# Replaced during read\n")
            return value
        with patch.object(reader, "_read", replacing):
            self.rejected("snapshot_changed")

    def test_attempt_change_during_read_is_rejected(self):
        original_read, changed = reader._read, False
        def changing(task_id, path):
            nonlocal changed
            value = original_read(task_id, path)
            if path == self.note and not changed:
                changed = True
                start_pipeline_attempt(task_id)
            return value
        with patch.object(reader, "_read", changing):
            self.rejected("publication_unavailable")

    def test_saved_or_corrupt_personal_edition_and_recovery_are_never_ignored(self):
        path = notes._edition_path("task", self.task.id)
        path.parent.mkdir()
        for content in ("invalid personal text", json.dumps({"text": "Personal", "revision": "invalid", "edited": True})):
            path.write_text(content)
            self.rejected("personal_state_present")
            self.assertEqual(path.read_text(), content)
        path.unlink()
        recovery = self.root / "personal-state" / "restore-pending"
        recovery.mkdir(parents=True)
        self.rejected("personal_state_present")

    def test_personal_save_appearing_during_read_is_rejected(self):
        original_read, changed = reader._read, False
        def saving(task_id, path):
            nonlocal changed
            value = original_read(task_id, path)
            if path == self.note and not changed:
                changed = True
                storage.atomic_write_text(notes._edition_path("task", task_id), "Private edition")
            return value
        with patch.object(reader, "_read", saving):
            self.rejected("personal_state_present")

    def test_symlink_artifact_or_personal_parent_rejects(self):
        outside = self.root / "outside.md"
        outside.write_text("Do not read")
        self.note.unlink()
        try:
            self.note.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        self.rejected("artifact_unavailable")
        self.note.unlink()
        self.note.write_text("# Wrong body")
        (self.root / "user-editions").symlink_to(self.work, target_is_directory=True)
        self.rejected("artifact_unavailable")

    def test_missing_or_legacy_witness_and_non_task_requests_fail_closed(self):
        metrics = storage.read_json(self.task.id, "pipeline_metrics.json")
        del metrics["attempts"][-1]["control_generation"]
        storage.write_json(self.task.id, "pipeline_metrics.json", metrics)
        self.rejected("publication_unavailable")
        for value in ([], {"schema_version": 2}):
            storage.write_json(self.task.id, "pipeline_metrics.json", value)
            self.rejected("publication_unavailable")
        with self.assertRaises(HTTPException) as caught:
            notes.get_edition("material", "other", True, self.task.control_generation)
        self.assertEqual(caught.exception.status_code, 409)

    def test_task_disappearing_during_read_returns_missing(self):
        original_read, removed = reader._read, False
        def deleting(task_id, path):
            nonlocal removed
            value = original_read(task_id, path)
            if path == self.note and not removed:
                removed = True
                (self.work / "task.json").unlink()
            return value
        with patch.object(reader, "_read", deleting), self.assertRaises(HTTPException) as caught:
            self.get()
        self.assertEqual(caught.exception.status_code, 404)

    def test_identical_task_directory_recreation_is_rejected(self):
        original_read, replaced = reader._read, False
        def replacing(task_id, path):
            nonlocal replaced
            value = original_read(task_id, path)
            if path == self.note and not replaced:
                replaced = True
                old = self.work.with_name(self.work.name + "-old")
                self.work.rename(old)
                shutil.copytree(old, self.work)
            return value
        with patch.object(reader, "_read", replacing):
            self.rejected("snapshot_changed")

    def test_unreadable_manifest_does_not_report_a_deleted_task(self):
        original_stat = Path.lstat
        def denied(path, *args, **kwargs):
            if path == self.work / "task.json":
                raise PermissionError("synthetic unavailable manifest")
            return original_stat(path, *args, **kwargs)
        with patch.object(Path, "lstat", denied):
            self.rejected("artifact_unavailable")

    def test_directory_incarnation_brackets_first_manifest_and_last_publication(self):
        for target, occurrence in (("task.json", 1), ("pipeline_metrics.json", 2)):
            with self.subTest(target=target):
                original_read, seen = reader._read, 0
                def replacing(task_id, path):
                    nonlocal seen
                    value = original_read(task_id, path)
                    if path.name == target:
                        seen += 1
                        if seen == occurrence:
                            old = self.work.with_name(self.work.name + "-" + target)
                            self.work.rename(old)
                            shutil.copytree(old, self.work)
                    return value
                with patch.object(reader, "_read", replacing):
                    self.rejected("snapshot_changed")


if __name__ == "__main__":
    unittest.main()
