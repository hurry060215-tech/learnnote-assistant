import unittest

from app.model_route import plan_route
from app.models import TaskOptions


class ModelRouteTests(unittest.TestCase):
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
