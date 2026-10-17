"""Grounding traces are bounded source-free diagnostics, never a provider ledger."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from app.models import TaskOptions, TranscriptResult, TranscriptSegment
from app import summarizer
from app.summary_outcome import safe_summary_diagnostics, safe_summary_events, safe_summary_warning, summary_failure_message
from app.summary_diagnostics import build_summary_diagnostics


def response(content):
    return NS(choices=[NS(message=NS(content=content), finish_reason="stop")])


class GroundingDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.options = TaskOptions(content_mode="text", visual_understanding=False,
            llm_api_key="fixture-key", llm_base_url="http://127.0.0.1:9/v1", llm_model="synthetic")

    def test_terminal_failure_survives_twenty_event_bound_and_double_projection(self):
        events = [{"stage": "vision_cache", "code": "success", "batch": i} for i in range(25)]
        terminal = {"stage": "grounding_validation", "code": "rejected",
            "issues": ["unsupported_terms:privateName", "unsupported_quantity:500元", "unknown:private"],
            "chunk_index": 19, "chunk_count": 24, "completed_chunks": 18,
            "request_stage": "text_summary", "repair_outcome": "rejected", "prompt": "private"}
        events += [{"stage": "grounding_repair", "code": "api_error", "message": "private 429"}, terminal]
        safe = safe_summary_events(events)
        self.assertEqual(len(safe), 20)
        self.assertEqual(safe[-2]["stage"], "grounding_repair")
        self.assertEqual(safe[-1]["issue_codes"], ["unsupported_quantity", "unsupported_terms"])
        self.assertEqual(safe[-1]["completed_chunks"], 18)
        self.assertNotIn("private", json.dumps(safe))
        self.assertNotIn("500", json.dumps(safe))
        self.assertEqual(safe_summary_diagnostics({"llm_events": safe})["llm_events"], safe)
        self.assertEqual(safe_summary_events(safe), safe)

    def test_new_metadata_rejects_unknown_values_and_noninteger_chunk_scope(self):
        for invalid in (True, False, 1.2, "1", -1, 1000001, None):
            with self.subTest(invalid=invalid):
                event = {"stage": "grounding_validation", "code": "rejected", "chunk_count": invalid,
                    "chunk_index": 1, "completed_chunks": 0, "request_stage": {"private": 1},
                    "repair_outcome": ["private"], "issue_codes": ["private", {"private": 1}]}
                self.assertEqual(safe_summary_events([event]), [{"stage": "grounding_validation", "code": "rejected"}])
        for name, value in (("chunk_index", True), ("chunk_index", 3), ("completed_chunks", True), ("completed_chunks", 3)):
            result = safe_summary_events([{"stage": "grounding_validation", "code": "rejected",
                "chunk_count": 2, "chunk_index": 1, "completed_chunks": 0, name: value}])[0]
            self.assertNotIn(name, result)

    def test_long_chunk_failure_identifies_scope_without_raw_content_or_audit_files(self):
        text = "今天我们讨论周末计划。" * 1200
        transcript = TranscriptResult(source="faster-whisper", full_text="\n".join([text] * 4),
            segments=[TranscriptSegment(start=i*4050, end=(i+1)*4050, text=text) for i in range(4)])
        good = "# 周末计划\n\n今天我们讨论周末计划。"
        bad = "# 周末计划\n\n使用 InventedPrivateName 安排周末。"
        events, sections = [], []
        with tempfile.TemporaryDirectory() as directory, patch("openai.OpenAI", return_value=object()), \
             patch.object(summarizer, "_compatible_completion", side_effect=[response(good), response(bad), response(bad)]) as create:
            result = summarizer.summarize_with_llm("周末计划", transcript, [], self.options,
                events=events, section_callback=sections.append, vision_cache_dir=Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])  # Deliberately no new raw chunk storage.
        self.assertIsNone(result)
        self.assertEqual(create.call_count, 3)
        self.assertEqual(len(sections), 1)
        final = safe_summary_events(events)[-1]
        self.assertEqual({k: final[k] for k in ("chunk_index", "chunk_count", "completed_chunks")},
            {"chunk_index": 2, "chunk_count": 4, "completed_chunks": 1})
        self.assertEqual(final["request_stage"], "text_summary")
        self.assertEqual(final["repair_outcome"], "rejected")
        self.assertEqual(final["issue_codes"], ["unsupported_terms"])
        for warning in (summarizer.llm_warning_from_events(self.options, events, "fallback"), summary_failure_message("", events)):
            diagnostics = build_summary_diagnostics("0" * 32, "周末计划", "", self.options, [], [], "local-template", warning, events)
            self.assertEqual(diagnostics["llm_failure_code"], "rejected")
            self.assertEqual(diagnostics["llm_failure_stage"], "grounding_validation")
            self.assertEqual(diagnostics["llm_failure_reason"], "")
            self.assertNotIn("InventedPrivateName", json.dumps(diagnostics))
        message = summary_failure_message("", events)
        self.assertIn("核对字幕", message)
        self.assertNotIn("调整模型", message)
        self.assertEqual(safe_summary_warning(message), message)
        self.assertEqual(summary_failure_message(message), message)

    def test_provider_recovery_guidance_and_repair_error_remain_distinct(self):
        self.assertIn("调整模型", summary_failure_message("HTTP 401"))
        transcript = TranscriptResult(full_text="我们线下见面。")
        events = []
        with patch.object(summarizer, "_compatible_completion", side_effect=RuntimeError("private 429")):
            result = summarizer._validated_generated_note(object(), "synthetic", {}, "使用 Zoom。",
                transcript, [], "", events)
        self.assertEqual(result, "")
        safe = safe_summary_events(events)
        self.assertEqual(safe[-2]["repair_outcome"], "api_error")
        self.assertEqual(safe[-2]["message"], "HTTP 429")
        self.assertEqual(safe[-1]["repair_outcome"], "rejected")
        self.assertEqual(safe[-1]["issue_codes"], ["empty_note"])

    def test_retry_executes_only_saved_transcript_and_preserves_original_bytes(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.storage import create_task, get_task, update_task, write_json
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            for target in ("app.storage.TASK_DIR", "app.observability.TASK_DIR", "app.summary_diagnostics.TASK_DIR"):
                stack.enter_context(patch(target, root))
            stack.enter_context(patch("app.storage.ensure_dirs"))
            forbidden = [stack.enter_context(patch("app.processor." + name, side_effect=AssertionError(name)))
                for name in ("MediaDownloader", "transcribe_audio", "transcribe_audio_openai_compatible", "extract_audio", "normalize_video")]
            task = create_task("local", "周末计划", options=self.options)
            text = "今天我们讨论周末计划，先见面再散步。"
            path = write_json(task.id, "transcript.json", TranscriptResult(source="faster-whisper", full_text=text,
                segments=[TranscriptSegment(start=0, end=10, text=text)]).model_dump(mode="json"))
            original = path.read_bytes()
            update_task(task.id, status="failed", phase="failed", error_code="summary_unavailable",
                transcript_path=str(path), checkpoint="transcript_ready")
            with patch("app.main.schedule_processing") as schedule:
                result = TestClient(app).post(f"/api/tasks/{task.id}/retry-summary", json=self.options.model_dump())
            self.assertEqual(result.status_code, 200, result.text)
            args = schedule.call_args.args
            with patch("openai.OpenAI", return_value=object()), \
                 patch.object(summarizer, "_compatible_completion", return_value=response("# 周末计划\n\n" + text)) as create:
                args[1](*args[2:])
            self.assertEqual(create.call_count, 1)
            self.assertEqual(get_task(task.id).status, "success")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(get_task(task.id).summary_source, "text-llm")
            for spy in forbidden:
                spy.assert_not_called()
