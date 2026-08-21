from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.embeddings import embedding_status, semantic_rank


class EmbeddingContractTests(unittest.TestCase):
    def test_status_is_local_and_explicit_when_optional_dependency_is_missing(self) -> None:
        with patch("app.embeddings.find_spec", return_value=None):
            status = embedding_status()
            self.assertFalse(status["available"])
            self.assertTrue(status["local_only"])
            with self.assertRaisesRegex(RuntimeError, "local_embedding_unavailable"):
                semantic_rank("query", [{"title": "doc", "text": "text"}])

    def test_api_reports_optional_embedding_as_actionable_conflict(self) -> None:
        with patch("app.embeddings.find_spec", return_value=None):
            response = TestClient(app).get("/api/knowledge/search?q=test&mode=embedding")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "local_embedding_unavailable")


if __name__ == "__main__":
    unittest.main()
