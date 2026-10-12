"""Offline contracts. MockChunk/MockStream are SDK-shaped mocks, not live models."""
from __future__ import annotations

from contextlib import ExitStack
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from app.chapter_sections import chapter_payload
from app.models import FrameGrid, TaskOptions, TranscriptResult, TranscriptSegment
from app.observability import read_task_events_after
from app.partial_note_projection import read_partial_note
from app.pipeline_progress import start_pipeline_attempt, write_progressive_draft
from app.progressive_sections import partial_section_callback
from app.reading_notes import source_block_entries
from app.storage import create_task, get_task, read_json, task_dir, update_task, write_json
from app.streamed_chapters import ChapterEnvelope, streamed_chapters, supports_streamed_chapters
from app.summarizer import SummarizationCancelled, summarize_with_llm
from app.task_artifacts import read_task_note
from app.token_usage import usage_report


def chapter(title="主题一", body="来源内容保持完整。", indexes=None):
    return {"title": title, "source_blocks": indexes if indexes is not None else [0], "markdown": body}


def envelope(*chapters, ascii=False):
    return json.dumps({"chapters": list(chapters or [chapter()])}, ensure_ascii=ascii)


def mock_chunk(content=None, *, reason=None, usage=None, **delta):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(index=0, finish_reason=reason,
        delta=types.SimpleNamespace(content=content, **delta))], usage=usage)


class MockStream:
    """SDK-shaped synchronous iterable with inspectable response-only closing."""
    def __init__(self, chunks):
        self.chunks, self.close_count = iter(chunks), 0

    def __iter__(self):
        return self

    def __next__(self):
        item = next(self.chunks)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.close_count += 1


