from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.routers.system import ModelSetupCheckRequest, _validated_model_endpoint, check_model_setup


class _FakeMessage:
    content = "OK"


class _FakeChoice:
    message = _FakeMessage()


class _FakeChatResponse:
    choices = [_FakeChoice()]


class _FakeModel:
    def __init__(self, model_id: str) -> None:
        self.id = model_id


class _FakeModelsResponse:
    data = [_FakeModel("model-b"), _FakeModel("model-a"), _FakeModel("bad model id")]


class _FakeCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return _FakeChatResponse()


class _FakeModels:
    def list(self):
        return _FakeModelsResponse()


class _FakeOpenAI:
    def __init__(self, **kwargs) -> None:
        self.options = kwargs
        self.chat = types.SimpleNamespace(completions=_FakeCompletions())
        self.models = _FakeModels()


class ModelSetupTests(unittest.TestCase):
    def test_endpoint_allowlist_accepts_builtin_and_local_hosts(self):
        self.assertEqual(_validated_model_endpoint("https://api.openai.com/v1")[:2], ("https://api.openai.com/v1", "api.openai.com"))
        self.assertEqual(_validated_model_endpoint("http://127.0.0.1:11434/v1")[1:], ("127.0.0.1", True))

    def test_endpoint_allowlist_blocks_ssrf_and_url_credentials(self):
        for value in (
            "http://169.254.169.254/latest/meta-data",
            "https://example.com/v1",
            "https://user:pass@api.openai.com/v1",
            "https://api.openai.com/v1?token=secret",
        ):
            with self.subTest(value=value), self.assertRaises(HTTPException):
                _validated_model_endpoint(value)

    def test_missing_remote_key_returns_actionable_result_without_network(self):
        result = check_model_setup(ModelSetupCheckRequest(
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-test",
            api_key="",
        ))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "missing_api_key")

    def test_short_chat_validates_model_without_returning_key(self):
        fake_module = types.SimpleNamespace(OpenAI=_FakeOpenAI)
        with patch.dict(sys.modules, {"openai": fake_module}):
            result = check_model_setup(ModelSetupCheckRequest(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-test",
                api_key="test-secret-never-return",
            ))
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "chat")
        self.assertNotIn("test-secret-never-return", repr(result))

    def test_model_discovery_filters_and_sorts_ids(self):
        fake_module = types.SimpleNamespace(OpenAI=_FakeOpenAI)
        with patch.dict(sys.modules, {"openai": fake_module}):
            result = check_model_setup(ModelSetupCheckRequest(
                provider="openai",
                base_url="https://api.openai.com/v1",
                model="gpt-test",
                api_key="test-secret-never-return",
                mode="models",
            ))
        self.assertTrue(result["ok"])
        self.assertEqual(result["models"], ["model-a", "model-b"])


if __name__ == "__main__":
    unittest.main()
