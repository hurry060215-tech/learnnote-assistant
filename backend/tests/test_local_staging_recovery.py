"""Real-media API contracts for local preflight and single-use staging tokens."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, knowledge, library, main, model_connections, observability, storage, upload_limits
from app.runtime import ffmpeg_bin, hidden_subprocess_kwargs


class LocalStagingRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ffmpeg = ffmpeg_bin()
        if not ffmpeg:
            raise unittest.SkipTest("FFmpeg is required for real local staging contracts")
        fixture_dir = tempfile.TemporaryDirectory(prefix="local-staging-media-", dir=config.DATA_DIR)
        cls.addClassCleanup(fixture_dir.cleanup)
        cls.original = Path(fixture_dir.name) / "synthetic-lesson.mkv"
        subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=2:duration=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000:duration=1",
                "-c:v", "ffv1", "-c:a", "pcm_s16le", "-shortest", str(cls.original),
            ],
            check=True, capture_output=True, timeout=20, **hidden_subprocess_kwargs(),
        )
        cls.video_bytes = cls.original.read_bytes()
        cls.fingerprint = hashlib.sha256(cls.video_bytes).hexdigest()

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="local-staging-api-", dir=config.DATA_DIR)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.uploads = self.root / "uploads"
        self.tasks = self.root / "tasks"
        stack = ExitStack()
        self.addCleanup(stack.close)
        paths = {
            "DATA_DIR": self.root,
            "UPLOAD_DIR": self.uploads,
            "TASK_DIR": self.tasks,
            "TEMP_DIR": self.root / "temp",
            "STATIC_DIR": self.root / "static",
            "MODEL_CACHE_DIR": self.root / "model-cache",
        }
        # Keep task JSON, events, indexing and upload reservations in this test's
        # exact disposable directory, including imported configuration aliases.
        for module in (config, knowledge, library, main, model_connections, observability, storage, upload_limits):
            for name, path in paths.items():
                if hasattr(module, name):
                    stack.enter_context(patch.object(module, name, path))
        config.ensure_dirs()
        self.create = stack.enter_context(patch.object(main, "create_task", wraps=main.create_task))
        self.write_upload = stack.enter_context(patch.object(main, "write_video_upload", wraps=main.write_video_upload))
        self.schedule = stack.enter_context(patch.object(main, "schedule_processing"))
        self.process = stack.enter_context(patch.object(
            main, "process_local_video_task", side_effect=AssertionError("Unexpected media processing"),
        ))
        # Processing is outside these admission contracts. Do not start workers
        # through lifespan or create a persistent queue merely to render a task.
        stack.enter_context(patch.object(main, "queue_status", return_value={"state": "none"}))
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def preflight(self) -> dict:
        response = self.client.post(
            "/api/media/preflight-local",
            files={"file": (self.original.name, self.video_bytes, "video/x-matroska")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertGreater(body["duration"], 0)
        self.assertGreater(body["estimated_seconds"], 0)
        self.assertEqual(body["integrity"]["status"], "ready")
        self.assertTrue(body["integrity"]["has_video"])
        self.assertTrue(body["integrity"]["has_audio"])
        self.assertEqual(body["integrity"]["file_size"], len(self.video_bytes))
        self.assertEqual(body["integrity"]["sha256"], self.fingerprint)
        self.assertEqual(body["source_fingerprint"], self.fingerprint)
        self.assertRegex(body["staging_token"], r"^[a-f0-9]{32}$")
        return body

    def submit(self, token: str):
        return self.client.post(
            "/api/tasks/from-local",
            data={"staging_token": token, "options": json.dumps({"content_mode": "subtitles"})},
        )

    def assert_task_count(self, count: int) -> None:
        self.assertEqual(len(storage.list_tasks()), count)
        self.assertEqual(len(list(self.tasks.glob("*/task.json"))), count)
        self.assertEqual(self.create.call_count, count)
        self.assertEqual(self.schedule.call_count, count)
        self.process.assert_not_called()

    def assert_missing_token(self, token: str) -> None:
        response = self.submit(token)
        self.assertEqual(response.status_code, 404, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "staging_token_not_found")
        self.assertIsInstance(detail["message"], str)
        self.assertTrue(detail["message"])

    def assert_created_from_original(self, response) -> str:
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        task = storage.get_task(body["task_id"])
        media_path = Path(task.source_media_path)
        self.assertEqual(media_path.parent, self.uploads)
        self.assertEqual(media_path.read_bytes(), self.video_bytes)
        self.assertEqual(task.media_integrity.sha256, self.fingerprint)
        self.assertEqual(task.source_identity.media_sha256, self.fingerprint)
        self.assertEqual(body["task"]["media_integrity"]["sha256"], self.fingerprint)
        self.assertEqual(list(self.uploads.iterdir()), [media_path])
        self.assertEqual(self.original.read_bytes(), self.video_bytes)
        return task.id

    def test_preflight_stages_real_media_without_creating_or_processing_a_task(self) -> None:
        body = self.preflight()
        staged = list(self.uploads.glob(f"staged_{body['staging_token']}_*"))
        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0].read_bytes(), self.video_bytes)
        self.assertEqual(list(self.uploads.iterdir()), staged)
        self.assert_task_count(0)
        self.assertEqual(list(self.tasks.iterdir()), [])
        self.assertFalse((self.root / "library.sqlite3").exists())
        self.assertFalse((self.root / "task-queue.sqlite3").exists())

    def test_token_only_create_preserves_bytes_and_creates_only_once(self) -> None:
        token = self.preflight()["staging_token"]
        self.assert_task_count(0)
        self.write_upload.reset_mock()
        task_id = self.assert_created_from_original(self.submit(token))
        self.write_upload.assert_not_called()  # Token submission sends no file.
        self.assert_task_count(1)
        self.assert_missing_token(token)
        self.assert_task_count(1)

        # A deliberate fresh preflight of identical bytes still follows existing
        # fingerprint deduplication while the original task remains active.
        fresh_token = self.preflight()["staging_token"]
        self.assertNotEqual(fresh_token, token)
        duplicate = self.submit(fresh_token)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json()["task_id"], task_id)
        self.assertTrue(duplicate.json()["deduplicated"])
        self.assertTrue(duplicate.json()["source_media_reused"])
        self.assert_missing_token(fresh_token)
        self.assert_task_count(1)
        self.assertEqual(len(list(self.uploads.iterdir())), 1)

    def assert_lost_creation_response_cannot_replay(self, status: str) -> None:
        token = self.preflight()["staging_token"]
        # The server accepted the first request even if the client lost its
        # response. A later retry must not create a second task after failure.
        task_id = self.assert_created_from_original(self.submit(token))
        storage.update_task(task_id, status=status, phase=status)
        self.write_upload.reset_mock()
        self.assert_missing_token(token)
        self.assert_task_count(1)
        self.write_upload.assert_not_called()
        self.assertEqual(storage.get_task(task_id).status, status)
        self.assertEqual(len(list(self.uploads.iterdir())), 1)

    def test_consumed_token_retry_cannot_create_again_after_original_task_failed(self) -> None:
        self.assert_lost_creation_response_cannot_replay("failed")

    def test_consumed_token_retry_cannot_create_again_after_original_task_cancelled(self) -> None:
        self.assert_lost_creation_response_cannot_replay("cancelled")

    def test_expired_token_requires_explicit_preflight_of_original_bytes(self) -> None:
        expired_token = self.preflight()["staging_token"]
        staged = next(self.uploads.glob(f"staged_{expired_token}_*"))
        now = time.time()
        expired_at = now - main.STAGED_UPLOAD_MAX_AGE_SECONDS - 60
        os.utime(staged, (expired_at, expired_at))
        self.assertEqual(main.cleanup_expired_staged_uploads(now=now), 1)
        self.assertEqual(list(self.uploads.iterdir()), [])
        self.assert_missing_token(expired_token)
        self.assert_task_count(0)
        self.assertEqual(self.original.read_bytes(), self.video_bytes)

        fresh_token = self.preflight()["staging_token"]
        self.assertNotEqual(fresh_token, expired_token)
        self.assert_task_count(0)
        self.assert_created_from_original(self.submit(fresh_token))
        self.assert_missing_token(expired_token)
        self.assert_missing_token(fresh_token)
        self.assert_task_count(1)

    def test_malformed_media_is_rejected_and_cleaned_before_task_creation(self) -> None:
        for endpoint in ("/api/media/preflight-local", "/api/tasks/from-local"):
            for content, code in ((b"not a Matroska video", "invalid_local_video"), (b"", "empty_local_file")):
                with self.subTest(endpoint=endpoint, code=code):
                    response = self.client.post(
                        endpoint,
                        files={"file": ("malformed.mkv", content, "video/x-matroska")},
                        data={"options": json.dumps({"content_mode": "subtitles"})},
                    )
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertEqual(response.json()["detail"]["code"], code)
                    self.assertEqual(list(self.uploads.iterdir()), [])
                    self.assert_task_count(0)


if __name__ == "__main__":
    unittest.main()
