import hashlib
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.models import TaskOptions
from app.model_connections import connected_api_key
from app.routers import connections


class ModelConnectionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.origin = {"Origin": "http://127.0.0.1:8765"}
        connections._pending.clear()

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
