import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app, require_ready_note_model
from app.models import TaskOptions


class ModelReadinessTests(unittest.TestCase):
    def test_explicit_ai_mode_stops_before_creating_or_scheduling_work(self):
        with patch("app.summarizer._model_key", return_value=""), patch("app.main.create_task") as create, patch("app.main.schedule_processing") as schedule:
            response = TestClient(app).post("/api/tasks/from-current-page", json={
                "page_url": "https://www.bilibili.com/video/BV1ioh56JEFf",
                "options": {"content_mode": "text", "llm_base_url": "https://api.xiaomimimo.com/v1", "llm_model": "mimo-v2.5"},
            })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "model_required")
        create.assert_not_called()
        schedule.assert_not_called()

    def test_caption_and_legacy_modes_remain_available_without_model(self):
        with patch("app.summarizer._model_key", return_value="") as key:
            require_ready_note_model(TaskOptions(content_mode="subtitles"))
            require_ready_note_model(TaskOptions(content_mode="auto"))
            key.assert_not_called()

    def test_known_text_only_model_cannot_start_explicit_visual_work(self):
        with patch("app.summarizer._model_key", return_value="test-key"):
            with self.assertRaises(HTTPException) as raised:
                require_ready_note_model(TaskOptions(content_mode="visual", llm_base_url="https://api.deepseek.com/v1", llm_model="deepseek-chat"))
        self.assertEqual(raised.exception.detail["code"], "visual_model_required")

    def test_health_reports_the_selected_model_capability_for_the_extension(self):
        from app.main import health_payload
        with patch("app.main.selected_connection_status", return_value={"model": {"provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "use_saved_connection": True}, "configured": True}):
            health = health_payload()
        self.assertTrue(health["llm_model_configured"])
        self.assertFalse(health["default_llm_supports_vision"])
        self.assertFalse(health["vision_model_configured"])
