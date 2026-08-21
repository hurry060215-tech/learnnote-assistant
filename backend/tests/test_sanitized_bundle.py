from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app.main import api_export_sanitized_bundle
from app.models import TaskRecord


class SanitizedBundleTests(unittest.TestCase):
    def test_bundle_excludes_media_urls_and_diagnostics(self) -> None:
        task = TaskRecord(
            id="abc123def456", source_type="current_page", mode="video", title="共享课程",
            page_url="https://private.example/course?token=secret", status="success", phase="completed",
            created_at="2026-08-21T00:00:00+00:00", updated_at="2026-08-21T00:00:00+00:00",
        )
        with patch("app.main.get_task", return_value=task), \
             patch("app.main.read_note", return_value="# 重点\n本地证据"), \
             patch("app.main.read_transcript", return_value={"segments": []}), \
             patch("app.main.read_visual_index", return_value={"windows": []}), \
             patch("app.main.read_task_qa_history", return_value=[]):
            response = api_export_sanitized_bundle(task.id)
        with ZipFile(io.BytesIO(response.body)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            self.assertIn("note.md", names)
            self.assertNotIn("task.json", names)
            self.assertNotIn("diagnostics.md", names)
            self.assertFalse(manifest["privacy"]["signed_urls"])
            self.assertNotIn("private.example", archive.read("manifest.json").decode())


if __name__ == "__main__":
    unittest.main()
