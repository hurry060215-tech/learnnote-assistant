import tempfile
import time
import unittest
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import token_usage
from app.assistant_stream import completion_text, StreamControl


class TokenUsageTests(unittest.TestCase):
    def test_empty_ledger_and_provider_zero_have_distinct_coverage(self):
        with tempfile.TemporaryDirectory() as root, patch.object(token_usage, "DATA_DIR", Path(root)):
            empty = token_usage.usage_report()
            self.assertEqual(empty["schema_version"], 2)
            self.assertEqual(empty["totals"]["requests"], 0)
            self.assertEqual(empty["totals"]["total_tokens"], 0)
            self.assertEqual(empty["totals"]["measured_requests"], 0)
            self.assertEqual(empty["daily"], [])
            token_usage.record_usage(SimpleNamespace(), "zero", "note",
                SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0), time.monotonic())
            report = token_usage.usage_report()
            for group in [report["totals"], *report["models"], *report["daily"]]:
                self.assertEqual(group["requests"], 1)
                for field, coverage in (("input_tokens", "measured_input_requests"), ("output_tokens", "measured_output_requests"), ("total_tokens", "measured_requests")):
                    self.assertEqual(group[field], 0)
                    self.assertEqual(group[coverage], 1)

    def test_all_unknown_and_failure_remain_null_in_every_aggregate(self):
        with tempfile.TemporaryDirectory() as root, patch.object(token_usage, "DATA_DIR", Path(root)):
            for status in ("success", "failed"):
                token_usage.record_usage(SimpleNamespace(), "unknown", "note", None, time.monotonic(), status)
            report = token_usage.usage_report()
            for group in [report["totals"], *report["models"], *report["daily"]]:
                self.assertEqual(group["requests"], 2)
                for field, coverage in (("input_tokens", "measured_input_requests"), ("output_tokens", "measured_output_requests"), ("total_tokens", "measured_requests")):
                    self.assertIsNone(group[field])
                    self.assertEqual(group[coverage], 0)

    def test_components_have_independent_coverage_and_are_not_inferred(self):
        with tempfile.TemporaryDirectory() as root, patch.object(token_usage, "DATA_DIR", Path(root)):
            client = SimpleNamespace()
            token_usage.record_usage(client, "total-only", "note", SimpleNamespace(total_tokens=9), time.monotonic())
            token_usage.record_usage(client, "components-only", "note", SimpleNamespace(prompt_tokens=5, completion_tokens=2), time.monotonic())
            token_usage.record_usage(client, "unknown", "note", None, time.monotonic(), "failed")
            report = token_usage.usage_report()
            self.assertEqual(report["totals"], {"requests": 3, "measured_requests": 1, "total_tokens": 9,
                "measured_input_requests": 1, "input_tokens": 5, "measured_output_requests": 1, "output_tokens": 2})
            by_model = {group["model"]: group for group in report["models"]}
            self.assertIsNone(by_model["total-only"]["input_tokens"])
            self.assertIsNone(by_model["components-only"]["total_tokens"])
            self.assertEqual(by_model["total-only"]["measured_requests"], 1)
            self.assertEqual(by_model["components-only"]["measured_requests"], 0)

    def test_model_and_day_groups_keep_their_own_coverage_including_failed_usage(self):
        from datetime import datetime, timezone, timedelta
        with tempfile.TemporaryDirectory() as root, patch.object(token_usage, "DATA_DIR", Path(root)):
            token_usage.record_usage(SimpleNamespace(base_url="https://one.invalid"), "one", "note",
                SimpleNamespace(prompt_tokens=20, completion_tokens=5, total_tokens=25), time.monotonic(), "failed")
            token_usage.record_usage(SimpleNamespace(base_url="https://two.invalid"), "two", "note", None, time.monotonic())
            with sqlite3.connect(Path(root) / "token-usage.sqlite3") as db:
                db.execute("UPDATE usage SET at = ? WHERE model = 'one'",
                    ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))
            report = token_usage.usage_report()
            self.assertEqual(report["totals"]["total_tokens"], 25)
            self.assertEqual(report["totals"]["measured_requests"], 1)
            self.assertEqual(report["daily"][0]["total_tokens"], 25)
            self.assertEqual(report["daily"][0]["measured_requests"], 1)
            self.assertIsNone(report["daily"][1]["total_tokens"])
            self.assertEqual(report["daily"][1]["measured_requests"], 0)
            self.assertEqual(report["recent"][1]["status"], "failed")
            self.assertEqual(report["recent"][1]["total_tokens"], 25)

    def test_invalid_reported_counts_remain_unknown(self):
        with tempfile.TemporaryDirectory() as root, patch.object(token_usage, "DATA_DIR", Path(root)):
            token_usage.record_usage(SimpleNamespace(), "invalid", "note",
                SimpleNamespace(prompt_tokens=True, completion_tokens=-1, total_tokens="9"), time.monotonic())
            totals = token_usage.usage_report()["totals"]
            self.assertIsNone(totals["input_tokens"])
            self.assertIsNone(totals["output_tokens"])
            self.assertIsNone(totals["total_tokens"])

    def test_legacy_ledger_bytes_and_recent_records_are_preserved_on_api_read(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.system import system_router
        with tempfile.TemporaryDirectory() as root, patch.object(token_usage, "DATA_DIR", Path(root)):
            db_path = Path(root) / "token-usage.sqlite3"
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE usage (at TEXT, model TEXT, host TEXT, purpose TEXT, status TEXT, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, elapsed_ms INTEGER)")
                db.executemany("INSERT INTO usage VALUES (?,?,?,?,?,?,?,?,?)", [
                    ("2020-01-01T00:00:00+00:00", "old", "fixture.invalid", "note", "success", 8, 1, 9, 1),
                    ("2020-01-02T00:00:00+00:00", "old", "fixture.invalid", "note", "failed", None, None, None, 2)])
            original = db_path.read_bytes()
            app = FastAPI(); app.include_router(system_router)
            with TestClient(app, base_url="http://127.0.0.1") as client:
                response = client.get("/api/model/usage")
            self.assertEqual(response.status_code, 200)
            report = response.json()
            self.assertEqual(report["schema_version"], 2)
            self.assertEqual(report["totals"]["total_tokens"], 9)
            self.assertEqual(report["totals"]["requests"], 2)
            self.assertEqual(report["totals"]["measured_requests"], 1)
            self.assertIsNone(report["recent"][0]["total_tokens"])
            self.assertEqual(report["daily"], [], "Old entries remain in totals, outside the 14-day chart")
            self.assertEqual(db_path.read_bytes(), original, "Report must not migrate, rewrite or relabel exported legacy bytes")

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
