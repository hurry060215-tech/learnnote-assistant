from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.knowledge import evidence_for_task
from app.library import index_task, search_library
from app.models import EvidenceCoverage, FrameGrid, MediaIntegrity, TaskOptions, TranscriptResult, TranscriptSegment
from app.observability import read_task_events_after, record_task_event
from app.pipeline_progress import start_pipeline_attempt, write_progressive_draft
from app.processor_state import TaskCancelled
from app.progressive_sections import partial_section_callback
from app.routers.notes import notes_router
from app.storage import create_task, get_task, read_json, task_dir, update_task, write_json
from app.summarizer import SummarizationCancelled, summarize_with_diagnostics_audit
from app.task_artifacts import read_task_note


class ProgressiveSectionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("storage", "library", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        for module in ("library", "knowledge", "routers.notes"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        self.options = TaskOptions(llm_base_url="http://127.0.0.1:1/v1", llm_model="fixture-vision",
                                   llm_api_key="fixture", use_saved_connection=False,
                                   vision_batch_size=1, vision_concurrency=1)
        self.task = create_task("local", "Fixture source", options=self.options)
        self.transcript = TranscriptResult(source="fixture-transcript", full_text="Original source remains readable.",
            segments=[TranscriptSegment(start=0, end=30, text="Original source remains readable.")])
        self.work = task_dir(self.task.id)
        self.transcript_path = write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        self.source_bytes = self.transcript_path.read_bytes()
        start_pipeline_attempt(self.task.id)
        draft = write_progressive_draft(self.task.id, self.task.title, self.transcript)
        self.draft_bytes = draft.read_bytes()
        update_task(self.task.id, status="running", phase="summarizing", checkpoint="visual_ready",
                    transcript_path=str(self.transcript_path), note_path=str(draft), summary_source="transcript-draft")

    def payload(self, start=0, text="DistinctiveUnverifiedDraft claim.", generation="a"):
        return {"generation_revision": generation * 64,
                "source_windows": [{"index": int(start // 10), "start": start, "end": start + 10}],
                "markdown": text}

    def sections(self):
        return read_json(self.task.id, "partial_note.json", {})

    def events(self):
        return [(cursor, event) for cursor, event in read_task_events_after(self.task.id)
                if event["event"] == "partial_section_ready"]

    def test_reader_index_and_portable_export_keep_draft_boundary(self):
        partial_section_callback(self.task.id, self.transcript)(self.payload())
        current = get_task(self.task.id)
        self.assertEqual(current.summary_source, "partial-draft")
        self.assertEqual(current.checkpoint, "visual_ready")
        self.assertEqual(current.status, "running")
        self.assertFalse((self.work / "note.md").exists())
        section = self.sections()["sections"][0]
        self.assertEqual(section["status"], "evidence_pending")
        self.assertFalse(section["verified"])
        self.assertIn("【待核对：未找到支持来源】", section["markdown"])
        self.assertTrue(index_task(current))
        self.assertEqual(search_library("DistinctiveUnverifiedDraft"), [])
        self.assertTrue(search_library("Original source"))
        self.assertFalse(any(item["metadata"].get("kind") == "note" for item in evidence_for_task(self.task.id)))
        app = FastAPI()
        app.include_router(notes_router)
        client = TestClient(app)
        edition = client.get(f"/api/tasks/editions/task/{self.task.id}").json()
        self.assertIn("DistinctiveUnverifiedDraft", edition["text"])
        export = client.get(f"/api/tasks/editions/task/{self.task.id}/exports/markdown")
        self.assertEqual(export.status_code, 200)
        self.assertIn("草稿 · 证据补充中 · 未完成最终校验", export.text)
        self.assertIn("【待核对：未找到支持来源】", export.text)
        self.assertEqual(self.source_bytes, self.transcript_path.read_bytes())
        self.assertEqual(self.draft_bytes, (self.work / "draft.md").read_bytes())

    def test_failed_merge_keeps_partial_provenance_out_of_task_qa(self):
        from app.main import _task_qa_context, task_artifact_status, api_export_markdown
        partial_section_callback(self.task.id, self.transcript)(self.payload())
        update_task(self.task.id, status="failed", phase="failed", summary_source="local-template",
                    error_code="summary_unavailable")
        current = get_task(self.task.id)
        artifacts = task_artifact_status(current)
        self.assertTrue(artifacts["draft_available"])
        self.assertTrue(artifacts["partial_draft_available"])
        self.assertFalse(artifacts["final"])
        context, citations = _task_qa_context(current)
        self.assertNotIn("DistinctiveUnverifiedDraft", context)
        self.assertFalse(any(item.get("source") == "note" for item in citations))
        self.assertTrue(any(item.get("source") == "transcript" for item in citations))
        export = api_export_markdown(self.task.id)
        self.assertIn("未完成最终校验", export.body.decode())
        self.assertTrue(index_task(current))
        self.assertEqual(search_library("DistinctiveUnverifiedDraft"), [])

    def test_malformed_known_projection_is_rebuilt_from_completed_batch(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload())
        document = self.sections()
        for malformed in ([], None, False, {"schema_version": []}, {**document, "sections": None},
                          {**document, "sections": [{}]},
                          {**document, "sections": [{**document["sections"][0], "verified": True}]},
                          {**document, "sections": [{**document["sections"][0], "markdown": "Altered bytes"}]}):
            write_json(self.task.id, "partial_note.json", malformed)
            callback(self.payload())
            self.assertEqual(self.sections(), document)

    def test_each_changed_section_updates_reader_revision_without_replay_churn(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        real_write_text = Path.write_text
        def windows_write_text(path, text, *args, **kwargs):
            kwargs.setdefault("newline", "\r\n")
            return real_write_text(path, text, *args, **kwargs)
        # Exercise the real atomic writer with Windows text-mode translation,
        # including on Linux; os.linesep alone does not change that translation.
        with patch.object(Path, "write_text", new=windows_write_text):
            with patch("app.storage.now_iso", return_value="2026-10-09T01:00:00+00:00"):
                callback(self.payload(0))
            self.assertIn(b"\r\n", (self.work / "draft.partial.md").read_bytes())
            with patch("app.storage.now_iso", return_value="2026-10-09T01:00:01+00:00"):
                callback(self.payload(10))
            self.assertEqual(get_task(self.task.id).updated_at, "2026-10-09T01:00:01+00:00")
            with patch("app.storage.now_iso", return_value="2026-10-09T01:00:02+00:00"):
                callback(self.payload(10))
            self.assertEqual(get_task(self.task.id).updated_at, "2026-10-09T01:00:01+00:00")

    def test_lf_and_crlf_projection_replay_preserves_bytes_and_reader_revision(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload())
        target = self.work / "draft.partial.md"
        canonical = target.read_text(encoding="utf-8")
        task_bytes = (self.work / "task.json").read_bytes()
        events = (self.work / "events.jsonl").read_bytes()
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                # Reproduce Windows text-mode storage on every test platform.
                stored = canonical.replace("\n", newline).encode("utf-8")
                target.write_bytes(stored)
                with patch("app.storage.now_iso", return_value="2099-01-01T00:00:00+00:00"):
                    callback(self.payload())
                self.assertEqual((self.work / "task.json").read_bytes(), task_bytes)
                self.assertEqual((self.work / "events.jsonl").read_bytes(), events)
                self.assertEqual(target.read_bytes(), stored)
                self.assertEqual(read_task_note(self.task.id), canonical)
                self.assertEqual((self.work / "draft.md").read_bytes(), self.draft_bytes)
                self.assertEqual(self.transcript_path.read_bytes(), self.source_bytes)

    def test_boolean_saved_bounds_are_not_reused_as_numeric_source_positions(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload(0))
        document = self.sections()
        document["sections"][0]["start"] = False  # False == 0 must not validate a source position.
        write_json(self.task.id, "partial_note.json", document)
        callback(self.payload(10))
        self.assertEqual([section["start"] for section in self.sections()["sections"]], [10])

    def test_internal_typeerror_never_repeats_a_started_summary(self):
        from app.processor import _summarize_with_optional_cache
        calls = []
        def summary(*args, **kwargs):
            calls.append((args, kwargs))
            raise TypeError("wrapper got an unexpected keyword argument 'section_callback'")
        with self.assertRaises(TypeError):
            _summarize_with_optional_cache(summary, "fixture", cache_dir=self.work / "vision_cache",
                                           section_callback=lambda _section: None)
        self.assertEqual(len(calls), 1)

    def test_legacy_nonstreaming_adapter_is_adapted_before_its_only_call(self):
        from app.processor import _summarize_with_optional_cache
        calls = []
        def legacy(title):
            calls.append(title)
            return "legacy result"
        result = _summarize_with_optional_cache(legacy, "fixture", cache_dir=self.work / "vision_cache",
                                               cancel_check=lambda: False, section_callback=lambda _section: None)
        self.assertEqual(result, "legacy result")
        self.assertEqual(calls, ["fixture"])

    def run_video_pipeline(self, summarize):
        from app.processor import _process_video_file
        from app.transcript_pipeline import TranscriptArtifacts
        from app.visual_pipeline import VisualArtifacts
        source = self.work / "synthetic-source.mp4"
        source.write_bytes(b"fixture media bytes, never decoded")
        def normalize(_source, target):
            target.write_bytes(b"fixture normalized media")
        with patch("app.processor.probe_media_integrity", return_value=MediaIntegrity(
                status="ready", duration=30, file_size=10, sha256="fixture-sha")), \
             patch("app.processor.normalize_video", side_effect=normalize), \
             patch("app.processor.prepare_transcript", return_value=TranscriptArtifacts(
                 self.transcript, "", None, "", self.transcript_path)), \
             patch("app.processor.extract_visual_evidence", return_value=VisualArtifacts([], [], [], "")), \
             patch("app.processor.calculate_evidence_coverage", return_value=EvidenceCoverage(status="ready", can_summarize=True)), \
             patch("app.processor.summarize_with_diagnostics", new=summarize):
            _process_video_file(self.task.id, source, self.task.title, "", self.options)

    def test_pipeline_final_gate_never_publishes_failed_or_corrupt_merge(self):
        for source, final_note, error in (("local-template", "fallback", "summary_unavailable"),
                                         ("vision-llm", "## Result\n\nOnly one \ufffd character.", "note_quality_failed")):
            def summarize(*_args, section_callback=None, **_kwargs):
                section_callback(self.payload())
                self.assertIn("DistinctiveUnverifiedDraft", read_task_note(self.task.id))
                self.assertFalse((self.work / "note.md").exists())
                return final_note, source, "", []
            self.run_video_pipeline(summarize)
            current = get_task(self.task.id)
            self.assertEqual(current.status, "failed")
            self.assertEqual(current.error_code, error)
            self.assertFalse((self.work / "note.md").exists())
            self.assertIn("未完成最终校验", read_task_note(self.task.id))

    def test_pipeline_cancellation_during_projection_records_cancelled_stage(self):
        def summarize(*_args, section_callback=None, **_kwargs):
            update_task(self.task.id, cancel_requested=True)
            section_callback(self.payload())
            self.fail("cancelled callback must not return to generation")
        with self.assertRaises(TaskCancelled):
            self.run_video_pipeline(summarize)
        stages = read_json(self.task.id, "pipeline_metrics.json", {})["stages"]
        self.assertEqual(stages["summary"]["status"], "cancelled")
        self.assertEqual(get_task(self.task.id).status, "cancelled")
        self.assertFalse((self.work / "draft.partial.md").exists())

    def test_resume_repairs_projection_without_duplicate_events_or_sections(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload(10))
        callback(self.payload(0))
        original = self.sections()
        before = self.events()
        (self.work / "draft.partial.md").write_text("interrupted projection", encoding="utf-8")
        # Recreate the coordinator from persisted state, as after restart.
        resumed = partial_section_callback(self.task.id, self.transcript)
        resumed(self.payload(10))
        self.assertEqual(self.sections(), original)
        self.assertEqual(self.events(), before)
        self.assertIn("证据补充中", read_task_note(self.task.id))
        self.assertEqual([section["start"] for section in original["sections"]], [0, 10])
        self.assertEqual(len({section["id"] for section in original["sections"]}), 2)
        self.assertEqual([cursor for cursor, _ in before], sorted({cursor for cursor, _ in before}))
        self.assertEqual(read_task_events_after(self.task.id, after=before[-1][0]), [])
        (self.work / "draft.partial.md").write_bytes(b"\xff")
        resumed(self.payload(0))
        self.assertIn("证据补充中", read_task_note(self.task.id))
        self.assertEqual(self.events(), before)

    def test_new_attempt_rejects_late_callback_and_new_generation_drops_stale_sections(self):
        old = partial_section_callback(self.task.id, self.transcript)
        old(self.payload(0, "Old generation draft."))
        start_pipeline_attempt(self.task.id)
        before = self.sections()
        old(self.payload(10, "Late stale draft."))
        self.assertEqual(self.sections(), before)
        current = partial_section_callback(self.task.id, self.transcript)
        current(self.payload(10, "Current generation draft.", generation="b"))
        self.assertEqual(len(self.sections()["sections"]), 1)
        self.assertNotIn("Old generation draft", read_task_note(self.task.id))
        self.assertNotIn("Late stale draft", read_task_note(self.task.id))

    def test_replay_after_long_event_history_does_not_duplicate_section_notification(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload())
        for _ in range(2005):
            record_task_event(self.task.id, "reference_history")
        path = self.work / "events.jsonl"
        before = path.read_bytes()
        partial_section_callback(self.task.id, self.transcript)(self.payload())
        self.assertEqual(path.read_bytes(), before)

    def test_unknown_future_schema_and_published_note_are_preserved(self):
        write_json(self.task.id, "partial_note.json", {"schema_version": 2, "future": "preserve me"})
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload())
        self.assertEqual(self.sections(), {"schema_version": 2, "future": "preserve me"})
        write_json(self.task.id, "partial_note.json", {})
        published = self.work / "note.md"
        published.write_bytes(b"# Earlier published note\n\nExact prior bytes.\n")
        update_task(self.task.id, note_path=str(published), summary_source="vision-llm")
        callback(self.payload())
        self.assertEqual(get_task(self.task.id).note_path, str(published))
        self.assertEqual(published.read_bytes(), b"# Earlier published note\n\nExact prior bytes.\n")

    def test_additive_artifacts_can_roll_back_to_retained_source_draft_without_data_loss(self):
        from app.models import TaskRecord
        canonical = self.draft_bytes.decode("utf-8").replace("\r\n", "\n")
        draft = self.work / "draft.md"
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                original = canonical.replace("\n", newline).encode("utf-8")
                draft.write_bytes(original)
                partial_section_callback(self.task.id, self.transcript)(self.payload())
                saved = (self.work / "draft.partial.md").read_bytes()
                current = TaskRecord.model_validate_json((self.work / "task.json").read_bytes())
                self.assertEqual(current.summary_source, "partial-draft")
                self.assertEqual(draft.read_bytes(), original)
                # Pointer-only rollback retains raw bytes; the ordinary public
                # reader intentionally returns canonical LF text under #150.
                update_task(self.task.id, note_path=str(draft), summary_source="transcript-draft")
                self.assertEqual(read_task_note(self.task.id), canonical)
                self.assertEqual(draft.read_bytes(), original)
                self.assertEqual((self.work / "draft.partial.md").read_bytes(), saved)
                self.assertEqual(self.transcript_path.read_bytes(), self.source_bytes)
                self.assertEqual(search_library("DistinctiveUnverifiedDraft"), [])

    def test_invalid_text_is_not_exposed_and_cancellation_keeps_prior_draft(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        for text in ("Only one \ufffd character.", "待核对草稿：【识别不清】", "系统提示：不要输出 JSON。"):
            callback(self.payload(text=text))
            self.assertFalse((self.work / "draft.partial.md").exists())
        callback(self.payload(text="Original source remains readable. https://example.test/?token=private-value"))
        self.assertNotIn("private-value", read_task_note(self.task.id))
        saved = (self.work / "draft.partial.md").read_bytes()
        update_task(self.task.id, cancel_requested=True)
        with self.assertRaises(TaskCancelled):
            callback(self.payload(10))
        self.assertEqual((self.work / "draft.partial.md").read_bytes(), saved)

    def run_provider(self, completion, *, concurrency=1, callback=None):
        grids = []
        for index in range(3):
            image = self.work / f"grid-{index}.jpg"
            image.write_bytes(f"synthetic image {index}".encode())
            grids.append(FrameGrid(path=str(image), url=f"/api/tasks/{self.task.id}/grids/{image.name}",
                                   start=index * 10, end=(index + 1) * 10, frame_count=1))
        provider = types.ModuleType("openai")
        provider.OpenAI = lambda **_kwargs: types.SimpleNamespace(chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=completion)))
        with patch.dict(sys.modules, {"openai": provider}):
            return summarize_with_diagnostics_audit(self.task.title, self.transcript, grids,
                self.options.model_copy(update={"vision_concurrency": concurrency}),
                vision_cache_dir=self.work / "vision_cache",
                cancel_check=lambda: get_task(self.task.id).cancel_requested,
                section_callback=callback or partial_section_callback(self.task.id, self.transcript))

    def test_completed_nonstreaming_batches_are_readable_before_later_calls_and_cached_on_resume(self):
        calls = []

        def completion(**kwargs):
            content = kwargs["messages"][0]["content"]
            calls.append(content)
            if not isinstance(content, list):
                self.assertEqual(len(self.sections()["sections"]), 3)
                self.assertIn("Generated batch 3", read_task_note(self.task.id))
                raise RuntimeError("synthetic merge interruption")
            batch = len(calls)
            if batch > 1:
                self.assertIn(f"Generated batch {batch - 1}", read_task_note(self.task.id))
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
                content=f"Generated batch {batch} has completed."))])

        result = self.run_provider(completion)
        self.assertEqual(result[1], "local-template")
        self.assertEqual(len(calls), 4)
        before = self.events()
        # All three complete batches survive a new attempt; only merge retries.
        start_pipeline_attempt(self.task.id)
        result = self.run_provider(completion)
        self.assertEqual(len(calls), 5)
        self.assertEqual(len([e for e in result[3] if e["stage"] == "vision_cache"]), 3)
        self.assertEqual(self.events(), before)

    def test_concurrent_completion_is_published_before_next_dispatch_and_cancel_stops_more(self):
        ready = threading.Event()
        original_callback = partial_section_callback(self.task.id, self.transcript)
        calls = []

        def callback(payload):
            original_callback(payload)
            if payload["source_windows"][0]["start"] == 10:
                update_task(self.task.id, cancel_requested=True)
                ready.set()

        def completion(**kwargs):
            prompt = kwargs["messages"][0]["content"][0]["text"]
            calls.append(prompt)
            if "批次：1" in prompt:
                self.assertTrue(ready.wait(5), "second completed batch was not published while first was running")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="Completed batch draft."))])

        with self.assertRaises(SummarizationCancelled):
            self.run_provider(completion, concurrency=2, callback=callback)
        self.assertEqual(len(calls), 2)
        self.assertEqual([s["start"] for s in self.sections()["sections"]], [10])


if __name__ == "__main__":
    unittest.main()
