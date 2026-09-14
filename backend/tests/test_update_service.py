from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import update_service


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class UpdateServiceTests(unittest.TestCase):
    def test_api_rate_limit_falls_back_to_official_checksum(self):
        from types import SimpleNamespace
        api = SimpleNamespace(status_code=403)
        page = SimpleNamespace(url=update_service.RELEASE_BASE+"/tag/v9.8.7", raise_for_status=lambda:None)
        checksums = SimpleNamespace(text="a"*64+"  LearnNote-Setup-x64.exe\n", raise_for_status=lambda:None)
        with tempfile.TemporaryDirectory() as root, patch.object(update_service,"DATA_DIR",Path(root)), patch.object(update_service.requests,"get",side_effect=[api,page,checksums]):
            result=update_service.fetch_latest_release(force=True)
        self.assertEqual(result["version"],"9.8.7")
        self.assertTrue(result["client"]["installable"])
        self.assertEqual(result["client"]["sha256"],"a"*64)

    def setUp(self):
        update_service._release_cache = None
        update_service._release_cache_at = 0

    def test_release_payload_accepts_only_official_install_asset(self):
        checksum = "a" * 64
        version = "9.8.7"
        payload = {
            "tag_name": "v" + version,
            "html_url": "https://github.com/hurry060215-tech/learnnote-assistant/releases/tag/v" + version,
            "assets": [
                {
                    "name": "LearnNote-Setup-x64.exe",
                    "browser_download_url": "https://github.com/hurry060215-tech/learnnote-assistant/releases/download/v9.8.7/LearnNote-Setup-x64.exe",
                    "digest": "sha256:" + checksum,
                    "size": 1024,
                },
                {
                    "name": "LearnNote-Browser-Extension-v9.8.7.zip",
                    "browser_download_url": "https://github.com/hurry060215-tech/learnnote-assistant/releases/download/v9.8.7/LearnNote-Browser-Extension-v9.8.7.zip",
                    "digest": "sha256:" + "b" * 64,
                    "size": 512,
                },
            ],
        }
        result = update_service._release_payload(payload)
        self.assertTrue(result["client"]["installable"])
        self.assertEqual(checksum, result["client"]["sha256"])
        self.assertTrue(result["extension"]["available"])

    def test_missing_cache_is_rechecked_even_with_recent_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "config").mkdir()
            (data_dir / "config" / "update-preferences.json").write_text(
                json.dumps({"auto_check": True, "auto_download": True, "last_checked_at": 4102444800}),
                encoding="utf-8",
            )
            with patch.object(update_service, "DATA_DIR", data_dir), patch.object(update_service.requests, "get", side_effect=update_service.requests.ConnectionError("offline")) as request:
                result = update_service.status(force=False)
            request.assert_called_once()
            self.assertTrue(result["check_due"])
            self.assertIsNone(result["latest"])

    def test_disabled_checks_do_not_access_network(self):
        with tempfile.TemporaryDirectory() as root, patch.object(update_service, "DATA_DIR", Path(root)), patch.object(update_service.requests, "get") as request:
            update_service.save_preferences({"auto_check":False})
            self.assertFalse(update_service.status()["check_due"])
            request.assert_not_called()

    def test_extension_asset_is_not_installable_without_trusted_digest_and_size(self):
        version = "9.8.7"
        payload = {
            "tag_name": "v" + version,
            "html_url": "https://github.com/hurry060215-tech/learnnote-assistant/releases/tag/v" + version,
            "assets": [{
                "name": "LearnNote-Browser-Extension-v9.8.7.zip",
                "browser_download_url": "https://evil.example/extension.zip",
                "digest": "sha256:" + "b" * 64,
                "size": 0,
            }],
        }
        result = update_service._release_payload(payload)
        self.assertFalse(result["extension"]["available"])
        self.assertEqual(result["extension"]["url"], "")
        self.assertEqual(result["extension"]["sha256"], "")

    def test_force_check_records_release_time_and_does_not_expose_arbitrary_urls(self):
        content = b"installer"
        checksum = hashlib.sha256(content).hexdigest()
        payload = {
            "tag_name": "v9.8.7",
            "html_url": "https://github.com/hurry060215-tech/learnnote-assistant/releases/tag/v9.8.7",
            "assets": [
                {
                    "name": "LearnNote-Setup-x64.exe",
                    "browser_download_url": "https://github.com/hurry060215-tech/learnnote-assistant/releases/download/v9.8.7/LearnNote-Setup-x64.exe",
                    "digest": "sha256:" + checksum,
                    "size": len(content),
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(update_service, "DATA_DIR", Path(directory)), patch.object(
                update_service, "DEPLOYMENT_MODE", "desktop"
            ), patch.object(update_service.requests, "get", return_value=Response(payload)):
                result = update_service.status(force=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["check_due"])
            self.assertEqual("9.8.7", result["latest"]["version"])
            self.assertTrue(result["latest"]["client"]["url"].startswith("https://github.com/"))
            saved = json.loads((Path(directory) / "config" / "update-preferences.json").read_text(encoding="utf-8"))
            self.assertGreater(saved["last_checked_at"], 0)
            with patch.object(update_service, "DATA_DIR", Path(directory)), patch.object(update_service,"_release_cache",None), patch.object(update_service.requests,"get") as request:
                restarted = update_service.status()
                self.assertEqual(restarted["latest"]["version"], "9.8.7")
                self.assertFalse(restarted["check_due"])
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
