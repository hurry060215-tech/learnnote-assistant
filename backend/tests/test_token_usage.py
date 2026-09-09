import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import token_usage
from app.assistant_stream import completion_text, StreamControl


class TokenUsageTests(unittest.TestCase):
    def test_stream_records_final_usage_chunk_without_choices(self):
        usage = SimpleNamespace(prompt_tokens=20, completion_tokens=5, total_tokens=25)
        class Stream:
            def close(self): pass
            def __iter__(self):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="answer"), finish_reason="stop")])
                yield SimpleNamespace(choices=[], usage=usage)
        client = SimpleNamespace(close=lambda: None, base_url="https://example.com", chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: Stream())))
        with tempfile.TemporaryDirectory() as root, patch.object(token_usage, "DATA_DIR", Path(root)):
            answer = completion_text(client, model="test", control=StreamControl(), emit=lambda *args: None)
            self.assertEqual(answer, "answer")
            self.assertEqual(token_usage.usage_report()["totals"]["total_tokens"], 25)

    def test_provider_counts_and_unknown_are_distinct(self):
        with tempfile.TemporaryDirectory() as root, patch.object(token_usage, "DATA_DIR", Path(root)):
            client = SimpleNamespace(base_url="https://example.com/v1")
            token_usage.record_usage(client, "test", "assistant", SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15), time.monotonic())
            token_usage.record_usage(client, "test", "assistant", None, time.monotonic(), "failed")
            report = token_usage.usage_report()
            self.assertEqual(report["totals"]["requests"], 2)
            self.assertEqual(report["totals"]["measured_requests"], 1)
            self.assertEqual(report["totals"]["total_tokens"], 15)
            self.assertIsNone(report["recent"][0]["total_tokens"])
            self.assertEqual(report["recent"][0]["status"], "failed")

    def test_ledger_failure_does_not_fail_model_call(self):
        response = SimpleNamespace(usage=None)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response)))
        with patch.object(token_usage, "_db", side_effect=OSError("unwritable")):
            self.assertIs(token_usage.tracked_completion(client, model="test"), response)
