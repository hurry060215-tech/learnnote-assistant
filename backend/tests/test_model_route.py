import unittest
from unittest.mock import Mock, patch
import sys
import types
import tempfile
from pathlib import Path

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

    def test_selected_missing_key_does_not_borrow_default_environment_readiness(self):
        from app.routers.system import api_model_route
        from app.summarizer import _model_key
        selected = {"configured": False, "model": {"base_url": "https://selected.invalid/v1", "model": "synthetic", "use_saved_connection": True}}
        with patch("app.model_connections.selected_connection_status", return_value=selected), \
             patch("app.config.LLM_API_KEY", "synthetic-default-key"), \
             patch("app.config.LLM_BASE_URL", "https://default.invalid/v1"), \
             patch("app.summarizer.LLM_API_KEY", "synthetic-default-key"), \
             patch("app.summarizer.LLM_BASE_URL", "https://default.invalid/v1"), \
             patch("app.summarizer.connected_api_key", return_value=""), \
             patch("app.local_models.model_status", return_value={"status": "not_downloaded"}):
            result = api_model_route(content_mode="text")
            self.assertFalse(_model_key(TaskOptions(llm_base_url="https://selected.invalid/v1", use_saved_connection=True)))
        self.assertFalse(next(route["ready"] for route in result["routes"] if route["id"] == "remote_text_model"))
        self.assertEqual(result["capability_catalog"]["text"]["status"], "not_configured")
        self.assertNotIn("synthetic-default-key", str(result))

    def test_default_loopback_configuration_is_ready_without_a_key_or_probe(self):
        from app.routers.system import api_model_route
        factory = Mock(side_effect=AssertionError("Readiness must not construct a provider client"))
        with patch("app.model_connections.selected_connection_status", return_value={"model": None, "configured": False}), \
             patch("app.config.LLM_BASE_URL", "http://127.0.0.1:11434/v1"), \
             patch("app.summarizer.LLM_BASE_URL", "http://127.0.0.1:11434/v1"), \
             patch("app.summarizer.LLM_API_KEY", ""), \
             patch("app.local_models.model_status", return_value={"status": "not_downloaded"}), \
             patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}):
            result = api_model_route(content_mode="text")
        factory.assert_not_called()
        self.assertTrue(next(route["ready"] for route in result["routes"] if route["id"] == "remote_text_model"))
        self.assertFalse(result["offline_ready"], "A local gateway does not establish that the source is cached")

    def test_keyless_loopback_text_does_not_claim_compatible_audio_readiness(self):
        from app.routers.system import api_model_route
        from app.transcriber import transcribe_audio_openai_compatible
        selected = {"configured": True, "model": {"base_url": "http://127.0.0.1:11434/v1", "model": "fixture", "use_saved_connection": False}}
        factory = Mock(side_effect=AssertionError("A keyless audio route must not probe even loopback"))
        with patch("app.model_connections.selected_connection_status", return_value=selected), \
             patch("app.config.LLM_API_KEY", ""), patch("app.transcriber.LLM_API_KEY", ""), \
             patch("app.local_models.model_status", return_value={"status": "not_downloaded"}), \
             patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}):
            result = api_model_route(content_mode="text", transcriber="groq")
            actual = transcribe_audio_openai_compatible(Path("synthetic-never-opened.wav"),
                TaskOptions(transcriber="groq", llm_base_url=selected["model"]["base_url"]))
        routes = {item["id"]: item for item in result["routes"]}
        self.assertTrue(routes["remote_text_model"]["ready"])
        self.assertEqual(routes["remote_asr"]["kind"], "local")
        self.assertFalse(routes["remote_asr"]["ready"])
        self.assertEqual(result["capability_catalog"]["asr"]["status"], "not_configured")
        self.assertTrue(actual.source.endswith("missing-key"))
        factory.assert_not_called()

    def test_asr_readiness_reuses_execution_helper_with_the_selected_endpoint_snapshot(self):
        from app.routers.system import api_model_route
        for saved, key in ((False, ""), (True, ""), (True, "fixture-not-returned")):
            selected = {"model": {"base_url": "https://selected.invalid/v1", "model": "fixture", "use_saved_connection": saved}, "configured": True}
            with self.subTest(saved=saved, configured=bool(key)), \
                 patch("app.model_connections.selected_connection_status", return_value=selected), \
                 patch("app.local_models.model_status", return_value={"status": "not_downloaded"}), \
                 patch("app.transcriber.remote_asr_api_key", return_value=key) as key_lookup:
                result = api_model_route(content_mode="text", transcriber="groq")
                actual = key_lookup.call_args.args[0]
                self.assertEqual(actual.llm_base_url, selected["model"]["base_url"])
                self.assertEqual(actual.use_saved_connection, saved)
                self.assertEqual(next(route["ready"] for route in result["routes"] if route["id"] == "remote_asr"), bool(key))
                self.assertNotIn("fixture-not-returned", str(result))

    def test_all_compatible_audio_modes_use_the_text_endpoint_without_redirecting_to_groq(self):
        from app.model_route import REMOTE_ASR_NAMES
        from app.transcriber import transcribe_audio_openai_compatible
        client = types.SimpleNamespace(audio=types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=Mock(
            return_value={"text": "Synthetic audio transcript", "segments": [{"start": 0, "end": 1, "text": "Synthetic audio transcript"}]}))))
        factory = Mock(return_value=client)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}):
            audio = Path(directory) / "synthetic.wav"
            audio.write_bytes(b"synthetic fixture, never decoded")
            for mode in sorted(REMOTE_ASR_NAMES):
                with self.subTest(mode=mode):
                    factory.reset_mock()
                    result = transcribe_audio_openai_compatible(audio, TaskOptions(transcriber=mode, whisper_model="fixture-asr",
                        llm_base_url="https://selected-text.invalid/v1", llm_api_key="synthetic-explicit-key"))
                    self.assertEqual(result.full_text, "Synthetic audio transcript")
                    self.assertEqual(factory.call_count, 1)
                    self.assertEqual(factory.call_args.kwargs["base_url"], "https://selected-text.invalid/v1")
                    self.assertEqual(factory.call_args.kwargs["api_key"], "synthetic-explicit-key")

    def test_no_key_readiness_has_no_provider_calls_or_downloads_in_all_modes(self):
        from app.routers.system import api_model_route
        factory = Mock(side_effect=AssertionError("Unexpected remote probe"))
        selected = {"configured": False, "model": {"base_url": "https://fixture.invalid/v1", "model": "fixture"}}
        with patch("app.model_connections.selected_connection_status", return_value=selected), \
             patch("app.transcriber.LLM_API_KEY", ""), \
             patch("app.local_models.model_status", return_value={"status": "not_downloaded"}), \
             patch("app.local_models.prepare_model") as download, \
             patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}):
            for mode in ("auto", "subtitles", "text", "visual"):
                for transcriber in ("faster-whisper", "openai-compatible", "groq"):
                    with self.subTest(mode=mode, transcriber=transcriber):
                        result = api_model_route(content_mode=mode, transcriber=transcriber)
                        self.assertFalse(result["local_fallback"]["requires_model_key"])
                        self.assertEqual(result["local_fallback"]["content_mode"], "subtitles")
                        self.assertEqual(result["estimates"]["uncertainty"], "unmeasured")
                        self.assertIsNone(result["estimates"]["cost_range"])
                        self.assertIsNone(result["estimates"]["duration_seconds_range"])
        factory.assert_not_called()
        download.assert_not_called()

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
