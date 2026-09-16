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
