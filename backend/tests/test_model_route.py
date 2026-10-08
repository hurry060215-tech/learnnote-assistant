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

    def test_cached_subtitle_route_is_offline_and_does_not_require_model(self):
        result = plan_route(TaskOptions(content_mode="subtitles"), source_available_offline=True)
        self.assertTrue(result["offline_ready"])
        self.assertEqual(result["routes"][0]["id"], "platform_or_embedded_subtitles")
        self.assertEqual(result["blocking_reasons"], [])

    def test_uncaptured_platform_subtitles_do_not_claim_offline_readiness(self):
        result = plan_route(TaskOptions(content_mode="subtitles"))
        self.assertFalse(result["offline_ready"])
        self.assertFalse(result["offline_source_confirmed"])
        self.assertFalse(result["local_fallback"]["requires_model_key"])

    def test_auto_visual_route_discloses_frames_and_remote_audio(self):
        result = plan_route(TaskOptions(content_mode="auto", transcriber="openai-compatible", llm_base_url="https://fixture.invalid/v1"), model_configured=True, vision_configured=True)
        self.assertIn("remote_asr", [item["id"] for item in result["routes"]])
        self.assertEqual(result["data_leaving_device"], ["audio", "instructions", "selected_frames", "transcript"])
        self.assertFalse(result["offline_ready"])

    def test_local_vision_endpoint_is_not_mislabeled_as_remote(self):
        result = plan_route(TaskOptions(content_mode="visual", llm_base_url="http://127.0.0.1:11434/v1"), local_asr_available=True, model_configured=True, vision_configured=True, source_available_offline=True)
        self.assertTrue(result["offline_ready"])
        self.assertEqual(result["data_leaving_device"], [])
        self.assertEqual(result["routes"][-1]["kind"], "local")
        self.assertIn("gateway", result["readiness_scope"])

    def test_remote_asr_names_match_execution_contract_and_no_secrets_are_returned(self):
        from app.asr_pipeline import REMOTE_ASR_TRANSCRIBERS
        from app.model_route import REMOTE_ASR_NAMES
        self.assertEqual(REMOTE_ASR_NAMES, REMOTE_ASR_TRANSCRIBERS)
        result = plan_route(TaskOptions(llm_api_key="fixture-not-a-real-key", llm_base_url="https://fixture.invalid/private"))
        self.assertNotIn("fixture-not-a-real-key", str(result))
        self.assertNotIn("fixture.invalid", str(result))

    def test_visual_route_explains_missing_local_and_remote_prerequisites(self):
        result = plan_route(TaskOptions(content_mode="visual"), local_asr_available=False, model_configured=False, vision_configured=False)
        self.assertFalse(result["offline_ready"])
        self.assertEqual([item["id"] for item in result["routes"]], ["platform_or_embedded_subtitles", "local_asr", "remote_text_model", "remote_vision_model"])
        self.assertEqual(len(result["blocking_reasons"]), 3)


if __name__ == "__main__":
    unittest.main()
