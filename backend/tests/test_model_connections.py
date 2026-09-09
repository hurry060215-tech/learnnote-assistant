import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.models import TaskOptions
from app.model_connections import connected_api_key
from app import model_connections as saved_models
from app.routers import connections


class ModelConnectionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.origin = {"Origin": "http://127.0.0.1:8765"}
        connections._pending.clear()
        self.storage_patch = patch.object(saved_models, "connection_storage", return_value="session")
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)

    def test_pkce_callback_binds_browser_and_returns_no_secret(self):
        result = self.client.post("/api/connections/openrouter/start", headers=self.origin)
        self.assertEqual(result.status_code, 200)
        params = parse_qs(urlsplit(result.json()["authorization_url"]).query)
        self.assertEqual(params["code_challenge_method"], ["S256"])
        callback = params["callback_url"][0]
        self.assertIn("HttpOnly", result.headers["set-cookie"])
        fake = Mock()
        fake.json.return_value = {"key": "secret-test-not-real"}
        with patch.object(connections.requests, "post", return_value=fake) as post, patch.object(connections, "save_connection") as save:
            response = self.client.get(callback + "&code=one-time-code", follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertTrue(response.headers["location"].endswith("connection=connected"))
            self.assertNotIn("secret-test", response.text + str(response.headers))
            save.assert_called_once_with("secret-test-not-real")
            self.assertEqual(post.call_args.kwargs["json"]["code_challenge_method"], "S256")
            self.assertFalse(post.call_args.kwargs["allow_redirects"])
            again = self.client.get(callback + "&code=one-time-code", follow_redirects=False)
            self.assertTrue(again.headers["location"].endswith("connection=failed"))
            self.assertEqual(post.call_count, 1)

    def test_external_origin_and_missing_browser_cookie_are_rejected(self):
        denied = self.client.post("/api/connections/openrouter/start", headers={"Origin": "https://evil.example"})
        self.assertEqual(denied.status_code, 403)
        started = self.client.post("/api/connections/openrouter/start", headers=self.origin).json()
        callback = parse_qs(urlsplit(started["authorization_url"]).query)["callback_url"][0]
        self.client.cookies.clear()
        with patch.object(connections.requests, "post") as post:
            self.client.get(callback + "&code=untrusted", follow_redirects=False)
            post.assert_not_called()

    def test_connection_key_cannot_be_used_for_another_endpoint(self):
        with patch("app.model_connections.read_connection", return_value="bound-secret") as read:
            self.assertEqual(connected_api_key(TaskOptions(llm_base_url="https://openrouter.ai/api/v1", use_saved_connection=True)), "bound-secret")
            for endpoint in ["https://evil.example/api/v1", "https://openrouter.ai/other", "http://127.0.0.1:1234/v1"]:
                self.assertEqual(connected_api_key(TaskOptions(llm_base_url=endpoint, use_saved_connection=True)), "")
            self.assertEqual(read.call_count, 1)


class SelectedModelPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = {}
        self.patches = [
            patch.object(saved_models, "DATA_DIR", self.root),
            patch.object(saved_models, "PUBLIC_DEPLOYMENT", False),
            patch.object(saved_models, "connection_storage", return_value="system"),
            patch("desktop.credentials.write_secret", side_effect=lambda name, key: self.vault.__setitem__(name, key)),
            patch("desktop.credentials.read_secret", side_effect=lambda name: self.vault.get(name, "")),
            patch("desktop.credentials.delete_secret", side_effect=lambda name: self.vault.pop(name, None)),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        saved_models._selected_sessions.clear()
        self.addCleanup(saved_models._selected_sessions.clear)
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.origin = {"Origin": "http://127.0.0.1:8765"}
        self.selection = {"provider": "xiaomi", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-test", "api_key": "test-secret-not-real"}

    def save(self, **overrides):
        result = self.client.put("/api/model/connection", json={**self.selection, **overrides}, headers=self.origin)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotIn("test-secret", result.text)
        return result.json()

    def test_saved_connection_survives_page_and_process_restart_without_plaintext_key(self):
        result = self.save()
        self.assertTrue(result["configured"])
        self.assertEqual(result["storage"], "system")
        text = (self.root / "model-connection.json").read_text(encoding="utf-8")
        self.assertNotIn("test-secret", text)
        self.assertNotIn("api_key", text)
        saved_models._selected_sessions.clear()  # Simulate another service process.
        response = self.client.get("/api/model/connection").json()
        self.assertEqual(response["model"]["provider"], "xiaomi")
        self.assertTrue(response["configured"])
        options = saved_models.resolve_model_options(TaskOptions())
        self.assertEqual(options.llm_base_url, self.selection["base_url"])
        self.assertEqual(options.llm_model, "mimo-test")
        self.assertIsNone(options.llm_api_key)
        self.assertTrue(options.use_saved_connection)
        self.assertEqual(connected_api_key(options), "test-secret-not-real")

    def test_health_and_deferred_extension_snapshot_selected_provider(self):
        from app import main
        from app.models import CurrentPageTaskRequest, TaskRecord
        from fastapi import BackgroundTasks
        self.save()
        health = self.client.get("/health").json()
        self.assertEqual(health["default_llm_model"], "mimo-test")
        self.assertTrue(health["llm_model_configured"])
        self.assertTrue(health["default_use_saved_connection"])
        fake = TaskRecord(id="123456789abc", source_type="current_page", title="lesson", mode="video", created_at="2026-09-09T00:00:00Z", updated_at="2026-09-09T00:00:00Z")
        request = CurrentPageTaskRequest(page_url="https://www.bilibili.com/video/BV1xx411c7mD", title="lesson")
        with patch.object(main, "create_task", return_value=fake) as create, patch.object(main, "update_task", return_value=fake), patch.object(main, "schedule_processing") as schedule:
            main.create_from_current_page(request, BackgroundTasks())
        options = create.call_args.kwargs["options"]
        self.assertEqual(options.llm_base_url, self.selection["base_url"])
        self.assertIsNone(options.llm_api_key)
        self.assertEqual(schedule.call_args.args[-1].options.llm_model, "mimo-test")

    def test_endpoint_path_and_data_directory_binding_and_clear_active_only(self):
        self.save()
        first = saved_models.resolve_model_options(TaskOptions())
        self.save(provider="deepseek", base_url="https://api.deepseek.com/v1", model="deepseek-chat", api_key="test-secret-second")
        second = saved_models.resolve_model_options(TaskOptions())
        self.assertEqual(connected_api_key(first), "test-secret-not-real")
        self.assertEqual(connected_api_key(second), "test-secret-second")
        wrong = first.model_copy(update={"llm_base_url": self.selection["base_url"] + "/other"})
        self.assertEqual(connected_api_key(wrong), "")
        with patch.object(saved_models, "DATA_DIR", self.root / "other-library"):
            self.assertEqual(connected_api_key(first), "")
        self.assertEqual(self.client.delete("/api/model/connection", headers=self.origin).status_code, 200)
        self.assertEqual(connected_api_key(second), "")
        self.assertEqual(connected_api_key(first), "test-secret-not-real")

    def test_secure_store_failure_is_explicit_session_only_and_never_plaintext(self):
        with patch("desktop.credentials.write_secret", side_effect=OSError("not available")):
            result = self.save()
        self.assertEqual(result["storage"], "session")
        self.assertIn("重启", result["message"])
        self.assertTrue(result["configured"])
        saved_models._selected_sessions.clear()
        result = self.client.get("/api/model/connection").json()
        self.assertFalse(result["configured"])
        self.assertEqual(result["model"]["model"], "mimo-test")
        self.assertNotIn("test-secret", (self.root / "model-connection.json").read_text(encoding="utf-8"))

    def test_explicit_request_endpoint_and_key_are_not_overridden(self):
        self.save()
        request = TaskOptions(llm_base_url="https://api.openai.com/v1", llm_model="explicit-model", llm_api_key="explicit-key")
        self.assertIs(saved_models.resolve_model_options(request), request)
        with patch("app.summarizer.LLM_API_KEY", "default-secret"), patch("app.summarizer.LLM_BASE_URL", "https://api.openai.com/v1"):
            from app.summarizer import _model_key
            self.assertEqual(_model_key(TaskOptions(llm_base_url="https://other.example/v1")), "")
            self.assertEqual(_model_key(TaskOptions(llm_base_url="http://127.0.0.1:1234/v1")), "local-no-key")
            self.assertEqual(_model_key(TaskOptions(llm_base_url="https://api.openai.com/v1")), "default-secret")

    def test_failed_metadata_save_restores_previous_key_and_selection(self):
        self.save()
        previous_metadata = (self.root / "model-connection.json").read_text(encoding="utf-8")
        with patch("app.storage.atomic_write_text", side_effect=OSError("read only")):
            result = self.client.put("/api/model/connection", json={**self.selection, "model": "new-model", "api_key": "replacement-test-key"}, headers=self.origin)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("replacement-test-key", result.text)
        self.assertEqual((self.root / "model-connection.json").read_text(encoding="utf-8"), previous_metadata)
        self.assertEqual(connected_api_key(saved_models.resolve_model_options(TaskOptions())), "test-secret-not-real")
        saved_models._selected_sessions.clear()
        self.assertEqual(connected_api_key(saved_models.resolve_model_options(TaskOptions())), "test-secret-not-real")

    def test_failed_first_save_does_not_leave_a_usable_key(self):
        with patch("app.storage.atomic_write_text", side_effect=OSError("read only")):
            result = self.client.put("/api/model/connection", json=self.selection, headers=self.origin)
        self.assertEqual(result.status_code, 503)
        self.assertFalse(self.vault)
        self.assertFalse(saved_models._selected_sessions)
        self.assertFalse((self.root / "model-connection.json").exists())

    def test_removing_key_does_not_revive_it_after_provider_switch(self):
        self.save()
        original = saved_models.resolve_model_options(TaskOptions())
        self.save(api_key="", use_saved_connection=False)
        self.save(provider="deepseek", base_url="https://api.deepseek.com/v1", model="deepseek-chat", api_key="test-secret-second")
        saved_models._selected_sessions.clear()
        self.assertEqual(connected_api_key(original), "")

    def test_session_replacement_does_not_revive_previous_system_key(self):
        self.save()
        original = saved_models.resolve_model_options(TaskOptions())
        with patch("desktop.credentials.write_secret", side_effect=OSError("unavailable")):
            self.assertEqual(self.save(api_key="replacement-test-key")["storage"], "session")
        self.assertEqual(connected_api_key(original), "replacement-test-key")
        self.save(provider="deepseek", base_url="https://api.deepseek.com/v1", model="deepseek-chat", api_key="test-secret-second")
        saved_models._selected_sessions.clear()
        self.assertEqual(connected_api_key(original), "")

    def test_vault_errors_are_safe_and_clear_does_not_disable_explicit_environment(self):
        with patch("desktop.credentials.read_secret", side_effect=RuntimeError("private-vault-diagnostic")):
            result = self.client.put("/api/model/connection", json=self.selection, headers=self.origin)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private-vault-diagnostic", result.text)
        self.save()
        self.client.delete("/api/model/connection", headers=self.origin)
        with patch("app.summarizer.LLM_API_KEY", "environment-test-key"), patch("app.summarizer.LLM_BASE_URL", "https://api.openai.com/v1"):
            from app.summarizer import _model_key
            self.assertEqual(_model_key(saved_models.resolve_model_options(TaskOptions())), "environment-test-key")

    def test_writes_require_same_origin_and_public_mode_cannot_expose_saved_connection(self):
        self.save()
        self.assertEqual(self.client.delete("/api/model/connection").status_code, 403)
        self.assertEqual(self.client.put("/api/model/connection", json=self.selection).status_code, 403)
        with patch.object(connections, "PUBLIC_DEPLOYMENT", True), patch.object(saved_models, "PUBLIC_DEPLOYMENT", True):
            self.assertEqual(self.client.get("/api/model/connection").status_code, 403)
            self.assertEqual(self.client.put("/api/model/connection", json=self.selection, headers=self.origin).status_code, 403)
            self.assertEqual(self.client.delete("/api/model/connection", headers=self.origin).status_code, 403)
            self.assertIsNone(saved_models.selected_connection_status()["model"])
            self.assertEqual(connected_api_key(TaskOptions(llm_base_url=self.selection["base_url"], use_saved_connection=True)), "")

    def test_save_requires_local_origin_and_rejects_embedded_credentials(self):
        response = self.client.put("/api/model/connection", json=self.selection, headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        for endpoint in ["https://user:pass@example.com/v1", "https://api.openai.com/v1?api_key=bad", "http://remote.example/v1"]:
            response = self.client.put("/api/model/connection", json={**self.selection, "base_url": endpoint}, headers=self.origin)
            self.assertEqual(response.status_code, 422)

    def test_local_no_key_and_existing_openrouter_authorization_are_supported(self):
        self.save(provider="local", base_url="http://127.0.0.1:1234/v1", model="local-model", api_key="")
        result = self.client.get("/api/model/connection").json()
        self.assertTrue(result["configured"])
        self.assertFalse(result["model"]["use_saved_connection"])
        with patch.object(saved_models, "read_connection", return_value="oauth-test-secret"):
            self.save(provider="openrouter", base_url=saved_models.OPENROUTER_BASE, model="openrouter/auto", api_key="", use_saved_connection=True)
            self.assertEqual(connected_api_key(saved_models.resolve_model_options(TaskOptions())), "oauth-test-secret")
