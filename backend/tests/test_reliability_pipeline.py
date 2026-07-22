from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main as main_module
from app.config import DATA_DIR, UPLOAD_DIR
from app.main import STAGED_UPLOAD_MAX_AGE_SECONDS, app, build_handoff_integrity, cleanup_expired_staged_uploads, local_upload_filename
from app.media import _adaptive_frame_plan, probe_media_integrity
from app.models import CurrentPageTaskRequest, EvidenceCoverage, FrameSample, MediaIntegrity, ResourceCandidate, TaskOptions, TranscriptResult, TranscriptSegment
from app.processor import ContentMismatchError, _process_video_file
from app.reliability import calculate_evidence_coverage, current_page_source_identity, evidence_coverage_markdown, validate_source_identity
from app.runtime import ffmpeg_bin
from app.storage import create_task, get_task, task_dir


TEST_RUN_DIR = DATA_DIR / "test-runs"


class EvidenceCoverageTests(unittest.TestCase):
    def test_opening_only_transcript_is_blocked(self) -> None:
        integrity = MediaIntegrity(status="ready", duration=100, has_video=True, has_audio=True)
        transcript = TranscriptResult(
            source="faster-whisper",
            segments=[TranscriptSegment(start=0, end=12, text="Opening material with enough characters to look plausible.")],
            full_text="Opening material with enough characters to look plausible.",
        )
        frames = [
            FrameSample(path=f"frame-{value}.jpg", timestamp=value)
            for value in (10, 30, 50, 70, 90)
        ]

        coverage = calculate_evidence_coverage(integrity, transcript, frames, visual_enabled=True)

        self.assertFalse(coverage.can_summarize)
        self.assertIn("transcript_coverage", coverage.blocking_reasons)
        self.assertIn("timeline_consistency", coverage.blocking_reasons)

    def test_distributed_transcript_and_frames_pass(self) -> None:
        integrity = MediaIntegrity(status="ready", duration=100, has_video=True, has_audio=True)
        segments = [
            TranscriptSegment(start=value - 5, end=value + 5, text=f"Supported lesson point around {value} seconds.")
            for value in (10, 30, 50, 70, 90)
        ]
        transcript = TranscriptResult(
            source="faster-whisper",
            segments=segments,
            full_text=" ".join(segment.text for segment in segments),
        )
        frames = [FrameSample(path=f"frame-{value}.jpg", timestamp=value) for value in (10, 30, 50, 70, 90)]

        coverage = calculate_evidence_coverage(integrity, transcript, frames, visual_enabled=True)

        self.assertTrue(coverage.can_summarize)
        self.assertGreaterEqual(coverage.transcript_coverage_ratio, 0.25)
        self.assertEqual(coverage.matched_transcript_checkpoints, 5)

    def test_single_track_is_blocked_even_with_timed_subtitle(self) -> None:
        integrity = MediaIntegrity(status="video_only", duration=20, has_video=True, has_audio=False)
        missing = calculate_evidence_coverage(
            integrity,
            TranscriptResult(source="no-audio"),
            [],
            visual_enabled=False,
        )
        subtitle = TranscriptResult(
            source="browser-subtitle",
            segments=[TranscriptSegment(start=0, end=20, text="A complete browser subtitle provides the textual basis.")],
            full_text="A complete browser subtitle provides the textual basis.",
        )
        allowed = calculate_evidence_coverage(integrity, subtitle, [], visual_enabled=False)

        self.assertFalse(missing.can_summarize)
        self.assertIn("media_tracks", missing.blocking_reasons)
        self.assertFalse(allowed.can_summarize)
        self.assertIn("media_tracks", allowed.blocking_reasons)

    def test_note_evidence_appendix_is_user_facing_chinese(self) -> None:
        integrity = MediaIntegrity(status="ready", has_video=True, has_audio=True, has_subtitles=False)
        coverage = EvidenceCoverage(
            status="ready",
            can_summarize=True,
            transcript_source="browser-subtitle",
            transcript_coverage_ratio=0.75,
            platform_subtitle_coverage_ratio=0.75,
            visual_frame_count=12,
        )

        markdown = evidence_coverage_markdown(integrity, coverage)

        self.assertIn("## 依据与覆盖", markdown)
        self.assertIn("平台或浏览器字幕覆盖", markdown)
        self.assertIn("本地转写覆盖", markdown)
        self.assertIn("轨道完整性", markdown)
        self.assertNotIn("Media integrity", markdown)

    def test_adaptive_plan_reserves_full_timeline_coverage(self) -> None:
        plan = _adaptive_frame_plan(
            duration=120,
            interval=20,
            max_frames=10,
            scene_timestamps=list(range(1, 80)),
            anchor_timestamps=None,
        )
        timestamps = [timestamp for timestamp, _reasons in plan]
        reasons = {reason for _timestamp, values in plan for reason in values}

        self.assertEqual(len(plan), 10)
        self.assertIn(0, timestamps)
        self.assertGreaterEqual(max(timestamps), 100)
        self.assertIn("content_change", reasons)
        self.assertIn("interaction_context", reasons)

    def test_processor_hard_blocks_before_summary_call(self) -> None:
        task = create_task("local", "Reliability gate", mode="local")
        source = task_dir(task.id) / "source.mp4"
        subtitle = task_dir(task.id) / "source.srt"
        source.write_bytes(b"media")
        subtitle.write_text("subtitle", encoding="utf-8")
        transcript = TranscriptResult(
            source="page-subtitle",
            segments=[TranscriptSegment(start=0, end=10, text="Only the opening section is available as subtitle evidence.")],
            full_text="Only the opening section is available as subtitle evidence.",
        )

        def normalize(_source: Path, output: Path) -> Path:
            output.write_bytes(b"normalized")
            return output

        try:
            with (
                patch("app.processor.probe_media_integrity", return_value=MediaIntegrity(
                    status="ready",
                    duration=100,
                    has_video=True,
                    has_audio=True,
                    sha256="abc",
                )),
                patch("app.processor.normalize_video", side_effect=normalize),
                patch("app.processor.parse_subtitle_or_none", return_value=transcript),
                patch("app.processor.summarize_with_diagnostics") as summarize,
            ):
                with self.assertRaises(ContentMismatchError):
                    _process_video_file(
                        task.id,
                        source,
                        task.title,
                        "",
                        TaskOptions(visual_understanding=False),
                        subtitle_path=subtitle,
                    )

            summarize.assert_not_called()
            saved = get_task(task.id)
            self.assertEqual(saved.evidence_coverage.status, "blocked")
            self.assertTrue(Path(saved.evidence_coverage_path).is_file())
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_current_page_identity_detects_resource_or_title_change(self) -> None:
        original = CurrentPageTaskRequest(
            page_url="https://www.bilibili.com/video/BV1xx411c7mD?p=1",
            title="Lesson A",
            resources=[ResourceCandidate(url="https://cdn.example/video.m4s", kind="video")],
        )
        switched = original.model_copy(update={
            "title": "Lesson B",
            "resources": [ResourceCandidate(url="https://cdn.example/other.m4s", kind="video")],
        })

        expected = current_page_source_identity(original)
        actual = current_page_source_identity(switched)
        reasons = validate_source_identity(expected, actual)

        self.assertIn("resource_fingerprint_changed", reasons)
        self.assertIn("title_changed", reasons)
        self.assertEqual(expected.platform_id, "BV1xx411c7mD")


