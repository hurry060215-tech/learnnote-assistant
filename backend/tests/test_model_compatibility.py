"""Deterministic provider compatibility fixtures; no real SDK or network calls."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.models import TaskOptions, TranscriptResult, TranscriptSegment
from app.summarizer import _compatible_completion, SummarizationCancelled
from app.summary_outcome import safe_summary_events, safe_summary_diagnostics


class ProviderError(Exception):
    def __init__(self, status=400, code="unsupported_parameter", param="temperature", nested=True):
        super().__init__("synthetic private body sk-fixturePrivateValue https://private.invalid/?token=fixture")
        self.status_code = status
        detail = {"code": code, "param": param, "message": str(self), "private_body": str(self)}
        self.body = {"error": detail} if nested else detail


class ModelCompatibilityTests(unittest.TestCase):
    def setUp(self):
        ledger = patch("app.token_usage.record_usage")
        self.ledger = ledger.start()
        self.addCleanup(ledger.stop)
        self.response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content="# Synthetic lesson\n\n## Key point\n\nLearning rate controls parameter updates."))])
        self.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=Mock())))
        self.kwargs = {"model": "synthetic-model", "messages": [{"role": "user", "content": "Synthetic source"}],
                       "temperature": 0.2, "max_tokens": 32, "max_completion_tokens": 64,
                       "extra_body": {"thinking": {"type": "disabled"}}, "safety_identifier": "fixture"}

    def test_explicit_unsupported_temperature_retries_same_request_once(self):
        for status, nested in ((400, True), (422, False)):
            with self.subTest(status=status):
                create = self.client.chat.completions.create
                create.reset_mock(side_effect=True)
                create.side_effect = [ProviderError(status=status, nested=nested), self.response]
                events = []
                result = _compatible_completion(self.client, events=events, stage="text_summary", **self.kwargs)
                self.assertIs(result, self.response)
                self.assertEqual(create.call_count, 2)
                self.assertEqual(create.call_args_list[0].kwargs, self.kwargs)
                self.assertEqual(create.call_args_list[1].kwargs, {key: value for key, value in self.kwargs.items() if key != "temperature"})
                self.assertIs(create.call_args_list[1].kwargs["messages"], self.kwargs["messages"])
                self.assertEqual(self.kwargs["temperature"], 0.2)
                self.assertEqual(events, [{"stage": "provider_compatibility", "code": "repaired", "request_stage": "text_summary",
                    "original_status": status, "original_code": "unsupported_parameter", "parameter": "temperature", "retry_outcome": "success"}])

    def test_other_statuses_parameters_and_unstructured_errors_never_retry(self):
        errors = [ProviderError(status=status) for status in (401, 403, 429, 500, 400.0, True)]
        errors += [ProviderError(status=status, code="invalid_request_error") for status in (400, 422)]
        errors += [ProviderError(param=param) for param in ("max_tokens", "max_completion_tokens", "thinking", "extra_body", "safety_identifier", "top_p", "Temperature", "temperature.value")]
        errors += [RuntimeError("400 Unsupported parameter: temperature"), TypeError("unsupported_parameter temperature"), TimeoutError("timeout"), ConnectionError("offline")]
        for error in errors:
            with self.subTest(error=type(error).__name__, status=getattr(error, "status_code", None), body=getattr(error, "body", None)):
                create = self.client.chat.completions.create
                create.reset_mock(side_effect=True)
                create.side_effect = error
                events = []
                with self.assertRaises(type(error)) as caught:
                    _compatible_completion(self.client, events=events, stage="text_summary", **self.kwargs)
                self.assertIs(caught.exception, error)
                self.assertEqual(create.call_count, 1)
                self.assertEqual(events, [])

    def test_absent_temperature_and_second_rejection_do_not_retry(self):
        create = self.client.chat.completions.create
        create.side_effect = ProviderError()
        with self.assertRaises(ProviderError):
            _compatible_completion(self.client, events=[], stage="vision_merge",
                **{key: value for key, value in self.kwargs.items() if key != "temperature"})
        self.assertEqual(create.call_count, 1)
        create.reset_mock(side_effect=True)
        second = ProviderError(status=422)
        create.side_effect = [ProviderError(), second]
        events = []
        with self.assertRaises(ProviderError) as caught:
            _compatible_completion(self.client, events=events, stage="vision_merge", **self.kwargs)
        self.assertIs(caught.exception, second)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(events[0]["original_status"], 400)
        self.assertEqual(events[0]["retry_outcome"], "failed")

    def test_cancellation_after_rejection_prevents_second_request(self):
        self.client.chat.completions.create.side_effect = ProviderError()
        events = []
        with self.assertRaises(SummarizationCancelled):
            _compatible_completion(self.client, events=events, stage="vision_batch",
                cancel_check=Mock(side_effect=SummarizationCancelled("cancelled")), **self.kwargs)
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.assertEqual(events[0]["retry_outcome"], "cancelled")

    def test_compatibility_diagnostics_preserve_only_bounded_provenance(self):
        event = {"stage": "provider_compatibility", "code": "repaired", "request_stage": "text_summary",
                 "original_status": 400, "original_code": "unsupported_parameter", "parameter": "temperature", "retry_outcome": "success"}
        private = str(ProviderError())
        poisoned = {**event, "message": private, "body": private, "endpoint": private, "api_key": private, "error_type": private}
        self.assertEqual(safe_summary_events([poisoned]), [event])
        self.assertEqual(safe_summary_diagnostics({"llm_events": [poisoned]})["llm_events"], [event])
        for key in ("request_stage", "original_code", "parameter", "retry_outcome"):
            self.assertNotIn(key, safe_summary_events([{**poisoned, key: private}])[0])
        self.assertNotIn("original_status", safe_summary_events([{**poisoned, "original_status": 500}])[0])

    def test_task_parameter_recovery_keeps_source_and_reports_actual_ai_success(self):
        from app.processor import process_saved_transcript_task
        from app.storage import create_task, get_task, update_task, write_json
        for recover in (True, False):
            with self.subTest(recover=recover), tempfile.TemporaryDirectory() as directory, \
                 patch("app.storage.TASK_DIR", Path(directory)), patch("app.storage.ensure_dirs"), \
                 patch("app.observability.TASK_DIR", Path(directory)), \
                 patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=Mock(return_value=self.client))}), \
                 patch("app.processor.MediaDownloader") as download, patch("app.processor.transcribe_audio") as asr:
                options = TaskOptions(content_mode="text", llm_api_key="fixture-key", llm_base_url="https://fixture.invalid/v1", llm_model="synthetic-model")
                task = create_task("local", "Synthetic lesson", options=options)
                transcript = TranscriptResult(source="faster-whisper", full_text="Learning rate controls parameter updates.",
                    segments=[TranscriptSegment(start=0, end=10, text="Learning rate controls parameter updates.")])
                path = write_json(task.id, "transcript.json", transcript.model_dump(mode="json"))
                original = path.read_bytes()
                update_task(task.id, transcript_path=str(path))
                create = self.client.chat.completions.create
                create.reset_mock(side_effect=True)
                create.side_effect = [ProviderError(), self.response if recover else ProviderError(status=422)]
                process_saved_transcript_task(task.id, options)
                saved = get_task(task.id)
                self.assertEqual(create.call_count, 2)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(saved.status, "success" if recover else "failed")
                if recover:
                    self.assertEqual(saved.summary_source, "text-llm")
                    self.assertIn("Learning rate controls parameter updates", Path(saved.note_path).read_text(encoding="utf-8"))
                else:
                    self.assertEqual(saved.error_code, "summary_unavailable")
                    self.assertEqual(saved.checkpoint, "transcript_ready")
                diagnostics = json.loads(Path(saved.summary_diagnostics_path).read_text(encoding="utf-8"))
                retry = next(event for event in diagnostics["llm_events"] if event["stage"] == "provider_compatibility")
                self.assertEqual(retry["retry_outcome"], "success" if recover else "failed")
                self.assertNotIn("fixturePrivateValue", json.dumps(diagnostics))
                download.assert_not_called()
                asr.assert_not_called()
