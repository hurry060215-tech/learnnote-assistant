from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import APP_VERSION, UX_PROTOCOL_VERSION
from app.main import app
from app.models import CurrentPageTaskRequest
from app.processor import process_page_text_task
from app.storage import create_task, get_task, update_task


class TaskManagementApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = {
            "DATA_DIR": root,
            "TASK_DIR": root / "tasks",
            "UPLOAD_DIR": root / "uploads",
            "TEMP_DIR": root / "temp",
            "MODEL_CACHE_DIR": root / "model-cache",
            "STATIC_DIR": root / "static",
        }
        for path in self.paths.values():
            path.mkdir(parents=True, exist_ok=True)
        self.patches = [patch(f"app.storage.{name}", value) for name, value in self.paths.items()]
        self.patches.append(patch("app.storage.ensure_dirs", lambda: None))
        for item in self.patches:
            item.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_health_and_heartbeat_report_compatible_versions(self) -> None:
        heartbeat = self.client.post(
            "/api/extension/heartbeat",
            json={"extension_version": APP_VERSION, "protocol_version": UX_PROTOCOL_VERSION},
        )
        self.assertEqual(heartbeat.status_code, 200)
        self.assertTrue(heartbeat.json()["extension_compatible"])

        payload = self.client.get("/health").json()
        self.assertEqual(payload["app_version"], APP_VERSION)
        self.assertEqual(payload["protocol_version"], UX_PROTOCOL_VERSION)
        self.assertEqual(payload["extension_version"], APP_VERSION)
        self.assertTrue(payload["extension_compatible"])

    def test_cancel_retry_delete_and_storage_summary(self) -> None:
        active = create_task("local", "Active task")
        update_task(active.id, status="running", phase="transcribing")
        cancelled = self.client.post(f"/api/tasks/{active.id}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(get_task(active.id).status, "cancelling")
        process_page_text_task(
            active.id,
            CurrentPageTaskRequest(mode="page_text", page_url="https://example.com", page_text="sample"),
        )
        self.assertEqual(get_task(active.id).status, "cancelled")

        no_media = create_task("current_page", "Needs recapture", page_url="https://example.com/video")
        update_task(no_media.id, status="failed", phase="failed", error_code="no_media_found")
        retry = self.client.post(f"/api/tasks/{no_media.id}/retry")
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(retry.json()["detail"]["code"], "recapture_required")

        finished = create_task("local", "Finished task")
        update_task(finished.id, status="success", phase="completed", progress=100)
        artifact = self.paths["TASK_DIR"] / finished.id / "note.md"
        artifact.write_text("# note", encoding="utf-8")
        summary = self.client.get("/api/storage")
        self.assertEqual(summary.status_code, 200)
        self.assertGreaterEqual(summary.json()["task_count"], 3)
        self.assertGreater(summary.json()["categories"]["tasks"], 0)

        deleted = self.client.delete(f"/api/tasks/{finished.id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse((self.paths["TASK_DIR"] / finished.id).exists())


if __name__ == "__main__":
    unittest.main()
