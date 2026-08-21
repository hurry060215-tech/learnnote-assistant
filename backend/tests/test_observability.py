from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from app.main import api_export_support_package, api_task_events
from app.models import TaskRecord
from app.observability import read_task_events, record_task_event


class ObservabilityTests(unittest.TestCase):
    def test_events_are_persisted_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.observability.TASK_DIR", root):
                record_task_event(
                    "abc123def456",
                    "download_attempt",
                    phase="downloading",
                    details={"cookie": "secret", "url": "https://example.test/x?token=secret", "bytes": 10},
                )
                events = read_task_events("abc123def456")
                self.assertEqual(len(events), 1)
                payload = json.dumps(events, ensure_ascii=False)
                self.assertNotIn("secret", payload)
                self.assertIn("bytes", payload)

    def test_support_package_has_no_task_content_or_secrets(self) -> None:
        task = TaskRecord(
            id="abc123def456", source_type="current_page", mode="video", title="诊断任务",
            page_url="https://private.test/?token=secret", status="failed", phase="failed",
            error_code="download_forbidden", error_detail="blocked", created_at="2026-08-21T00:00:00+00:00",
            updated_at="2026-08-21T00:00:00+00:00",
        )
        with patch("app.main.get_task", return_value=task), \
             patch("app.main.read_task_events", return_value=[{"message": "safe"}]), \
             patch("app.main.render_diagnostics_markdown", return_value="diagnostic"), \
             patch("app.main.render_task_audit_markdown", return_value="audit"):
            response = api_export_support_package(task.id)
        with ZipFile(io.BytesIO(response.body)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertFalse(manifest["privacy"]["cookies"])
            self.assertNotIn("task.json", archive.namelist())
            self.assertNotIn("secret", archive.read("manifest.json").decode())


if __name__ == "__main__":
    unittest.main()
