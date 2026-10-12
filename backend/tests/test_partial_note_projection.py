from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import TranscriptResult, TranscriptSegment
from app.observability import record_task_event
from app.pipeline_progress import start_pipeline_attempt, write_progressive_draft
from app.progressive_sections import partial_section_callback
from app.reading_notes import source_block_entries
from app.routers.notes import notes_router
from app.storage import create_task, get_task, task_dir, update_task, write_json
from app.text_chunk_sections import text_chunk_payload, text_chunk_source


def revision(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class PartialNoteProjectionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("storage", "library", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        for module in ("library", "knowledge", "routers.notes"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        self.task = create_task("local", "Partial-note fixture")
        self.work = task_dir(self.task.id)
        self.transcript = TranscriptResult(source="fixture", full_text="Literal source.",
            segments=[TranscriptSegment(start=0, end=10, text="Literal source.")])
        self.transcript_path = write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        self.attempt = start_pipeline_attempt(self.task.id)
        self.note_path = self.work / "draft.partial.md"
        self.note_path.write_text("# Retained unverified draft\n", encoding="utf-8")
        update_task(self.task.id, status="running", phase="summarizing", note_path=str(self.note_path),
                    transcript_path=str(self.transcript_path), summary_source="partial-draft")
        source = revision([self.task.source_identity.media_sha256, self.transcript.model_dump(mode="json")])
        self.markdown = "# Literal draft\r\n\r\n  【待核对】don't normalize\t\n\n"
        windows = [{"index": 0, "start": 0, "end": 10}]
        section = {"id": "vision-" + revision([source, [[0, 10]]])[:24], "kind": "vision_batch",
                   "start": 0, "end": 10, "source_windows": windows, "status": "evidence_pending",
                   "verified": False, "summary_generated": True, "markdown": self.markdown,
                   "revision": revision(self.markdown)}
        self.document = {"schema_version": 1, "status": "draft", "verified": False, "attempt_id": self.attempt,
                         "source_revision": source, "generation_revision": "a" * 64, "sections": [section]}
        self.save_document(self.document)
        app = FastAPI()
        app.include_router(notes_router)
        self.client = self.stack.enter_context(TestClient(app))

    def save_document(self, value, *, notify=True):
        value["revision"] = revision({key: item for key, item in value.items() if key != "revision"})
        write_json(self.task.id, "partial_note.json", value)
        if notify:
            record_task_event(self.task.id, "partial_section_ready", phase="summary", status="draft",
                details={"schema_version": 1, "revision": value["revision"], "artifact": "draft.partial.md", "verified": False})

    def read(self):
        result = self.client.get(f"/api/tasks/{self.task.id}/partial-note")
        self.assertEqual(result.status_code, 200)
        return result.json()

    def assert_unavailable(self, reason=None, *, provenance=False):
        value = self.read()
        self.assertEqual(value["status"], "unavailable")
        self.assertFalse(value["verified"])
        self.assertEqual(value["sections"], [])
        self.assertEqual(value["revision"], "")
        if reason is not None:
            self.assertEqual(value["reason"], reason)
        if provenance:
            self.assertEqual(value["source_revision"], self.document["source_revision"])
            self.assertEqual(value["generation_revision"], self.document["generation_revision"])
        else:
            self.assertEqual(value["source_revision"], "")
            self.assertEqual(value["generation_revision"], "")
        return value

    def test_literal_whitelisted_projection_is_read_only_and_replay_stable(self):
        self.document["internal_path"] = "/private/model"
        self.document["sections"][0].update(private_model_config="secret", block_index="private")
        self.document["sections"][0]["source_windows"][0]["diagnostic"] = "private"
        self.save_document(self.document)
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        first = self.read()
        self.assertEqual(first, self.read())
        self.assertEqual(first["status"], "draft")
        self.assertEqual(first["reason"], "ready")
        self.assertFalse(first["verified"])
        self.assertEqual(first["task_id"], self.task.id)
        self.assertEqual(first["attempt_id"], self.attempt)
        self.assertEqual(first["task_updated_at"], get_task(self.task.id).updated_at)
        self.assertEqual(first["revision"], self.document["revision"])
        self.assertEqual(first["sections"][0]["markdown"], self.markdown)
        self.assertEqual(first["sections"][0]["order"], 0)
        self.assertEqual(first["sections"][0]["source_windows"], [{"index": 0, "start": 0, "end": 10}])
        self.assertNotIn("private", json.dumps(first))
        self.assertNotIn("block_index", first["sections"][0])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_real_generation_writer_is_compatible(self):
        partial_section_callback(self.task.id, self.transcript)({"generation_revision": "b" * 64,
            "source_windows": [{"index": 1, "start": 10, "end": 20}], "markdown": "New unverified claim."})
        result = self.read()
        self.assertEqual(result["status"], "draft")
        stored = json.loads((self.work / "partial_note.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["attempt_id"], self.attempt)
        self.assertEqual(len(result["sections"]), 1)
        self.assertIn("New unverified claim.", result["sections"][0]["markdown"])
        self.assertFalse(result["sections"][0]["verified"])

    def test_unknown_task_and_unsafe_ids_never_create_a_directory(self):
        before = set(self.root.rglob("*"))
        self.assertEqual(self.client.get("/api/tasks/missing/partial-note").status_code, 404)
        self.assertEqual(before, set(self.root.rglob("*")))
        from app.routers.notes import api_partial_note
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as failure:
            api_partial_note("../foreign")
        self.assertEqual(failure.exception.status_code, 404)

    def test_missing_task_404_never_exposes_internal_path_or_exception_chain(self):
        from app.routers.notes import api_partial_note
        from fastapi import HTTPException
        import traceback

        private_path = "/synthetic/private/task-owner/transcript.json"
        private_message = "Synthetic private storage diagnostic"
        with patch("app.routers.notes.read_partial_note",
                   side_effect=FileNotFoundError(2, private_message, private_path)):
            response = self.client.get(f"/api/tasks/{self.task.id}/partial-note")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "Task not found"})
            with self.assertRaises(HTTPException) as failure:
                api_partial_note(self.task.id)

        error = failure.exception
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.detail, "Task not found")
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        public_error = "".join(traceback.format_exception(error))
        for private_value in (private_path, private_message):
            self.assertNotIn(private_value, response.text)
            self.assertNotIn(private_value, public_error)

    def test_partial_exception_messages_never_become_public_reason_codes(self):
        from app.partial_note_projection import _UnavailablePartial

        private_error = "Synthetic private diagnostic: /private/task-owner/model-config.json"
        for error, reason in ((_UnavailablePartial(private_error), "source_mismatch"),
                              (ValueError(private_error), "invalid_artifact")):
            with self.subTest(error=type(error).__name__):
                with patch("app.partial_note_projection._partial_sections", side_effect=error):
                    result = self.assert_unavailable(reason)
                self.assertNotIn(private_error, json.dumps(result))
                self.assertNotIn("/private/task-owner", json.dumps(result))

    def test_missing_draft_and_inactive_pointer_are_unavailable(self):
        for changes in ({"note_path": ""}, {"note_path": str(self.work / "draft.md")},
                        {"note_path": str(self.work / "note.md")}, {"status": "queued"},
                        {"status": "success"}, {"summary_source": "vision-llm"}):
            with self.subTest(changes=changes):
                update_task(self.task.id, status="running", note_path=str(self.note_path), summary_source="partial-draft")
                update_task(self.task.id, **changes)
                self.assert_unavailable("not_ready")

    def test_failed_and_cancelled_current_drafts_remain_explicitly_unverified(self):
        for status in ("failed", "cancelled"):
            with self.subTest(status=status):
                update_task(self.task.id, status=status, summary_source="local-template")
                result = self.read()
                self.assertEqual(result["status"], "draft")
                self.assertFalse(result["verified"])

    def test_new_attempt_cannot_claim_old_partial_even_with_retained_pointer(self):
        new_attempt = start_pipeline_attempt(self.task.id)
        value = self.assert_unavailable("attempt_mismatch")
        self.assertEqual(value["attempt_id"], new_attempt)
        partial_section_callback(self.task.id, self.transcript)({"generation_revision": "b" * 64,
            "source_windows": [{"index": 0, "start": 0, "end": 10}], "markdown": "Fresh generation."})
        result = self.read()
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["attempt_id"], new_attempt)
        self.assertNotIn("don't normalize", result["sections"][0]["markdown"])

    def test_missing_or_unrecorded_provenance_fails_closed(self):
        (self.work / "events.jsonl").unlink()
        self.assert_unavailable("publication_pending", provenance=True)
        record_task_event(self.task.id, "pipeline_attempt_started", details={"attempt_id": self.attempt})
        self.assert_unavailable("publication_pending", provenance=True)

    def test_unstamped_or_old_attempt_document_cannot_claim_a_new_ready_event(self):
        self.document.pop("attempt_id")
        self.save_document(self.document)
        self.assert_unavailable("legacy_unproven")
        old_attempt = self.attempt
        self.attempt = start_pipeline_attempt(self.task.id)
        self.document["attempt_id"] = old_attempt
        # Simulate a late callback finishing after a newer attempt starts.
        self.save_document(self.document)
        self.assert_unavailable("attempt_mismatch")

    def test_same_generation_new_attempt_drops_previous_sections_and_records_ready(self):
        old_revision = self.document["revision"]
        old_bytes = (self.work / "partial_note.json").read_bytes()
        self.attempt = start_pipeline_attempt(self.task.id)
        partial_section_callback(self.task.id, self.transcript)({"generation_revision": "a" * 64,
            "source_windows": [{"index": 1, "start": 10, "end": 20}], "markdown": "Current completed batch."})
        result = self.read()
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["attempt_id"], self.attempt)
        self.assertNotEqual(result["revision"], old_revision)
        self.assertEqual(len(result["sections"]), 1)
        self.assertEqual(result["sections"][0]["start"], 10)
        self.assertEqual(self.previous_backup(old_bytes).read_bytes(), old_bytes)

    def legacy_text_document(self):
        self.transcript = TranscriptResult(source="fixture-text", full_text="Legacy source sentence. " * 1800)
        write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        source = revision([self.task.source_identity.media_sha256, self.transcript.model_dump(mode="json")])
        blocks = source_block_entries(self.transcript)
        self.assertGreaterEqual(len(blocks), 3)
        sections = []
        for index in range(2):
            markdown = f"# Legacy chapter {index}\r\n\r\nExact older text batch {index}.\n"
            payload = text_chunk_payload(blocks[index], index, markdown, "a" * 64)
            sections.append({**text_chunk_source(payload, blocks, source), "markdown": markdown,
                "revision": revision(markdown), "status": "evidence_pending", "verified": False, "summary_generated": True})
        legacy = {"schema_version": 1, "status": "draft", "verified": False,
                  "source_revision": source, "generation_revision": "a" * 64, "sections": sections}
        self.save_document(legacy)
        path = self.work / "partial_note.json"
        raw = path.read_bytes().replace(b"\n", b"\r\n")
        path.write_bytes(raw)
        return legacy, raw, text_chunk_payload(blocks[2], 2, "Current third chapter.", "a" * 64)

    def previous_backup(self, raw):
        return self.work / f"partial_note.previous.{hashlib.sha256(raw).hexdigest()}.json"

    def stamped_text_document(self):
        document, _raw, payload = self.legacy_text_document()
        document["attempt_id"] = self.attempt
        self.save_document(document)
        path = self.work / "partial_note.json"
        raw = path.read_bytes().replace(b"\n", b"\r\n")
        path.write_bytes(raw)
        return document, raw, payload

    def test_stamped_text_chapters_remain_recoverable_after_retry_completes_one_then_fails(self):
        previous, raw, payload = self.stamped_text_document()
        self.assertFalse((self.work / "vision_cache").exists())
        attempt = start_pipeline_attempt(self.task.id)
        partial_section_callback(self.task.id, self.transcript)(payload)
        update_task(self.task.id, status="failed", summary_source="local-template")
        current = self.read()
        self.assertEqual(current["attempt_id"], attempt)
        self.assertEqual([section["block_index"] for section in current["sections"]], [2])
        backup = self.previous_backup(raw)
        self.assertEqual(backup.read_bytes(), raw)
        self.assertEqual(json.loads(backup.read_bytes())["sections"], previous["sections"])
        modified = backup.stat().st_mtime_ns
        (self.work / "partial_note.json").write_bytes(raw)
        partial_section_callback(self.task.id, self.transcript)(payload)
        self.assertEqual(backup.read_bytes(), raw)
        self.assertEqual(backup.stat().st_mtime_ns, modified)

    def test_stamped_backup_failure_keeps_active_projection_and_markdown_untouched(self):
        _previous, raw, payload = self.stamped_text_document()
        start_pipeline_attempt(self.task.id)
        markdown = self.note_path.read_bytes()
        events = (self.work / "events.jsonl").read_bytes()
        with patch("app.progressive_sections.preserve_previous_partial", side_effect=OSError("Fixture backup failure")):
            partial_section_callback(self.task.id, self.transcript)(payload)
        self.assertEqual((self.work / "partial_note.json").read_bytes(), raw)
        self.assertEqual(self.note_path.read_bytes(), markdown)
        self.assertEqual((self.work / "events.jsonl").read_bytes(), events)

    def test_malformed_stamped_documents_are_preserved_before_replacement(self):
        mutations = (lambda value: value.update(status="verified"), lambda value: value.update(verified=True),
                     lambda value: value.update(schema_version=True),
                     lambda value: value["sections"][0].update(markdown="Changed without section revision"))
        for change in mutations:
            with self.subTest(change=change):
                previous, _raw, payload = self.stamped_text_document()
                change(previous)
                self.save_document(previous)
                raw = (self.work / "partial_note.json").read_bytes()
                partial_section_callback(self.task.id, self.transcript)(payload)
                self.assertEqual(self.previous_backup(raw).read_bytes(), raw)
                self.assertEqual(len(json.loads((self.work / "partial_note.json").read_bytes())["sections"]), 1)
        previous, _raw, payload = self.stamped_text_document()
        previous["revision"] = "0" * 64
        write_json(self.task.id, "partial_note.json", previous)
        raw = (self.work / "partial_note.json").read_bytes()
        partial_section_callback(self.task.id, self.transcript)(payload)
        self.assertEqual(self.previous_backup(raw).read_bytes(), raw)
        self.assertEqual(len(json.loads((self.work / "partial_note.json").read_bytes())["sections"]), 1)

    def test_same_attempt_legacy_upgrade_preserves_uncached_text_chapters_after_restart(self):
        legacy, raw, payload = self.legacy_text_document()
        self.assert_unavailable()  # Unstamped legacy files are never exposed directly.
        self.assertFalse((self.work / "vision_cache").exists())
        partial_section_callback(self.task.id, self.transcript)(payload)
        current = json.loads((self.work / "partial_note.json").read_text(encoding="utf-8"))
        self.assertEqual(current["attempt_id"], self.attempt)
        self.assertEqual(current["sections"][:2], legacy["sections"])
        self.assertEqual(len(self.read()["sections"]), 3)
        self.assertEqual(self.previous_backup(raw).read_bytes(), raw)
        backup_time = self.previous_backup(raw).stat().st_mtime_ns
        (self.work / "partial_note.json").write_bytes(raw)
        self.save_document(legacy)  # Repeat a migration with the same proven bytes.
        (self.work / "partial_note.json").write_bytes(raw)
        partial_section_callback(self.task.id, self.transcript)(payload)
        self.assertEqual(self.previous_backup(raw).stat().st_mtime_ns, backup_time)
        self.assertEqual(self.previous_backup(raw).read_bytes(), raw)
        self.assertEqual(len(self.read()["sections"]), 3)

    def test_different_attempt_legacy_chapters_are_preserved_but_not_reused(self):
        _legacy, raw, payload = self.legacy_text_document()
        attempt = start_pipeline_attempt(self.task.id)
        partial_section_callback(self.task.id, self.transcript)(payload)
        result = self.read()
        self.assertEqual(result["attempt_id"], attempt)
        self.assertEqual(len(result["sections"]), 1)
        self.assertEqual(result["sections"][0]["block_index"], 2)
        self.assertEqual(self.previous_backup(raw).read_bytes(), raw)

    def test_unprovable_and_malformed_legacy_bytes_survive_replacement(self):
        _legacy, raw, payload = self.legacy_text_document()
        (self.work / "events.jsonl").unlink()
        partial_section_callback(self.task.id, self.transcript)(payload)
        self.assertEqual(self.previous_backup(raw).read_bytes(), raw)
        self.assertEqual(len(json.loads((self.work / "partial_note.json").read_bytes())["sections"]), 1)
        raw = b"{broken legacy projection\r\n\xff"
        (self.work / "partial_note.json").write_bytes(raw)
        partial_section_callback(self.task.id, self.transcript)(payload)
        self.assertEqual(self.previous_backup(raw).read_bytes(), raw)
        self.assertEqual(len(json.loads((self.work / "partial_note.json").read_bytes())["sections"]), 1)

    def test_legacy_backup_failures_leave_active_bytes_untouched(self):
        _legacy, raw, payload = self.legacy_text_document()
        markdown = self.note_path.read_bytes()
        events = (self.work / "events.jsonl").read_bytes()
        with patch("app.progressive_sections.prepare_legacy_partial", side_effect=OSError("Fixture backup failure")):
            partial_section_callback(self.task.id, self.transcript)(payload)
        self.assertEqual((self.work / "partial_note.json").read_bytes(), raw)
        self.assertEqual(self.note_path.read_bytes(), markdown)
        self.assertEqual((self.work / "events.jsonl").read_bytes(), events)
        backup = self.previous_backup(raw)
        backup.write_bytes(b"Existing file must not be overwritten")
        partial_section_callback(self.task.id, self.transcript)(payload)
        self.assertEqual((self.work / "partial_note.json").read_bytes(), raw)
        self.assertEqual(backup.read_bytes(), b"Existing file must not be overwritten")
        backup.unlink()
        foreign = self.root / "foreign-backup.json"
        foreign.write_bytes(b"Foreign contents")
        backup.symlink_to(foreign)
        partial_section_callback(self.task.id, self.transcript)(payload)
        self.assertEqual((self.work / "partial_note.json").read_bytes(), raw)
        self.assertEqual(foreign.read_bytes(), b"Foreign contents")

    def show_source_outline(self):
        draft = write_progressive_draft(self.task.id, self.task.title, self.transcript)
        update_task(self.task.id, note_path=str(draft), summary_source="transcript-draft")
        return json.loads((self.work / "draft_sections.json").read_bytes())

    def test_short_transcript_outline_is_readable_before_any_generated_batch(self):
        document = self.show_source_outline()
        before = {str(path): path.read_bytes() for path in self.work.rglob("*") if path.is_file()}
        result = self.read()
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["reason"], "ready")
        self.assertEqual(result["attempt_id"], self.attempt)
        self.assertEqual(result["generation_revision"], "")
        section = result["sections"][0]
        self.assertEqual(section["kind"], "temporal_outline")
        self.assertEqual(section["id"], document["sections"][0]["id"])
        self.assertEqual(section["excerpts"], document["sections"][0]["excerpts"])
        self.assertEqual(section["revision"], revision(document["sections"][0]))
        self.assertEqual(section["status"], "draft")
        self.assertFalse(section["verified"])
        self.assertFalse(section["summary_generated"])
        self.assertNotIn("markdown", section)
        self.assertEqual(result, self.read())
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.work.rglob("*") if path.is_file()})

    def test_outline_identity_and_excerpts_survive_generated_batch_arrival(self):
        self.show_source_outline()
        first = self.read()
        partial_section_callback(self.task.id, self.transcript)({"generation_revision": "b" * 64,
            "source_windows": [{"index": 1, "start": 10, "end": 20}], "markdown": "New generated batch."})
        result = self.read()
        self.assertEqual(result["sections"][0], first["sections"][0])
        self.assertEqual(result["source_revision"], first["source_revision"])
        self.assertEqual(result["generation_revision"], "b" * 64)
        self.assertEqual([section["kind"] for section in result["sections"]], ["temporal_outline", "vision_batch"])
        self.assertEqual([section["order"] for section in result["sections"]], [0, 1])

    def test_pending_generated_document_preserves_bounded_provenance_even_with_outline(self):
        self.show_source_outline()
        update_task(self.task.id, note_path=str(self.note_path), summary_source="partial-draft")
        self.document["sections"][0]["markdown"] = "Current completed batch awaiting ready event."
        self.document["sections"][0]["revision"] = revision(self.document["sections"][0]["markdown"])
        self.save_document(self.document, notify=False)
        self.assert_unavailable("publication_pending", provenance=True)

    def test_invalid_outline_does_not_hide_valid_generated_sections(self):
        document = self.show_source_outline()
        update_task(self.task.id, note_path=str(self.note_path), summary_source="partial-draft")
        for change in (lambda value: value.update(schema_version=2),
                       lambda value: value["sections"][0].update(verified=True),
                       lambda value: value["sections"][0]["excerpts"][0].update(text="Invented source")):
            with self.subTest(change=change):
                value = deepcopy(document)
                change(value)
                write_json(self.task.id, "draft_sections.json", value)
                result = self.read()
                self.assertEqual(result["reason"], "ready")
                self.assertEqual([section["kind"] for section in result["sections"]], ["vision_batch"])
        path = self.work / "draft_sections.json"
        path.unlink()
        foreign = self.root / "foreign-outline.json"
        foreign.write_text(json.dumps(document), encoding="utf-8")
        path.symlink_to(foreign)
        self.assertEqual([section["kind"] for section in self.read()["sections"]], ["vision_batch"])

    def test_valid_outline_keeps_generated_failure_reason_without_exposing_generated_text(self):
        outline = self.show_source_outline()
        update_task(self.task.id, note_path=str(self.note_path), summary_source="partial-draft")
        failures = {
            "legacy_unproven": lambda value: value.pop("attempt_id"),
            "invalid_artifact": lambda value: value.update(verified=True),
            "attempt_mismatch": lambda value: value.update(attempt_id="b" * 12),
            "source_mismatch": lambda value: value.update(source_revision="b" * 64),
        }
        for reason, change in failures.items():
            with self.subTest(reason=reason):
                value = deepcopy(self.document)
                change(value)
                self.save_document(value)
                result = self.read()
                self.assertEqual(result["status"], "draft")
                self.assertEqual(result["reason"], reason)
                self.assertFalse(result["verified"])
                self.assertEqual(result["source_revision"], self.document["source_revision"])
                self.assertEqual(result["generation_revision"], "")
                self.assertEqual([section["kind"] for section in result["sections"]], ["temporal_outline"])
                self.assertEqual(result["sections"][0]["excerpts"], outline["sections"][0]["excerpts"])
                self.assertNotIn(self.markdown, json.dumps(result, ensure_ascii=False))

    def test_outline_only_rejects_new_attempt_changed_source_and_malformed_document(self):
        self.show_source_outline()
        new_attempt = start_pipeline_attempt(self.task.id)
        result = self.assert_unavailable("not_ready")
        self.assertEqual(result["attempt_id"], new_attempt)
        self.show_source_outline()
        self.assertEqual(self.read()["reason"], "ready")
        changed = self.transcript.model_copy(update={"segments": [TranscriptSegment(start=0, end=10, text="Changed source.")]})
        write_json(self.task.id, "transcript.json", changed.model_dump(mode="json"))
        self.assert_unavailable("invalid_artifact")
        (self.work / "draft_sections.json").write_bytes(b"{broken")
        self.assert_unavailable("invalid_artifact")

    def test_attempt_or_task_change_during_projection_discards_sections(self):
        from app import partial_note_projection as projection
        real_check = projection.attempt_owns_partial_revision
        def switch_attempt(*args):
            result = real_check(*args)
            start_pipeline_attempt(self.task.id)
            return result
        with patch.object(projection, "attempt_owns_partial_revision", side_effect=switch_attempt):
            self.assert_unavailable("snapshot_changed")
        self.attempt = start_pipeline_attempt(self.task.id)
        self.document["attempt_id"] = self.attempt
        self.save_document(self.document)
        def publish(*args):
            result = real_check(*args)
            update_task(self.task.id, status="success", note_path=str(self.work / "note.md"))
            return result
        with patch.object(projection, "attempt_owns_partial_revision", side_effect=publish):
            value = self.assert_unavailable("snapshot_changed")
        self.assertEqual(value["task_updated_at"], get_task(self.task.id).updated_at)

    def test_progress_message_and_timestamp_updates_do_not_starve_ready_sections(self):
        from app import partial_note_projection as projection
        real_check = projection.attempt_owns_partial_revision
        before = get_task(self.task.id).updated_at
        def progress(*args):
            ready = real_check(*args)
            update_task(self.task.id, progress=77, message="Next batch running")
            return ready
        with patch.object(projection, "attempt_owns_partial_revision", side_effect=progress):
            result = self.read()
        self.assertEqual(result["reason"], "ready")
        self.assertEqual(result["sections"][0]["markdown"], self.markdown)
        self.assertNotEqual(result["task_updated_at"], before)
        self.assertEqual(result["task_updated_at"], get_task(self.task.id).updated_at)

    def test_source_options_and_retry_changes_during_read_invalidate_snapshot(self):
        from app import partial_note_projection as projection
        real_check = projection.attempt_owns_partial_revision
        original = get_task(self.task.id)
        for change in ({"source_identity": original.source_identity.model_copy(update={"media_sha256": "b" * 64})},
                       {"options": original.options.model_copy(update={"generate_questions": not original.options.generate_questions})},
                       {"retry_count": original.retry_count + 1}):
            with self.subTest(change=change):
                update_task(self.task.id, source_identity=original.source_identity, options=original.options,
                            retry_count=original.retry_count)
                def change_provenance(*args):
                    ready = real_check(*args)
                    update_task(self.task.id, **change)
                    return ready
                with patch.object(projection, "attempt_owns_partial_revision", side_effect=change_provenance):
                    self.assert_unavailable("snapshot_changed")

    def test_changed_transcript_or_media_identity_rejects_stale_source(self):
        write_json(self.task.id, "transcript.json", self.transcript.model_copy(update={"full_text": "Changed source"}).model_dump(mode="json"))
        self.assert_unavailable("source_mismatch")
        write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        identity = get_task(self.task.id).source_identity.model_copy(update={"media_sha256": "b" * 64})
        update_task(self.task.id, source_identity=identity)
        self.assert_unavailable("source_mismatch")

    def test_corrupt_future_and_falsely_verified_documents_fail_closed(self):
        mutations = [lambda value: value.update(schema_version=2), lambda value: value.update(schema_version=True),
                     lambda value: value.update(verified=True), lambda value: value.update(status="verified"),
                     lambda value: value.update(sections=[]), lambda value: value.update(generation_revision="private config"),
                     lambda value: value["sections"][0].update(verified=True),
                     lambda value: value["sections"][0].update(start=False),
                     lambda value: value["sections"][0].update(markdown="Tampered section"),
                     lambda value: value["sections"].append(deepcopy(value["sections"][0])),
                     lambda value: value["sections"][0]["source_windows"][0].update(start=float("nan"))]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = deepcopy(self.document)
                mutate(value)
                self.save_document(value)
                self.assert_unavailable()
        path = self.work / "partial_note.json"
        for raw in (b"{broken", b"[]", b"null", b"\xff"):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                self.assert_unavailable()

    def test_malformed_or_missing_metrics_are_unavailable(self):
        for value in ([], None, {}, {"schema_version": 3, "current_attempt_id": self.attempt},
                      {"schema_version": 2, "current_attempt_id": "/private/secret"}):
            with self.subTest(value=value):
                write_json(self.task.id, "pipeline_metrics.json", value)
                self.assertEqual(self.assert_unavailable()["attempt_id"], "")
        (self.work / "pipeline_metrics.json").unlink()
        self.assert_unavailable()

    def test_foreign_artifacts_and_symlinks_are_never_read(self):
        outside = self.root / "foreign-transcript.json"
        outside.write_text('{"full_text": "private"}', encoding="utf-8")
        update_task(self.task.id, transcript_path=str(outside))
        self.assert_unavailable()
        loop = self.work / "loop"
        loop.symlink_to(loop, target_is_directory=True)
        update_task(self.task.id, transcript_path=str(loop / "transcript.json"))
        self.assert_unavailable()
        update_task(self.task.id, transcript_path=str(self.transcript_path))
        for name in ("partial_note.json", "pipeline_metrics.json", "events.jsonl", "transcript.json", "draft.partial.md"):
            with self.subTest(name=name):
                path = self.work / name
                saved = path.read_bytes()
                path.unlink()
                path.symlink_to(outside)
                self.assert_unavailable()
                path.unlink()
                path.write_bytes(saved)
        record_path = self.work / "task.json"
        record_path.unlink()
        record_path.symlink_to(outside)
        self.assertEqual(self.client.get(f"/api/tasks/{self.task.id}/partial-note").status_code, 404)

    def test_symlinked_task_directory_is_not_followed(self):
        original = self.work.with_name("retained-task")
        self.work.rename(original)
        self.work.symlink_to(original, target_is_directory=True)
        with patch("app.partial_note_projection.get_task", side_effect=AssertionError("Must reject before reading the task")):
            response = self.client.get(f"/api/tasks/{self.task.id}/partial-note")
        self.assertEqual(response.status_code, 404)

    def test_text_sections_use_exact_source_blocks_and_reject_fabricated_times(self):
        transcript = TranscriptResult(source="page_text", full_text="Untimed source text.")
        write_json(self.task.id, "transcript.json", transcript.model_dump(mode="json"))
        source = revision([self.task.source_identity.media_sha256, transcript.model_dump(mode="json")])
        blocks = source_block_entries(transcript)
        payload = text_chunk_payload(blocks[0], 0, self.markdown, "a" * 64)
        section = {**text_chunk_source(payload, blocks, source), "markdown": self.markdown,
                   "revision": revision(self.markdown), "status": "evidence_pending", "verified": False, "summary_generated": True}
        document = {**self.document, "source_revision": source, "sections": [section]}
        self.save_document(document)
        result = self.read()
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["sections"][0]["block_index"], 0)
        self.assertEqual(result["sections"][0]["source_windows"], [])
        self.assertNotIn("start", result["sections"][0])
        section["start"] = 0
        section["end"] = 10
        self.save_document(document)
        self.assert_unavailable()


if __name__ == "__main__":
    unittest.main()
