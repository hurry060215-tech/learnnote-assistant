from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class ExtensionPairingTests(unittest.TestCase):
    def test_local_issue_allows_extension_write_with_short_lived_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.main.DATA_DIR", Path(tmp)):
                client = TestClient(app)
                issued = client.get("/api/pairing/issue")
                self.assertEqual(issued.status_code, 200)
                token = issued.json()["token"]
                response = client.post(
                    "/api/media/preflight-current-page",
                    headers={"Origin": "chrome-extension://abcdefghijklmnop", "X-LearnNote-Pairing": token},
                    json={"page_url": "https://course.example.com/lesson", "probe_limit": 0, "resources": []},
                )
                self.assertEqual(response.status_code, 200)

    def test_extension_write_without_pairing_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.main.DATA_DIR", Path(tmp)):
                client = TestClient(app)
                response = client.post(
                    "/api/media/preflight-current-page",
                    headers={"Origin": "chrome-extension://abcdefghijklmnop"},
                    json={"page_url": "https://course.example.com/lesson", "probe_limit": 0, "resources": []},
                )
                self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
