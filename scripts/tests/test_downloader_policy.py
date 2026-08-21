from __future__ import annotations

import unittest

from backend.app.downloader_policy import (
    DOWNLOAD_FAILURE_PRIORITY,
    classify_ytdlp_error,
    prefer_ytdlp_before_page_scan,
    should_run_ytdlp_cli,
    truncate_process_output,
)


class DownloaderPolicyTests(unittest.TestCase):
    def test_error_classification_and_priority_are_network_free(self) -> None:
        self.assertEqual(classify_ytdlp_error("SSL EOF while reading"), "network_tls_error")
        self.assertEqual(classify_ytdlp_error("Sign in required"), "auth_required")
        self.assertGreater(DOWNLOAD_FAILURE_PRIORITY["drm_or_encrypted"], DOWNLOAD_FAILURE_PRIORITY["no_media_found"])
        self.assertTrue(prefer_ytdlp_before_page_scan("https://www.youtube.com/watch?v=demo"))
        self.assertFalse(prefer_ytdlp_before_page_scan("https://example.org/lesson"))

    def test_process_output_and_frozen_cli_policy(self) -> None:
        self.assertEqual(truncate_process_output(b"  hello  "), "hello")
        self.assertTrue(should_run_ytdlp_cli(type("Module", (), {"__file__": "yt_dlp.py"})()))


if __name__ == "__main__":
    unittest.main()