class ChapterEnvelopeTests(unittest.TestCase):
    blocks = [{"text": "来源内容", "source_windows": []}]

    def test_arbitrary_boundaries_unicode_escapes_and_braces_emit_exactly_once(self):
        values = [chapter("主题😀", '引用 "文字"，反斜线 \\，大括号 {x} 和数组 [1]。'), chapter("主题二", "完成。")]
        for ascii in (True, False):
            text = envelope(*values, ascii=ascii)
            for step in (1, 2, 3, 7, 64, len(text)):
                emitted = []
                parser = ChapterEnvelope(self.blocks, lambda value, index: emitted.append((value, index)))
                for index in range(0, len(text), step):
                    parser.feed(text[index:index + step])
                self.assertEqual(parser.finish(), values)
                self.assertEqual(emitted, [(value, index) for index, value in enumerate(values)])

    def test_complete_object_is_visible_before_delimiter_or_next_chapter(self):
        emitted = []
        parser = ChapterEnvelope(self.blocks, lambda value, index: emitted.append(value))
        parser.feed('{ "chapters" : [ ' + json.dumps(chapter()))
        self.assertEqual(emitted, [chapter()])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            parser.finish()
        parser.feed("] }")
        self.assertEqual(parser.finish(), [chapter()])

    def test_duplicate_keys_and_bad_tail_retain_only_prior_complete_objects(self):
        prefix = '{"chapters":[' + json.dumps(chapter())
        bad = [',{"title":"bad","title":"again","source_blocks":[0],"markdown":"x"}]}',
               '],"chapters":[]}', ',{"title":"bad","source_blocks":[NaN],"markdown":"x"}]}',
               ',{"title":"bad","source_blocks":[0],"markdown":"unterminated',
               "]} trailing", ",]}", "]", "]}{}"]
        for tail in bad:
            emitted = []
            parser = ChapterEnvelope(self.blocks, lambda value, index: emitted.append(value))
            with self.assertRaises(ValueError):
                parser.feed(prefix + tail)
                parser.finish()
            self.assertEqual(emitted, [chapter()], tail)

    def test_source_ids_text_fields_surrogates_and_generated_locators_are_rejected(self):
        for update in ({"source_blocks": [True]}, {"source_blocks": [-1]}, {"source_blocks": [1]},
                       {"source_blocks": [0, 0]}, {"source_blocks": []}, {"start": 10},
                       {"title": "一\n二"}, {"title": "x" * 161}, {"title": "\ud800"},
                       {"markdown": ""}, {"markdown": "## nested"}, {"markdown": "从 59:59 开始"},
                       {"markdown": "```python\nprint(1)"},
                       {"markdown": "https://example.test/fake"}, {"markdown": "x" * 12001}):
            emitted = []
            parser = ChapterEnvelope(self.blocks, lambda value, index: emitted.append(value))
            with self.assertRaises((ValueError, UnicodeError)):
                parser.feed(envelope({**chapter(), **update}, ascii=True))
                parser.finish()
            self.assertEqual(emitted, [], update)

    def test_parser_bounds_chapter_envelope_count_and_nesting(self):
        cases = [("MAX_CHAPTER_BYTES", 40, envelope()),
                 ("MAX_ENVELOPE_BYTES", 180, envelope() + " " * 200),
                 ("MAX_CHAPTERS", 1, envelope(chapter(), chapter("二")))]
        for setting, limit, text in cases:
            with patch("app.streamed_chapters." + setting, limit):
                with self.assertRaises(ValueError):
                    ChapterEnvelope(self.blocks, lambda *_args: None).feed(text)
        with self.assertRaises(ValueError):
            ChapterEnvelope(self.blocks, lambda *_args: None).feed('{"chapters":[{"nested":[[[[[]]]]]}]}')

    def test_missing_source_coverage_never_completes(self):
        parser = ChapterEnvelope(self.blocks * 2, lambda *_args: None)
        parser.feed(envelope())
        with self.assertRaisesRegex(ValueError, "coverage"):
            parser.finish()

    def test_source_exact_time_url_and_code_remain_literal(self):
        body = '会议在12:30开始。\n\n```python\n# source comment\nurl = "https://example.test/course"\n```'
        values = [chapter(title="C# 与数组 [0]", body=body)]
        blocks = [{"text": body, "source_windows": []}]
        parser = ChapterEnvelope(blocks, lambda *_args: None)
        parser.feed(envelope(*values))
        self.assertEqual(parser.finish(), values)

    def test_normalization_cannot_activate_a_fence_or_foreign_locator(self):
        for body in ("\x00```python\nprint(1)", "\x7f```python\nprint(1)",
                     "http\x00s://invented.example/path", "http\x7fs://invented.example/path"):
            emitted = []
            parser = ChapterEnvelope(self.blocks, lambda value, index: emitted.append(value))
            with self.assertRaises(ValueError):
                parser.feed(envelope(chapter(body=body)))
            self.assertEqual(emitted, [])
        body = "    ```python\n    print(1)"
        parser = ChapterEnvelope(self.blocks, lambda *_args: None)
        parser.feed(envelope(chapter(body=body), chapter("主题二")))
        self.assertEqual(parser.finish()[0]["markdown"], body)

    def test_source_exact_sensitive_url_redacts_consistently_and_expanded_title_rejects(self):
        from app.text_cleanup import redact_sensitive_url_values
        body = "来源链接 https://example.test/?token=synthetic"
        parser = ChapterEnvelope([{"text": body, "source_windows": []}], lambda *_args: None)
        parser.feed(envelope(chapter(body=body)))
        self.assertEqual(parser.finish()[0]["markdown"], redact_sensitive_url_values(body))
        self.assertNotIn("synthetic", parser.finish()[0]["markdown"])
        emitted = []
        parser = ChapterEnvelope(self.blocks, lambda value, index: emitted.append(value))
        with self.assertRaises(ValueError):
            parser.feed(envelope(chapter(title="Bearer x " * 17)))
        self.assertEqual(emitted, [])

    def test_exact_documented_profile_only(self):
        for base in ("https://api.openai.com/v1", "https://api.openai.com/v1/"):
            for model in ("gpt-4.1", "gpt-4.1-2025-04-14"):
                self.assertTrue(supports_streamed_chapters(base, model))
        for base, model in (("https://api.openai.com/v1?x=1", "gpt-4.1"),
                            ("https://api.openai.com:443/v1", "gpt-4.1"),
                            ("https://custom.example/v1", "gpt-4.1"),
                            ("https://api.openai.com.evil.test/v1", "gpt-4.1"),
                            ("https://api.openai.com/v1", "gpt-4.1-future"),
                            ("https://api.openai.com/v1", "gpt-4.1-mini")):
            self.assertFalse(supports_streamed_chapters(base, model))


class StreamedChapterTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("storage", "library", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        for module in ("storage", "library", "knowledge", "routers.notes", "token_usage"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        # These modules imported config.ensure_dirs directly; rebinding DATA_DIR
        # alone does not change that function's original config globals.
        for module in ("storage", "observability", "library", "knowledge"):
            self.stack.enter_context(patch(f"app.{module}.ensure_dirs"))
        self.options = TaskOptions(llm_base_url="https://api.openai.com/v1", llm_model="gpt-4.1",
            llm_api_key="fixture-only", use_saved_connection=False, visual_understanding=False)
        self.task = create_task("local", "课程", options=self.options)
        self.transcript = TranscriptResult(source="fixture", full_text="来源内容保持完整。主题一和主题二。",
            segments=[TranscriptSegment(start=2.25, end=9.75, text="来源内容保持完整。主题一和主题二。")])
        self.work = task_dir(self.task.id)
        self.path = write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        self.source_bytes = self.path.read_bytes()
        start_pipeline_attempt(self.task.id)
        draft = write_progressive_draft(self.task.id, self.task.title, self.transcript)
        self.draft_bytes = draft.read_bytes()
        update_task(self.task.id, status="running", phase="summarizing", transcript_path=str(self.path),
                    note_path=str(draft), summary_source="transcript-draft", checkpoint="transcript_ready")
        self.calls, self.initializations, self.client_closes = [], [], []

    def provider(self, completion):
        module = types.ModuleType("openai")
        def create(**kwargs):
            self.calls.append(kwargs)
            return completion(**kwargs)
        def client(**kwargs):
            self.initializations.append(kwargs)
            return types.SimpleNamespace(base_url=kwargs["base_url"], chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=create)), close=lambda: self.client_closes.append(True))
        module.OpenAI = client
        return patch.dict(sys.modules, {"openai": module})

    def summary(self, **kwargs):
        return summarize_with_llm(self.task.title, self.transcript, [], self.options,
            section_callback=kwargs.pop("section_callback", partial_section_callback(self.task.id, self.transcript)),
            cancel_check=kwargs.pop("cancel_check", lambda: get_task(self.task.id).cancel_requested), **kwargs)

    def document(self):
        return read_json(self.task.id, "partial_note.json", {})

    def events(self):
        return [event for _, event in read_task_events_after(self.task.id) if event["event"] == "partial_section_ready"]

    def direct(self, stream, *, callback=None, check_cancel=lambda: None, **provider_kwargs):
        client = types.SimpleNamespace(base_url="http://127.0.0.1/v1", chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **kw: self.calls.append(kw) or stream)))
        return streamed_chapters(client, model="gpt-4.1", messages=[{"role": "user", "content": "fixture"}],
            provider_kwargs=provider_kwargs, blocks=source_block_entries(self.transcript), title=self.task.title,
            generation="a" * 64, section_callback=callback or partial_section_callback(self.task.id, self.transcript),
            check_cancel=check_cancel)

    def test_first_chapter_durable_before_second_and_final_gate_sees_markdown(self):
        def chunks():
            yield mock_chunk('{"chapters":[' + json.dumps(chapter()))
            self.assertEqual(len(self.events()), 1)
            self.assertEqual(len(self.document()["sections"]), 1)
            self.assertIn("## 主题一", read_task_note(self.task.id))
            self.assertIn("未完成最终校验", read_task_note(self.task.id))
            self.assertFalse((self.work / "note.md").exists())
            yield mock_chunk("," + json.dumps(chapter("主题二")) + "]}")
            yield mock_chunk(reason="stop")
            yield types.SimpleNamespace(choices=[], usage=types.SimpleNamespace(prompt_tokens=20, completion_tokens=30, total_tokens=50))
        stream = MockStream(chunks())
        with self.provider(lambda **_kwargs: stream), patch("app.summarizer._validated_generated_note", side_effect=lambda *_args, **_kw: _args[3]) as gate:
            result = self.summary()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["stream_options"], {"include_usage": True})
        self.assertEqual(self.calls[0]["temperature"], 0.2)
        self.assertNotIn("timeout", self.calls[0])
        self.assertEqual(self.calls[0]["model"], self.options.llm_model)
        self.assertEqual(self.initializations[0]["base_url"], self.options.llm_base_url)
        from app.config import LLM_MAX_RETRIES, LLM_REQUEST_TIMEOUT_SECONDS
        self.assertEqual(self.initializations[0]["max_retries"], LLM_MAX_RETRIES)
        self.assertEqual(self.initializations[0]["timeout"], LLM_REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(gate.call_count, 1)
        self.assertTrue(gate.call_args.args[3].startswith("# 课程\n\n## 主题一\n"))
        self.assertNotIn('"chapters"', gate.call_args.args[3])
        self.assertEqual(result[1], "text-llm")
        self.assertEqual(stream.close_count, 1)
        self.assertEqual(self.client_closes, [])
        report = usage_report()
        self.assertEqual(report["totals"]["requests"], 1)
        self.assertEqual(report["totals"]["total_tokens"], 50)
        self.assertEqual(report["recent"][0]["status"], "success")
        self.assertEqual(self.path.read_bytes(), self.source_bytes)
        self.assertEqual((self.work / "draft.md").read_bytes(), self.draft_bytes)
        self.assertEqual([item["chapter_index"] for item in self.document()["sections"]], [0, 1])
        projection = read_partial_note(self.task.id)
        topics = [item for item in projection["sections"] if item["kind"] == "topic_chapter"]
        self.assertEqual(len(topics), 2)
        self.assertTrue(all(item["verified"] is False and item["status"] == "evidence_pending" for item in topics))
        self.assertEqual(topics[0]["source_windows"], [{"index": 0, "start": 2.25, "end": 9.75}])

    def test_failures_retain_first_draft_without_retry_or_final_gate(self):
        prefix = '{"chapters":[' + json.dumps(chapter())
        tails = [[mock_chunk(",")], [TimeoutError("synthetic timeout")],
                 [mock_chunk("]}", reason="length")], [mock_chunk("]}", reason="content_filter")],
                 [mock_chunk(refusal="synthetic refusal")], [mock_chunk("]}", reason="tool_calls")],
                 [mock_chunk("]} trailing", reason="stop")], [mock_chunk("]}")],
                 [mock_chunk(',{"title":"x","title":"y","source_blocks":[0],"markdown":"x"}]}', reason="stop")]]
        for tail in tails:
            start_pipeline_attempt(self.task.id)
            stream = MockStream([mock_chunk(prefix), *tail])
            before = len(self.calls)
            with self.provider(lambda **_kwargs: stream), patch("app.summarizer._validated_generated_note") as gate:
                self.assertIsNone(self.summary())
            self.assertEqual(len(self.calls) - before, 1)
            self.assertEqual(len(self.document()["sections"]), 1)
            self.assertFalse(gate.called)
            self.assertFalse((self.work / "note.md").exists())
            self.assertEqual(stream.close_count, 1)
        self.assertEqual(usage_report()["totals"]["requests"], len(tails))
        self.assertTrue(all(item["status"] == "failed" and item["total_tokens"] is None for item in usage_report()["recent"]))

    def test_missing_usage_stays_unknown_and_reasoning_is_not_consumed(self):
        stream = MockStream([mock_chunk(reasoning_content="private reasoning that is not JSON"),
                             mock_chunk(envelope(), reason="stop")])
        result = self.direct(stream, temperature=0.2, max_tokens=1234, seed=9)
        self.assertNotIn("private reasoning", result)
        self.assertEqual(self.calls[0]["max_tokens"], 1234)
        self.assertEqual(self.calls[0]["seed"], 9)
        self.assertIsNone(usage_report()["recent"][0]["total_tokens"])

    def test_callback_cancellation_closes_stream_and_never_reads_second_chapter(self):
        def chunks():
            yield mock_chunk('{"chapters":[' + json.dumps(chapter()))
            self.fail("Cancellation must stop consumption before another chunk")
        stream = MockStream(chunks())
        original = partial_section_callback(self.task.id, self.transcript)
        def callback(payload):
            original(payload)
            update_task(self.task.id, cancel_requested=True)
        with self.provider(lambda **_kwargs: stream), patch("app.summarizer._validated_generated_note") as gate:
            with self.assertRaises(SummarizationCancelled):
                self.summary(section_callback=callback)
        self.assertEqual(stream.close_count, 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.document()["sections"]), 1)
        self.assertFalse(gate.called)

    def test_cancellation_before_request_has_no_call_or_usage_entry(self):
        stream = MockStream([])
        def check():
            raise SummarizationCancelled("summary_cancelled")
        with self.assertRaises(SummarizationCancelled):
            self.direct(stream, check_cancel=check)
        self.assertEqual(self.calls, [])
        self.assertEqual(stream.close_count, 0)
        self.assertEqual(usage_report()["totals"]["requests"], 0)

    def test_idle_mock_stream_is_closed_on_cancel(self):
        requested, closed = threading.Event(), threading.Event()
        class BlockedStream(MockStream):
            def __next__(self):
                requested.set()
                if not closed.wait(3):
                    raise AssertionError("Idle stream was not closed")
                raise OSError("closed fixture transport")
            def close(self):
                super().close()
                closed.set()
        def check():
            if requested.is_set():
                raise SummarizationCancelled("summary_cancelled")
        stream = BlockedStream([])
        with self.assertRaises(SummarizationCancelled):
            self.direct(stream, check_cancel=check)
        self.assertTrue(closed.is_set())
        self.assertEqual(stream.close_count, 1)

    def test_rejected_final_grounding_retains_drafts(self):
        stream = MockStream([mock_chunk(envelope(), reason="stop")])
        with self.provider(lambda **_kwargs: stream), patch("app.summarizer._validated_generated_note", return_value="") as gate:
            self.assertIsNone(self.summary())
        self.assertEqual(gate.call_count, 1)
        self.assertEqual(len(self.document()["sections"]), 1)
        self.assertFalse((self.work / "note.md").exists())

    def test_existing_grounding_repair_is_a_separate_unchanged_nonstream_call(self):
        stream = MockStream([mock_chunk(envelope(chapter(body="InventedUnsupportedTerm。")), reason="stop")])
        repaired = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="# 课程\n\n来源内容保持完整。"))])
        with self.provider(lambda **kwargs: stream if kwargs.get("stream") else repaired):
            result = self.summary()
        self.assertIsNotNone(result)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(self.calls[0]["stream"])
        self.assertNotIn("stream", self.calls[1])
        self.assertNotIn("response_format", self.calls[1])
        self.assertIn("## 主题一", self.calls[1]["messages"][0]["content"])
        self.assertNotIn('"chapters"', self.calls[1]["messages"][0]["content"])

    def test_many_cue_windows_keep_complete_provenance_and_bounded_visible_ranges(self):
        self.transcript = TranscriptResult(full_text="来源内容", segments=[
            TranscriptSegment(start=index, end=index + 0.5, text="来源") for index in range(1000)])
        write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        blocks = source_block_entries(self.transcript)
        value = chapter_payload(chapter(indexes=list(range(len(blocks)))), 0, blocks, "a" * 64)
        partial_section_callback(self.task.id, self.transcript)(value)
        section = self.document()["sections"][0]
        self.assertEqual(len(section["source_windows"]), 1000)
        self.assertLess(len(section["markdown"]), 500)
        self.assertIn("粗略定位", section["markdown"])

    def test_transformed_chapter_boundary_preserves_later_heading_and_warning(self):
        from app.markdown_structure import structural_lines
        first = chapter(body="    ```python\n    print(1)")
        result = self.direct(MockStream([mock_chunk(envelope(first, chapter("主题二"))), mock_chunk(reason="stop")]))
        for text in (result, read_task_note(self.task.id)):
            lines = list(structural_lines(text.splitlines()))
            self.assertIn(("## 主题二", True), lines)
            self.assertIn(("    ```python", False), lines)
        stored = (self.work / "partial_note.json").read_bytes()
        draft = (self.work / "draft.partial.md").read_bytes()
        callback = partial_section_callback(self.task.id, self.transcript)
        for body in ("\x00```python\nprint(1)", "\x7f```python\nprint(1)"):
            callback(chapter_payload(chapter("危险边界", body), 2, source_block_entries(self.transcript), "a" * 64))
            self.assertEqual((self.work / "partial_note.json").read_bytes(), stored)
            self.assertEqual((self.work / "draft.partial.md").read_bytes(), draft)
        self.assertEqual(self.path.read_bytes(), self.source_bytes)

    def test_generation_change_old_attempt_source_mismatch_and_replay(self):
        blocks = source_block_entries(self.transcript)
        value = chapter_payload(chapter(), 0, blocks, "a" * 64)
        callback = partial_section_callback(self.task.id, self.transcript)
        callback(value)
        first = copy.deepcopy(self.document())
        callback({**value, "generation_revision": "b" * 64, "markdown": "wrong generation"})
        self.assertEqual(self.document(), first)
        events = self.events()
        (self.work / "draft.partial.md").write_text("interrupted render", encoding="utf-8")
        # Recreate the callback as after an in-process replay/restart.
        partial_section_callback(self.task.id, self.transcript)(value)
        self.assertEqual(self.events(), events)
        self.assertIn("主题一", read_task_note(self.task.id))
        start_pipeline_attempt(self.task.id)
        callback(value)
        self.assertEqual(self.document(), first)
        current = partial_section_callback(self.task.id, self.transcript)
        current({**value, "generation_revision": "b" * 64})
        self.assertNotEqual(self.document()["attempt_id"], first["attempt_id"])
        self.assertTrue(list(self.work.glob("partial_note.previous.*.json")))
        second = copy.deepcopy(self.document())
        write_json(self.task.id, "transcript.json", self.transcript.model_copy(update={"full_text": "changed"}).model_dump(mode="json"))
        current({**value, "generation_revision": "b" * 64, "markdown": "late completion"})
        self.assertEqual(self.document(), second)

    def test_changed_media_identity_and_source_during_callback_cannot_overwrite(self):
        from app.models import SourceIdentity
        value = chapter_payload(chapter(), 0, source_block_entries(self.transcript), "a" * 64)
        callback = partial_section_callback(self.task.id, self.transcript)
        update_task(self.task.id, source_identity=SourceIdentity(media_sha256="b" * 64))
        callback(value)
        self.assertEqual(self.document(), {})
        callback = partial_section_callback(self.task.id, self.transcript)
        from app.claims import build_claim_evidence_map
        def changed_source(*args, **kwargs):
            write_json(self.task.id, "transcript.json", self.transcript.model_copy(update={"full_text": "changed"}).model_dump(mode="json"))
            return build_claim_evidence_map(*args, **kwargs)
        with patch("app.partial_section_content.build_claim_evidence_map", side_effect=changed_source):
            callback(value)
        self.assertEqual(self.document(), {})

    def test_slow_claim_preparation_keeps_other_tasks_accessible_and_discards_stale_attempt(self):
        from app.claims import build_claim_evidence_map
        entered, release, other_done = (threading.Event() for _ in range(3))
        errors = []
        callback = partial_section_callback(self.task.id, self.transcript)
        payload = chapter_payload(chapter(), 0, source_block_entries(self.transcript), "a" * 64)
        other = create_task("local", "其他合成任务", options=self.options)
        def slow_claims(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Claim preparation was not released")
            return build_claim_evidence_map(*args, **kwargs)
        def publish():
            try:
                callback(payload)
            except BaseException as exc:
                errors.append(exc)
        def update_other_and_attempt():
            try:
                update_task(other.id, title="仍可访问")
                self.assertEqual(get_task(other.id).title, "仍可访问")
                start_pipeline_attempt(self.task.id)
                other_done.set()
            except BaseException as exc:
                errors.append(exc)
        older = threading.Thread(target=publish, daemon=True)
        newer = threading.Thread(target=update_other_and_attempt, daemon=True)
        with patch("app.partial_section_content.build_claim_evidence_map", side_effect=slow_claims):
            older.start()
            try:
                self.assertTrue(entered.wait(5))
                newer.start()
                self.assertTrue(other_done.wait(2), "Claim matching held the global task lock")
            finally:
                release.set()
                older.join(5)
                if newer.ident is not None:
                    newer.join(5)
        self.assertEqual(errors, [])
        self.assertFalse(older.is_alive() or newer.is_alive())
        self.assertEqual(self.document(), {})
        self.assertEqual(self.events(), [])
        self.assertEqual(self.path.read_bytes(), self.source_bytes)

    def test_competing_attempt_cannot_interleave_topic_publication(self):
        from app.storage import _lock
        old_attempt = read_json(self.task.id, "pipeline_metrics.json")["current_attempt_id"]
        blocks = source_block_entries(self.transcript)
        old_payload = chapter_payload(chapter(body="旧批次内容。"), 0, blocks, "a" * 64)
        callback = partial_section_callback(self.task.id, self.transcript)
        at_write, probed, release_old, newer_done = (threading.Event() for _ in range(4))
        probe, errors, newer_attempt = [], [], []
        def pause_publication(task_id, name, value):
            if name == "partial_note.json" and value["attempt_id"] == old_attempt:
                at_write.set()
                if not release_old.wait(5):
                    raise TimeoutError("Old publication barrier was not released")
            return write_json(task_id, name, value)
        def old_worker():
            try:
                callback(old_payload)
            except BaseException as exc:
                errors.append(exc)
        def new_worker():
            acquired = _lock.acquire(blocking=False)
            probe.append(acquired)
            probed.set()
            if not acquired:
                _lock.acquire()
            try:
                newer_attempt.append(start_pipeline_attempt(self.task.id))
                value = chapter_payload(chapter(body="新批次内容。"), 0, blocks, "b" * 64)
                partial_section_callback(self.task.id, self.transcript)(value)
            except BaseException as exc:
                errors.append(exc)
            finally:
                _lock.release()
                newer_done.set()
        older = threading.Thread(target=old_worker, daemon=True)
        newer = threading.Thread(target=new_worker, daemon=True)
        with patch("app.progressive_sections.write_json", side_effect=pause_publication):
            older.start()
            try:
                self.assertTrue(at_write.wait(5))
                newer.start()
                self.assertTrue(probed.wait(5))
                if probe[0]:
                    # Pre-fix: make the new attempt finish before allowing the
                    # old callback to overwrite its artifacts. No timing guess.
                    self.assertTrue(newer_done.wait(5))
            finally:
                release_old.set()
                older.join(5)
                if newer.ident is not None:
                    newer.join(5)
        self.assertFalse(older.is_alive() or newer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.document()["attempt_id"], newer_attempt[0])
        self.assertIn("新批次内容", read_task_note(self.task.id))
        self.assertNotIn("旧批次内容", read_task_note(self.task.id))
        self.assertEqual(probe, [False])
        events = [event for _, event in read_task_events_after(self.task.id)]
        new_start = next(index for index, event in enumerate(events) if event["event"] == "pipeline_attempt_started"
                         and event["details"]["attempt_id"] == newer_attempt[0])
        ready = [event for event in events[new_start + 1:] if event["event"] == "partial_section_ready"]
        self.assertEqual([event["details"]["revision"] for event in ready], [self.document()["revision"]])

    def test_draft_title_is_redacted_and_topic_provenance_tampering_is_unavailable(self):
        value = chapter_payload(chapter(title="sk-syntheticsecretvalue"), 0, source_block_entries(self.transcript), "a" * 64)
        partial_section_callback(self.task.id, self.transcript)(value)
        document = self.document()
        self.assertNotIn("syntheticsecretvalue", json.dumps(document))
        self.assertNotIn("syntheticsecretvalue", read_task_note(self.task.id))
        self.assertEqual(read_partial_note(self.task.id)["reason"], "ready")
        from app.partial_note_projection import partial_revision
        for update in ({"chapter_index": True}, {"source_blocks": [99]}, {"block_digests": ["f" * 64]},
                       {"start": 500}, {"verified": True}):
            changed = copy.deepcopy(document)
            changed["sections"][0].update(update)
            changed["revision"] = partial_revision({key: value for key, value in changed.items() if key != "revision"})
            write_json(self.task.id, "partial_note.json", changed)
            self.assertEqual(read_partial_note(self.task.id)["reason"], "invalid_artifact")

    def test_untimed_sources_never_gain_timestamps_and_forged_bindings_reject(self):
        self.transcript = TranscriptResult(full_text="来源内容保持完整。")
        write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        value = chapter_payload(chapter(), 0, source_block_entries(self.transcript), "a" * 64)
        callback = partial_section_callback(self.task.id, self.transcript)
        for update in ({"chapter_index": True}, {"chapter_index": 32}, {"source_blocks": [1]},
                       {"block_digests": ["forged"]}, {"source_windows": [{"index": 0, "start": 0, "end": 99}]}):
            callback({**value, **update})
            self.assertEqual(self.document(), {})
        callback(value)
        section = self.document()["sections"][0]
        self.assertEqual(section["source_windows"], [])
        self.assertNotIn("start", section)
        self.assertNotIn("end", section)
        self.assertIn("原文无时间点", section["markdown"])

    def test_unknown_profile_and_no_callback_preserve_nonstream_request_and_output(self):
        response = types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason="stop", message=types.SimpleNamespace(content="# 课程\n\n来源内容保持完整。"))])
        drafts = []
        for change in ({"llm_base_url": "http://localhost:1/v1"}, {"llm_model": "gpt-4.1-mini"}, {}):
            self.options = self.options.model_copy(update={"llm_base_url": "https://api.openai.com/v1", "llm_model": "gpt-4.1", **change})
            with self.provider(lambda **_kwargs: response):
                result = self.summary(section_callback=drafts.append if change else None)
            self.assertEqual(result[1], "text-llm")
            self.assertNotIn("stream", self.calls[-1])
            self.assertNotIn("response_format", self.calls[-1])
            self.assertNotIn("输出协议", self.calls[-1]["messages"][0]["content"][0]["text"])
        self.assertEqual(self.document(), {})
        self.assertEqual([draft["kind"] for draft in drafts], ["full_response", "full_response"])

    def test_failed_vision_batches_keep_existing_nonstream_text_fallback(self):
        grid = FrameGrid(path=str(self.root / "synthetic.png"), url="", start=2, end=10, frame_count=1)
        response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="# 课程\n\n来源内容保持完整。"))])
        def completion(**kwargs):
            if any(item.get("type") == "image_url" for item in kwargs["messages"][0]["content"]):
                raise RuntimeError("synthetic vision failure")
            return response
        with self.provider(completion), patch("app.summarizer._grid_image_content_items", return_value=[
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,Zml4dHVyZQ=="}}]):
            result = summarize_with_llm(self.task.title, self.transcript, [grid], self.options,
                section_callback=partial_section_callback(self.task.id, self.transcript))
        self.assertEqual(result[1], "text-llm")
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all("stream" not in request and "response_format" not in request for request in self.calls))
        self.assertEqual(self.document(), {})

    def test_long_source_keeps_parent_chunk_windows_without_child_streams(self):
        self.transcript = TranscriptResult(full_text="来源内容保持完整。" * 8000,
            segments=[TranscriptSegment(start=10, end=900, text="来源内容保持完整。" * 8000)])
        write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="# 课程\n\n来源内容保持完整。"))])
        with self.provider(lambda **_kwargs: response):
            self.assertIsNotNone(self.summary())
        self.assertEqual(len(self.calls), len(source_block_entries(self.transcript)))
        self.assertTrue(all("stream" not in request and "response_format" not in request for request in self.calls))
        self.assertTrue(all(item["kind"] == "text_chunk" and item["start"] == 10 and item["end"] == 900
                            for item in self.document()["sections"]))

    def test_real_sdk_loopback_sse_persists_chapter_before_server_releases_next(self):
        # Real installed OpenAI SDK and HTTP transport; this loopback fixture
        # calls the consumer directly, never expands the production allowlist.
        from openai import DefaultHttpxClient, OpenAI
        requested, ready, failures = [], threading.Event(), []
        first = '{"chapters":[' + json.dumps(chapter("主题😀"), ensure_ascii=False)
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *_args):
                pass
            def do_POST(self):
                requested.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Connection", "close")
                self.end_headers()
                def send(text=None, reason=None, usage=None):
                    event = {"id": "fixture", "object": "chat.completion.chunk", "created": 0, "model": "gpt-4.1",
                             "choices": [] if usage else [{"index": 0, "delta": {"content": text} if text else {}, "finish_reason": reason}]}
                    if usage:
                        event["usage"] = usage
                    wire = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
                    # Split real wire bytes, including multi-byte Unicode.
                    for offset in range(0, len(wire), 7):
                        self.wfile.write(wire[offset:offset + 7])
                        self.wfile.flush()
                send(first)
                if not ready.wait(3):
                    failures.append("Chapter one was not durable before chapter two")
                # Valid provider pauses keep the selected SDK timeout; there is
                # no new sub-second timeout that would reject this chapter.
                threading.Event().wait(1.2)
                send("," + json.dumps(chapter("主题二")) + "]}")
                send(reason="stop")
                send(usage={"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60})
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        original = partial_section_callback(self.task.id, self.transcript)
        def callback(payload):
            original(payload)
            if payload["chapter_index"] == 0:
                self.assertEqual(len(self.events()), 1)
                self.assertEqual(len(self.document()["sections"]), 1)
                self.assertIn("主题😀", read_task_note(self.task.id))
                ready.set()
        with OpenAI(api_key="fixture-only", base_url=f"http://127.0.0.1:{server.server_port}/v1", max_retries=0,
                    timeout=3, http_client=DefaultHttpxClient(trust_env=False)) as client:
            result = streamed_chapters(client, model="gpt-4.1", messages=[{"role": "user", "content": "synthetic JSON fixture"}],
                provider_kwargs={"temperature": 0.2}, blocks=source_block_entries(self.transcript), title=self.task.title,
                generation="a" * 64, section_callback=callback, check_cancel=lambda: None)
            self.assertFalse(client.is_closed())
        self.assertEqual(failures, [])
        self.assertEqual(len(requested), 1)
        self.assertTrue(requested[0]["stream"])
        self.assertIn("主题二", result)
        self.assertEqual(len(self.document()["sections"]), 2)
        self.assertEqual(usage_report()["totals"]["total_tokens"], 60)

    def test_real_sdk_idle_response_cancellation_retains_draft_and_bounds_read(self):
        from openai import DefaultHttpxClient, OpenAI
        cancelled, release, sent = threading.Event(), threading.Event(), threading.Event()
        requests = []
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *_args):
                pass
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                chunk = {"id": "fixture", "object": "chat.completion.chunk", "created": 0, "model": "gpt-4.1",
                         "choices": [{"index": 0, "finish_reason": None, "delta": {
                             "content": '{"chapters":[' + json.dumps(chapter())}}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.flush()
                sent.set()
                release.wait(2)  # Bound the fixture even if the client fails.
                self.close_connection = True
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        original = partial_section_callback(self.task.id, self.transcript)
        timers = []
        def callback(payload):
            original(payload)
            timer = threading.Timer(0.1, cancelled.set)
            timers.append(timer)
            timer.start()
        def check():
            if cancelled.is_set():
                raise SummarizationCancelled("summary_cancelled")
        started = time.monotonic()
        try:
            with OpenAI(api_key="fixture-only", base_url=f"http://127.0.0.1:{server.server_port}/v1", max_retries=0,
                        timeout=0.4, http_client=DefaultHttpxClient(trust_env=False)) as client:
                with self.assertRaises(SummarizationCancelled):
                    streamed_chapters(client, model="gpt-4.1", messages=[{"role": "user", "content": "synthetic JSON"}],
                        provider_kwargs={}, blocks=source_block_entries(self.transcript), title=self.task.title,
                        generation="a" * 64, section_callback=callback, check_cancel=check)
                self.assertFalse(client.is_closed())
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertTrue(sent.is_set())
            self.assertEqual(len(requests), 1)
            self.assertEqual(len(self.document()["sections"]), 1)
            self.assertFalse((self.work / "note.md").exists())
            self.assertEqual(usage_report()["recent"][0]["status"], "failed")
        finally:
            release.set()
            for timer in timers:
                timer.cancel()
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
