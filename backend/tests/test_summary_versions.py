import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import TaskOptions, TranscriptResult, TranscriptSegment
from app.processor import process_saved_transcript_task
from app.storage import create_task, get_task, update_task
from app.summary_versions import list_summary_versions, read_summary_version, snapshot_summary


class SummaryVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch("app.storage.TASK_DIR", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        # These tests isolate version retention after a usable model was chosen;
        # missing-model rejection is covered by test_model_readiness.
        ready = patch("app.summarizer._model_key", return_value="fixture-key")
        ready.start()
        self.addCleanup(ready.stop)
        self.task = create_task("local", "历史正文", options=TaskOptions(content_mode="text"))
        self.note = self.root / self.task.id / "note.md"
        self.note.write_text("# 原有笔记\n\n已经整理的结论。", encoding="utf-8")
        self.transcript = self.note.with_name("transcript.json")
        self.transcript.write_text(TranscriptResult(source="browser-subtitle", full_text="字幕证据",
            segments=[TranscriptSegment(start=0, end=10, text="字幕证据")]).model_dump_json(), encoding="utf-8")
        update_task(self.task.id, status="failed", phase="failed", note_path=str(self.note),
                    transcript_path=str(self.transcript), summary_source="llm")
        self.client = TestClient(app)

    def test_retry_history_is_deduplicated_readable_and_keeps_exact_original(self):
        original = self.note.read_bytes()
        with patch("app.main.schedule_processing"):
            response = self.client.post(f"/api/tasks/{self.task.id}/retry-summary", json={})
        self.assertEqual(response.status_code, 200, response.text)
        version_id = snapshot_summary(self.task.id)
        listing = self.client.get(f"/api/tasks/{self.task.id}/summary-versions").json()
        self.assertEqual(len(listing["versions"]), 1)
        self.assertTrue(listing["versions"][0]["current"])
        self.assertNotIn("markdown", listing["versions"][0])
        self.note.write_text("# 新笔记", encoding="utf-8")
        detail = self.client.get(f"/api/tasks/{self.task.id}/summary-versions/{version_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["markdown"].encode("utf-8"), original)
        self.assertFalse(list_summary_versions(self.task.id)["versions"][0]["current"])

    def test_resume_takes_snapshot_before_worker_can_replace_current_note(self):
        media = self.note.with_name("media.mp4")
        media.write_bytes(b"original media")
        update_task(self.task.id, media_path=str(media))
        with patch("app.main.schedule_processing") as schedule:
            response = self.client.post(f"/api/tasks/{self.task.id}/resume", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(list_summary_versions(self.task.id)["versions"]), 1)
        self.assertEqual(get_task(self.task.id).note_path, str(self.note))
        schedule.assert_called_once()

    def test_snapshot_failure_does_not_queue_or_mutate_task(self):
        before = get_task(self.task.id)
        with patch("app.summary_versions.snapshot_summary", side_effect=OSError("disk full")), patch("app.main.schedule_processing") as schedule:
            response = self.client.post(f"/api/tasks/{self.task.id}/retry-summary", json={})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "summary_backup_failed")
        self.assertEqual(get_task(self.task.id), before)
        schedule.assert_not_called()

    def test_resume_failure_after_transcript_keeps_previous_summary_visible(self):
        from app.models import MediaIntegrity
        from app.processor import _process_video_file
        from app.transcript_pipeline import TranscriptArtifacts
        media = self.note.with_name("media.mp4")
        media.write_bytes(b"source media")
        transcript = TranscriptResult.model_validate_json(self.transcript.read_bytes())
        with patch("app.processor.probe_media_integrity", return_value=MediaIntegrity(status="ready", duration=10, has_audio=True, has_video=True)), \
             patch("app.processor.normalize_video"), \
             patch("app.processor.prepare_transcript", return_value=TranscriptArtifacts(transcript, "", None, "", self.transcript)), \
             patch("app.processor.extract_visual_evidence", side_effect=RuntimeError("visual fixture failure")):
            with self.assertRaisesRegex(RuntimeError, "visual fixture failure"):
                _process_video_file(self.task.id, media, self.task.title, "", TaskOptions(content_mode="visual"))
        self.assertEqual(get_task(self.task.id).note_path, str(self.note))
        self.assertEqual(get_task(self.task.id).summary_source, "llm")
        self.assertEqual(len(list_summary_versions(self.task.id)["versions"]), 1)

    def test_modes_cannot_silently_gain_model_calls_or_lose_visual_processing(self):
        for mode in ("subtitles", "visual"):
            update_task(self.task.id, options=TaskOptions(content_mode=mode))
            with patch("app.main.schedule_processing") as schedule:
                response = self.client.post(f"/api/tasks/{self.task.id}/retry-summary", json={})
                self.assertEqual(response.status_code, 409, response.text)
                schedule.assert_not_called()
                response = self.client.post(f"/api/tasks/{self.task.id}/retry-summary", json={"content_mode": "text"})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(schedule.call_args.args[3].content_mode, "text")
            update_task(self.task.id, status="failed", phase="failed")

    def test_recovered_summary_job_also_respects_explicit_mode(self):
        with patch("app.processor.summarize_with_diagnostics") as summarize:
            process_saved_transcript_task(self.task.id, TaskOptions(content_mode="subtitles"))
        summarize.assert_not_called()
        self.assertEqual(get_task(self.task.id).error_code, "summary_mode_required")
        self.assertEqual(self.note.read_text(encoding="utf-8"), "# 原有笔记\n\n已经整理的结论。")

    def test_corrupt_unowned_or_path_like_versions_are_never_served(self):
        version_id = snapshot_summary(self.task.id)
        root = self.note.parent / "summary_versions"
        (root / f"{version_id}.md").write_text("tampered", encoding="utf-8")
        self.assertEqual(list_summary_versions(self.task.id)["versions"], [])
        self.assertEqual(self.client.get(f"/api/tasks/{self.task.id}/summary-versions/{version_id}").status_code, 404)
        for invalid in ("..", "task.json", "note.md", "A" * 64):
            with self.assertRaises(FileNotFoundError):
                read_summary_version(self.task.id, invalid)
        elsewhere = self.root / "outside.md"
        elsewhere.write_text("private outside file", encoding="utf-8")
        update_task(self.task.id, note_path=str(elsewhere))
        self.assertIsNone(snapshot_summary(self.task.id))

    def test_history_cannot_read_a_link_outside_the_task(self):
        outside = self.root / "outside.md"
        outside.write_text("private outside file", encoding="utf-8")
        version_id = hashlib.sha256(outside.read_bytes()).hexdigest()
        versions = self.note.parent / "summary_versions"
        versions.mkdir()
        try:
            (versions / f"{version_id}.md").symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable on this Windows account")
        self.assertEqual(list_summary_versions(self.task.id)["versions"], [])
        with self.assertRaises(FileNotFoundError):
            read_summary_version(self.task.id, version_id)


if __name__ == "__main__":
    unittest.main()
