from __future__ import annotations

import functools
import io
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.downloader import DownloadError
from app.main import app, local_upload_filename, render_diagnostics_markdown
from app.models import DownloadAttempt, ResourceCandidate, TranscriptResult, TranscriptSegment
from app.runtime import ffmpeg_bin
from app.storage import create_task, task_dir, update_task


TEST_RUN_DIR = DATA_DIR / "test-runs"


class LocalUploadValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_web_index_references_mounted_static_assets(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('/web/styles.css', response.text)
        self.assertIn('/web/app.js', response.text)

        css = self.client.get("/web/styles.css")
        script = self.client.get("/web/app.js")

        self.assertEqual(css.status_code, 200)
        self.assertIn(".app-shell", css.text)
        self.assertEqual(script.status_code, 200)
        self.assertIn("loadTasks", script.text)

    def test_health_reports_duration_probe_fallback(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("duration_probe_available", payload)
        self.assertEqual(payload["duration_probe_available"], bool(payload["duration_probe"]))
        self.assertIn("vision_model_configured", payload)
        self.assertIsInstance(payload["vision_model_configured"], bool)
        self.assertTrue(payload["default_llm_model"])
        self.assertTrue(payload["default_llm_base_url"])
        if payload["ffmpeg"] and not payload["ffprobe"]:
            self.assertTrue(payload["ffprobe_optional"])
            self.assertEqual(payload["duration_probe"], "ffmpeg")

    def test_local_upload_filename_is_sanitized_and_mime_can_supply_extension(self) -> None:
        self.assertEqual(local_upload_filename("..\\course:demo?.mkv", ""), "course_demo.mkv")
        self.assertEqual(local_upload_filename("", "video/mp4"), "local-video.mp4")

    def test_local_upload_rejects_unsupported_extension_before_task_creation(self) -> None:
        response = self.client.post(
            "/api/tasks/from-local",
            files={"file": ("notes.txt", io.BytesIO(b"not a video"), "text/plain")},
            data={"title": "bad local file"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "unsupported_local_file")

    def test_local_upload_rejects_empty_video_before_task_creation(self) -> None:
        response = self.client.post(
            "/api/tasks/from-local",
            files={"file": ("empty.mp4", io.BytesIO(b""), "video/mp4")},
            data={"title": "empty local file"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "empty_local_file")
        self.assertFalse(list((DATA_DIR / "uploads").glob("pending_*empty.mp4")))

    def test_media_preview_endpoint_streams_inline_video(self) -> None:
        task = create_task("local", "Preview media")
        media = task_dir(task.id) / "media.mp4"
        media.write_bytes(b"fake mp4 preview bytes")
        try:
            update_task(task.id, media_path=str(media))

            response = self.client.get(f"/api/tasks/{task.id}/media")

            self.assertEqual(response.status_code, 200)
            self.assertIn("video/mp4", response.headers["content-type"])
            self.assertIn("inline", response.headers["content-disposition"])
            self.assertEqual(response.content, b"fake mp4 preview bytes")
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_task_list_includes_embedded_audit_summary(self) -> None:
        task = create_task("current_page", "List audit", "https://course.example.com/lesson")
        media = task_dir(task.id) / "media.mp4"
        media.write_bytes(b"fake mp4 bytes")
        try:
            update_task(task.id, status="success", phase="completed", progress=100, media_path=str(media))

            response = self.client.get("/api/tasks")

            self.assertEqual(response.status_code, 200)
            listed = next(item for item in response.json()["tasks"] if item["id"] == task.id)
            self.assertIn("audit", listed)
            self.assertEqual(listed["audit"]["blocked_gate"], "transcript")
            gates = {gate["key"]: gate for gate in listed["audit"]["gates"]}
            self.assertEqual(gates["media"]["state"], "pass")
            self.assertEqual(gates["transcript"]["state"], "warn")
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_page_preflight_report_ranks_candidates_without_probe(self) -> None:
        response = self.client.post(
            "/api/media/preflight-current-page",
            json={
                "page_url": "https://course.example.com/lesson",
                "probe_limit": 0,
                "resources": [
                    {
                        "url": "https://cdn.example.com/chunk/lesson_001.ts",
                        "kind": "fragment",
                        "source": "webRequest",
                        "score": 60,
                    },
                    {
                        "url": "https://cdn.example.com/lesson.mp4",
                        "kind": "video",
                        "source": "webRequest",
                        "score": 90,
                        "is_main_video": True,
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.json()["report"]
        self.assertFalse(report["ready"])
        self.assertGreaterEqual(report["candidate_count"], 2)
        self.assertEqual(report["probed_count"], 0)
        self.assertEqual(report["candidates"][0]["resource"]["url"], "https://cdn.example.com/lesson.mp4")
        self.assertEqual(report["candidates"][0]["preflight"]["strategy"], "not-probed")
        self.assertTrue(any(item["resource"]["source"] in {"inferred-manifest", "manifest-guess"} for item in report["candidates"]))

    def test_diagnostics_include_chaoxing_recovery_hint(self) -> None:
        task = create_task("current_page", "学习通课程", "https://mooc1.chaoxing.com/mycourse/studentstudy")
        try:
            task = update_task(
                task.id,
                status="failed",
                phase="failed",
                progress=100,
                error_code="download_forbidden",
                error_detail="HTTP 403",
                selected_resource=ResourceCandidate(
                    url="https://mooc1.chaoxing.com/ananas/status/lesson.m3u8",
                    kind="hls",
                    source="webRequest",
                    request_headers={"Referer": "https://mooc1.chaoxing.com/mycourse/studentstudy"},
                ),
                download_attempts=[
                    DownloadAttempt(
                        strategy="manifest-ffmpeg",
                        url="https://mooc1.chaoxing.com/ananas/status/lesson.m3u8",
                        code="download_forbidden",
                        message="HTTP 403",
                    )
                ],
            )

            diagnostics = render_diagnostics_markdown(task)

            self.assertIn("学习通/超星", diagnostics)
            self.assertIn("不刷课", diagnostics)
            self.assertIn("ananas", diagnostics)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    @unittest.skipUnless(ffmpeg_bin(), "ffmpeg or ffprobe is required for local upload content validation")
    def test_local_upload_rejects_fake_video_before_task_creation(self) -> None:
        response = self.client.post(
            "/api/tasks/from-local",
            files={"file": ("fake.mp4", io.BytesIO(b"not a real mp4"), "video/mp4")},
            data={"title": "fake local file"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "invalid_local_video")
        self.assertFalse(list((DATA_DIR / "uploads").glob("pending_*fake.mp4")))


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


def make_silent_video(root: Path, name: str = "silent.mp4") -> Path:
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
            "testsrc=duration=3:size=320x180:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    return video


def make_hls(root: Path, source: Path) -> Path:
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        raise unittest.SkipTest("ffmpeg is required for HLS tests")
    playlist = root / "lesson.m3u8"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-c",
            "copy",
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            "-hls_segment_filename",
            str(root / "lesson_%03d.ts"),
            str(playlist),
        ],
        check=True,
    )
    return playlist


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
                self.assertEqual(task["options"]["frame_interval"], 1)
                self.assertEqual(task["options"]["visual_understanding"], True)
                self.assertTrue(Path(task["media_path"]).exists())
                self.assertTrue(task["frame_grids"])
                self.assertTrue(task["visual_windows"])
                self.assertTrue(task["frame_grids"][0]["frame_timestamps"])
                self.assertEqual(task["visual_windows"][0]["frame_timestamps"], task["frame_grids"][0]["frame_timestamps"])
                self.assertTrue(Path(task["visual_index_path"]).exists())
                self.assertTrue(task["summary_diagnostics"])
                self.assertTrue(Path(task["summary_diagnostics_path"]).exists())
                self.assertEqual(task["summary_diagnostics"]["summary_source"], task["summary_source"])
                self.assertEqual(task["summary_diagnostics"]["frame_grid_count"], len(task["frame_grids"]))
                self.assertEqual(task["summary_diagnostics"]["visual_window_count"], len(task["visual_windows"]))
                self.assertEqual(task["summary_diagnostics"]["vision_grid_count"], len(task["frame_grids"]))
                self.assertEqual(task["summary_diagnostics"]["vision_image_count"], len(task["frame_grids"]))
                self.assertEqual(task["summary_diagnostics"]["omitted_frame_grid_count"], 0)
                visual_index = self.client.get(f"/api/tasks/{task_id}/visual-index").json()
                self.assertEqual(visual_index["task_id"], task_id)
                self.assertTrue(visual_index["windows"])
                self.assertIn("grid_url", visual_index["windows"][0])
                self.assertIn("frame_timestamps", visual_index["windows"][0])
                self.assertTrue(visual_index["windows"][0]["frame_timestamps"])
                self.assertIn("transcript_excerpt", visual_index["windows"][0])
                note = self.client.get(f"/api/tasks/{task_id}/note").text
                self.assertIn("Local synthetic lesson", note)
                self.assertIn("画面-字幕对齐索引", note)
                self.assertIn("画面索引", note)
                export = self.client.get(f"/api/tasks/{task_id}/exports/markdown")
                self.assertEqual(export.status_code, 200)
                self.assertIn("text/markdown", export.headers["content-type"])
                self.assertIn("attachment", export.headers["content-disposition"])
                self.assertIn(".md", export.headers["content-disposition"])
                self.assertIn("Local synthetic lesson", export.text)
                media_export = self.client.get(f"/api/tasks/{task_id}/exports/media")
                self.assertEqual(media_export.status_code, 200)
                self.assertIn("video/mp4", media_export.headers["content-type"])
                self.assertIn("attachment", media_export.headers["content-disposition"])
                self.assertIn(".mp4", media_export.headers["content-disposition"])
                self.assertGreater(len(media_export.content), 1024)
                visual_windows_export = self.client.get(f"/api/tasks/{task_id}/exports/visual-windows")
                self.assertEqual(visual_windows_export.status_code, 200)
                self.assertIn("text/markdown", visual_windows_export.headers["content-type"])
                self.assertIn("attachment", visual_windows_export.headers["content-disposition"])
                self.assertIn("-visual-windows.md", visual_windows_export.headers["content-disposition"])
                self.assertIn("LearnNote 画面切片索引", visual_windows_export.text)
                self.assertIn("Local synthetic lesson", visual_windows_export.text)
                self.assertIn("帧时间", visual_windows_export.text)
                self.assertIn("回看检查点", visual_windows_export.text)
                bundle = self.client.get(f"/api/tasks/{task_id}/exports/bundle")
                self.assertEqual(bundle.status_code, 200)
                self.assertEqual(bundle.headers["content-type"], "application/zip")
                self.assertIn("attachment", bundle.headers["content-disposition"])
                with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
                    names = set(archive.namelist())
                    self.assertIn("diagnostics.md", names)
                    self.assertIn("note.md", names)
                    self.assertIn("task.json", names)
                    self.assertIn("transcript.json", names)
                    self.assertIn("visual_index.json", names)
                    self.assertIn("visual_windows.md", names)
                    self.assertIn("summary_diagnostics.json", names)
                    self.assertTrue(any(name.startswith("grids/") and name.endswith(".jpg") for name in names))
                    self.assertIn("Local synthetic lesson", archive.read("note.md").decode("utf-8"))
                    visual_windows_markdown = archive.read("visual_windows.md").decode("utf-8")
                    expected_grid_name = Path(task["visual_windows"][0]["grid_path"]).name
                    self.assertIn("LearnNote 画面切片索引", visual_windows_markdown)
                    self.assertIn("Local synthetic lesson", visual_windows_markdown)
                    self.assertIn(f"grids/{expected_grid_name}", visual_windows_markdown)
                    self.assertIn("帧时间", visual_windows_markdown)
                    self.assertIn("回看检查点", visual_windows_markdown)
                    self.assertIn("这一段课程讲解函数封装", visual_windows_markdown)
                    diagnostics_report = archive.read("diagnostics.md").decode("utf-8")
                    self.assertIn("LearnNote 任务诊断报告", diagnostics_report)
                    self.assertIn("Local synthetic lesson", diagnostics_report)
                    visual_payload = json.loads(archive.read("visual_index.json").decode("utf-8"))
                    self.assertEqual(visual_payload["task_id"], task_id)
                    summary_payload = json.loads(archive.read("summary_diagnostics.json").decode("utf-8"))
                    self.assertEqual(summary_payload["task_id"], task_id)
                    self.assertEqual(summary_payload["frame_grid_count"], len(task["frame_grids"]))
            finally:
                shutil.rmtree(task_dir(task_id), ignore_errors=True)

    def test_silent_local_video_continues_with_frame_grid_without_transcript(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            video = make_silent_video(Path(tmp))
            with patch("app.processor.transcribe_audio", side_effect=AssertionError("Whisper should not run without an extracted audio track")):
                with video.open("rb") as file:
                    response = self.client.post(
                        "/api/tasks/from-local",
                        files={"file": ("silent.mp4", file, "video/mp4")},
                        data={
                            "title": "Silent visual lesson",
                            "options": json.dumps({"visual_understanding": True, "frame_interval": 1}),
                        },
                    )

            self.assertEqual(response.status_code, 200)
            task_id = response.json()["task_id"]
            try:
                task = self.client.get(f"/api/tasks/{task_id}").json()["task"]
                self.assertEqual(task["status"], "success")
                self.assertTrue(Path(task["media_path"]).exists())
                self.assertFalse(task["audio_path"])
                self.assertTrue(task["frame_grids"])
                self.assertTrue(task["visual_windows"])
                transcript = self.client.get(f"/api/tasks/{task_id}/transcript").json()
                self.assertEqual(transcript["source"], "no-audio")
                self.assertEqual(transcript["segments"], [])
                self.assertIn("音轨", transcript["warning"])
                note = self.client.get(f"/api/tasks/{task_id}/note").text
                self.assertIn("Silent visual lesson", note)
                self.assertIn("转写提示", note)
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
                rerun_task_id = ""
                try:
                    task = self.client.get(f"/api/tasks/{task_id}").json()["task"]
                    self.assertEqual(task["status"], "success")
                    self.assertEqual(task["options"]["frame_interval"], 1)
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

    def test_media_preflight_reports_direct_resource_accessible(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            root = Path(tmp)
            video = make_video(root)
            handler = functools.partial(QuietHandler, directory=str(root))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                response = self.client.post(
                    "/api/media/preflight",
                    json={
                        "page_url": f"http://127.0.0.1:{server.server_port}/lesson.html",
                        "resource": {
                            "url": media_url,
                            "source": "webRequest",
                            "kind": "video",
                            "mime": "video/mp4",
                            "score": 100,
                        },
                        "cookies": [],
                    },
                )
                self.assertEqual(response.status_code, 200)
                preflight = response.json()["preflight"]
                self.assertTrue(preflight["ok"])
                self.assertTrue(preflight["downloadable"])
                self.assertEqual(preflight["strategy"], "direct-file-probe")
                self.assertEqual(preflight["kind"], "video")
                self.assertGreater(preflight["bytes_checked"], 0)
                self.assertNotIn("Cookie", preflight["request_header_names"])
            finally:
                server.shutdown()
                server.server_close()

    def test_current_page_download_only_stops_after_media_export(self) -> None:
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
                    "mode": "download_only",
                    "page_url": f"http://127.0.0.1:{server.server_port}/lesson.html",
                    "title": "Download only lesson",
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
                with patch("app.processor.extract_audio", side_effect=AssertionError("download_only should not extract audio")):
                    with patch("app.processor.transcribe_audio", side_effect=AssertionError("download_only should not transcribe")):
                        with patch("app.processor.extract_frames", side_effect=AssertionError("download_only should not slice frames")):
                            with patch("app.processor.summarize_with_diagnostics", side_effect=AssertionError("download_only should not summarize")):
                                response = self.client.post("/api/tasks/from-current-page", json=payload)

                self.assertEqual(response.status_code, 200)
                task_id = response.json()["task_id"]
                try:
                    task = self.client.get(f"/api/tasks/{task_id}").json()["task"]
                    self.assertEqual(task["status"], "success")
                    self.assertEqual(task["phase"], "completed")
                    self.assertTrue(Path(task["media_path"]).exists())
                    self.assertFalse(task["audio_path"])
                    self.assertFalse(task["transcript_path"])
                    self.assertFalse(task["note_path"])
                    self.assertEqual(task["frame_grids"], [])
                    self.assertEqual(task["visual_windows"], [])
                    self.assertEqual(task["selected_resource"]["url"], media_url)
                    self.assertEqual(task["download_attempts"][0]["strategy"], "direct-file")
                    media_export = self.client.get(f"/api/tasks/{task_id}/exports/media")
                    self.assertEqual(media_export.status_code, 200)
                    self.assertGreater(len(media_export.content), 1024)
                    diagnostics_export = self.client.get(f"/api/tasks/{task_id}/exports/diagnostics")
                    self.assertEqual(diagnostics_export.status_code, 200)
                    self.assertIn("text/markdown", diagnostics_export.headers["content-type"])
                    self.assertIn("Download only lesson", diagnostics_export.text)
                    self.assertIn("direct-file", diagnostics_export.text)
                    bundle = self.client.get(f"/api/tasks/{task_id}/exports/bundle")
                    self.assertEqual(bundle.status_code, 200)
                    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
                        names = set(archive.namelist())
                        self.assertIn("diagnostics.md", names)
                        self.assertIn("task.json", names)
                        self.assertNotIn("note.md", names)
                        self.assertIn("Download only lesson", archive.read("diagnostics.md").decode("utf-8"))
                    self.assertEqual(self.client.get(f"/api/tasks/{task_id}/exports/markdown").status_code, 404)
                    self.assertEqual(self.client.get(f"/api/tasks/{task_id}/note").text, "")
                    self.assertEqual(self.client.get(f"/api/tasks/{task_id}/transcript").json()["segments"], [])

                    with patch("app.processor.transcribe_audio", side_effect=fake_transcribe_audio):
                        rerun_response = self.client.post(
                            f"/api/tasks/{task_id}/rerun-from-media",
                            json={"visual_understanding": True, "frame_interval": 1},
                        )
                    self.assertEqual(rerun_response.status_code, 200)
                    rerun_payload = rerun_response.json()
                    rerun_task_id = rerun_payload["task_id"]
                    self.assertEqual(rerun_payload["source_task_id"], task_id)
                    rerun_task = self.client.get(f"/api/tasks/{rerun_task_id}").json()["task"]
                    self.assertEqual(rerun_task["status"], "success")
                    self.assertEqual(rerun_task["source_type"], "local")
                    self.assertEqual(rerun_task["page_url"], payload["page_url"])
                    self.assertEqual(rerun_task["selected_resource"]["url"], media_url)
                    self.assertEqual(rerun_task["download_attempts"][0]["strategy"], "direct-file")
                    self.assertTrue(Path(rerun_task["media_path"]).exists())
                    self.assertTrue(rerun_task["transcript_path"])
                    self.assertTrue(rerun_task["frame_grids"])
                    self.assertTrue(rerun_task["visual_windows"])
                    rerun_note = self.client.get(f"/api/tasks/{rerun_task_id}/note").text
                    self.assertIn("Download only lesson", rerun_note)
                    self.assertIn("画面索引", rerun_note)
                    rerun_bundle = self.client.get(f"/api/tasks/{rerun_task_id}/exports/bundle")
                    self.assertEqual(rerun_bundle.status_code, 200)
                    with zipfile.ZipFile(io.BytesIO(rerun_bundle.content)) as archive:
                        names = set(archive.namelist())
                        self.assertIn("note.md", names)
                        self.assertIn("transcript.json", names)
                        self.assertIn("visual_windows.md", names)
                        self.assertTrue(any(name.startswith("grids/") and name.endswith(".jpg") for name in names))
                        visual_windows_markdown = archive.read("visual_windows.md").decode("utf-8")
                        self.assertIn("Download only lesson", visual_windows_markdown)
                        self.assertIn("grids/", visual_windows_markdown)
                finally:
                    if rerun_task_id:
                        shutil.rmtree(task_dir(rerun_task_id), ignore_errors=True)
                    shutil.rmtree(task_dir(task_id), ignore_errors=True)
            finally:
                server.shutdown()
                server.server_close()

    def test_current_page_hls_manifest_reaches_note_with_frame_grid(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            root = Path(tmp)
            video = make_video(root)
            playlist = make_hls(root, video)
            handler = functools.partial(QuietHandler, directory=str(root))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                hls_url = f"http://127.0.0.1:{server.server_port}/{playlist.name}"
                payload = {
                    "mode": "video",
                    "page_url": f"http://127.0.0.1:{server.server_port}/lesson.html",
                    "title": "HLS manifest lesson",
                    "resources": [
                        {
                            "url": hls_url,
                            "source": "webRequest",
                            "kind": "hls",
                            "mime": "application/vnd.apple.mpegurl",
                            "score": 100,
                            "label": "unit hls",
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
                    self.assertEqual(task["selected_resource"]["url"], hls_url)
                    self.assertEqual(task["download_attempts"][0]["strategy"], "manifest-ffmpeg")
                    self.assertEqual(task["download_attempts"][0]["status"], "success")
                    self.assertTrue(Path(task["media_path"]).exists())
                    self.assertTrue(task["frame_grids"])
                    note = self.client.get(f"/api/tasks/{task_id}/note").text
                    self.assertIn("HLS manifest lesson", note)
                finally:
                    shutil.rmtree(task_dir(task_id), ignore_errors=True)
            finally:
                server.shutdown()
                server.server_close()

    def test_current_page_prefers_page_subtitle_over_whisper(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            root = Path(tmp)
            video = make_video(root)
            subtitle = root / "lesson.vtt"
            subtitle.write_text(
                "\n".join([
                    "WEBVTT",
                    "",
                    "00:00:00.000 --> 00:00:02.000",
                    "这是平台字幕第一句。",
                    "",
                    "00:00:02.000 --> 00:00:04.000",
                    "这是平台字幕第二句。",
                    "",
                ]),
                encoding="utf-8",
            )
            handler = functools.partial(QuietHandler, directory=str(root))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                subtitle_url = f"http://127.0.0.1:{server.server_port}/{subtitle.name}"
                payload = {
                    "mode": "video",
                    "page_url": f"http://127.0.0.1:{server.server_port}/lesson.html",
                    "title": "Subtitle first lesson",
                    "resources": [
                        {"url": media_url, "source": "webRequest", "kind": "video", "mime": "video/mp4", "score": 100},
                        {"url": subtitle_url, "source": "subtitleTrack", "kind": "subtitle", "mime": "text/vtt", "score": 80},
                    ],
                    "options": {"visual_understanding": True, "frame_interval": 1},
                }
                with patch("app.processor.extract_audio", side_effect=AssertionError("Audio extraction should not run when subtitle is available")):
                    with patch("app.processor.transcribe_audio", side_effect=AssertionError("Whisper should not run when subtitle is available")):
                        response = self.client.post("/api/tasks/from-current-page", json=payload)

                self.assertEqual(response.status_code, 200)
                task_id = response.json()["task_id"]
                try:
                    task = self.client.get(f"/api/tasks/{task_id}").json()["task"]
                    self.assertEqual(task["status"], "success")
                    self.assertTrue(task["subtitle_path"])
                    self.assertFalse(task["audio_path"])
                    self.assertTrue(any(attempt["strategy"] == "subtitle-file" and attempt["status"] == "success" for attempt in task["download_attempts"]))
                    transcript = self.client.get(f"/api/tasks/{task_id}/transcript").json()
                    self.assertEqual(transcript["source"], "page-subtitle")
                    self.assertIn("这是平台字幕第一句", transcript["full_text"])
                    note = self.client.get(f"/api/tasks/{task_id}/note").text
                    self.assertIn("这是平台字幕第二句", note)
                finally:
                    shutil.rmtree(task_dir(task_id), ignore_errors=True)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
