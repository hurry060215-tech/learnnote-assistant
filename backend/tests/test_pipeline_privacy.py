from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app


class PipelinePrivacyTests(unittest.TestCase):
    def read(self, diagnostics):
        task = SimpleNamespace(id="fixture", status="failed", phase="summary", progress=85,
                               checkpoint="transcript_ready", summary_diagnostics=diagnostics)
        with patch("app.main.get_task", return_value=task), patch("app.main.task_artifact_status", return_value={}):
            response = TestClient(app).get("/api/tasks/fixture/pipeline-status")
        self.assertEqual(response.status_code, 200)
        return response.json()["privacy"]

    def test_local_configuration_error_is_not_reported_as_a_remote_call(self):
        privacy = self.read({"llm_event_count": 1, "llm_events": [{"stage": "configuration", "code": "missing_api_key"}]})
        self.assertIsNone(privacy["remote_calls"])
        self.assertFalse(privacy["remote_call_count_available"])
        self.assertEqual(privacy["diagnostic_event_count"], 1)

    def test_provider_and_cache_events_do_not_assert_task_is_local_only(self):
        for code in ("ok", "cache_hit", "request_failed"):
            with self.subTest(code=code):
                privacy = self.read({"llm_event_count": 2, "llm_events": [{"stage": "summary", "code": code}]})
                self.assertIsNone(privacy["local_only"])
                self.assertIsNone(privacy["remote_calls"])

    def test_missing_or_malformed_legacy_diagnostics_remain_unknown(self):
        for diagnostics in ({}, None, {"llm_event_count": "broken"}, {"llm_event_count": -1}, {"llm_event_count": True}):
            with self.subTest(diagnostics=diagnostics):
                privacy = self.read(diagnostics)
                self.assertIsNone(privacy["diagnostic_event_count"])
                self.assertIsNone(privacy["remote_calls"])
