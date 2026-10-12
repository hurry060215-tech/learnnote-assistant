"""Synthetic endpoint-scope regressions: no real credentials, SDK or network."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from app.models import TaskOptions
from app.transcriber import remote_asr_api_key, transcribe_audio_openai_compatible


DEFAULT_BASE = "https://default.invalid/v1"
DEFAULT_KEY = "SYNTHETIC_DEFAULT_ASR_KEY_ONLY"


class AsrCredentialBindingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("app.transcriber.LLM_API_KEY", DEFAULT_KEY))
        self.stack.enter_context(patch("app.transcriber.LLM_BASE_URL", DEFAULT_BASE))
        # Exercise the real saved-key endpoint matcher without reading a store.
        self.stack.enter_context(patch("app.model_connections._read_selected", return_value=None))
        self.stack.enter_context(patch("app.model_connections.connection_storage", return_value="session"))
        self.stack.enter_context(patch("app.model_connections.read_connection", return_value=""))
        self.stack.enter_context(patch.dict("app.model_connections._selected_sessions", {}, clear=True))

    def test_default_credential_requires_exact_endpoint_and_unsaved_selection(self):
        for endpoint in (None, DEFAULT_BASE, DEFAULT_BASE + "/"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(remote_asr_api_key(TaskOptions(llm_base_url=endpoint)), DEFAULT_KEY)
        for endpoint in ("https://custom.invalid/v1", "https://default.invalid/v2", "https://default.invalid.attacker.test/v1",
                         "http://127.0.0.1:11434/v1", "http://localhost:11434/v1", "http://[::1]:11434/v1"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(remote_asr_api_key(TaskOptions(llm_base_url=endpoint)), "")
        self.assertEqual(remote_asr_api_key(TaskOptions(llm_base_url=DEFAULT_BASE, use_saved_connection=True)), "")

    def test_explicit_keys_and_endpoint_bound_saved_keys_keep_their_selection(self):
        for endpoint in ("https://custom.invalid/v1", "http://127.0.0.1:11434/v1"):
            with self.subTest(endpoint=endpoint), patch("app.transcriber.connected_api_key") as lookup:
                self.assertEqual(remote_asr_api_key(TaskOptions(llm_base_url=endpoint, llm_api_key="SYNTHETIC_EXPLICIT")), "SYNTHETIC_EXPLICIT")
                lookup.assert_not_called()
        with patch("app.model_connections._read_selected", return_value={"base_url": "https://saved.invalid/v1"}), \
             patch("app.model_connections._selected_key", return_value="SYNTHETIC_SAVED") as saved:
            self.assertEqual(remote_asr_api_key(TaskOptions(llm_base_url="https://saved.invalid/v1/", use_saved_connection=True)), "SYNTHETIC_SAVED")
            saved.assert_called_once()
            saved.reset_mock()
            for endpoint in ("https://other.invalid/v1", "https://saved.invalid/v2", DEFAULT_BASE):
                self.assertEqual(remote_asr_api_key(TaskOptions(llm_base_url=endpoint, use_saved_connection=True)), "")
            saved.assert_not_called()

    def test_matching_default_and_explicit_keys_reach_only_the_selected_fake_client(self):
        client = types.SimpleNamespace(audio=types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=Mock(return_value={"text": "Synthetic transcript"}))))
        factory = Mock(return_value=client)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}):
            audio = Path(directory) / "fixture.wav"
            audio.write_bytes(b"Synthetic audio, never decoded")
            for endpoint, explicit, expected in ((DEFAULT_BASE, "", DEFAULT_KEY), ("https://custom.invalid/v1", "SYNTHETIC_EXPLICIT", "SYNTHETIC_EXPLICIT")):
                factory.reset_mock()
                result = transcribe_audio_openai_compatible(audio, TaskOptions(transcriber="groq", llm_base_url=endpoint, llm_api_key=explicit))
                self.assertEqual(result.full_text, "Synthetic transcript")
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(factory.call_args.kwargs["base_url"], endpoint)
                self.assertEqual(factory.call_args.kwargs["api_key"], expected)

    def test_missing_and_keyless_loopback_do_not_construct_a_client_or_open_audio(self):
        factory = Mock(side_effect=AssertionError("Unexpected provider construction"))
        with patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}), patch.object(Path, "open", side_effect=AssertionError("Unexpected audio read")):
            for endpoint in ("https://custom.invalid/v1", "http://127.0.0.1:11434/v1"):
                result = transcribe_audio_openai_compatible(Path("never-opened.wav"), TaskOptions(transcriber="groq", llm_base_url=endpoint))
                self.assertTrue(result.source.endswith("missing-key"))
                self.assertNotIn(DEFAULT_KEY, result.model_dump_json())
            with patch("app.transcriber.LLM_API_KEY", ""):
                result = transcribe_audio_openai_compatible(Path("never-opened.wav"), TaskOptions(llm_base_url=DEFAULT_BASE))
                self.assertTrue(result.source.endswith("missing-key"))
        factory.assert_not_called()

    def test_provider_errors_redact_the_exact_selected_key_and_keep_retry_count(self):
        for source in ("default", "explicit", "saved"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                options = TaskOptions(llm_base_url=DEFAULT_BASE)
                key = DEFAULT_KEY
                if source == "explicit":
                    key = "opaqueFixtureCredentialWithoutKnownPrefix123"
                    options = TaskOptions(llm_base_url="https://custom.invalid/v1", llm_api_key=key)
                elif source == "saved":
                    key = "savedOpaqueFixtureCredential456"
                    options = TaskOptions(llm_base_url="https://saved.invalid/v1", use_saved_connection=True)
                    stack.enter_context(patch("app.model_connections._read_selected", return_value={"base_url": options.llm_base_url}))
                    stack.enter_context(patch("app.model_connections._selected_key", return_value=key))
                create = Mock(side_effect=RuntimeError(f"Provider echoed credential {key} verbatim. " + "x" * 500))
                client = types.SimpleNamespace(audio=types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=create)))
                stack.enter_context(patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=Mock(return_value=client))}))
                audio = Path(directory) / "fixture.wav"
                audio.write_bytes(b"Synthetic audio, never decoded")
                log = io.StringIO()
                with redirect_stdout(log), redirect_stderr(log):
                    result = transcribe_audio_openai_compatible(audio, options)
                self.assertEqual(create.call_count, 3, "Keep the existing ASR response-format fallback count")
                self.assertTrue(result.source.endswith("error"))
                self.assertNotIn(key, result.model_dump_json() + log.getvalue())
                self.assertIn("<redacted>", result.warning)
                self.assertLess(len(result.warning), 500)

    def test_real_auto_task_snapshot_cannot_reuse_default_key_for_custom_asr(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.storage import get_task
        factory = Mock(side_effect=AssertionError("Auto mode must not send the default key to a custom endpoint"))
        log = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
             patch("app.storage.TASK_DIR", Path(directory) / "tasks"), patch("app.storage.ensure_dirs"), \
             patch("app.main.schedule_processing") as schedule, \
             patch("app.model_connections.selected_connection_status", return_value={"model": None, "configured": False}), \
             patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}), \
             redirect_stdout(log), redirect_stderr(log):
            response = TestClient(app).post("/api/tasks/from-current-page", json={
                "page_url": "https://source.invalid/lesson", "title": "Synthetic lesson", "options": {
                    "content_mode": "auto", "transcriber": "groq", "llm_base_url": "https://custom.invalid/v1", "use_saved_connection": False}})
            self.assertEqual(response.status_code, 200, response.text)
            actual = schedule.call_args.args[3].options
            stored = get_task(response.json()["task_id"])
            self.assertEqual(actual.llm_base_url, "https://custom.invalid/v1")
            self.assertEqual(stored.options.llm_base_url, actual.llm_base_url)
            self.assertFalse(actual.use_saved_connection)
            self.assertFalse(stored.options.use_saved_connection)
            result = transcribe_audio_openai_compatible(Path(directory) / "never-opened.wav", actual)
            self.assertTrue(result.source.endswith("missing-key"))
            serialized = response.text + stored.model_dump_json() + result.model_dump_json() + log.getvalue()
            self.assertNotIn(DEFAULT_KEY, serialized)
            self.assertIsNone(stored.options.llm_api_key)
        factory.assert_not_called()
