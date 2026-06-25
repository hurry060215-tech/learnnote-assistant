from __future__ import annotations

import functools
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.downloader import DownloadError
from app.main import app
from app.models import TranscriptResult, TranscriptSegment
from app.runtime import ffmpeg_bin
from app.storage import task_dir


TEST_RUN_DIR = DATA_DIR / "test-runs"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def make_video(root: Path, name: str = "synthetic.mp4") -> Path:
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        raise unittest.SkipTest("ffmpeg is required for API pipeline tests")
    root.mkdir(parents=True, exist_ok=True)
    video = root / name
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=320x180:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    return video


def fake_transcribe_audio(audio_path: Path, model_size: str = "small") -> TranscriptResult:
    return TranscriptResult(
        language="zh",
        source="unit",
        full_text="这一段课程讲解函数封装、演示步骤和复习要点。",
        segments=[
            TranscriptSegment(start=0, end=2, text="这一段课程讲解函数封装。"),
            TranscriptSegment(start=2, end=4, text="画面中有演示步骤和复习要点。"),
        ],
    )


@unittest.skipUnless(ffmpeg_bin(), "ffmpeg is required for API pipeline tests")
class ApiPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_RUN_DIR.mkdir(parents=True, exist_ok=True)
        self.client = TestClient(app)

    def test_local_upload_reaches_note_with_frame_grid(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            video = make_video(Path(tmp))
            with patch("app.processor.transcribe_audio", side_effect=fake_transcribe_audio):
                with video.open("rb") as file:
                    response = self.client.post(
                        "/api/tasks/from-local",
                        files={"file": ("synthetic.mp4", file, "video/mp4")},
                        data={
                            "title": "Local synthetic lesson",
                            "options": json.dumps({"visual_understanding": True, "frame_interval": 1}),
                        },
                    )

            self.assertEqual(response.status_code, 200)
            task_id = response.json()["task_id"]
            try:
                task = self.client.get(f"/api/tasks/{task_id}").json()["task"]
                self.assertEqual(task["status"], "success")
                self.assertTrue(Path(task["media_path"]).exists())
                self.assertTrue(task["frame_grids"])
                note = self.client.get(f"/api/tasks/{task_id}/note").text
                self.assertIn("Local synthetic lesson", note)
                self.assertIn("画面索引", note)
            finally:
                shutil.rmtree(task_dir(task_id), ignore_errors=True)

    def test_current_page_direct_resource_reaches_note_with_frame_grid(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            root = Path(tmp)
            video = make_video(root)
            handler = functools.partial(QuietHandler, directory=str(root))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                payload = {
                    "mode": "video",
                    "page_url": f"http://127.0.0.1:{server.server_port}/lesson.html",
                    "title": "Direct resource lesson",
                    "resources": [
                        {
                            "url": media_url,
                            "source": "webRequest",
                            "kind": "video",
                            "mime": "video/mp4",
                            "score": 100,
                            "label": "unit mp4",
                        }
                    ],
                    "options": {"visual_understanding": True, "frame_interval": 1},
                }
                with patch("app.processor.transcribe_audio", side_effect=fake_transcribe_audio):
                    with patch(
                        "app.downloader.MediaDownloader._download_with_ytdlp",
                        side_effect=DownloadError("download_forbidden", "skip page resolver in unit test"),
                    ):
                        response = self.client.post("/api/tasks/from-current-page", json=payload)

                self.assertEqual(response.status_code, 200)
                task_id = response.json()["task_id"]
                try:
                    task = self.client.get(f"/api/tasks/{task_id}").json()["task"]
                    self.assertEqual(task["status"], "success")
                    self.assertEqual(task["selected_resource"]["url"], media_url)
                    self.assertEqual(task["download_attempts"][0]["strategy"], "direct-file")
                    self.assertEqual(task["download_attempts"][0]["status"], "success")
                    self.assertTrue(task["frame_grids"])
                    note = self.client.get(f"/api/tasks/{task_id}/note").text
                    self.assertIn("Direct resource lesson", note)
                    self.assertIn("这一段课程讲解函数封装", note)
                finally:
                    shutil.rmtree(task_dir(task_id), ignore_errors=True)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
