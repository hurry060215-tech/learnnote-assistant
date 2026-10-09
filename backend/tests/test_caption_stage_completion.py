"""Caption-only completion preserves source bytes and requires no model/ASR work."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.models import ActiveVideoInfo, BrowserSubtitleCue, CurrentPageTaskRequest, TaskOptions, TranscriptResult, TranscriptSegment
from app.caption_extraction import finish_caption_extraction
from app.observability import read_task_events
from app.pipeline_progress import record_stage_duration, start_pipeline_attempt, write_progressive_draft
from app.processor import process_local_video_task, process_subtitle_only_task
from app.storage import create_task, get_task, read_json, task_dir, update_task, write_json


class CaptionStageCompletionTests(unittest.TestCase):
    text = "这是一段完整的短视频字幕。保留原文供核对。"
    title = "字幕样例"

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("storage", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        self.options = TaskOptions(content_mode="subtitles", use_saved_connection=False)
        self.transcript = TranscriptResult(source="page-subtitle", full_text=self.text,
            segments=[TranscriptSegment(start=0, end=10, text=self.text)])
        self.subtitle = self.root / "source.srt"
        self.source_bytes = f"1\r\n00:00:00,000 --> 00:00:10,000\r\n{self.text}\r\n".encode("utf-8")
        self.subtitle.write_bytes(self.source_bytes)
        self.media = self.root / "source.mp4"
        self.media_bytes = b"synthetic source, never decoded"
        self.media.write_bytes(self.media_bytes)
        self.forbidden = []
        for name in ("summarize_with_diagnostics", "summarize_page_text_with_diagnostics",
                     "transcribe_with_task_progress", "transcribe_audio", "transcribe_audio_openai_compatible",
                     "extract_audio", "extract_visual_evidence", "extract_embedded_subtitle", "_process_video_file"):
            self.forbidden.append(self.stack.enter_context(patch(f"app.processor.{name}", side_effect=AssertionError(f"Forbidden caption work: {name}"))))
        self.forbidden.append(self.stack.enter_context(patch("app.processor.MediaDownloader", side_effect=AssertionError("Caption route must not download"))))

    def metrics(self, task_id):
        return read_json(task_id, "pipeline_metrics.json", {})

    def expected_note(self):
        return f"# {self.title}\n\n> 字幕原文 · 按你的选择，仅提取已有字幕，没有下载视频、转写音频或调用模型。\n\n`00:00` {self.text}\n"

    def run_route(self, route):
        task = create_task("local" if route == "local" else "current_page", self.title, options=self.options)
        if route == "local":
            process_local_video_task(task.id, self.media, self.title, self.options, subtitle_path=self.subtitle)
        else:
            request = CurrentPageTaskRequest(page_url="https://example.invalid/source", title=self.title,
                active_video=ActiveVideoInfo(duration=10), options=self.options,
                browser_subtitles=[BrowserSubtitleCue(start=0, end=10, text=self.text)])
            before = request.model_dump_json()
            process_subtitle_only_task(task.id, request)
            self.assertEqual(request.model_dump_json(), before)
        return task

    def assert_caption_result(self, task, *, completed=True):
        record = get_task(task.id)
        self.assertEqual(record.status, "success")
        self.assertEqual(record.summary_source, "subtitle-extract")
        self.assertEqual(Path(record.note_path).read_text(encoding="utf-8"), self.expected_note())
        transcript = TranscriptResult.model_validate_json(Path(record.transcript_path).read_text(encoding="utf-8"))
        self.assertEqual(transcript.full_text, self.text)
        self.assertEqual(transcript.segments, self.transcript.segments)
        self.assertEqual(self.subtitle.read_bytes(), self.source_bytes)
        self.assertEqual(self.media.read_bytes(), self.media_bytes)
        for forbidden in self.forbidden:
            forbidden.assert_not_called()
        if completed:
            attempt = self.metrics(task.id)["attempts"][-1]
            self.assertEqual(attempt["status"], "completed")
            self.assertIn("finished_at_unix_ms", attempt)
            self.assertEqual(attempt["stages"]["summary"]["status"], "skipped")
            for stage in ("frames", "vision", "merge", "verify"):
                entry = attempt["stages"][stage]
                self.assertEqual(entry["status"], "skipped")
                self.assertEqual(entry["attempt_id"], attempt["attempt_id"])
                self.assertNotIn("duration_ms", entry)

    def test_browser_caption_attempt_finishes_after_persisted_success(self):
        self.assert_caption_result(self.run_route("browser"))

    def test_local_caption_attempt_finishes_after_persisted_success(self):
        self.assert_caption_result(self.run_route("local"))


    def test_both_routes_complete_only_after_caption_files_and_success_are_persisted(self):
        calls = []
        def verify_before_finish(task_id, **changes):
            self.assertEqual(self.metrics(task_id)["attempts"][-1]["status"], "running")
            self.assertEqual(Path(changes["note_path"]).read_text(encoding="utf-8"), self.expected_note())
            self.assertTrue(Path(changes["transcript_path"]).is_file())
            result = update_task(task_id, **changes)
            self.assertEqual(get_task(task_id).status, "success")
            self.assertEqual(self.metrics(task_id)["attempts"][-1]["status"], "running")
            calls.append(task_id)
            return result
        with patch("app.caption_extraction.update_task", side_effect=verify_before_finish):
            for route in ("browser", "local"):
                self.assert_caption_result(self.run_route(route))
        self.assertEqual(len(calls), 2)

    def test_both_routes_pass_originating_identity_instead_of_recapturing_a_retry(self):
        snapshots = {}
        def interleave(task_id, *args, **kwargs):
            origin = self.metrics(task_id)["current_attempt_id"]
            self.assertEqual(kwargs["attempt_id"], origin)
            start_pipeline_attempt(task_id)
            snapshots[task_id] = self.metrics(task_id)
            finish_caption_extraction(task_id, *args, **kwargs)
        with patch("app.caption_extraction.finish_caption_extraction", side_effect=interleave):
            for route in ("browser", "local"):
                task = self.run_route(route)
                self.assert_caption_result(task, completed=False)
                self.assertEqual(self.metrics(task.id), snapshots[task.id])
                self.assertEqual(self.metrics(task.id)["stages"], {})

    def test_late_final_completion_does_not_finish_or_write_events_into_retry(self):
        task = create_task("local", self.title, options=self.options)
        attempt_a = start_pipeline_attempt(task.id)
        snapshots, events = [], []
        def retry_after_save(task_id, **changes):
            result = update_task(task_id, **changes)
            start_pipeline_attempt(task_id)
            snapshots.append(self.metrics(task_id))
            events.append(read_task_events(task_id))
            return result
        with patch("app.caption_extraction.update_task", side_effect=retry_after_save):
            finish_caption_extraction(task.id, self.title, self.transcript, str(self.subtitle), attempt_id=attempt_a)
        self.assert_caption_result(task, completed=False)
        self.assertEqual(self.metrics(task.id), snapshots[0])
        self.assertEqual(read_task_events(task.id), events[0])
        self.assertEqual(self.metrics(task.id)["attempts"][-1]["status"], "running")
        self.assertNotIn("finished_at_unix_ms", self.metrics(task.id)["attempts"][-1])

    def test_unknown_capture_stays_disabled_without_recapturing_current_attempt(self):
        for explicit_none in (True, False):
            with self.subTest(explicit_none=explicit_none):
                task = create_task("local", self.title, options=self.options)
                start_pipeline_attempt(task.id)
                before = self.metrics(task.id)
                event_before = [event for event in read_task_events(task.id) if event["event"] == "stage_timing"]
                with patch("app.caption_extraction.current_pipeline_attempt", return_value=None) as capture:
                    kwargs = {"attempt_id": None} if explicit_none else {}
                    finish_caption_extraction(task.id, self.title, self.transcript, str(self.subtitle), **kwargs)
                self.assertEqual(capture.call_count, 0 if explicit_none else 1)
                self.assert_caption_result(task, completed=False)
                self.assertEqual(self.metrics(task.id), before)
                self.assertEqual([event for event in read_task_events(task.id) if event["event"] == "stage_timing"], event_before)

    def test_explicit_unknown_timing_and_draft_never_read_metrics_but_keep_artifacts(self):
        task = create_task("local", self.title, options=self.options)
        start_pipeline_attempt(task.id)
        before = self.metrics(task.id)
        with patch("app.pipeline_progress._metrics", side_effect=AssertionError("Disabled metadata must not be read")) as read:
            result = record_stage_duration(task.id, "verify", 0, expected_attempt_id=None)
            draft = write_progressive_draft(task.id, self.title, self.transcript, expected_attempt_id=None)
        read.assert_not_called()
        self.assertEqual(result, {})
        self.assertTrue(draft.is_file())
        self.assertIn(self.text, draft.read_text(encoding="utf-8"))
        self.assertTrue((task_dir(task.id) / "draft_sections.json").is_file())
        self.assertEqual(self.metrics(task.id), before)
        self.assertEqual(self.subtitle.read_bytes(), self.source_bytes)

    def test_unreadable_attempt_capture_does_not_block_saved_caption_success(self):
        task = create_task("local", self.title, options=self.options)
        start_pipeline_attempt(task.id)
        before = self.metrics(task.id)
        with patch("app.pipeline_progress._metrics", side_effect=OSError("synthetic metrics read failure")) as read:
            finish_caption_extraction(task.id, self.title, self.transcript, str(self.subtitle))
        read.assert_called_once_with(task.id)
        self.assert_caption_result(task, completed=False)
        self.assertEqual(self.metrics(task.id), before)

    def test_failed_caption_or_success_write_never_finishes_attempt(self):
        for failure in ("transcript", "captions", "status"):
            with self.subTest(failure=failure):
                task = create_task("local", self.title, options=self.options)
                attempt = start_pipeline_attempt(task.id)
                write_text = Path.write_text
                def fail_caption(path, *args, **kwargs):
                    if path.name == "captions.md":
                        raise OSError("synthetic caption write failure")
                    return write_text(path, *args, **kwargs)
                with ExitStack() as stack:
                    finish = stack.enter_context(patch("app.caption_extraction.finish_pipeline_attempt"))
                    if failure == "transcript":
                        stack.enter_context(patch("app.caption_extraction.write_json", side_effect=OSError("synthetic transcript failure")))
                    elif failure == "captions":
                        stack.enter_context(patch.object(Path, "write_text", new=fail_caption))
                    else:
                        stack.enter_context(patch("app.caption_extraction.update_task", side_effect=OSError("synthetic status failure")))
                    with self.assertRaises(OSError):
                        finish_caption_extraction(task.id, self.title, self.transcript, str(self.subtitle), attempt_id=attempt)
                    finish.assert_not_called()
                self.assertEqual(self.metrics(task.id)["attempts"][-1]["status"], "running")
                self.assertNotIn("finished_at_unix_ms", self.metrics(task.id)["attempts"][-1])
                self.assertNotEqual(get_task(task.id).status, "success")
                self.assertEqual(self.subtitle.read_bytes(), self.source_bytes)
                self.assertEqual(self.media.read_bytes(), self.media_bytes)

    def test_final_metrics_failure_keeps_saved_caption_success(self):
        task = create_task("local", self.title, options=self.options)
        attempt = start_pipeline_attempt(task.id)
        def fail_finish(task_id, filename, payload):
            if filename == "pipeline_metrics.json" and payload["attempts"][-1]["status"] == "completed":
                raise OSError("synthetic metrics failure")
            return write_json(task_id, filename, payload)
        with patch("app.pipeline_progress.write_json", side_effect=fail_finish):
            finish_caption_extraction(task.id, self.title, self.transcript, str(self.subtitle), attempt_id=attempt)
        self.assert_caption_result(task, completed=False)
        self.assertEqual(self.metrics(task.id)["attempts"][-1]["status"], "running")
        self.assertNotIn("finished_at_unix_ms", self.metrics(task.id)["attempts"][-1])

    def test_optional_detailed_skip_record_failure_keeps_caption_success(self):
        task = create_task("local", self.title, options=self.options)
        attempt = start_pipeline_attempt(task.id)
        def broken(*args, **kwargs):
            raise OSError("synthetic observation failure")
        with patch("app.caption_extraction.stage_duration_recorder", return_value=broken):
            finish_caption_extraction(task.id, self.title, self.transcript, str(self.subtitle), attempt_id=attempt)
        self.assert_caption_result(task, completed=False)
        self.assertEqual(self.metrics(task.id)["attempts"][-1]["status"], "completed")
        for stage in ("frames", "vision", "merge", "verify"):
            self.assertNotIn(stage, self.metrics(task.id)["stages"])


if __name__ == "__main__":
    unittest.main()
