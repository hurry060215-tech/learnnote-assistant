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
from urllib.parse import urlparse
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.downloader import DownloadError
from app.main import app, diagnostic_recovery_profile, local_upload_filename, render_bundle_manifest, render_diagnostics_markdown, render_task_audit_markdown, render_visual_windows_markdown
from app.models import ActiveVideoInfo, DownloadAttempt, FrameGrid, ResourceCandidate, TaskOptions, TranscriptResult, TranscriptSegment, VisualWindow
from app.runtime import ffmpeg_bin
from app.storage import create_task, task_dir, update_task


TEST_RUN_DIR = DATA_DIR / "test-runs"


class PagePreflightGateHandler(SimpleHTTPRequestHandler):
    media_body = b"\x00\x00\x00\x18ftypmp42" + (b"learnnote-media" * 512)

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/protected.mp4":
            self.send_error(403, "missing signed playback context")
            return
        if path == "/open.mp4":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.media_body)))
            self.end_headers()
            self.wfile.write(self.media_body)
            return
        self.send_error(404)


class JsonPlayEndpointHandler(SimpleHTTPRequestHandler):
    media_body = b"\x00\x00\x00\x18ftypmp42" + (b"json-play-media" * 512)

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/lesson.html":
            host = self.headers.get("Host", "")
            body = f'<html><script>window.__lesson = {{"mediaUrl":"http://{host}/real.mp4"}};</script></html>'.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/play":
            host = self.headers.get("Host", "")
            body = json.dumps({"mediaUrl": f"http://{host}/real.mp4"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/real.mp4":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.media_body)))
            self.end_headers()
            self.wfile.write(self.media_body)
            return
        self.send_error(404)


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
        self.assertIn("local_asr_available", payload)
        self.assertIsInstance(payload["local_asr_available"], bool)
        self.assertEqual(payload["local_asr_package"], "faster-whisper")
        if not payload["local_asr_available"]:
            self.assertIn("faster-whisper", payload["local_asr_install_hint"])
        self.assertTrue(payload["default_llm_model"])
        self.assertTrue(payload["default_llm_base_url"])
        self.assertTrue(payload["default_llm_base_host"])
        self.assertTrue(payload["default_llm_provider"])
        self.assertIn("data_paths", payload)
        self.assertTrue(payload["data_paths"]["root"])
        self.assertTrue(payload["data_paths"]["all_under_data_dir"])
        self.assertTrue(payload["data_paths"]["all_on_data_drive"])
        self.assertEqual(payload["data_paths"]["data_drive"], DATA_DIR.resolve().drive)
        self.assertEqual(payload["data_paths"]["paths"]["data"], str(DATA_DIR.resolve()))
        self.assertTrue(payload["data_paths"]["paths"]["tasks"].endswith("\\data\\tasks") or payload["data_paths"]["paths"]["tasks"].endswith("/data/tasks"))
        self.assertIn("model_provider_presets", payload)
        preset_keys = {item["key"] for item in payload["model_provider_presets"]}
        self.assertIn("openai", preset_keys)
        self.assertIn("groq", preset_keys)
        self.assertIn("dashscope", preset_keys)
        self.assertNotIn("siliconflow", preset_keys)
        self.assertNotIn("openrouter", preset_keys)
        self.assertNotIn("local-openai", preset_keys)
        openai_preset = next(item for item in payload["model_provider_presets"] if item["key"] == "openai")
        self.assertEqual(openai_preset["tier"], "mainstream")
        self.assertTrue(openai_preset["recommended"])
        self.assertIn("vision", openai_preset["capabilities"])
        groq_preset = next(item for item in payload["model_provider_presets"] if item["key"] == "groq")
        self.assertEqual(groq_preset["transcriber"], "groq")
        self.assertIn("vision", groq_preset["capabilities"])
        self.assertIn("asr", groq_preset["capabilities"])
        self.assertIn("assistant_capabilities", payload)
        capabilities = payload["assistant_capabilities"]
        self.assertIn("current_page_direct", capabilities["routes"])
        self.assertIn("local_upload", capabilities["routes"])
        self.assertIn("m3u8", capabilities["direct_media"]["manifests"])
        self.assertIn("tab_recording", capabilities["non_goals"])
        self.assertIn("drm_bypass", capabilities["non_goals"])
        self.assertRegex(payload["backend_origin"], r"^https?://(127\.0\.0\.1|localhost):\d+")
        if payload["ffmpeg"] and not payload["ffprobe"]:
            self.assertTrue(payload["ffprobe_optional"])
            self.assertEqual(payload["duration_probe"], "ffmpeg")

    def test_api_health_alias_matches_health_payload(self) -> None:
        health = self.client.get("/health")
        api_health = self.client.get("/api/health")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(api_health.status_code, 200)
        health_payload = health.json()
        api_payload = api_health.json()
        for key in (
            "ok",
            "ffmpeg",
            "ffprobe",
            "duration_probe",
            "backend_origin",
            "local_asr_available",
            "local_asr_package",
            "local_asr_install_hint",
            "vision_model_configured",
            "default_llm_model",
            "default_llm_base_host",
            "default_llm_provider",
            "data_paths",
            "model_provider_presets",
            "assistant_capabilities",
        ):
            self.assertEqual(api_payload[key], health_payload[key])

    def test_api_write_rejects_foreign_browser_origin(self) -> None:
        response = self.client.post(
            "/api/media/preflight-current-page",
            headers={"Origin": "https://evil.example"},
            json={
                "page_url": "https://course.example.com/lesson",
                "probe_limit": 0,
                "resources": [],
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_api_write_allows_local_browser_origin(self) -> None:
        response = self.client.post(
            "/api/media/preflight-current-page",
            headers={"Origin": "http://127.0.0.1:8765"},
            json={
                "page_url": "https://course.example.com/lesson",
                "probe_limit": 0,
                "resources": [],
            },
        )

        self.assertEqual(response.status_code, 200)

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

    def test_local_upload_rejects_invalid_task_options_before_file_validation(self) -> None:
        response = self.client.post(
            "/api/tasks/from-local",
            files={"file": ("lesson.mp4", io.BytesIO(b"not a real video"), "video/mp4")},
            data={"title": "bad options", "options": json.dumps({"frame_interval": 0})},
        )

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "invalid_task_options")
        self.assertIn("frame_interval", detail["message"])
        self.assertFalse(list((DATA_DIR / "uploads").glob("pending_*lesson.mp4")))

    def test_local_upload_records_source_media_path_before_processing(self) -> None:
        with patch("app.main.validate_local_upload_file") as validate, \
            patch("app.main.process_local_video_task") as process_task:
            response = self.client.post(
                "/api/tasks/from-local",
                files={"file": ("queued-local.mp4", io.BytesIO(b"fake local video bytes"), "video/mp4")},
                data={"title": "Queued local lesson"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = payload["task"]
        task_id = payload["task_id"]
        source_media_path = Path(task["source_media_path"])
        try:
            self.assertEqual(source_media_path.name, f"{task_id}_queued-local.mp4")
            self.assertEqual(source_media_path.parent, (DATA_DIR / "uploads").resolve())
            self.assertTrue(source_media_path.is_file())
            self.assertEqual(source_media_path.read_bytes(), b"fake local video bytes")
            self.assertEqual(task["message"], "Local upload saved; queued for processing")
            validate.assert_called_once()
            process_task.assert_called_once()
            self.assertEqual(process_task.call_args.args[0], task_id)
            self.assertEqual(process_task.call_args.args[1], source_media_path)
            detail = self.client.get(f"/api/tasks/{task_id}").json()["task"]
            self.assertEqual(detail["source_media_path"], str(source_media_path))
            self.assertEqual(detail["reuse"]["source_media_path"], str(source_media_path))
            self.assertFalse(list((DATA_DIR / "uploads").glob("pending_*queued-local.mp4")))
        finally:
            source_media_path.unlink(missing_ok=True)
            shutil.rmtree(task_dir(task_id), ignore_errors=True)

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

    def test_task_question_answers_from_note_and_transcript_without_llm_key(self) -> None:
        task = create_task("local", "函数封装课程", "https://course.example/lesson")
        root = task_dir(task.id)
        note = root / "note.md"
        transcript = root / "transcript.json"
        visual_index = root / "visual_index.json"
        note.write_text(
            "# 函数封装课程\n\n核心概念：函数封装可以复用逻辑，并通过参数控制输入，通过返回值输出结果。\n",
            encoding="utf-8",
        )
        transcript.write_text(json.dumps({
            "source": "unit",
            "segments": [
                {"start": 12, "end": 18, "text": "函数封装减少重复代码。"},
                {"start": 40, "end": 48, "text": "返回值用于把计算结果交给调用者。"},
            ],
            "full_text": "函数封装减少重复代码。返回值用于把计算结果交给调用者。",
        }, ensure_ascii=False), encoding="utf-8")
        visual_index.write_text(json.dumps({
            "task_id": task.id,
            "windows": [
                {
                    "id": "W001",
                    "start": 0,
                    "end": 60,
                    "transcript_excerpt": "函数封装与返回值示例",
                    "grid_url": "/api/tasks/qa-visual/grids/grid_000.jpg",
                }
            ],
        }, ensure_ascii=False), encoding="utf-8")
        try:
            update_task(
                task.id,
                status="success",
                phase="completed",
                note_path=str(note),
                transcript_path=str(transcript),
                visual_index_path=str(visual_index),
            )

            with patch("app.main.LLM_API_KEY", ""):
                response = self.client.post(
                    f"/api/tasks/{task.id}/qa",
                    json={"question": "函数封装有什么作用？"},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["source"], "local-extractive")
            self.assertEqual(payload["warning"], "missing_api_key")
            self.assertIn("函数封装", payload["answer"])
            self.assertTrue(payload["citations"])
            visual_citation = next(item for item in payload["citations"] if item.get("source") == "visual_window")
            self.assertEqual(visual_citation["window_id"], "W001")
            self.assertEqual(visual_citation["time_range"], "00:00-01:00")
            self.assertEqual(visual_citation["grid_url"], "/api/tasks/qa-visual/grids/grid_000.jpg")
            self.assertEqual(visual_citation["target_tab"], "slices")
            self.assertEqual(payload["history_count"], 1)
            self.assertEqual(payload["history_item"]["source"], "local-extractive")
            history_visual = next(item for item in payload["history_item"]["citations"] if item.get("source") == "visual_window")
            self.assertEqual(history_visual["window_id"], "W001")

            history_response = self.client.get(f"/api/tasks/{task.id}/qa")
            self.assertEqual(history_response.status_code, 200)
            history = history_response.json()
            self.assertEqual(len(history["items"]), 1)
            self.assertEqual(history["items"][0]["source"], "local-extractive")
            task_payload = self.client.get(f"/api/tasks/{task.id}").json()["task"]
            self.assertEqual(task_payload["qa"]["history_count"], 1)
            self.assertEqual(len(task_payload["qa"]["recent"]), 1)
            self.assertEqual(task_payload["qa"]["recent"][0]["source"], "local-extractive")
            self.assertIn("answer_excerpt", task_payload["qa"]["recent"][0])
            self.assertTrue(task_payload["qa"]["suggestions"])
            suggestion_questions = [item["question"] for item in task_payload["qa"]["suggestions"]]
            self.assertTrue(any("3 个概念" in item for item in suggestion_questions))
            self.assertTrue(any("画面索引" in item for item in suggestion_questions))
            next_action_keys = [item["key"] for item in task_payload["next_actions"]]
            self.assertIn("ask_qa", next_action_keys)
            self.assertIn("review_slices", next_action_keys)
            self.assertIn("export_markdown", next_action_keys)
            self.assertIn("export_bundle", next_action_keys)

            qa_export = self.client.get(f"/api/tasks/{task.id}/exports/qa")
            self.assertEqual(qa_export.status_code, 200)
            self.assertIn("text/markdown", qa_export.headers["content-type"])
            self.assertIn("# LearnNote 问答记录", qa_export.text)
            self.assertIn("local-extractive", qa_export.text)
            self.assertIn("W001", qa_export.text)
            self.assertIn("00:00-01:00", qa_export.text)
            self.assertIn("/api/tasks/qa-visual/grids/grid_000.jpg", qa_export.text)

            manifest = self.client.get(f"/api/tasks/{task.id}/exports/manifest")
            self.assertEqual(manifest.status_code, 200)
            manifest_payload = manifest.json()
            self.assertEqual(manifest_payload["qa"]["history_count"], 1)
            self.assertTrue(manifest_payload["qa"]["suggestions"])
            self.assertIn("next_actions", manifest_payload)
            self.assertIn("ask_qa", [item["key"] for item in manifest_payload["next_actions"]])
            self.assertEqual(manifest_payload["artifacts"]["qa"], "qa.md")
            self.assertEqual(manifest_payload["artifacts"]["qa_history"], "qa_history.json")

            bundle = self.client.get(f"/api/tasks/{task.id}/exports/bundle")
            self.assertEqual(bundle.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
                self.assertIn("qa.md", archive.namelist())
                self.assertIn("qa_history.json", archive.namelist())
                self.assertIn("local-extractive", archive.read("qa.md").decode("utf-8"))
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_task_next_actions_allow_qa_from_transcript_without_note(self) -> None:
        task = create_task("local", "Transcript only lesson", "https://course.example/lesson")
        root = task_dir(task.id)
        transcript = root / "transcript.json"
        transcript.write_text(json.dumps({
            "source": "unit",
            "segments": [
                {"start": 0, "end": 12, "text": "The lesson explains function parameters."},
                {"start": 20, "end": 35, "text": "Return values pass computed results back to callers."},
            ],
            "full_text": "The lesson explains function parameters. Return values pass computed results back to callers.",
        }, ensure_ascii=False), encoding="utf-8")
        try:
            update_task(
                task.id,
                status="success",
                phase="completed",
                progress=100,
                transcript_path=str(transcript),
            )

            response = self.client.get(f"/api/tasks/{task.id}")

            self.assertEqual(response.status_code, 200)
            task_payload = response.json()["task"]
            next_action_keys = [item["key"] for item in task_payload["next_actions"]]
            self.assertIn("ask_qa", next_action_keys)
            self.assertIn("review_transcript", next_action_keys)
            self.assertIn("export_bundle", next_action_keys)
            self.assertNotIn("export_markdown", next_action_keys)
            self.assertTrue(task_payload["qa"]["suggestions"])
            self.assertTrue(any(item["source"] == "transcript" for item in task_payload["qa"]["suggestions"]))
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_stale_media_path_is_not_reported_reusable(self) -> None:
        task = create_task("current_page", "Missing media", "https://course.example.com/lesson", mode="download_only")
        missing_media = task_dir(task.id) / "media.mp4"
        try:
            update_task(
                task.id,
                status="success",
                phase="completed",
                progress=100,
                media_path=str(missing_media),
                selected_resource=ResourceCandidate(url="https://cdn.example.com/lesson.mp4", kind="video", source="webRequest"),
                download_attempts=[DownloadAttempt(strategy="direct-file", url="https://cdn.example.com/lesson.mp4", status="success")],
            )

            detail = self.client.get(f"/api/tasks/{task.id}").json()["task"]
            gates = {gate["key"]: gate for gate in detail["audit"]["gates"]}
            self.assertFalse(detail["reuse"]["media_available"])
            self.assertEqual(detail["reuse"]["media_path_recorded"], str(missing_media))
            self.assertFalse(detail["reuse"]["rerun_from_media_ready"])
            self.assertEqual(gates["media"]["state"], "warn")
            self.assertFalse(detail["direct_extraction"]["media_landed"])
            self.assertFalse(detail["direct_extraction"]["media_reusable"])

            manifest_response = self.client.get(f"/api/tasks/{task.id}/exports/manifest")
            self.assertEqual(manifest_response.status_code, 200)
            manifest = manifest_response.json()
            self.assertFalse(manifest["artifacts"]["media_available"])
            self.assertFalse(manifest["reuse"]["media_available"])
            self.assertFalse(manifest["reuse"]["rerun_from_media_ready"])
            self.assertFalse(manifest["direct_extraction"]["media_landed"])

            diagnostics = self.client.get(f"/api/tasks/{task.id}/exports/diagnostics")
            self.assertEqual(diagnostics.status_code, 200)
            self.assertIn("Media available: no", diagnostics.text)
            self.assertIn("Rerun from media ready: no", diagnostics.text)
            self.assertIn("Media landed: no", diagnostics.text)
            audit = self.client.get(f"/api/tasks/{task.id}/exports/audit")
            self.assertEqual(audit.status_code, 200)
            self.assertIn("# LearnNote 任务审计报告", audit.text)
            self.assertIn("媒体存在：no", audit.text)
            bundle = self.client.get(f"/api/tasks/{task.id}/exports/bundle")
            self.assertEqual(bundle.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
                self.assertIn("audit.md", archive.namelist())
                self.assertIn("diagnostics.md", archive.namelist())
                self.assertIn("LearnNote 任务审计报告", archive.read("audit.md").decode("utf-8"))
            self.assertEqual(self.client.get(f"/api/tasks/{task.id}/exports/media").status_code, 404)
            self.assertEqual(self.client.post(f"/api/tasks/{task.id}/rerun-from-media", json={"frame_interval": 1}).status_code, 404)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_media_export_uses_recorded_raw_filename(self) -> None:
        task = create_task("current_page", "Raw downloaded lesson", "https://course.example.com/lesson", mode="video")
        work_dir = task_dir(task.id)
        media = work_dir / "downloaded-original.mp4"
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            media.write_bytes(b"fake mp4 bytes")
            update_task(
                task.id,
                status="failed",
                phase="failed",
                progress=100,
                error_code="processing_failed",
                media_path=str(media),
            )

            export = self.client.get(f"/api/tasks/{task.id}/exports/media")
            self.assertEqual(export.status_code, 200)
            self.assertIn("attachment", export.headers["content-disposition"])
            self.assertIn("downloaded-original.mp4", export.headers["content-disposition"])
            self.assertEqual(export.content, b"fake mp4 bytes")

            preview = self.client.get(f"/api/tasks/{task.id}/media")
            self.assertEqual(preview.status_code, 200)
            self.assertIn("inline", preview.headers["content-disposition"])
            self.assertIn("downloaded-original.mp4", preview.headers["content-disposition"])

            detail = self.client.get(f"/api/tasks/{task.id}").json()["task"]
            action_labels = {item["key"]: item["label"] for item in detail["next_actions"]}
            self.assertEqual(action_labels["continue_from_media"], "从 downloaded-original.mp4 继续")
            self.assertEqual(action_labels["export_media"], "导出 downloaded-original.mp4")
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_reuse_ready_when_media_has_slices_but_no_note(self) -> None:
        task = create_task("current_page", "Failed after slicing", "https://course.example.com/lesson", mode="video")
        work_dir = task_dir(task.id)
        media = work_dir / "media.mp4"
        grid = work_dir / "grids" / "grid_000.jpg"
        try:
            grid.parent.mkdir(parents=True, exist_ok=True)
            media.write_bytes(b"fake mp4 bytes")
            grid.write_bytes(b"fake jpg bytes")
            update_task(
                task.id,
                status="failed",
                phase="summarizing",
                progress=84,
                error_code="processing_failed",
                error_detail="LLM failed after slicing",
                media_path=str(media),
                frame_grids=[
                    FrameGrid(
                        path=str(grid),
                        url=f"/data/tasks/{task.id}/grids/grid_000.jpg",
                        start=0,
                        end=180,
                        frame_count=9,
                        frame_timestamps=[0, 20, 40],
                    )
                ],
            )

            detail = self.client.get(f"/api/tasks/{task.id}").json()["task"]

            self.assertTrue(detail["reuse"]["media_available"])
            self.assertTrue(detail["reuse"]["has_visual_slices"])
            self.assertFalse(detail["reuse"]["note_ready"])
            self.assertTrue(detail["reuse"]["rerun_from_media_ready"])
            self.assertEqual(detail["reuse"]["suggested_next_step"], "rerun_from_media")
            self.assertEqual(detail["recovery"]["next_action"], "continue_from_media")
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_failed_task_with_downloaded_raw_media_can_rerun_from_media(self) -> None:
        task = create_task("current_page", "Failed raw media", "https://course.example.com/lesson", mode="video")
        work_dir = task_dir(task.id)
        media = make_video(work_dir, "downloaded-original.mp4")
        rerun_task_id = ""
        try:
            update_task(
                task.id,
                status="failed",
                phase="failed",
                progress=100,
                error_code="processing_failed",
                error_detail="normalize failed",
                media_path=str(media),
                selected_resource=ResourceCandidate(url="https://cdn.example.com/lesson.mp4", kind="video", source="webRequest"),
                download_attempts=[DownloadAttempt(strategy="direct-file", url="https://cdn.example.com/lesson.mp4", status="success")],
            )

            detail = self.client.get(f"/api/tasks/{task.id}").json()["task"]

            self.assertTrue(detail["reuse"]["media_available"])
            self.assertTrue(detail["reuse"]["rerun_from_media_ready"])
            self.assertEqual(detail["reuse"]["suggested_next_step"], "rerun_from_media")
            self.assertEqual(detail["recovery"]["next_action"], "continue_from_media")
            self.assertIn("downloaded-original.mp4", detail["recovery"]["diagnosis"])
            self.assertEqual(detail["recovery"]["primary_action"]["ui_intent"], "continue_from_media")
            self.assertTrue(any(item["key"] == "continue_from_media" for item in detail["next_actions"]))

            with patch("app.main.process_local_video_task") as process_task:
                response = self.client.post(f"/api/tasks/{task.id}/rerun-from-media", json={"visual_understanding": False})
            self.assertEqual(response.status_code, 200)
            rerun_task_id = response.json()["task_id"]
            process_task.assert_called_once()
            rerun = self.client.get(f"/api/tasks/{rerun_task_id}").json()["task"]
            self.assertEqual(rerun["source_task_id"], task.id)
            self.assertEqual(rerun["source_media_path"], str(media))
        finally:
            if rerun_task_id:
                shutil.rmtree(task_dir(rerun_task_id), ignore_errors=True)
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_failed_local_upload_can_rerun_from_source_media_path(self) -> None:
        task = create_task("local", "Failed queued upload", mode="video")
        upload_path = make_video(DATA_DIR / "uploads", f"{task.id}_queued-local.mp4")
        rerun_task_id = ""
        try:
            update_task(
                task.id,
                status="failed",
                phase="failed",
                progress=100,
                error_code="processing_failed",
                error_detail="first local processing failed",
                source_media_path=str(upload_path),
            )

            detail = self.client.get(f"/api/tasks/{task.id}").json()["task"]

            self.assertEqual(detail["media_path"], "")
            self.assertEqual(detail["source_media_path"], str(upload_path))
            self.assertTrue(detail["reuse"]["media_available"])
            self.assertTrue(detail["reuse"]["rerun_from_media_ready"])
            self.assertEqual(detail["reuse"]["suggested_next_step"], "rerun_from_media")
            self.assertEqual(detail["recovery"]["next_action"], "continue_from_media")

            export = self.client.get(f"/api/tasks/{task.id}/exports/media")
            self.assertEqual(export.status_code, 200)
            self.assertIn(upload_path.name, export.headers["content-disposition"])
            self.assertEqual(export.content, upload_path.read_bytes())
            preview = self.client.get(f"/api/tasks/{task.id}/media")
            self.assertEqual(preview.status_code, 200)
            self.assertIn("inline", preview.headers["content-disposition"])
            self.assertIn(upload_path.name, preview.headers["content-disposition"])

            with patch("app.main.process_local_video_task") as process_task:
                response = self.client.post(f"/api/tasks/{task.id}/rerun-from-media", json={"visual_understanding": False})
            self.assertEqual(response.status_code, 200)
            rerun_task_id = response.json()["task_id"]
            process_task.assert_called_once()
            self.assertEqual(process_task.call_args.args[1], upload_path)
            rerun = self.client.get(f"/api/tasks/{rerun_task_id}").json()["task"]
            self.assertEqual(rerun["source_task_id"], task.id)
            self.assertEqual(rerun["source_media_path"], str(upload_path))
        finally:
            if rerun_task_id:
                shutil.rmtree(task_dir(rerun_task_id), ignore_errors=True)
            shutil.rmtree(task_dir(task.id), ignore_errors=True)
            upload_path.unlink(missing_ok=True)

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

    def test_visual_window_clip_export_generates_and_reuses_cached_clip(self) -> None:
        task = create_task("local", "Clip lesson", "", mode="local")
        work_dir = task_dir(task.id)
        media = work_dir / "media.mp4"
        try:
            media.write_bytes(b"fake source media")
            update_task(
                task.id,
                status="success",
                phase="completed",
                progress=100,
                media_path=str(media),
                visual_windows=[
                    VisualWindow(
                        id="W001",
                        index=1,
                        start=10,
                        end=40,
                        frame_count=2,
                        grid_url="/data/tasks/clip/grids/grid_000.jpg",
                    )
                ],
            )

            calls = []

            def fake_extract(video_path, output_path, start, end):
                calls.append((Path(video_path), Path(output_path), start, end))
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"clip bytes")
                return Path(output_path)

            with patch("app.main.extract_video_clip", side_effect=fake_extract):
                response = self.client.get(f"/api/tasks/{task.id}/exports/clips/W001")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"clip bytes")
                self.assertIn("video/mp4", response.headers["content-type"])
                self.assertIn("W001", response.headers["content-disposition"])
                self.assertEqual(calls[0][0], media)
                self.assertEqual(calls[0][2:], (10.0, 40.0))

                cached = self.client.get(f"/api/tasks/{task.id}/exports/clips/W001")
                self.assertEqual(cached.status_code, 200)
                self.assertEqual(cached.content, b"clip bytes")
                self.assertEqual(len(calls), 1)

            missing = self.client.get(f"/api/tasks/{task.id}/exports/clips/W999")
            self.assertEqual(missing.status_code, 404)
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

    def test_page_preflight_selects_first_downloadable_candidate_after_failed_probe(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), PagePreflightGateHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            response = self.client.post(
                "/api/media/preflight-current-page",
                json={
                    "page_url": f"{base_url}/lesson.html",
                    "probe_limit": 3,
                    "resources": [
                        {
                            "url": f"{base_url}/protected.mp4",
                            "kind": "video",
                            "source": "webRequest",
                            "score": 100,
                            "label": "stale signed mp4",
                        },
                        {
                            "url": f"{base_url}/open.mp4",
                            "kind": "video",
                            "source": "webRequest",
                            "score": 95,
                            "label": "playable mp4",
                        },
                    ],
                },
            )

            self.assertEqual(response.status_code, 200)
            report = response.json()["report"]
            self.assertTrue(report["ready"])
            self.assertEqual(report["selected_url"], f"{base_url}/open.mp4")
            self.assertEqual(report["candidate_count"], 2)
            self.assertEqual(report["probed_count"], 2)
            self.assertEqual(report["downloadable_count"], 1)
            self.assertEqual(report["candidates"][0]["resource"]["url"], f"{base_url}/protected.mp4")
            self.assertEqual(report["candidates"][0]["preflight"]["code"], "auth_required")
            self.assertFalse(report["candidates"][0]["preflight"]["downloadable"])
            self.assertEqual(report["candidates"][1]["resource"]["url"], f"{base_url}/open.mp4")
            self.assertTrue(report["candidates"][1]["resource"]["user_selected"])
            self.assertEqual(report["candidates"][1]["resource"]["score"], 100)
            self.assertTrue(report["candidates"][1]["preflight"]["downloadable"])
            self.assertEqual(report["candidates"][1]["preflight"]["strategy"], "direct-file-probe")
        finally:
            server.shutdown()
            server.server_close()

    def test_page_preflight_active_src_prioritizes_current_candidate(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), PagePreflightGateHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            open_url = f"{base_url}/open.mp4#t=12"
            response = self.client.post(
                "/api/media/preflight-current-page",
                json={
                    "page_url": f"{base_url}/lesson.html",
                    "probe_limit": 1,
                    "active_video": {
                        "src": open_url,
                        "current_time": 12,
                        "duration": 180,
                        "width": 1280,
                        "height": 720,
                    },
                    "resources": [
                        {
                            "url": f"{base_url}/protected.mp4",
                            "kind": "video",
                            "source": "webRequest",
                            "score": 100,
                            "label": "stale signed mp4",
                        },
                        {
                            "url": open_url,
                            "kind": "video",
                            "source": "webRequest",
                            "score": 10,
                            "label": "current mp4",
                        },
                    ],
                },
            )

            self.assertEqual(response.status_code, 200)
            report = response.json()["report"]
            self.assertTrue(report["ready"])
            self.assertEqual(report["selected_url"], open_url)
            self.assertEqual(report["probed_count"], 1)
            candidate = report["candidates"][0]["resource"]
            self.assertEqual(candidate["url"], open_url)
            self.assertTrue(candidate["is_main_video"])
            self.assertEqual(candidate["playback_match"], "exact-src")
            self.assertEqual(candidate["current_time"], 12)
        finally:
            server.shutdown()
            server.server_close()

    def test_page_preflight_scans_page_when_extension_candidates_are_empty(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), JsonPlayEndpointHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            media_url = f"{base_url}/real.mp4"
            response = self.client.post(
                "/api/media/preflight-current-page",
                json={
                    "page_url": f"{base_url}/lesson.html",
                    "probe_limit": 3,
                    "resources": [],
                },
            )

            self.assertEqual(response.status_code, 200)
            report = response.json()["report"]
            self.assertTrue(report["ready"])
            self.assertEqual(report["selected_url"], media_url)
            self.assertEqual(report["page_scan"]["discovered_count"], 1)
            self.assertTrue(report["page_scan"]["attempted"])
            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["probed_count"], 1)
            candidate = report["candidates"][0]["resource"]
            self.assertEqual(candidate["url"], media_url)
            self.assertEqual(candidate["source"], "page-scan")
            self.assertTrue(report["candidates"][0]["preflight"]["downloadable"])
        finally:
            server.shutdown()
            server.server_close()

    def test_page_preflight_report_keeps_resolved_media_url_on_candidate(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), JsonPlayEndpointHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            play_url = f"{base_url}/api/play?id=42"
            media_url = f"{base_url}/real.mp4"
            response = self.client.post(
                "/api/media/preflight-current-page",
                json={
                    "page_url": f"{base_url}/lesson.html",
                    "probe_limit": 1,
                    "resources": [
                        {
                            "url": play_url,
                            "kind": "video",
                            "mime": "video/mp4",
                            "source": "webRequest",
                            "score": 100,
                            "label": "json play endpoint",
                        },
                    ],
                },
            )

            self.assertEqual(response.status_code, 200)
            report = response.json()["report"]
            self.assertTrue(report["ready"])
            self.assertEqual(report["selected_url"], play_url)
            candidate = report["candidates"][0]["resource"]
            preflight = report["candidates"][0]["preflight"]
            self.assertEqual(candidate["url"], play_url)
            self.assertEqual(candidate["resolved_url"], media_url)
            self.assertEqual(candidate["kind"], "video")
            self.assertEqual(preflight["resolved_url"], media_url)
            self.assertEqual(preflight["strategy"], "direct-response-probe")
        finally:
            server.shutdown()
            server.server_close()

    def test_page_preflight_resolves_unknown_playback_api_candidate(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), JsonPlayEndpointHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            play_url = f"{base_url}/api/play?id=42"
            media_url = f"{base_url}/real.mp4"
            response = self.client.post(
                "/api/media/preflight-current-page",
                json={
                    "page_url": f"{base_url}/lesson.html",
                    "probe_limit": 1,
                    "resources": [
                        {
                            "url": play_url,
                            "kind": "unknown",
                            "mime": "application/json",
                            "source": "webRequest",
                            "request_type": "fetch",
                            "method": "GET",
                            "score": 76,
                            "label": "playback api endpoint",
                        },
                    ],
                },
            )

            self.assertEqual(response.status_code, 200)
            report = response.json()["report"]
            self.assertTrue(report["ready"])
            self.assertEqual(report["selected_url"], play_url)
            candidate = report["candidates"][0]["resource"]
            preflight = report["candidates"][0]["preflight"]
            self.assertEqual(candidate["url"], play_url)
            self.assertEqual(candidate["resolved_url"], media_url)
            self.assertEqual(candidate["kind"], "video")
            self.assertTrue(preflight["downloadable"])
            self.assertEqual(preflight["resolved_url"], media_url)
            self.assertEqual(preflight["strategy"], "direct-response-probe")
        finally:
            server.shutdown()
            server.server_close()

    def test_page_preflight_reports_blob_only_page_as_drm_boundary(self) -> None:
        response = self.client.post(
            "/api/media/preflight-current-page",
            json={
                "page_url": "https://course.example.com/lesson",
                "drm_detected": True,
                "probe_limit": 1,
                "resources": [
                    {
                        "url": "blob:https://course.example.com/player",
                        "kind": "blob",
                        "source": "activeVideo",
                        "score": 12,
                        "label": "active blob",
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.json()["report"]
        self.assertFalse(report["ready"])
        self.assertEqual(report["code"], "drm_or_encrypted")
        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(report["downloadable_count"], 0)

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
            recovery = diagnostic_recovery_profile(task)

            self.assertIn("学习通/超星", diagnostics)
            self.assertIn("不刷课", diagnostics)
            self.assertIn("ananas", diagnostics)
            self.assertIn("## 恢复档案", diagnostics)
            self.assertIn("归类：download_forbidden", diagnostics)
            self.assertEqual(recovery["code"], "download_forbidden")
            self.assertEqual(recovery["next_action"], "refresh_playback_and_retry")
            self.assertEqual(recovery["primary_action"]["ui_intent"], "retry_current_page")
            self.assertEqual(recovery["primary_action"]["label"], "继续播放后重检")
            self.assertIn("local_upload", [action["key"] for action in recovery["actions"]])
            self.assertIn("export_diagnostics", [action["key"] for action in recovery["actions"]])
            self.assertTrue(recovery["is_chaoxing"])
            self.assertIn("不刷课", " ".join(recovery["boundary_notes"]))
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_recovery_prefers_rerun_when_failed_task_has_media(self) -> None:
        task = create_task("current_page", "已下载课程", "https://mooc1.chaoxing.com/mycourse/studentstudy")
        try:
            media = task_dir(task.id) / "media.mp4"
            media.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"learnnote-media" * 512))
            task = update_task(
                task.id,
                status="failed",
                phase="failed",
                progress=100,
                media_path=str(media),
                error_code="download_forbidden",
                error_detail="HTTP 403 after media landed",
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
                        message="HTTP 403 after media landed",
                    )
                ],
            )

            recovery = diagnostic_recovery_profile(task)

            self.assertEqual(recovery["code"], "media_ready_for_rerun")
            self.assertEqual(recovery["next_action"], "continue_from_media")
            self.assertEqual(recovery["primary_action"]["ui_intent"], "continue_from_media")
            self.assertEqual(recovery["primary_action"]["label"], "继续切片总结")
            self.assertIn("media.mp4", recovery["diagnosis"])
            self.assertIn("local_upload", [action["key"] for action in recovery["actions"]])
            self.assertIn("export_diagnostics", [action["key"] for action in recovery["actions"]])
            self.assertTrue(recovery["is_chaoxing"])
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_bundle_manifest_redacts_sensitive_options_and_headers(self) -> None:
        task = create_task("current_page", "Manifest redaction lesson", "https://course.example.com/watch")
        try:
            task.options.llm_api_key = "secret-key"
            task.selected_resource = ResourceCandidate(
                url="https://cdn.example.com/lesson.mp4",
                kind="video",
                source="webRequest",
                user_selected=True,
                is_main_video=True,
                playback_match="range-near-playhead",
                current_time=12,
                duration=120,
                width=1280,
                height=720,
                request_headers={"Cookie": "session=secret", "Authorization": "Bearer secret", "Referer": "https://course.example.com/watch"},
                headers={"content-type": "video/mp4", "set-cookie": "secret=value"},
            )
            task.active_video = ActiveVideoInfo(
                src="blob:https://course.example.com/player",
                current_time=12,
                duration=120,
                paused=False,
                width=1280,
                height=720,
                frame_id=2,
                label="course player",
            )
            task.cookie_summary = {
                "total": 3,
                "domains": {"course.example.com": 2, "cdn.example.com": 1},
                "domain_count": 2,
                "secure_count": 2,
                "http_only_count": 1,
                "partitioned_count": 2,
                "partition_key_count": 1,
            }
            task.download_attempts = [
                DownloadAttempt(strategy="direct-file", url="https://cdn.example.com/lesson.mp4", status="success")
            ]

            manifest = render_bundle_manifest(
                task,
                {"source": "browser-subtitle", "language": "zh", "segments": [{"start": 1, "end": 3, "text": "字幕"}]},
                {"windows": [{"id": "W001"}]},
            )
            encoded = json.dumps(manifest, ensure_ascii=False)

            self.assertEqual(manifest["options"]["llm_api_key"], "<redacted>")
            self.assertEqual(manifest["source"]["selected_resource"]["request_header_names"], ["Referer"])
            self.assertEqual(manifest["direct_extraction"]["selected_candidate"]["safe_request_header_names"], ["Referer"])
            self.assertTrue(manifest["direct_extraction"]["selected_candidate"]["user_selected"])
            self.assertEqual(manifest["direct_extraction"]["browser_context"]["cookie_domain_count"], 2)
            self.assertEqual(manifest["direct_extraction"]["browser_context"]["cookie_count"], 3)
            self.assertEqual(manifest["direct_extraction"]["browser_context"]["partitioned_cookie_count"], 2)
            self.assertEqual(manifest["direct_extraction"]["browser_context"]["partition_key_count"], 1)
            self.assertEqual(manifest["source"]["selected_resource"]["response_header_names"], ["content-type", "set-cookie"])
            self.assertTrue(manifest["source"]["playback"]["matched_current_playback"])
            self.assertEqual(manifest["source"]["playback"]["active_video"]["current_time"], 12)
            self.assertEqual(manifest["source"]["playback"]["selected_resource"]["playback_match"], "range-near-playhead")
            self.assertEqual(manifest["transcript"]["segment_count"], 1)
            self.assertIn("audit", manifest)
            self.assertEqual(manifest["artifacts"]["audit"], "audit.md")
            self.assertIn("recovery", manifest)
            self.assertEqual(manifest["recovery"]["selected_kind"], "video")
            self.assertEqual(manifest["recovery"]["attempt_count"], 1)
            self.assertNotIn("secret-key", encoded)
            self.assertNotIn("session=secret", encoded)
            self.assertNotIn("Bearer secret", encoded)
            self.assertNotIn("Authorization", json.dumps(manifest["direct_extraction"], ensure_ascii=False))
            self.assertNotIn("secret=value", encoded)
            diagnostics = render_diagnostics_markdown(task)
            self.assertIn("user selected yes", diagnostics)
            self.assertIn("cookie domains 2 / cookies 3", diagnostics)
            self.assertIn("Active playback: url / 00:12 / 02:00 / paused no / frame 2 / 1280x720", diagnostics)
            self.assertIn("Selected playback match: yes / range-near-playhead / 00:12 / 02:00", diagnostics)
            audit = render_task_audit_markdown(task)
            self.assertIn("# LearnNote 任务审计报告", audit)
            self.assertIn("不录制标签页：yes", audit)
            self.assertIn("安全请求头名：Referer", audit)
            self.assertIn("当前播放：url / 00:12 / 02:00 / paused no / frame 2 / 1280x720", audit)
            self.assertIn("选中资源播放匹配：yes / range-near-playhead / 00:12 / 02:00", audit)
            self.assertIn("Cookie：3 / 2 域", audit)
            self.assertIn("分区 Cookie：2 / 1 partition key", audit)
            self.assertNotIn("session=secret", audit)
            self.assertNotIn("Bearer secret", audit)
            self.assertNotIn("Authorization", audit)
            self.assertNotIn("secret=value", audit)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_bundle_manifest_and_diagnostics_include_mse_append_evidence(self) -> None:
        task = create_task("current_page", "MSE blob lesson", "https://course.example.com/watch")
        try:
            task.selected_resource = ResourceCandidate(
                url="blob:https://course.example.com/player-token",
                kind="blob",
                source="page-hook",
                blob_url="blob:https://course.example.com/player-token",
                mime="video/mp4",
                mse_append_bytes=4096,
                mse_append_total_bytes=10485760,
                mse_append_count=37,
                mse_append_magic="ftyp",
                mse_append_mime="video/mp4",
                mse_append_detected_kind="video",
                request_headers={"Cookie": "session=secret", "Referer": "https://course.example.com/watch"},
            )

            manifest = render_bundle_manifest(task, {"segments": []}, {"windows": []})
            diagnostics = render_diagnostics_markdown(task)
            encoded = json.dumps(manifest, ensure_ascii=False)
            evidence = manifest["source"]["selected_resource"]["mse_append_evidence"]

            self.assertEqual(evidence["append_count"], 37)
            self.assertEqual(evidence["append_bytes"], 4096)
            self.assertEqual(evidence["append_total_bytes"], 10485760)
            self.assertEqual(evidence["append_magic"], "ftyp")
            self.assertEqual(evidence["append_mime"], "video/mp4")
            self.assertEqual(evidence["append_detected_kind"], "video")
            self.assertEqual(manifest["reuse"]["mse_append_evidence"], evidence)
            direct = manifest["direct_extraction"]
            self.assertTrue(direct["no_tab_recording"])
            self.assertTrue(direct["no_drm_bypass"])
            self.assertEqual(direct["route"], "pending_or_no_media")
            self.assertEqual(direct["selected_candidate"]["kind"], "blob")
            self.assertEqual(direct["boundary"], "unresolved_blob_or_fragment_not_recorded")
            self.assertEqual(direct["selected_candidate"]["safe_request_header_names"], ["Referer"])
            self.assertNotIn("Cookie", direct["selected_candidate"]["safe_request_header_names"])
            self.assertNotIn("Authorization", json.dumps(direct, ensure_ascii=False))
            self.assertIn("### MSE Append Evidence", diagnostics)
            self.assertIn("## Direct Extraction Evidence", diagnostics)
            self.assertIn("No tab recording: yes", diagnostics)
            self.assertIn("Safe request headers: Referer", diagnostics)
            self.assertIn("Append count: 37", diagnostics)
            self.assertIn("Magic: ftyp", diagnostics)
            self.assertIn("Total append bytes: 10.0 MB", diagnostics)
            self.assertNotIn("session=secret", encoded)
            self.assertNotIn("Bearer secret", encoded)
            self.assertNotIn("session=secret", diagnostics)
            self.assertNotIn("Bearer secret", diagnostics)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_visual_window_exports_include_per_window_vision_status(self) -> None:
        task = create_task("current_page", "Vision status lesson", "https://course.example.com/watch")
        try:
            task.media_path = str(task_dir(task.id) / "media.mp4")
            task.visual_windows = [
                VisualWindow(
                    id="W001",
                    index=1,
                    start=0,
                    end=180,
                    duration=180,
                    frame_count=9,
                    frame_timestamps=[0, 20, 40],
                    grid_url="/api/tasks/task/assets/grid_001.jpg",
                    grid_path=str(task_dir(task.id) / "grids" / "grid_001.jpg"),
                    transcript_excerpt="00:00:00 introduction",
                    segments=[TranscriptSegment(start=0, end=10, text="introduction")],
                ),
                VisualWindow(
                    id="W002",
                    index=2,
                    start=180,
                    end=360,
                    duration=180,
                    frame_count=9,
                    frame_timestamps=[180, 200, 220],
                    grid_url="/api/tasks/task/assets/grid_002.jpg",
                    grid_path=str(task_dir(task.id) / "grids" / "grid_002.jpg"),
                ),
                VisualWindow(
                    id="W003",
                    index=3,
                    start=360,
                    end=540,
                    duration=180,
                    frame_count=9,
                    frame_timestamps=[360, 380, 400],
                    grid_url="/api/tasks/task/assets/grid_003.jpg",
                    grid_path=str(task_dir(task.id) / "grids" / "grid_003.jpg"),
                ),
            ]
            task.summary_diagnostics = {
                "visual_understanding": True,
                "used_vision_llm": True,
                "vision_image_window_ids": ["W001"],
                "missing_vision_image_window_ids": ["W002"],
                "omitted_vision_window_ids": ["W003"],
            }

            manifest = render_bundle_manifest(task, {"segments": []}, {"windows": []})
            windows = manifest["study"]["windows"]
            visual_markdown = render_visual_windows_markdown(task)

            self.assertEqual(windows[0]["vision_status"], "sent_to_vision")
            self.assertEqual(windows[1]["vision_status"], "missing_grid_image")
            self.assertEqual(windows[2]["vision_status"], "omitted_by_limit")
            self.assertEqual(manifest["study"]["vision_sent_count"], 1)
            self.assertEqual(manifest["study"]["vision_missing_image_count"], 1)
            self.assertEqual(manifest["study"]["vision_omitted_count"], 1)
            self.assertIn("视觉模型：已送入视觉模型", visual_markdown)
            self.assertIn(f"/api/tasks/{task.id}/exports/clips/W001", visual_markdown)
            self.assertIn("视觉模型：未送入：缺少网格图片", visual_markdown)
            self.assertIn("视觉模型：未送入：超过视觉窗口上限", visual_markdown)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_subtitle_artifact_is_exported_in_manifest_and_bundle(self) -> None:
        task = create_task("current_page", "Browser subtitle bundle", "https://course.example.com/watch")
        subtitle = task_dir(task.id) / "browser_subtitles.srt"
        subtitle.write_text("1\n00:00:01,000 --> 00:00:03,000\n浏览器字幕\n", encoding="utf-8")
        try:
            update_task(task.id, status="success", phase="completed", progress=100, subtitle_path=str(subtitle))

            subtitle_export = self.client.get(f"/api/tasks/{task.id}/exports/subtitles")
            self.assertEqual(subtitle_export.status_code, 200)
            self.assertIn("attachment", subtitle_export.headers["content-disposition"])
            self.assertIn("-subtitles.srt", subtitle_export.headers["content-disposition"])
            self.assertIn("浏览器字幕", subtitle_export.text)

            manifest_export = self.client.get(f"/api/tasks/{task.id}/exports/manifest")
            self.assertEqual(manifest_export.status_code, 200)
            manifest_payload = manifest_export.json()
            self.assertEqual(manifest_payload["artifacts"]["subtitles"], "subtitles/browser_subtitles.srt")

            bundle = self.client.get(f"/api/tasks/{task.id}/exports/bundle")
            self.assertEqual(bundle.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
                names = set(archive.namelist())
                self.assertIn("subtitles/browser_subtitles.srt", names)
                self.assertIn("浏览器字幕", archive.read("subtitles/browser_subtitles.srt").decode("utf-8"))
                bundled_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                self.assertEqual(bundled_manifest["artifacts"]["subtitles"], "subtitles/browser_subtitles.srt")
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

    def test_rerun_from_media_accepts_nested_options_request(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            video = make_video(Path(tmp))
            source = create_task(
                source_type="current_page",
                title="Nested rerun source",
                page_url="https://course.example.com/watch",
                options=TaskOptions(frame_interval=20, grid_columns=3, grid_rows=3, visual_understanding=True),
                mode="download_only",
            )
            update_task(source.id, status="success", phase="completed", progress=100, media_path=str(video))
            rerun_task_id = ""
            try:
                with patch("app.main.process_local_video_task") as process_task:
                    response = self.client.post(
                        f"/api/tasks/{source.id}/rerun-from-media",
                        json={"options": {"frame_interval": 5, "grid_columns": 4, "grid_rows": 2, "visual_understanding": False}},
                    )
                self.assertEqual(response.status_code, 200)
                rerun_task_id = response.json()["task_id"]
                rerun_task = self.client.get(f"/api/tasks/{rerun_task_id}").json()["task"]
                self.assertEqual(rerun_task["options"]["frame_interval"], 5)
                self.assertEqual(rerun_task["options"]["grid_columns"], 4)
                self.assertEqual(rerun_task["options"]["grid_rows"], 2)
                self.assertEqual(rerun_task["options"]["visual_understanding"], False)
                process_task.assert_called_once()
            finally:
                if rerun_task_id:
                    shutil.rmtree(task_dir(rerun_task_id), ignore_errors=True)
                shutil.rmtree(task_dir(source.id), ignore_errors=True)

    def test_rerun_from_media_rejects_invalid_media_path_before_queueing(self) -> None:
        source = create_task(source_type="current_page", title="Invalid rerun source", page_url="", mode="download_only")
        update_task(source.id, status="success", phase="completed", progress=100, media_path=str(task_dir(source.id)))
        try:
            with patch("app.main.process_local_video_task") as process_task:
                response = self.client.post(f"/api/tasks/{source.id}/rerun-from-media", json={"visual_understanding": False})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"]["code"], "media_not_found")
            process_task.assert_not_called()
        finally:
            shutil.rmtree(task_dir(source.id), ignore_errors=True)

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
                self.assertIn("资料包导览", visual_windows_export.text)
                self.assertIn("直取边界", visual_windows_export.text)
                self.assertIn("不录制标签页：yes", visual_windows_export.text)
                self.assertIn("任务路线：local_video_pipeline", visual_windows_export.text)
                self.assertIn("manifest.json", visual_windows_export.text)
                self.assertIn("帧时间", visual_windows_export.text)
                self.assertIn(f"/api/tasks/{task_id}/exports/clips/W001", visual_windows_export.text)
                self.assertIn("回看检查点", visual_windows_export.text)
                self.assertIn("自测问题", visual_windows_export.text)
                manifest_export = self.client.get(f"/api/tasks/{task_id}/exports/manifest")
                self.assertEqual(manifest_export.status_code, 200)
                self.assertIn("application/json", manifest_export.headers["content-type"])
                self.assertIn("-manifest.json", manifest_export.headers["content-disposition"])
                manifest_direct = manifest_export.json()
                self.assertEqual(manifest_direct["task"]["id"], task_id)
                self.assertEqual(manifest_direct["visual"]["window_count"], len(task["visual_windows"]))
                bundle = self.client.get(f"/api/tasks/{task_id}/exports/bundle")
                self.assertEqual(bundle.status_code, 200)
                self.assertEqual(bundle.headers["content-type"], "application/zip")
                self.assertIn("attachment", bundle.headers["content-disposition"])
                with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
                    names = set(archive.namelist())
                    self.assertIn("diagnostics.md", names)
                    self.assertIn("note.md", names)
                    self.assertIn("manifest.json", names)
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
                    self.assertIn("资料包导览", visual_windows_markdown)
                    self.assertIn("任务路线：local_video_pipeline", visual_windows_markdown)
                    self.assertIn(f"grids/{expected_grid_name}", visual_windows_markdown)
                    self.assertIn(f"/api/tasks/{task_id}/exports/clips/W001", visual_windows_markdown)
                    self.assertIn("帧时间", visual_windows_markdown)
                    self.assertIn("回看检查点", visual_windows_markdown)
                    self.assertIn("自测问题", visual_windows_markdown)
                    self.assertIn("这一段课程讲解函数封装", visual_windows_markdown)
                    diagnostics_report = archive.read("diagnostics.md").decode("utf-8")
                    self.assertIn("LearnNote 任务诊断报告", diagnostics_report)
                    self.assertIn("Local synthetic lesson", diagnostics_report)
                    visual_payload = json.loads(archive.read("visual_index.json").decode("utf-8"))
                    self.assertEqual(visual_payload["task_id"], task_id)
                    manifest_payload = json.loads(archive.read("manifest.json").decode("utf-8"))
                    self.assertEqual(manifest_payload["schema_version"], 1)
                    self.assertEqual(manifest_payload["task"]["id"], task_id)
                    self.assertEqual(manifest_payload["task"]["source_type"], "local")
                    self.assertEqual(manifest_payload["visual"]["window_count"], len(task["visual_windows"]))
                    self.assertEqual(manifest_payload["transcript"]["segment_count"], 2)
                    self.assertEqual(manifest_payload["study"]["review_deck"], "visual_windows.md")
                    self.assertEqual(manifest_payload["study"]["window_count"], len(task["visual_windows"]))
                    self.assertGreaterEqual(manifest_payload["study"]["review_question_count"], len(task["visual_windows"]))
                    self.assertGreaterEqual(manifest_payload["study"]["checkpoint_count"], len(task["visual_windows"]))
                    self.assertEqual(manifest_payload["study"]["windows"][0]["id"], task["visual_windows"][0]["id"])
                    self.assertIn(f"grids/{expected_grid_name}", manifest_payload["study"]["windows"][0]["grid_entry"])
                    self.assertTrue(manifest_payload["study"]["windows"][0]["checkpoints"])
                    self.assertTrue(manifest_payload["study"]["windows"][0]["review_questions"])
                    self.assertIn("这一段课程讲解函数封装", " ".join(manifest_payload["study"]["windows"][0]["checkpoints"]))
                    self.assertEqual(manifest_payload["artifacts"]["note"], "note.md")
                    self.assertIn(f"grids/{expected_grid_name}", manifest_payload["artifacts"]["grid_entries"])
                    self.assertTrue(manifest_payload["audit"]["gates"])
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

    def test_failed_current_page_preserves_attempted_resource_evidence(self) -> None:
        media_url = "https://mooc1.chaoxing.com/ananas/status/lesson.m3u8"
        payload = {
            "mode": "video",
            "page_url": "https://mooc1.chaoxing.com/mycourse/studentstudy",
            "title": "Failed Chaoxing resource",
            "resources": [
                {
                    "url": media_url,
                    "source": "webRequest",
                    "kind": "hls",
                    "mime": "application/vnd.apple.mpegurl",
                    "score": 98,
                    "label": "ananas hls",
                    "request_headers": {
                        "Referer": "https://mooc1.chaoxing.com/mycourse/studentstudy",
                        "Cookie": "secret=bad",
                    },
                }
            ],
        }
        with patch("app.downloader.MediaDownloader._download_candidate", side_effect=DownloadError("download_forbidden", "HTTP 403")):
            with patch("app.downloader.MediaDownloader._discover_page_resources", return_value=[]):
                with patch("app.downloader.MediaDownloader._download_with_ytdlp", side_effect=DownloadError("no_media_found", "no fallback")):
                    response = self.client.post("/api/tasks/from-current-page", json=payload)

        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        try:
            task = self.client.get(f"/api/tasks/{task_id}").json()["task"]

            self.assertEqual(task["status"], "failed")
            self.assertEqual(task["selected_resource"]["url"], media_url)
            self.assertEqual(task["selected_resource"]["kind"], "hls")
            self.assertEqual(task["selected_resource"]["request_headers"]["Referer"], "<redacted>")
            self.assertEqual(task["selected_resource"]["request_headers"]["Cookie"], "<redacted>")
            self.assertEqual(task["download_attempts"][0]["url"], media_url)
            self.assertEqual([attempt["strategy"] for attempt in task["download_attempts"]], ["manifest-ffmpeg", "candidate-ytdlp", "page-ytdlp"])
            self.assertEqual(task["recovery"]["code"], "download_forbidden")
            self.assertEqual(task["recovery"]["selected_kind"], "hls")
            self.assertEqual(task["recovery"]["attempt_count"], 3)
            self.assertTrue(task["recovery"]["is_chaoxing"])
            self.assertIn("不刷课", " ".join(task["recovery"]["boundary_notes"]))
            self.assertIn("学习通/超星", self.client.get(f"/api/tasks/{task_id}/exports/diagnostics").text)
        finally:
            shutil.rmtree(task_dir(task_id), ignore_errors=True)

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
                    "browser_subtitles": [
                        {"start": 0.2, "end": 1.4, "text": "downloaded browser subtitle"},
                        {"start": 1.4, "end": 2.5, "text": "second browser cue"},
                    ],
                    "options": {
                        "visual_understanding": True,
                        "frame_interval": 1,
                        "note_template": "cornell",
                        "summary_depth": "deep",
                        "llm_model": "vision-source-model",
                    },
                }
                with patch("app.processor.extract_audio", side_effect=AssertionError("download_only should not extract audio")):
                    with patch("app.processor.transcribe_audio", side_effect=AssertionError("download_only should not transcribe")):
                        with patch("app.processor.extract_frames", side_effect=AssertionError("download_only should not slice frames")):
                            with patch("app.processor.summarize_with_diagnostics", side_effect=AssertionError("download_only should not summarize")):
                                response = self.client.post("/api/tasks/from-current-page", json=payload)

                self.assertEqual(response.status_code, 200)
                task_id = response.json()["task_id"]
                rerun_task_id = ""
                try:
                    task = self.client.get(f"/api/tasks/{task_id}").json()["task"]
                    self.assertEqual(task["status"], "success")
                    self.assertEqual(task["phase"], "completed")
                    self.assertEqual(task["mode"], "download_only")
                    self.assertTrue(task["audit"]["ok"])
                    audit_gates = {gate["key"]: gate for gate in task["audit"]["gates"]}
                    self.assertEqual(audit_gates["media"]["state"], "pass")
                    self.assertEqual(audit_gates["transcript"]["state"], "pass")
                    self.assertEqual(audit_gates["transcript"]["value"], "browser subtitles saved")
                    self.assertEqual(audit_gates["visual"]["state"], "skip")
                    self.assertEqual(audit_gates["summary"]["state"], "skip")
                    self.assertTrue(Path(task["media_path"]).exists())
                    self.assertFalse(task["audio_path"])
                    self.assertTrue(task["transcript_path"])
                    self.assertTrue(task["subtitle_path"].endswith("browser_subtitles.srt"))
                    self.assertIn("downloaded browser subtitle", Path(task["subtitle_path"]).read_text(encoding="utf-8"))
                    self.assertFalse(task["note_path"])
                    self.assertEqual(task["frame_grids"], [])
                    self.assertEqual(task["visual_windows"], [])
                    self.assertEqual(task["browser_subtitles"][0]["text"], "downloaded browser subtitle")
                    self.assertTrue(task["reuse"]["media_available"])
                    source_media_path = task["media_path"]
                    self.assertTrue(task["reuse"]["subtitle_available"])
                    self.assertTrue(task["reuse"]["transcript_ready"])
                    self.assertEqual(task["reuse"]["transcript_source"], "browser-subtitle")
                    self.assertEqual(task["reuse"]["browser_subtitle_count"], 2)
                    self.assertEqual(task["reuse"]["frame_grid_count"], 0)
                    self.assertTrue(task["reuse"]["rerun_from_media_ready"])
                    self.assertEqual(task["reuse"]["suggested_next_step"], "rerun_from_media")
                    self.assertEqual(task["selected_resource"]["url"], media_url)
                    self.assertEqual(task["download_attempts"][0]["strategy"], "direct-file")
                    self.assertTrue(task["direct_extraction"]["no_tab_recording"])
                    self.assertEqual(task["direct_extraction"]["route"], "download_only_to_local_media")
                    self.assertTrue(task["direct_extraction"]["media_landed"])
                    self.assertEqual(task["direct_extraction"]["selected_candidate"]["kind"], "video")
                    self.assertEqual(task["direct_extraction"]["download"]["successful_attempt_count"], 1)
                    self.assertTrue(task["direct_extraction"]["processing"]["download_only"])
                    media_export = self.client.get(f"/api/tasks/{task_id}/exports/media")
                    self.assertEqual(media_export.status_code, 200)
                    self.assertGreater(len(media_export.content), 1024)
                    subtitle_export = self.client.get(f"/api/tasks/{task_id}/exports/subtitles")
                    self.assertEqual(subtitle_export.status_code, 200)
                    self.assertIn("downloaded browser subtitle", subtitle_export.text)
                    diagnostics_export = self.client.get(f"/api/tasks/{task_id}/exports/diagnostics")
                    self.assertEqual(diagnostics_export.status_code, 200)
                    self.assertIn("text/markdown", diagnostics_export.headers["content-type"])
                    self.assertIn("Download only lesson", diagnostics_export.text)
                    self.assertIn("模式：download_only", diagnostics_export.text)
                    self.assertIn("download-only route", diagnostics_export.text)
                    self.assertIn("browser subtitles saved", diagnostics_export.text)
                    self.assertIn("direct-file", diagnostics_export.text)
                    self.assertIn("## Direct Extraction Evidence", diagnostics_export.text)
                    self.assertIn("No tab recording: yes", diagnostics_export.text)
                    self.assertIn("Route: download_only_to_local_media", diagnostics_export.text)
                    self.assertIn("## Reuse Evidence", diagnostics_export.text)
                    self.assertIn("Saved subtitles: yes", diagnostics_export.text)
                    self.assertIn("Reusable transcript: yes / browser-subtitle", diagnostics_export.text)
                    self.assertIn("Browser subtitles: 2 cues", diagnostics_export.text)
                    self.assertIn("Rerun from media ready: yes", diagnostics_export.text)
                    manifest_export = self.client.get(f"/api/tasks/{task_id}/exports/manifest")
                    self.assertEqual(manifest_export.status_code, 200)
                    manifest_direct = manifest_export.json()
                    self.assertEqual(manifest_direct["task"]["id"], task_id)
                    self.assertEqual(manifest_direct["task"]["mode"], "download_only")
                    self.assertTrue(manifest_direct["audit"]["ok"])
                    self.assertEqual(manifest_direct["source"]["selected_resource"]["url"], media_url)
                    self.assertEqual(manifest_direct["direct_extraction"]["route"], "download_only_to_local_media")
                    self.assertTrue(manifest_direct["direct_extraction"]["no_tab_recording"])
                    self.assertTrue(manifest_direct["direct_extraction"]["media_reusable"])
                    self.assertTrue(manifest_direct["reuse"]["subtitle_available"])
                    self.assertTrue(manifest_direct["reuse"]["transcript_ready"])
                    self.assertEqual(manifest_direct["reuse"]["transcript_source"], "browser-subtitle")
                    self.assertEqual(manifest_direct["reuse"]["browser_subtitle_count"], 2)
                    self.assertTrue(manifest_direct["reuse"]["rerun_from_media_ready"])
                    self.assertEqual(manifest_direct["artifacts"]["note"], "")
                    self.assertEqual(manifest_direct["artifacts"]["subtitles"], "subtitles/browser_subtitles.srt")
                    self.assertTrue(manifest_direct["artifacts"]["media_available"])
                    bundle = self.client.get(f"/api/tasks/{task_id}/exports/bundle")
                    self.assertEqual(bundle.status_code, 200)
                    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
                        names = set(archive.namelist())
                        self.assertIn("diagnostics.md", names)
                        self.assertIn("manifest.json", names)
                        self.assertIn("task.json", names)
                        self.assertIn("transcript.json", names)
                        self.assertIn("subtitles/browser_subtitles.srt", names)
                        self.assertNotIn("note.md", names)
                        self.assertIn("downloaded browser subtitle", archive.read("subtitles/browser_subtitles.srt").decode("utf-8"))
                        self.assertIn("Download only lesson", archive.read("diagnostics.md").decode("utf-8"))
                        manifest_payload = json.loads(archive.read("manifest.json").decode("utf-8"))
                        self.assertEqual(manifest_payload["task"]["id"], task_id)
                        self.assertEqual(manifest_payload["task"]["mode"], "download_only")
                        self.assertTrue(manifest_payload["audit"]["ok"])
                        self.assertEqual(manifest_payload["source"]["selected_resource"]["url"], media_url)
                        self.assertEqual(manifest_payload["direct_extraction"]["route"], "download_only_to_local_media")
                        self.assertTrue(manifest_payload["direct_extraction"]["no_tab_recording"])
                        self.assertTrue(manifest_payload["reuse"]["subtitle_available"])
                        self.assertTrue(manifest_payload["reuse"]["transcript_ready"])
                        self.assertEqual(manifest_payload["reuse"]["transcript_source"], "browser-subtitle")
                        self.assertEqual(manifest_payload["reuse"]["browser_subtitle_count"], 2)
                        self.assertTrue(manifest_payload["reuse"]["rerun_from_media_ready"])
                        self.assertTrue(manifest_payload["artifacts"]["media_available"])
                        self.assertEqual(manifest_payload["artifacts"]["note"], "")
                        self.assertEqual(manifest_payload["artifacts"]["subtitles"], "subtitles/browser_subtitles.srt")
                    self.assertEqual(self.client.get(f"/api/tasks/{task_id}/exports/markdown").status_code, 404)
                    self.assertEqual(self.client.get(f"/api/tasks/{task_id}/note").text, "")
                    transcript_export = self.client.get(f"/api/tasks/{task_id}/transcript").json()
                    self.assertEqual(transcript_export["source"], "browser-subtitle")
                    self.assertIn("downloaded browser subtitle", transcript_export["full_text"])

                    with patch("app.processor.extract_audio", side_effect=AssertionError("rerun should reuse browser subtitles")):
                        with patch("app.processor.transcribe_audio", side_effect=AssertionError("rerun should not run ASR when browser subtitles were saved")):
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
                    self.assertEqual(rerun_task["mode"], "rerun_from_media")
                    self.assertEqual(rerun_task["source_task_id"], task_id)
                    self.assertEqual(rerun_task["source_media_path"], source_media_path)
                    self.assertEqual(rerun_task["page_url"], payload["page_url"])
                    self.assertEqual(rerun_task["options"]["frame_interval"], 1)
                    self.assertEqual(rerun_task["options"]["note_template"], "cornell")
                    self.assertEqual(rerun_task["options"]["summary_depth"], "deep")
                    self.assertEqual(rerun_task["options"]["llm_model"], "vision-source-model")
                    self.assertEqual(rerun_task["selected_resource"]["url"], media_url)
                    self.assertEqual(rerun_task["download_attempts"][0]["strategy"], "direct-file")
                    self.assertEqual(rerun_task["browser_subtitles"][0]["text"], "downloaded browser subtitle")
                    self.assertTrue(Path(rerun_task["media_path"]).exists())
                    self.assertTrue(rerun_task["transcript_path"])
                    rerun_transcript = self.client.get(f"/api/tasks/{rerun_task_id}/transcript").json()
                    self.assertEqual(rerun_transcript["source"], "browser-subtitle")
                    self.assertIn("downloaded browser subtitle", rerun_transcript["full_text"])
                    self.assertTrue(rerun_task["frame_grids"])
                    self.assertTrue(rerun_task["visual_windows"])
                    self.assertEqual(rerun_task["reuse"]["browser_subtitle_count"], 2)
                    self.assertEqual(rerun_task["reuse"]["source_task_id"], task_id)
                    self.assertEqual(rerun_task["reuse"]["source_media_path"], source_media_path)
                    self.assertGreater(rerun_task["reuse"]["frame_grid_count"], 0)
                    self.assertFalse(rerun_task["reuse"]["rerun_from_media_ready"])
                    self.assertEqual(rerun_task["reuse"]["suggested_next_step"], "review_visual_windows")
                    rerun_diagnostics = self.client.get(f"/api/tasks/{rerun_task_id}/exports/diagnostics")
                    self.assertEqual(rerun_diagnostics.status_code, 200)
                    self.assertIn("Browser subtitles: 2 cues", rerun_diagnostics.text)
                    self.assertIn(f"Source task: {task_id}", rerun_diagnostics.text)
                    self.assertIn(f"Source media: {source_media_path}", rerun_diagnostics.text)
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
                        rerun_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                        self.assertEqual(rerun_manifest["task"]["source_task_id"], task_id)
                        self.assertEqual(rerun_manifest["task"]["source_media_path"], source_media_path)
                        self.assertEqual(rerun_manifest["reuse"]["browser_subtitle_count"], 2)
                        self.assertEqual(rerun_manifest["reuse"]["source_task_id"], task_id)
                        self.assertEqual(rerun_manifest["reuse"]["source_media_path"], source_media_path)
                        self.assertEqual(rerun_manifest["direct_extraction"]["route"], "local_video_pipeline")
                        self.assertTrue(rerun_manifest["direct_extraction"]["no_tab_recording"])
                finally:
                    if rerun_task_id:
                        shutil.rmtree(task_dir(rerun_task_id), ignore_errors=True)
                    shutil.rmtree(task_dir(task_id), ignore_errors=True)
            finally:
                server.shutdown()
                server.server_close()

    def test_rerun_reuses_saved_browser_subtitle_file_without_cues(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            video = make_video(Path(tmp))
            source = create_task("current_page", "Saved browser subtitle lesson", "https://course.example.com/watch", mode="download_only")
            source_dir = task_dir(source.id)
            media = source_dir / "media.mp4"
            subtitle = source_dir / "browser_subtitles.srt"
            transcript_path = source_dir / "transcript.json"
            rerun_task_id = ""
            try:
                shutil.copy2(video, media)
                subtitle.write_text(
                    "\n".join([
                        "1",
                        "00:00:00.000 --> 00:00:02.000",
                        "saved browser subtitle line one",
                        "",
                        "2",
                        "00:00:02.000 --> 00:00:04.000",
                        "saved browser subtitle line two",
                        "",
                    ]),
                    encoding="utf-8",
                )
                transcript_path.write_text(
                    TranscriptResult(
                        source="browser-subtitle",
                        full_text="saved browser subtitle line one\nsaved browser subtitle line two",
                        segments=[
                            TranscriptSegment(start=0, end=2, text="saved browser subtitle line one"),
                            TranscriptSegment(start=2, end=4, text="saved browser subtitle line two"),
                        ],
                    ).model_dump_json(indent=2),
                    encoding="utf-8",
                )
                update_task(
                    source.id,
                    status="success",
                    phase="completed",
                    progress=100,
                    media_path=str(media),
                    subtitle_path=str(subtitle),
                    transcript_path=str(transcript_path),
                    browser_subtitles=[],
                )

                with patch("app.processor.extract_audio", side_effect=AssertionError("rerun should reuse saved browser subtitle file")):
                    with patch("app.processor.transcribe_audio", side_effect=AssertionError("rerun should not run ASR when saved browser subtitle file exists")):
                        response = self.client.post(
                            f"/api/tasks/{source.id}/rerun-from-media",
                            json={"visual_understanding": False},
                        )

                self.assertEqual(response.status_code, 200)
                rerun_task_id = response.json()["task_id"]
                rerun_task = self.client.get(f"/api/tasks/{rerun_task_id}").json()["task"]
                self.assertEqual(rerun_task["status"], "success")
                self.assertEqual(rerun_task["browser_subtitles"], [])
                self.assertFalse(rerun_task["audio_path"])
                self.assertTrue(rerun_task["subtitle_path"])
                self.assertEqual(Path(rerun_task["subtitle_path"]).parent, task_dir(rerun_task_id))
                rerun_transcript = self.client.get(f"/api/tasks/{rerun_task_id}/transcript").json()
                self.assertEqual(rerun_transcript["source"], "browser-subtitle")
                self.assertIn("saved browser subtitle line two", rerun_transcript["full_text"])
                self.assertEqual(rerun_task["reuse"]["transcript_source"], "browser-subtitle")
                self.assertEqual(rerun_task["reuse"]["browser_subtitle_count"], 0)
            finally:
                if rerun_task_id:
                    shutil.rmtree(task_dir(rerun_task_id), ignore_errors=True)
                shutil.rmtree(task_dir(source.id), ignore_errors=True)

    def test_current_page_download_only_saves_page_subtitle_without_full_processing(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_RUN_DIR) as tmp:
            root = Path(tmp)
            video = make_video(root)
            subtitle = root / "download-only.vtt"
            subtitle.write_text(
                "\n".join([
                    "WEBVTT",
                    "",
                    "00:00:00.000 --> 00:00:02.000",
                    "platform subtitle line one",
                    "",
                    "00:00:02.000 --> 00:00:04.000",
                    "platform subtitle line two",
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
                    "mode": "download_only",
                    "page_url": f"http://127.0.0.1:{server.server_port}/lesson.html",
                    "title": "Download only subtitle lesson",
                    "resources": [
                        {"url": media_url, "source": "webRequest", "kind": "video", "mime": "video/mp4", "score": 100},
                        {"url": subtitle_url, "source": "subtitleTrack", "kind": "subtitle", "mime": "text/vtt", "score": 80},
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
                rerun_task_id = ""
                try:
                    task = self.client.get(f"/api/tasks/{task_id}").json()["task"]
                    self.assertEqual(task["status"], "success")
                    self.assertEqual(task["mode"], "download_only")
                    self.assertTrue(Path(task["media_path"]).exists())
                    self.assertTrue(task["subtitle_path"])
                    self.assertTrue(task["transcript_path"])
                    self.assertFalse(task["audio_path"])
                    self.assertFalse(task["note_path"])
                    self.assertEqual(task["frame_grids"], [])
                    self.assertTrue(any(attempt["strategy"] == "subtitle-file" and attempt["status"] == "success" for attempt in task["download_attempts"]))
                    self.assertTrue(task["reuse"]["subtitle_available"])
                    self.assertTrue(task["reuse"]["transcript_ready"])
                    self.assertEqual(task["reuse"]["transcript_source"], "page-subtitle")
                    audit_gates = {gate["key"]: gate for gate in task["audit"]["gates"]}
                    self.assertEqual(audit_gates["transcript"]["state"], "pass")
                    transcript = self.client.get(f"/api/tasks/{task_id}/transcript").json()
                    self.assertEqual(transcript["source"], "page-subtitle")
                    self.assertIn("platform subtitle line one", transcript["full_text"])
                    subtitle_export = self.client.get(f"/api/tasks/{task_id}/exports/subtitles")
                    self.assertEqual(subtitle_export.status_code, 200)
                    self.assertIn("platform subtitle line two", subtitle_export.text)
                    diagnostics_export = self.client.get(f"/api/tasks/{task_id}/exports/diagnostics")
                    self.assertEqual(diagnostics_export.status_code, 200)
                    self.assertIn("Saved subtitles: yes", diagnostics_export.text)
                    self.assertIn("Reusable transcript: yes / page-subtitle", diagnostics_export.text)
                    manifest_export = self.client.get(f"/api/tasks/{task_id}/exports/manifest")
                    self.assertEqual(manifest_export.status_code, 200)
                    manifest_payload = manifest_export.json()
                    self.assertTrue(manifest_payload["reuse"]["subtitle_available"])
                    self.assertTrue(manifest_payload["reuse"]["transcript_ready"])
                    self.assertEqual(manifest_payload["reuse"]["transcript_source"], "page-subtitle")
                    self.assertEqual(self.client.get(f"/api/tasks/{task_id}/exports/markdown").status_code, 404)

                    with patch("app.processor.extract_audio", side_effect=AssertionError("rerun should reuse page subtitle")):
                        with patch("app.processor.transcribe_audio", side_effect=AssertionError("rerun should not run ASR when page subtitle was saved")):
                            rerun_response = self.client.post(
                                f"/api/tasks/{task_id}/rerun-from-media",
                                json={"visual_understanding": True, "frame_interval": 1},
                            )
                    self.assertEqual(rerun_response.status_code, 200)
                    rerun_task_id = rerun_response.json()["task_id"]
                    rerun_task = self.client.get(f"/api/tasks/{rerun_task_id}").json()["task"]
                    self.assertEqual(rerun_task["status"], "success")
                    self.assertFalse(rerun_task["audio_path"])
                    self.assertTrue(rerun_task["subtitle_path"])
                    self.assertEqual(Path(rerun_task["subtitle_path"]).parent, task_dir(rerun_task_id))
                    self.assertTrue(Path(rerun_task["subtitle_path"]).exists())
                    self.assertTrue(rerun_task["transcript_path"])
                    self.assertTrue(rerun_task["frame_grids"])
                    rerun_transcript = self.client.get(f"/api/tasks/{rerun_task_id}/transcript").json()
                    self.assertEqual(rerun_transcript["source"], "page-subtitle")
                    self.assertIn("platform subtitle line two", rerun_transcript["full_text"])
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