@unittest.skipUnless(ffmpeg_bin(), "ffmpeg is required for media integrity tests")
class LocalMediaContractTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_RUN_DIR.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEST_RUN_DIR)
        self.root = Path(self.temp.name)
        self.ffmpeg = ffmpeg_bin()
        assert self.ffmpeg is not None

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _video_bytes(self) -> bytes:
        path = self.root / "lesson.m4s"
        subprocess.run([
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=160x90:rate=5",
            "-an",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "mp4",
            str(path),
        ], check=True)
        return path.read_bytes()

    def test_m4s_extension_and_structured_probe(self) -> None:
        self.assertEqual(local_upload_filename("lesson.m4s"), "lesson.m4s")
        path = self.root / "lesson.m4s"
        path.write_bytes(self._video_bytes())

        integrity = probe_media_integrity(path)

        self.assertEqual(integrity.status, "video_only")
        self.assertTrue(integrity.has_video)
        self.assertFalse(integrity.has_audio)
        self.assertTrue(integrity.video_codec)
        self.assertEqual(integrity.stream_count, 1)
        self.assertEqual(len(integrity.sha256), 64)

    def test_preflight_token_can_create_task_without_reupload(self) -> None:
        client = TestClient(app)
        with patch("app.main.process_local_video_task"):
            preflight = client.post(
                "/api/media/preflight-local",
                files={"file": ("lesson.m4s", self._video_bytes(), "video/iso.segment")},
            )
            self.assertEqual(preflight.status_code, 200, preflight.text)
            body = preflight.json()
            self.assertEqual(body["integrity"]["status"], "video_only")
            self.assertTrue(body["source_fingerprint"])
            created = client.post(
                "/api/tasks/from-local",
                data={"staging_token": body["staging_token"], "options": "{}"},
            )
        self.assertEqual(created.status_code, 200, created.text)
        task_id = created.json()["task_id"]
        try:
            payload = created.json()["task"]
            self.assertEqual(payload["media_integrity"]["status"], "video_only")
            self.assertEqual(payload["source_identity"]["resource_fingerprint"], body["source_fingerprint"])
            self.assertEqual(payload["workflow_stage"], "acquire_media")
            self.assertGreater(payload["eta_seconds"], 0)
        finally:
            task = get_task(task_id)
            Path(task.source_media_path).unlink(missing_ok=True)
            shutil.rmtree(task_dir(task_id), ignore_errors=True)

    def test_expired_staged_upload_is_removed(self) -> None:
        staged = UPLOAD_DIR / "staged_00000000000000000000000000000000_expired.m4s"
        staged.write_bytes(b"expired")
        old = time.time() - STAGED_UPLOAD_MAX_AGE_SECONDS - 60
        staged.touch()
        os.utime(staged, (old, old))
        try:
            removed = cleanup_expired_staged_uploads(now=time.time())
            self.assertEqual(removed, 1)
            self.assertFalse(staged.exists())
        finally:
            staged.unlink(missing_ok=True)


class DeferredHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.payload = {
            "page_url": "https://www.bilibili.com/video/BV1xx411c7mD?p=1",
            "title": "Deferred lesson",
            "resources": [{
                "url": "https://cdn.example.com/video.m4s",
                "kind": "video",
                "score": 90,
                "audio_url": "https://cdn.example.com/audio.m4s",
                "request_headers": {"Referer": "https://www.bilibili.com/"},
            }],
            "active_video": {"src": "blob:https://www.bilibili.com/player", "duration": 180, "width": 1280, "height": 720},
            "browser_subtitles": [{"start": 0, "end": 5, "text": "First supported subtitle cue"}],
            "cookies": [{"name": "SESSDATA", "value": "secret", "domain": ".bilibili.com"}],
            "options": {"frame_interval": 20, "llm_api_key": "secret-key"},
        }

    def _cleanup(self, task_id: str) -> None:
        with main_module._deferred_handoffs_lock:
            main_module._deferred_handoffs.pop(task_id, None)
        shutil.rmtree(task_dir(task_id), ignore_errors=True)

    def test_deferred_handoff_waits_for_start_and_redacts_disk_copy(self) -> None:
        with patch("app.main.process_current_page_task") as process:
            created = self.client.post("/api/tasks/from-current-page?defer=true", json=self.payload)
            self.assertEqual(created.status_code, 200, created.text)
            task_id = created.json()["task_id"]
            try:
                task = created.json()["task"]
                self.assertTrue(task["awaiting_confirmation"])
                self.assertEqual(task["status"], "queued")
                self.assertTrue(task["handoff_integrity"]["provisional"])
                self.assertTrue(task["handoff_integrity"]["has_video"])
                self.assertTrue(task["handoff_integrity"]["has_audio"])
                self.assertTrue(task["handoff_integrity"]["has_subtitles"])
                self.assertEqual(task["handoff_integrity"]["duration"], 180)
                self.assertEqual(task["selected_resource"]["url"], "https://cdn.example.com/video.m4s")
                self.assertEqual(task["active_video"]["duration"], 180)
                self.assertEqual(len(task["browser_subtitles"]), 1)
                process.assert_not_called()
                redacted = (task_dir(task_id) / "deferred_preflight.json").read_text(encoding="utf-8")
                self.assertNotIn("secret-key", redacted)
                self.assertNotIn('"secret"', redacted)

                started = self.client.post(
                    f"/api/tasks/{task_id}/start",
                    json={"frame_interval": 12},
                )
                self.assertEqual(started.status_code, 200, started.text)
                self.assertFalse(started.json()["task"]["awaiting_confirmation"])
                process.assert_called_once()
                deferred_request = process.call_args.args[1]
                self.assertEqual(deferred_request.options.frame_interval, 12)
                self.assertEqual(deferred_request.options.llm_api_key, "secret-key")
                with main_module._deferred_handoffs_lock:
                    self.assertNotIn(task_id, main_module._deferred_handoffs)
            finally:
                self._cleanup(task_id)

    def test_missing_in_memory_handoff_returns_expired(self) -> None:
        created = self.client.post("/api/tasks/from-current-page?defer=true", json=self.payload)
        self.assertEqual(created.status_code, 200, created.text)
        task_id = created.json()["task_id"]
        try:
            with main_module._deferred_handoffs_lock:
                main_module._deferred_handoffs.pop(task_id, None)
            response = self.client.post(f"/api/tasks/{task_id}/start", json={})
            self.assertEqual(response.status_code, 410)
            self.assertEqual(response.json()["detail"]["code"], "handoff_expired")
        finally:
            self._cleanup(task_id)

    def test_subtitles_do_not_imply_handoff_audio(self) -> None:
        request = CurrentPageTaskRequest(
            page_url="https://example.com/lesson",
            browser_subtitles=[{"start": 0, "end": 5, "text": "Subtitle only"}],
            resources=[ResourceCandidate(url="https://cdn.example.com/video.m4s", kind="video")],
        )

        integrity = build_handoff_integrity(request)

        self.assertTrue(integrity.has_video)
        self.assertTrue(integrity.has_subtitles)
        self.assertFalse(integrity.has_audio)
        self.assertEqual(integrity.status, "video_only")


if __name__ == "__main__":
    unittest.main()
