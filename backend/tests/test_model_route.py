import unittest

from app.model_route import plan_route
from app.models import TaskOptions


class ModelRouteTests(unittest.TestCase):
    def test_remote_text_route_is_not_described_as_offline(self):
        result = plan_route(TaskOptions(content_mode="text", llm_base_url="https://api.example.com/v1"), local_asr_available=True, model_configured=True)
        self.assertFalse(result["offline_ready"])

    def test_settings_route_uses_saved_connection(self):
        from unittest.mock import patch
        from app.routers.system import api_model_route
        with patch("app.model_connections.selected_connection_status", return_value={"configured":True,"model":{"base_url":"https://api.xiaomimimo.com/v1","model":"mimo-v2.5"}}):
            result = api_model_route()
        self.assertTrue(next(r for r in result["routes"] if r["id"] == "remote_text_model")["ready"])

    def test_subtitle_route_is_offline_and_does_not_require_model(self):
        result = plan_route(TaskOptions(content_mode="subtitles"))
        self.assertTrue(result["offline_ready"])
        self.assertEqual(result["routes"][0]["id"], "platform_or_embedded_subtitles")
        self.assertEqual(result["blocking_reasons"], [])

    def test_visual_route_explains_missing_local_and_remote_prerequisites(self):
        result = plan_route(TaskOptions(content_mode="visual"), local_asr_available=False, model_configured=False, vision_configured=False)
        self.assertFalse(result["offline_ready"])
        self.assertEqual([item["id"] for item in result["routes"]], ["platform_or_embedded_subtitles", "local_asr", "remote_vision_model"])
        self.assertEqual(len(result["blocking_reasons"]), 2)


if __name__ == "__main__":
    unittest.main()
