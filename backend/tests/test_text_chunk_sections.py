from __future__ import annotations

from contextlib import ExitStack
import copy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from app.models import ActiveVideoInfo, BrowserSubtitleCue, CurrentPageTaskRequest, TaskOptions, TranscriptResult, TranscriptSegment
from app.observability import read_task_events_after
from app.pipeline_progress import start_pipeline_attempt, write_progressive_draft
from app.processor_state import TaskCancelled
from app.progressive_sections import partial_section_callback
from app.reading_notes import source_block_entries, source_blocks, stamp
from app.storage import create_task, get_task, read_json, task_dir, update_task, write_json
from app.summarizer import SummarizationCancelled, summarize_with_diagnostics_audit, summarize_with_llm
from app.task_artifacts import read_task_note
from app.text_chunk_sections import text_chunk_payload


class TextChunkSectionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("storage", "library", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        for module in ("library", "knowledge", "routers.notes"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        self.options = TaskOptions(llm_base_url="http://127.0.0.1:1/v1", llm_model="fixture-text",
                                   llm_api_key="fixture", use_saved_connection=False, visual_understanding=False)
        self.task = create_task("local", "课程", options=self.options)
        self.transcript = TranscriptResult(source="fixture", full_text="来源内容保持完整。" * 8000)
        self.work = task_dir(self.task.id)
        self.path = write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        self.source_bytes = self.path.read_bytes()
        start_pipeline_attempt(self.task.id)
        draft = write_progressive_draft(self.task.id, self.task.title, self.transcript)
        self.draft_bytes = draft.read_bytes()
        update_task(self.task.id, status="running", phase="summarizing", transcript_path=str(self.path),
                    note_path=str(draft), summary_source="transcript-draft", checkpoint="transcript_ready")

    def sections(self):
        return read_json(self.task.id, "partial_note.json", {})

    def events(self):
        return [event for _, event in read_task_events_after(self.task.id) if event["event"] == "partial_section_ready"]

    def payload(self, index=0, text="草稿内容仍需核对。", generation="a"):
        return text_chunk_payload(source_block_entries(self.transcript)[index], index, text, generation * 64)

    def provider(self, completion):
        provider = types.ModuleType("openai")
        provider.OpenAI = lambda **_kwargs: types.SimpleNamespace(chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=completion)))
        return patch.dict(sys.modules, {"openai": provider})

    @staticmethod
    def response(text="# 课程\n\n来源内容保持完整。"):
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))])

    def run_summary(self, callback=None, **kwargs):
        return summarize_with_llm(self.task.title, self.transcript, [], self.options,
            section_callback=callback, cancel_check=lambda: get_task(self.task.id).cancel_requested, **kwargs)

    def test_block_partition_bytes_match_existing_algorithm_including_split_cues(self):
        def previous_blocks(transcript, budget):
            parts = [f"[{stamp(s.start)} – {stamp(s.end)}] {s.text}" for s in transcript.segments if s.text.strip()]
            blocks, current = [], ""
            for part in parts or [transcript.full_text]:
                for offset in range(0, len(part), budget):
                    piece = part[offset:offset + budget]
                    if current and len(current) + len(piece) + 2 > budget:
                        blocks.append(current)
                        current = ""
                    current += ("\n\n" if current else "") + piece
            if current.strip():
                blocks.append(current)
            return blocks
        timed = TranscriptResult(full_text="Unused when original cues exist", segments=[
            TranscriptSegment(start=0, end=1, text=" "),
            TranscriptSegment(start=1.25, end=9.75, text="第一段" * 9000),
            TranscriptSegment(start=9.75, end=20, text="末尾段落")])
        for source in (self.transcript, timed, TranscriptResult(full_text=" \n ")):
            for budget in (30, 16000):
                self.assertEqual(source_blocks(source, budget), previous_blocks(source, budget))
        entries = source_block_entries(timed)
        self.assertEqual(entries[0]["source_windows"], [{"index": 1, "start": 1.25, "end": 9.75}])
        self.assertEqual(entries[-1]["source_windows"][-1]["index"], 2)

    def test_five_existing_calls_keep_exact_requests_and_final_text_and_publish_before_next(self):
        baseline, calls = [], []
        with self.provider(lambda **kw: baseline.append(kw) or self.response()):
            expected = self.run_summary()
        callback = partial_section_callback(self.task.id, self.transcript)
        def completion(**kwargs):
            self.assertEqual(len(self.events()), len(calls))
            if calls:
                self.assertIn(f"文字分段 {len(calls)}", read_task_note(self.task.id))
                self.assertEqual(len(self.sections()["sections"]), len(calls))
            calls.append(kwargs)
            return self.response()
        with self.provider(completion):
            actual = self.run_summary(callback)
        self.assertEqual(actual, expected)
        self.assertEqual(calls, baseline)
        self.assertEqual(len(calls), 5)
        self.assertEqual(len(self.events()), 5)
        self.assertEqual([s["block_index"] for s in self.sections()["sections"]], list(range(5)))
        self.assertEqual(self.path.read_bytes(), self.source_bytes)
        self.assertEqual((self.work / "draft.md").read_bytes(), self.draft_bytes)
        self.assertFalse((self.work / "note.md").exists())

    def test_short_input_has_one_existing_call_and_no_partial(self):
        self.transcript = TranscriptResult(full_text="来源内容保持完整。")
        calls, payloads = [], []
        with self.provider(lambda **kw: calls.append(kw) or self.response()):
            self.assertIsNotNone(self.run_summary(payloads.append))
        self.assertEqual(len(calls), 1)
        self.assertEqual(payloads, [])

    def test_compatibility_retry_publishes_once_after_success_without_changing_requests(self):
        from backend.tests.test_model_compatibility import ProviderError
        calls, payloads = [], []
        def completion(**kwargs):
            self.assertEqual(len(payloads), max(0, len(calls) - 1))
            calls.append(kwargs)
            if len(calls) == 1:
                raise ProviderError()
            return self.response()
        with self.provider(completion):
            self.assertIsNotNone(self.run_summary(payloads.append))
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(payloads), 5)
        self.assertEqual(calls[1], {key: value for key, value in calls[0].items() if key != "temperature"})

    def test_generation_revision_tracks_prompt_model_and_source_but_not_credentials(self):
        revisions = []
        for change in ({}, {"llm_api_key": "another-fixture"}, {"note_template": "outline"},
                       {"llm_model": "fixture-other"}, {"llm_base_url": "http://localhost:1/v1"}):
            payloads = []
            options = self.options.model_copy(update=change)
            with self.provider(lambda **_kw: self.response()):
                summarize_with_llm(self.task.title, self.transcript, [], options, section_callback=payloads.append)
            revisions.append(payloads[0]["generation_revision"])
            self.assertEqual(len({p["generation_revision"] for p in payloads}), 1)
        self.assertEqual(revisions[0], revisions[1])
        self.assertEqual(len(set(revisions)), 4)

    def test_later_failure_retains_completed_draft_and_does_not_continue_dispatch(self):
        calls = []
        def completion(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise RuntimeError("synthetic unavailable")
            return self.response()
        with self.provider(completion):
            result = summarize_with_diagnostics_audit(self.task.title, self.transcript, [], self.options,
                section_callback=partial_section_callback(self.task.id, self.transcript))
        self.assertEqual(result[1], "local-template")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.sections()["sections"]), 1)
        self.assertIn("待最终来源检查", read_task_note(self.task.id))
        self.assertFalse((self.work / "note.md").exists())

    def test_cancellation_after_first_or_last_callback_stops_generation(self):
        for stop_after in (1, 5):
            update_task(self.task.id, cancel_requested=False)
            calls = []
            original = partial_section_callback(self.task.id, self.transcript)
            def callback(payload):
                original(payload)
                if len(calls) == stop_after:
                    update_task(self.task.id, cancel_requested=True)
            with self.provider(lambda **kw: calls.append(kw) or self.response()):
                with self.assertRaises(SummarizationCancelled):
                    self.run_summary(callback)
            self.assertEqual(len(calls), stop_after)
        before = (self.work / "draft.partial.md").read_bytes()
        with self.assertRaises(TaskCancelled):
            partial_section_callback(self.task.id, self.transcript)(self.payload())
        self.assertEqual((self.work / "draft.partial.md").read_bytes(), before)

    def test_untimed_repeated_blocks_get_distinct_stable_ids_without_generated_timestamps(self):
        self.transcript = TranscriptResult(full_text="α" * 64000)
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload(1, text="草稿引用 12:34，但原文没有时间点。"))
        callback(self.payload(0))
        sections = self.sections()["sections"]
        self.assertEqual([s["block_index"] for s in sections], [0, 1])
        self.assertEqual(sections[0]["block_digest"], sections[1]["block_digest"])
        self.assertNotEqual(sections[0]["id"], sections[1]["id"])
        for section in sections:
            self.assertEqual(section["source_windows"], [])
            self.assertNotIn("start", section)
            self.assertNotIn("end", section)
            self.assertFalse(section["verified"])
            self.assertEqual(section["status"], "evidence_pending")
        self.assertIn("## 文字分段 1", read_task_note(self.task.id))
        self.assertIn("## 文字分段 2", read_task_note(self.task.id))

    def test_timed_chunks_keep_exact_original_indices_and_cue_bounds(self):
        self.transcript = TranscriptResult(segments=[TranscriptSegment(start=0, end=1, text=" "),
            TranscriptSegment(start=2.25, end=25.75, text="α" * 40000)])
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload(1, text="草稿声称 59:59，不能改变原文定位。"))
        section = self.sections()["sections"][0]
        self.assertEqual(section["source_windows"], [{"index": 1, "start": 2.25, "end": 25.75}])
        self.assertEqual((section["start"], section["end"]), (2.25, 25.75))
        self.assertTrue(section["markdown"].startswith("# 文字分段 2\n"))

    def test_foreign_or_malformed_chunk_identity_cannot_create_a_draft(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        for changes in ({"block_index": True}, {"block_index": -1}, {"block_index": 500},
                        {"block_digest": "wrong"}, {"source_windows": [{"index": 0, "start": 0, "end": 50}]},
                        {"kind": "semantic_chapter"}):
            callback({**self.payload(), **changes})
            self.assertEqual(self.sections(), {})

    def test_stale_attempt_source_and_generation_do_not_mix_and_replay_repairs_without_event_churn(self):
        old = partial_section_callback(self.task.id, self.transcript)
        old(self.payload(0))
        previous = copy.deepcopy(self.sections())
        start_pipeline_attempt(self.task.id)
        old(self.payload(1))
        self.assertEqual(self.sections(), previous)
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload(1, generation="b"))
        self.assertEqual([s["block_index"] for s in self.sections()["sections"]], [1])
        before = self.events()
        (self.work / "draft.partial.md").write_text("interrupted", encoding="utf-8")
        callback(self.payload(1, generation="b"))
        self.assertEqual(self.events(), before)
        self.assertIn("文字分段 2", read_task_note(self.task.id))
        self.transcript = self.transcript.model_copy(update={"source": "different-source-revision"})
        partial_section_callback(self.task.id, self.transcript)(self.payload(2, generation="b"))
        self.assertEqual([s["block_index"] for s in self.sections()["sections"]], [2])
        self.assertNotEqual(previous["source_revision"], self.sections()["source_revision"])

    def test_malformed_saved_text_positions_and_invented_timestamps_are_not_reused(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        for changes in ({"start": 0, "end": 10}, {"block_digest": "corrupt"}, {"block_index": False}):
            callback(self.payload())
            previous = self.sections()
            previous["sections"][0].update(changes)
            write_json(self.task.id, "partial_note.json", previous)
            callback(self.payload(1))
            self.assertEqual([s["block_index"] for s in self.sections()["sections"]], [1])

    def test_text_replay_preserves_crlf_bytes_and_reader_revision(self):
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(self.payload())
        target = self.work / "draft.partial.md"
        content = target.read_text(encoding="utf-8").replace("\n", "\r\n").encode()
        target.write_bytes(content)
        task_bytes = (self.work / "task.json").read_bytes()
        events = (self.work / "events.jsonl").read_bytes()
        callback(self.payload())
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual((self.work / "task.json").read_bytes(), task_bytes)
        self.assertEqual((self.work / "events.jsonl").read_bytes(), events)

    def test_artifact_is_durable_before_event_and_published_note_is_preserved(self):
        from app.observability import record_task_event
        published = self.work / "note.md"
        published.write_bytes(b"# Previous published note\n")
        update_task(self.task.id, note_path=str(published), summary_source="text-llm")
        def record(task_id, event, **kwargs):
            self.assertEqual(event, "partial_section_ready")
            self.assertEqual(kwargs["details"]["revision"], self.sections()["revision"])
            self.assertIn("文字分段 1", (self.work / "draft.partial.md").read_text(encoding="utf-8"))
            self.assertFalse(kwargs["details"]["verified"])
            return record_task_event(task_id, event, **kwargs)
        with patch("app.progressive_sections.record_task_event", side_effect=record):
            partial_section_callback(self.task.id, self.transcript)(self.payload())
        self.assertEqual(published.read_bytes(), b"# Previous published note\n")
        self.assertEqual(get_task(self.task.id).note_path, str(published))

    def test_text_drafts_keep_claim_markers_and_stay_out_of_retrieval_after_failure(self):
        from app.knowledge import evidence_for_task
        from app.library import index_task, search_library
        from app.main import _task_qa_context, task_artifact_status
        partial_section_callback(self.task.id, self.transcript)(self.payload(text="DistinctiveUnverifiedChunk claim."))
        update_task(self.task.id, status="failed", phase="failed", summary_source="local-template", error_code="summary_unavailable")
        current = get_task(self.task.id)
        self.assertTrue(task_artifact_status(current)["partial_draft_available"])
        self.assertIn("【待核对：未找到支持来源】", read_task_note(self.task.id))
        self.assertNotIn("DistinctiveUnverifiedChunk", _task_qa_context(current)[0])
        self.assertFalse(any(e["metadata"].get("kind") == "note" for e in evidence_for_task(self.task.id)))
        self.assertTrue(index_task(current))
        self.assertEqual(search_library("DistinctiveUnverifiedChunk"), [])

    def test_both_transcript_wrappers_publish_drafts_and_keep_failed_final_gate(self):
        from app.processor import process_saved_transcript_task, process_subtitle_only_task
        cues = [BrowserSubtitleCue(start=i * 10, end=i * 10 + 9, text="来源内容保持完整。" * 700) for i in range(12)]
        request = CurrentPageTaskRequest(page_url="https://example.test/fixture", title=self.task.title,
            browser_subtitles=cues, active_video=ActiveVideoInfo(duration=120), options=self.options)
        def summarize(_title, transcript, *_args, section_callback=None, **_kwargs):
            self.assertIsNotNone(section_callback)
            block = source_block_entries(transcript)[0]
            section_callback(text_chunk_payload(block, 0, "草稿内容仍需核对。", "c" * 64))
            self.assertIn("文字分段 1", read_task_note(self.task.id))
            return "fallback", "local-template", "synthetic interruption", []
        with patch("app.processor.summarize_with_diagnostics", new=summarize):
            process_subtitle_only_task(self.task.id, request)
        self.assertEqual(get_task(self.task.id).error_code, "summary_unavailable")
        original = self.path.read_bytes()
        for final_note, source, error in (("fallback", "local-template", "summary_unavailable"),
                                         ("# 课程\n\nOnly one \ufffd character.", "text-llm", "note_quality_failed")):
            def retry(*args, **kwargs):
                summarize(*args, **kwargs)
                return final_note, source, "", []
            with patch("app.processor.summarize_with_diagnostics", new=retry):
                process_saved_transcript_task(self.task.id, self.options)
            self.assertEqual(get_task(self.task.id).error_code, error)
            self.assertFalse((self.work / "note.md").exists())
            self.assertIn("待最终来源检查", read_task_note(self.task.id))
            self.assertEqual(self.path.read_bytes(), original)

        def success(*args, **kwargs):
            summarize(*args, **kwargs)
            return "# 课程\n\n来源内容保持完整。", "text-llm", "", []
        with patch("app.processor.summarize_with_diagnostics", new=success):
            process_saved_transcript_task(self.task.id, self.options)
        self.assertEqual(get_task(self.task.id).status, "success")
        self.assertEqual(Path(get_task(self.task.id).note_path).name, "note.md")
        self.assertFalse(self.sections()["verified"])
        self.assertTrue(all(s["verified"] is False for s in self.sections()["sections"]))
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
