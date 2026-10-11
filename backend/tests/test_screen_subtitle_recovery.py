from contextlib import ExitStack
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from PIL import Image
from app.models import MediaIntegrity, ScreenSubtitleSettings, TaskOptions
from app.screen_subtitles import ScreenOcrError, sample_frames
from app import screen_subtitle_tasks as processing, storage


class ScreenSubtitleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.stack = ExitStack()
        for module in ("app.storage.TASK_DIR", "app.observability.TASK_DIR"):
            self.stack.enter_context(patch(module, self.root / "tasks"))
        self.stack.enter_context(patch("app.storage.ensure_dirs", lambda: None))
        self.media = self.root / "video.mp4"; self.media.write_bytes(b"synthetic-video")
        self.options = TaskOptions(content_mode="subtitles", screen_subtitles=ScreenSubtitleSettings())
        self.task = storage.create_task("local", "Synthetic OCR", options=self.options, mode="screen_subtitles")
        storage.update_task(self.task.id, media_path=str(self.media))
        self.report_path = storage.task_dir(self.task.id) / "screen_subtitles.json"

    def tearDown(self):
        self.stack.close(); self.temp.cleanup()

    def extraction(self, path, settings, cache, **kwargs):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if kwargs.get("expected_media_sha256") and kwargs["expected_media_sha256"] != digest:
            raise ScreenOcrError("media_changed")
        report = {"media": {"duration": 1}, "media_sha256": digest, "fingerprint": "a" * 64,
            "settings": settings.model_dump(), "engine": {"version": "fixture"}, "warning": "未人工核验",
            "status": "running", "completed_windows": 0, "total_windows": 1, "cache_hits": 0,
            "coverage": {"complete": False, "sampled_seconds": 0, "requested_seconds": 1}, "cues": []}
        kwargs["progress"](report)
        report.update(status="ready", completed_windows=1, cues=[{"start": 0, "end": 1, "text": "合成字幕"}])
        report["coverage"].update(complete=True, sampled_seconds=1)
        kwargs["progress"](report)
        return report

    def run_task(self, options=None):
        with patch.object(processing, "extract", side_effect=self.extraction):
            processing.process_screen_subtitle_task(self.task.id, self.media, options or self.options)
        return storage.get_task(self.task.id)

    def test_corrupt_report_recovers_from_ocr_identity_and_preserves_original_bytes(self):
        self.assertEqual(self.run_task().status, "success")
        self.report_path.write_bytes(b"{broken\xff")
        self.assertEqual(self.run_task().status, "success")
        backups = list(self.report_path.parent.glob("screen_subtitles.corrupt-*.json"))
        self.assertEqual(len(backups), 1); self.assertEqual(backups[0].read_bytes(), b"{broken\xff")
        self.assertEqual(json.loads(self.report_path.read_text(encoding="utf-8"))["status"], "ready")

    def test_missing_report_cannot_rebind_a_changed_media_file(self):
        original = self.run_task().screen_subtitles_media_sha256
        self.report_path.unlink(); self.media.write_bytes(b"different-media")
        task = self.run_task()
        self.assertEqual(task.error_code, "screen_ocr_media_changed")
        self.assertEqual(task.screen_subtitles_media_sha256, original)
        self.assertFalse(self.report_path.exists())

    def test_conflicting_or_missing_history_fails_without_overwriting_report(self):
        self.run_task(); self.report_path.write_text(json.dumps({"media_sha256": "b" * 64}))
        original = self.report_path.read_bytes()
        self.assertEqual(self.run_task().status, "failed"); self.assertEqual(self.report_path.read_bytes(), original)
        storage.update_task(self.task.id, screen_subtitles_media_sha256="")
        self.report_path.write_text("{broken")
        self.assertEqual(self.run_task().status, "failed"); self.assertEqual(self.report_path.read_text(encoding="utf-8"), "{broken")

    def test_first_ocr_does_not_confuse_original_input_hash_with_normalized_media_hash(self):
        storage.update_task(self.task.id, media_integrity=MediaIntegrity(sha256="b" * 64))
        task = self.run_task()
        self.assertEqual(task.status, "success")
        self.assertEqual(task.screen_subtitles_media_sha256, hashlib.sha256(self.media.read_bytes()).hexdigest())

    def test_summary_reuse_checks_media_and_transcript_identity_before_model_or_backup(self):
        from app.processor import process_saved_transcript_task
        task = self.run_task(); transcript = Path(task.transcript_path)
        original_transcript, original_note = transcript.read_bytes(), Path(task.note_path).read_bytes()
        options = self.options.model_copy(update={"content_mode": "text"})
        with patch("app.processor.finish_transcript_note") as finish, patch("app.summary_versions.snapshot_summary"):
            process_saved_transcript_task(task.id, options)
        finish.assert_called_once()
        for change in ("in_place", "replacement", "missing", "transcript_identity"):
            with self.subTest(change=change):
                self.media.write_bytes(b"synthetic-video"); transcript.write_bytes(original_transcript)
                if change == "in_place": self.media.write_bytes(b"different-video")
                elif change == "replacement":
                    replacement = self.media.with_suffix(".new"); replacement.write_bytes(b"replacement-video"); replacement.replace(self.media)
                elif change == "missing": self.media.unlink()
                else:
                    data = json.loads(original_transcript); data["provenance"]["media_sha256"] = "a" * 64
                    transcript.write_text(json.dumps(data))
                with patch("app.processor.finish_transcript_note") as finish, patch("app.summary_versions.snapshot_summary") as backup:
                    process_saved_transcript_task(task.id, options)
                finish.assert_not_called(); backup.assert_not_called()
                self.assertEqual(storage.get_task(task.id).error_code, "transcript_unavailable")
                self.assertEqual(Path(task.note_path).read_bytes(), original_note)

    def test_cancel_during_export_cannot_be_overwritten_by_success(self):
        write = processing.atomic_write_text
        def cancel_at_note(path, text):
            write(path, text)
            if path.name == "screen_subtitles.md": storage.request_task_cancel(self.task.id)
        with patch.object(processing, "atomic_write_text", side_effect=cancel_at_note): task = self.run_task()
        self.assertEqual(task.status, "cancelled")
        metrics = storage.read_json(self.task.id, "pipeline_metrics.json", {})
        self.assertEqual(metrics["attempts"][-1]["status"], "cancelled")

    def test_cancelled_summary_finishes_extraction_attempt_before_its_own_attempt(self):
        from app.pipeline_progress import start_pipeline_attempt, finish_pipeline_attempt
        def summary(task_id, options):
            attempt = start_pipeline_attempt(task_id)
            storage.request_task_cancel(task_id); storage.mark_task_cancelled(task_id)
            finish_pipeline_attempt(task_id, "cancelled", expected_attempt_id=attempt)
        with patch("app.processor.process_saved_transcript_task", side_effect=summary):
            task = self.run_task(self.options.model_copy(update={"content_mode": "text"}))
        self.assertEqual(task.status, "cancelled")
        self.assertEqual([a["status"] for a in storage.read_json(self.task.id, "pipeline_metrics.json", {})["attempts"]], ["completed", "cancelled"])

    def test_legacy_range_offsets_and_nested_ranges_keep_original_time(self):
        from app.range_learning import create_range_task
        storage.update_task(self.task.id, learning_range={"start": 60, "end": 120})
        task = self.run_task()
        self.assertEqual(json.loads(Path(task.transcript_path).read_text(encoding="utf-8"))["provenance"]["original_time_offset"], 60)
        task = storage.update_task(task.id, media_integrity=MediaIntegrity(duration=60))
        with patch("app.range_learning.DATA_DIR", self.root), patch("app.range_learning.schedule_processing"):
            child = create_range_task(task.id, 10, 20, self.options, BackgroundTasks())
        self.assertEqual(child.learning_range["original_start"], 70)
        self.assertEqual(child.learning_range["original_end"], 80)

    def test_ranges_require_final_owned_clip_and_never_fall_back_to_original(self):
        from app.screen_subtitle_routes import create_screen_subtitles, ScreenSubtitleRequest
        task = storage.update_task(self.task.id, mode="video", status="failed", learning_range={"start": 60, "end": 120}, source_media_path=str(self.media))
        with self.assertRaises(HTTPException): create_screen_subtitles(task.id, ScreenSubtitleRequest(), BackgroundTasks())
        clip = storage.task_dir(task.id) / "selected-range-source.mp4"; clip.write_bytes(b"synthetic-final-slice")
        with patch("app.screen_subtitle_routes.media_info", return_value={"duration": 60}), patch("app.screen_subtitle_routes.schedule_processing"):
            created = create_screen_subtitles(task.id, ScreenSubtitleRequest(), BackgroundTasks())
            retained = Path(created["task"]["media_path"])
            self.assertNotEqual(retained, clip)
            self.assertTrue(retained.samefile(clip))
            storage.update_task(created["task_id"], status="success")
            nested = create_screen_subtitles(created["task_id"], ScreenSubtitleRequest(), BackgroundTasks())
            self.assertTrue(Path(nested["task"]["media_path"]).samefile(clip))
        clip.unlink()
        with self.assertRaises(HTTPException): create_screen_subtitles(task.id, ScreenSubtitleRequest(), BackgroundTasks())

    def test_source_directory_deletion_keeps_ocr_media_and_range_resume(self):
        from app.screen_subtitle_routes import create_screen_subtitles, resume_screen_subtitles, ScreenSubtitleRequest
        task = storage.update_task(self.task.id, mode="video", status="failed", learning_range={"start": 60, "end": 120})
        original = storage.task_dir(task.id) / "selected-range.mp4"
        original.write_bytes(b"synthetic-owned-clip")
        with patch("app.screen_subtitle_routes.media_info", return_value={"duration": 60}), patch("app.screen_subtitle_routes.schedule_processing"):
            result = create_screen_subtitles(task.id, ScreenSubtitleRequest(), BackgroundTasks())
        retained = Path(result["task"]["media_path"])
        self.assertTrue(retained.samefile(original))
        with patch("app.storage.DATA_DIR", self.root), patch("app.storage.remove_task", return_value=True):
            storage.delete_task(task.id)
        self.assertFalse(original.exists()); self.assertEqual(retained.read_bytes(), b"synthetic-owned-clip")
        storage.update_task(result["task_id"], status="cancelled")
        with patch("app.screen_subtitle_routes.media_info", return_value={"duration": 60}), patch("app.screen_subtitle_routes.schedule_processing") as schedule:
            resume_screen_subtitles(result["task_id"], BackgroundTasks())
        self.assertEqual(schedule.call_args.args[3], retained)

    def test_retention_failure_stops_before_queueing_and_never_deletes_source(self):
        from app.screen_subtitle_routes import create_screen_subtitles, ScreenSubtitleRequest
        from app.range_learning import create_range_task
        original = storage.task_dir(self.task.id) / "source.mp4"; original.write_bytes(b"synthetic-owned-video")
        storage.update_task(self.task.id, status="success", media_path=str(original))
        with patch("app.screen_subtitle_media.os.link", side_effect=OSError("private path")), patch("app.screen_subtitle_routes.schedule_processing") as schedule:
            with self.assertRaises(HTTPException) as raised:
                create_screen_subtitles(self.task.id, ScreenSubtitleRequest(), BackgroundTasks())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertNotIn("private path", str(raised.exception.detail)); schedule.assert_not_called()
        self.assertEqual(original.read_bytes(), b"synthetic-owned-video")
        failed = [task for task in storage.list_tasks() if task.id != self.task.id]
        self.assertEqual(failed, [])
        self.assertEqual(list((self.root / "tasks").glob(".screen-subtitles-*")), [])
        storage.update_task(self.task.id, media_integrity=MediaIntegrity(duration=60))
        with patch("app.screen_subtitle_media.os.link", side_effect=OSError("unsupported")), patch("app.range_learning.DATA_DIR", self.root), patch("app.range_learning.schedule_processing") as schedule:
            with self.assertRaises(HTTPException):
                create_range_task(self.task.id, 10, 20, self.options, BackgroundTasks())
        schedule.assert_not_called()
        self.assertEqual([task.id for task in storage.list_tasks()], [self.task.id])

    def test_retained_video_keeps_container_type_for_playback_and_download(self):
        from app.main import api_preview_media, api_export_media
        from app.screen_subtitle_routes import create_screen_subtitles, ScreenSubtitleRequest
        for suffix, content_type in ((".mp4", "video/mp4"), (".mkv", "video/x-matroska")):
            with self.subTest(suffix=suffix):
                original = storage.task_dir(self.task.id) / ("source" + suffix)
                original.write_bytes(b"synthetic-container")
                storage.update_task(self.task.id, status="success", media_path=str(original))
                with patch("app.screen_subtitle_routes.schedule_processing"):
                    child = create_screen_subtitles(self.task.id, ScreenSubtitleRequest(), BackgroundTasks())["task_id"]
                retained = Path(storage.get_task(child).media_path)
                self.assertTrue(retained.samefile(original)); self.assertEqual(retained.suffix, suffix)
                for response in (api_preview_media(child), api_export_media(child)):
                    self.assertEqual(response.media_type, content_type)
                    self.assertIn("screen-subtitles-source" + suffix, response.headers["content-disposition"])

    def test_pending_range_keeps_original_media_before_clipping_after_source_deletion(self):
        from app.range_learning import create_range_task
        from app.screen_subtitle_routes import resume_screen_subtitles
        original = storage.task_dir(self.task.id) / "source.mp4"; original.write_bytes(b"synthetic-owned-video")
        task = storage.update_task(self.task.id, status="success", media_path=str(original), media_integrity=MediaIntegrity(duration=60))
        with patch("app.range_learning.DATA_DIR", self.root), patch("app.range_learning.schedule_processing"):
            child = create_range_task(task.id, 10, 20, self.options, BackgroundTasks())
        retained = Path(child.source_media_path); self.assertTrue(retained.samefile(original))
        with patch("app.storage.DATA_DIR", self.root), patch("app.storage.remove_task", return_value=True): storage.delete_task(task.id)
        storage.update_task(child.id, status="cancelled")
        with patch("app.screen_subtitle_routes.schedule_processing") as schedule:
            resume_screen_subtitles(child.id, BackgroundTasks())
        self.assertEqual(schedule.call_args.kwargs["_queue_kind"], "range")
        self.assertEqual(schedule.call_args.args[3], retained)
        self.assertEqual(retained.read_bytes(), b"synthetic-owned-video")

    def test_retained_inode_replacement_and_in_place_changes_have_distinct_identities(self):
        from app.screen_subtitle_routes import create_screen_subtitles, ScreenSubtitleRequest
        original = storage.task_dir(self.task.id) / "source.mp4"; original.write_bytes(b"original-video")
        storage.update_task(self.task.id, status="success", media_path=str(original))
        with patch("app.screen_subtitle_routes.schedule_processing"):
            child = create_screen_subtitles(self.task.id, ScreenSubtitleRequest(), BackgroundTasks())["task_id"]
        retained = Path(storage.get_task(child).media_path)
        with patch.object(processing, "extract", side_effect=self.extraction):
            processing.process_screen_subtitle_task(child, retained, self.options)
            old_hash = storage.get_task(child).screen_subtitles_media_sha256
            replacement = original.with_suffix(".new"); replacement.write_bytes(b"new-original-video"); replacement.replace(original)
            self.assertEqual(retained.read_bytes(), b"original-video")
            processing.process_screen_subtitle_task(child, retained, self.options)
            self.assertEqual(storage.get_task(child).status, "success")
            alias = original.with_suffix(".alias"); alias.hardlink_to(retained); alias.write_bytes(b"in-place-change")
            processing.process_screen_subtitle_task(child, retained, self.options)
        self.assertEqual(storage.get_task(child).error_code, "screen_ocr_media_changed")
        self.assertEqual(storage.get_task(child).screen_subtitles_media_sha256, old_hash)

    def test_normalization_replaces_output_without_mutating_retained_inode(self):
        from app.media import normalize_video
        output = self.root / "normalized.mp4"; output.write_bytes(b"previous-normalized")
        retained = self.root / "retained.media"; retained.hardlink_to(output)
        def generate(command, *_): Path(command[-1]).write_bytes(b"new-normalized")
        with patch("app.media.require_ffmpeg"), patch("app.media.ffmpeg_bin", return_value="synthetic-ffmpeg"), patch("app.media._run", side_effect=generate):
            self.assertEqual(normalize_video(self.media, output), output)
        self.assertEqual(output.read_bytes(), b"new-normalized")
        self.assertEqual(retained.read_bytes(), b"previous-normalized")
        self.assertEqual(self.media.read_bytes(), b"synthetic-video")
        self.assertEqual(list(self.root.glob(".normalize-*")), [])

    def test_failed_normalization_keeps_existing_output_and_cleans_partial(self):
        from app.media import normalize_video, MediaProcessingError
        output = self.root / "normalized.mp4"; output.write_bytes(b"previous-normalized")
        def fail(command, *_):
            Path(command[-1]).write_bytes(b"partial")
            raise MediaProcessingError("synthetic failure")
        with patch("app.media.require_ffmpeg"), patch("app.media.ffmpeg_bin", return_value="synthetic-ffmpeg"), patch("app.media._run", side_effect=fail):
            with self.assertRaises(MediaProcessingError): normalize_video(self.media, output)
        self.assertEqual(output.read_bytes(), b"previous-normalized")
        self.assertEqual(list(self.root.glob(".normalize-*")), [])

    def test_ffmpeg_download_retries_cannot_rewrite_retained_media_inode(self):
        import subprocess
        from app.downloader import MediaDownloader
        from app.models import ResourceCandidate
        downloader = MediaDownloader(self.root / "download-task")
        cases = [("_download_manifest", "clip_manifest.mp4", ResourceCandidate(url="https://example.com/media.m3u8", kind="hls")),
                 ("_download_file_with_audio", "clip_direct_av.mp4", ResourceCandidate(url="https://example.com/video.mp4", audio_url="https://example.com/audio.m4a", kind="video"))]
        for method, name, candidate in cases:
            with self.subTest(method=method):
                output = downloader.download_dir / name; output.write_bytes(b"old-retained-content")
                retained = self.root / (name + ".retained"); retained.hardlink_to(output)
                def generate(command, **_):
                    Path(command[-1]).write_bytes(b"N" * 5000)
                    return subprocess.CompletedProcess(command, 0, "", "")
                with patch("app.downloader.ffmpeg_bin", return_value="synthetic-ffmpeg"), patch("app.downloader.subprocess.run", side_effect=generate), patch.object(downloader, "_manifest_file_from_replayed_request", return_value=None), patch.object(downloader, "_probe_manifest_before_ffmpeg"):
                    getattr(downloader, method)(candidate, [], "https://example.com/page", "clip")
                self.assertEqual(retained.read_bytes(), b"old-retained-content")
                self.assertEqual(output.read_bytes(), b"N" * 5000)

    def test_real_vfr_mkv_uses_next_pts_instead_of_nominal_packet_duration(self):
        try: import av
        except ImportError: self.skipTest("Optional PyAV is unavailable")
        path = self.root / "variable.mkv"
        with av.open(str(path), "w") as output:
            stream = output.add_stream("libx264", rate=25); stream.width = 64; stream.height = 48; stream.pix_fmt = "yuv420p"; stream.time_base = Fraction(1, 25)
            for color, pts in zip(["red", "green", "blue"], [0, 125, 250]):
                frame = av.VideoFrame.from_image(Image.new("RGB", (64, 48), color)); frame.pts = pts; frame.time_base = Fraction(1, 25)
                for packet in stream.encode(frame): output.mux(packet)
            for packet in stream.encode(): output.mux(packet)
        samples = list(sample_frames(path, [0, .5, 1, 4.5, 5, 5.5], ScreenSubtitleSettings()))
        self.assertEqual([item[1] for item in samples], [0, 0, 0, 0, 5, 5])
        retained = self.root / "screen-subtitles-source.media"; retained.hardlink_to(path)
        self.assertEqual([item[1] for item in sample_frames(retained, [.5, 5.5], ScreenSubtitleSettings())], [0, 5])
        with self.assertRaisesRegex(ScreenOcrError, "video_truncated"):
            list(sample_frames(path, [10.5], ScreenSubtitleSettings()))
