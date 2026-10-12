"""Synthetic, non-stream response drafts; no provider or credential access."""
from __future__ import annotations

from contextlib import ExitStack
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from app.models import TaskOptions, TranscriptResult, TranscriptSegment
from app.observability import read_task_events_after
from app.partial_note_projection import read_partial_note
from app.pipeline_progress import start_pipeline_attempt, write_progressive_draft
from app.progressive_sections import partial_section_callback
from app.reading_notes import source_block_entries
from app.storage import create_task, get_task, read_json, task_dir, update_task, write_json
from app.summarizer import SummarizationCancelled, summarize_with_llm
from app.task_artifacts import read_task_note
from app.full_response_sections import full_response_payload


class FullResponseDraftTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "data"
        for module in ("storage", "library", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        for module in ("library", "knowledge", "routers.notes"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        self.options = TaskOptions(llm_base_url="http://127.0.0.1:1/v1", llm_model="fixture-text",
                                   llm_api_key="fixture", use_saved_connection=False, visual_understanding=False)
        self.task = create_task("local", "课程", options=self.options)
        self.work = task_dir(self.task.id)
        self.source(TranscriptResult(full_text="来源内容保持完整。"))

    def source(self, transcript):
        self.transcript = transcript
        self.path = write_json(self.task.id, "transcript.json", transcript.model_dump(mode="json"))
        start_pipeline_attempt(self.task.id)
        draft = write_progressive_draft(self.task.id, self.task.title, transcript)
        update_task(self.task.id, status="running", phase="summarizing", transcript_path=str(self.path),
                    note_path=str(draft), summary_source="transcript-draft", checkpoint="transcript_ready")

    def provider(self, completion):
        provider = types.ModuleType("openai")
        provider.OpenAI = lambda **_kwargs: types.SimpleNamespace(chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=completion)))
        return patch.dict(sys.modules, {"openai": provider})

    @staticmethod
    def response(text="# 课程\n\n来源内容保持完整。", reason="stop"):
        return types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason=reason,
            message=types.SimpleNamespace(content=text))])

    def summary(self, callback=None):
        return summarize_with_llm(self.task.title, self.transcript, [], self.options,
            section_callback=callback, cancel_check=lambda: get_task(self.task.id).cancel_requested)

    def document(self):
        return read_json(self.task.id, "partial_note.json", {})

    def events(self):
        return [event for _, event in read_task_events_after(self.task.id) if event["event"] == "partial_section_ready"]

    def payload(self):
        return full_response_payload(source_block_entries(self.transcript), self.response().choices[0].message.content, "a" * 64)

    def test_one_to_three_blocks_keep_exact_request_and_result_and_publish_once_before_gate(self):
        from app.summarizer import _validated_generated_note
        for count in (1, 2, 3):
            self.source(TranscriptResult(full_text="来源内容保持完整。" + "甲" * (16000 * (count - 1))))
            baseline, requests, payloads, order = [], [], [], []
            with self.provider(lambda **kw: baseline.append(kw) or self.response()):
                expected = self.summary()
            def completion(**kwargs):
                self.assertEqual(payloads, [])
                requests.append(kwargs)
                order.append("response")
                return self.response()
            publish = partial_section_callback(self.task.id, self.transcript)
            def callback(payload):
                order.append("draft")
                payloads.append(payload)
                publish(payload)
            def gate(*args, **kwargs):
                order.append("gate")
                self.assertIn("完整响应草稿", read_task_note(self.task.id))
                return _validated_generated_note(*args, **kwargs)
            original = self.path.read_bytes()
            with self.provider(completion), patch("app.summarizer._validated_generated_note", side_effect=gate):
                actual = self.summary(callback)
            self.assertEqual(actual, expected)
            self.assertEqual(requests, baseline)
            self.assertEqual(len(requests), 1)
            self.assertEqual(order, ["response", "draft", "gate"])
            entries = source_block_entries(self.transcript)
            self.assertEqual(len(entries), count)
            self.assertEqual(payloads[0]["source_blocks"], list(range(count)))
            self.assertEqual(payloads[0]["block_digests"], [hashlib.sha256(entry["text"].encode()).hexdigest() for entry in entries])
            prompt = requests[0]["messages"][0]["content"][0]["text"]
            self.assertTrue(prompt.endswith("\n\n".join(entry["text"] for entry in entries)))
            self.assertEqual(self.path.read_bytes(), original)
            section = self.document()["sections"][0]
            self.assertNotIn("chapter_index", section)
            self.assertNotIn("block_index", section)
            self.assertNotIn("start", section)
            self.assertFalse(section["verified"])
            self.assertEqual(section["status"], "evidence_pending")
            self.assertEqual(read_partial_note(self.task.id)["reason"], "ready")

    def test_compatibility_retry_publishes_only_after_success_with_unchanged_requests(self):
        from backend.tests.test_model_compatibility import ProviderError
        baseline, requests, payloads = [], [], []
        def completion(calls, **kwargs):
            self.assertEqual(payloads, [])
            calls.append(kwargs)
            if len(calls) == 1:
                raise ProviderError()
            return self.response()
        with self.provider(lambda **kw: completion(baseline, **kw)):
            expected = self.summary()
        with self.provider(lambda **kw: completion(requests, **kw)):
            self.assertEqual(self.summary(payloads.append), expected)
        self.assertEqual(requests, baseline)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(payloads), 1)

    def test_truncated_response_and_quota_failure_never_claim_a_complete_response(self):
        for reason in (None, "", "length", "content_filter", "tool_calls"):
            payloads = []
            with self.provider(lambda **kw: self.response(reason=reason)):
                expected = self.summary()
                self.assertEqual(self.summary(payloads.append), expected)
            self.assertEqual(payloads, [])
        with self.provider(lambda **kw: (_ for _ in ()).throw(RuntimeError("insufficient_quota"))):
            self.assertIsNone(self.summary(partial_section_callback(self.task.id, self.transcript)))
        self.assertEqual(self.document(), {})
        self.assertEqual(self.events(), [])

    def test_optional_draft_write_failure_still_runs_original_final_gate(self):
        from app.summarizer import _validated_generated_note
        with self.provider(lambda **kw: self.response()):
            expected = self.summary()
        for error in (OSError("synthetic replace failure"), ValueError("synthetic projection failure")):
            def unavailable(_payload):
                raise error
            with self.provider(lambda **kw: self.response()), patch(
                    "app.summarizer._validated_generated_note", wraps=_validated_generated_note) as gate:
                self.assertEqual(self.summary(unavailable), expected)
            gate.assert_called_once()

    def test_projection_cancellation_is_not_swallowed_as_optional_failure(self):
        from app.processor_state import TaskCancelled
        for error in (TaskCancelled(), SummarizationCancelled()):
            def cancelled(_payload):
                raise error
            with self.provider(lambda **kw: self.response()), patch("app.summarizer._validated_generated_note") as gate:
                with self.assertRaises(SummarizationCancelled):
                    self.summary(cancelled)
            gate.assert_not_called()

    def test_existing_repair_request_and_final_output_are_unchanged_and_draft_is_not_repaired(self):
        baseline, requests, payloads = [], [], []
        def completion(calls, **kwargs):
            calls.append(kwargs)
            return self.response("# 课程\n\nInventedUnsupportedTerm。" if len(calls) == 1 else "# 课程\n\n来源内容保持完整。")
        with self.provider(lambda **kw: completion(baseline, **kw)):
            expected = self.summary()
        publish = partial_section_callback(self.task.id, self.transcript)
        def callback(payload):
            payloads.append(payload)
            publish(payload)
        with self.provider(lambda **kw: completion(requests, **kw)):
            self.assertEqual(self.summary(callback), expected)
        self.assertEqual(requests, baseline)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(payloads), 1)
        self.assertIn("InventedUnsupportedTerm", self.document()["sections"][0]["markdown"])
        self.assertFalse(self.document()["sections"][0]["verified"])
        self.assertIn("【待核对：未找到支持来源】", read_task_note(self.task.id))

    def test_cancellation_before_publication_keeps_source_draft_and_skips_gate(self):
        def completion(**kwargs):
            update_task(self.task.id, cancel_requested=True)
            return self.response()
        with self.provider(completion), patch("app.summarizer._validated_generated_note") as gate:
            with self.assertRaises(SummarizationCancelled):
                self.summary(partial_section_callback(self.task.id, self.transcript))
        gate.assert_not_called()
        self.assertEqual(self.document(), {})
        self.assertEqual(self.events(), [])

    def test_cancellation_from_callback_retains_only_pending_response_and_skips_gate(self):
        publish = partial_section_callback(self.task.id, self.transcript)
        def callback(payload):
            publish(payload)
            update_task(self.task.id, cancel_requested=True)
        with self.provider(lambda **kw: self.response()), patch("app.summarizer._validated_generated_note") as gate:
            with self.assertRaises(SummarizationCancelled):
                self.summary(callback)
        gate.assert_not_called()
        self.assertEqual(len(self.events()), 1)
        self.assertFalse(self.document()["sections"][0]["verified"])
        self.assertIn("待最终来源检查", read_task_note(self.task.id))
        self.assertFalse((self.work / "note.md").exists())

    def test_all_actual_cue_bounds_are_bound_without_generated_attribution(self):
        self.source(TranscriptResult(segments=[TranscriptSegment(start=0, end=1, text=" "),
            TranscriptSegment(start=2.25, end=10, text="甲" * 16000),
            TranscriptSegment(start=90, end=120.75, text="来源内容保持完整。")]))
        publish = partial_section_callback(self.task.id, self.transcript)
        publish(self.payload())
        section = self.document()["sections"][0]
        self.assertEqual(section["source_blocks"], [0, 1])
        self.assertEqual(section["source_windows"], [{"index": 1, "start": 2.25, "end": 10},
                                                    {"index": 2, "start": 90, "end": 120.75}])
        self.assertEqual((section["start"], section["end"]), (2.25, 120.75))
        self.assertIn("来源块范围（粗略定位，具体内容仍需回源核对）", section["markdown"])
        self.assertIn("来源块 2", section["markdown"])

    def test_missing_changed_or_invented_source_blocks_and_bad_markdown_do_not_publish(self):
        self.source(TranscriptResult(full_text="甲" * 17000))
        publish = partial_section_callback(self.task.id, self.transcript)
        value = self.payload()
        for change in ({"source_blocks": [0]}, {"source_blocks": [False, 1]}, {"block_digests": ["f" * 64] * 2},
                       {"source_windows": [{"index": 0, "start": 0, "end": 10}]},
                       {"generation_revision": "invalid"}, {"markdown": "```python\nprint(1)"}):
            publish({**value, **change})
            self.assertEqual(self.document(), {})
        self.assertEqual(self.events(), [])

    def test_stale_attempt_source_and_generation_never_replace_current_response(self):
        old = partial_section_callback(self.task.id, self.transcript)
        old(self.payload())
        previous = copy.deepcopy(self.document())
        old({**self.payload(), "generation_revision": "b" * 64, "markdown": "Late generation"})
        self.assertEqual(self.document(), previous)
        start_pipeline_attempt(self.task.id)
        old(self.payload())
        self.assertEqual(self.document(), previous)
        current = partial_section_callback(self.task.id, self.transcript)
        write_json(self.task.id, "transcript.json", TranscriptResult(full_text="Changed original").model_dump(mode="json"))
        current(self.payload())
        self.assertEqual(self.document(), previous)

    def test_source_changes_during_preparation_are_rechecked_before_publication(self):
        from app.partial_section_content import build_claim_evidence_map
        publish = partial_section_callback(self.task.id, self.transcript)
        publish(self.payload())
        previous = copy.deepcopy(self.document())
        def claims(*args, **kwargs):
            result = build_claim_evidence_map(*args, **kwargs)
            write_json(self.task.id, "transcript.json", TranscriptResult(full_text="Changed during preparation").model_dump(mode="json"))
            return result
        with patch("app.partial_section_content.build_claim_evidence_map", side_effect=claims):
            publish({**self.payload(), "markdown": "Late response"})
        self.assertEqual(self.document(), previous)
        self.assertEqual(len(self.events()), 1)

    def test_truncated_saved_response_body_is_not_projected_as_an_intact_draft(self):
        partial_section_callback(self.task.id, self.transcript)(self.payload())
        document = self.document()
        document["sections"][0]["markdown"] = document["sections"][0]["markdown"][:20]
        write_json(self.task.id, "partial_note.json", document)
        self.assertEqual(read_partial_note(self.task.id)["reason"], "invalid_artifact")

    def test_replay_repairs_markdown_without_event_churn_and_preserves_published_note(self):
        publish = partial_section_callback(self.task.id, self.transcript)
        publish(self.payload())
        expected = (self.work / "draft.partial.md").read_bytes()
        events = self.events()
        (self.work / "draft.partial.md").write_text("interrupted", encoding="utf-8")
        publish(self.payload())
        self.assertEqual((self.work / "draft.partial.md").read_bytes(), expected)
        self.assertEqual(self.events(), events)
        note = self.work / "note.md"
        note.write_text("# Already published\n", encoding="utf-8")
        update_task(self.task.id, note_path=str(note), summary_source="text-llm", status="success")
        publish(self.payload())
        self.assertEqual(note.read_text(encoding="utf-8"), "# Already published\n")
        self.assertEqual(get_task(self.task.id).note_path, str(note))
        self.assertFalse(self.document()["sections"][0]["verified"])

    def test_pipeline_failed_gate_and_final_success_leave_response_artifact_pending(self):
        from app.processor import process_saved_transcript_task
        self.source(TranscriptResult(full_text="来源内容保持完整。",
            segments=[TranscriptSegment(start=0, end=10, text="来源内容保持完整。")]))
        original = self.path.read_bytes()
        for generated, status in ((None, "failed"), ("# 课程\n\n来源内容保持完整。", "success")):
            with self.provider(lambda **kw: self.response()), patch("app.summarizer._validated_generated_note", return_value=generated):
                process_saved_transcript_task(self.task.id, self.options)
            self.assertEqual(get_task(self.task.id).status, status)
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(len(self.document()["sections"]), 1)
            self.assertFalse(self.document()["verified"])
            self.assertFalse(self.document()["sections"][0]["verified"])
            self.assertIn("待最终来源检查", (self.work / "draft.partial.md").read_text(encoding="utf-8"))
            self.assertEqual((self.work / "note.md").exists(), status == "success")
            if status == "failed":
                self.assertEqual(get_task(self.task.id).error_code, "summary_unavailable")
                self.assertIn("完整响应草稿", read_task_note(self.task.id))


if __name__ == "__main__":
    unittest.main()
