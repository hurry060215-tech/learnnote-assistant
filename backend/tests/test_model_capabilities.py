import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import model_capabilities as caps
from app.summarizer import llm_model_supports_vision


class ModelCapabilityTests(unittest.TestCase):
    def test_deepseek_capabilities_are_per_model_not_per_provider(self):
        for model in ["deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"]:
            self.assertTrue(llm_model_supports_vision("https://api.deepseek.com", model))
        self.assertFalse(llm_model_supports_vision("https://api.deepseek.com", "deepseek-chat"))
        self.assertIsNone(caps.model_description("deepseek","https://api.deepseek.com","deepseek-v4-pro")["vision"])

    def test_successful_probe_is_scoped_and_expires(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(caps,"DATA_DIR",Path(directory)), patch.object(caps.time,"time",return_value=1000000):
            caps.save_image_probe("https://api.deepseek.com","custom")
            self.assertTrue(caps.image_probe_verified("https://api.deepseek.com","custom"))
            self.assertFalse(caps.image_probe_verified("https://another.example","custom"))
            self.assertFalse(caps.image_probe_verified("https://api.deepseek.com","other"))
            self.assertTrue(llm_model_supports_vision("https://api.deepseek.com","custom"))
            with patch.object(caps.time,"time",return_value=1000000+8*86400):
                self.assertFalse(caps.image_probe_verified("https://api.deepseek.com","custom"))

    def test_catalog_separates_configuration_vision_asr_and_unknown_limits(self):
        with patch.object(caps, "image_probe_verified", return_value=False):
            catalog = caps.route_capabilities("openai-compatible", "https://fixture.invalid/v1", "fixture",
                configured=True, vision_allowed=True, remote_asr=True, local_asr_available=False)
        self.assertEqual(catalog["text"]["status"], "configured")
        self.assertEqual(catalog["vision"]["status"], "unknown")
        self.assertEqual(catalog["asr"]["status"], "unverified")
        for key in ("context_limit", "image_limit"):
            self.assertEqual(catalog[key]["status"], "unknown")
            self.assertIsNone(catalog[key]["value"])
            self.assertTrue(catalog[key]["detail"])

    def test_catalog_revision_is_independent_of_task_and_route_schema(self):
        from app.models import TaskOptions
        from app.model_route import plan_route, ROUTE_SCHEMA_VERSION
        schema = TaskOptions.model_json_schema()
        with patch.object(caps, "CAPABILITY_CATALOG_VERSION", 42), patch.object(caps, "image_probe_verified", return_value=False):
            catalog = caps.route_capabilities("deepseek", "https://api.deepseek.com", "deepseek-flash",
                configured=True, vision_allowed=True, remote_asr=False, local_asr_available=True)
            result = plan_route(capability_catalog=catalog)
            self.assertEqual(caps.model_description("deepseek", "https://api.deepseek.com", "deepseek-flash")["catalog_version"], 42)
        self.assertEqual(catalog["schema_version"], caps.CAPABILITY_SCHEMA_VERSION)
        self.assertEqual(catalog["vision"]["status"], "declared")
        self.assertEqual(catalog["asr"]["status"], "files_ready")
        self.assertEqual(result["schema_version"], ROUTE_SCHEMA_VERSION)
        self.assertEqual(result["capability_catalog"]["catalog_version"], 42)
        self.assertEqual(TaskOptions.model_json_schema(), schema)

    def test_catalog_reports_runtime_exclusions_and_explicit_image_verification(self):
        for verified, allowed, expected in ((False, False, "unsupported"), (True, True, "verified")):
            with self.subTest(expected=expected), patch.object(caps, "image_probe_verified", return_value=verified):
                catalog = caps.route_capabilities("deepseek", "https://api.deepseek.com", "deepseek-chat",
                    configured=False, vision_allowed=allowed, remote_asr=False, local_asr_available=False)
                self.assertEqual(catalog["vision"]["status"], expected)
                self.assertEqual(catalog["text"]["status"], "not_configured")
                self.assertEqual(catalog["asr"]["status"], "not_ready")
