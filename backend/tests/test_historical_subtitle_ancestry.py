"""Real rerun admission plus historical caption finalization, entirely synthetic."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app import main, processor, storage
from app.caption_extraction import finish_caption_extraction
from app.models import ActiveVideoInfo, MediaIntegrity, ResourceCandidate
from app.pipeline_progress import start_pipeline_attempt
from app.task_inputs import task_reuse_media_path
import test_task_export_boundary as export_fixtures


class HistoricalSubtitleAncestryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = export_fixtures.TaskExportBoundaryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.source = self.fixture.root, self.fixture.task
        self.media = self.root / "selected-range.mp4"
        self.media.write_bytes(b"synthetic normalized selected range; never decoded")
        self.subtitle = self.root / "browser_subtitles.srt"
        digest = hashlib.sha256(self.media.read_bytes()).hexdigest()
        self.integrity = MediaIntegrity(status="ready", sha256=digest, duration=5, file_size=self.media.stat().st_size)
        self.fixture.manifest(note_path=str(self.root / "note.md"), transcript_path=str(self.root / "transcript.json"),
            visual_index_path=str(self.root / "visual_index.json"), subtitle_path=str(self.subtitle),
            source_type="current_page", page_url="https://www.example.com/lesson?part=2", media_path=str(self.media),
            learning_range={"start": 10, "end": 15, "original_start": 10, "original_end": 15},
            selected_resource=ResourceCandidate(url="https://www.example.com/part2.mp4", kind="video").model_dump(mode="json"),
            active_video=ActiveVideoInfo(src="https://www.example.com/part2.mp4", current_time=11, duration=60).model_dump(mode="json"),
            media_integrity=self.integrity.model_copy(update={"sha256": "a" * 64}).model_dump(mode="json"))
        with patch.object(main, "validate_local_upload_file", return_value=self.integrity), \
                patch("app.range_media.probe_duration", return_value=5), patch.object(main, "schedule_processing") as schedule:
            result = self.fixture.client.post(f"/api/tasks/{self.source.id}/rerun-from-media", json={"content_mode": "subtitles", "use_saved_connection": False})
        self.assertEqual(result.status_code, 200, result.text)
        schedule.assert_called_once()
        self.child_id = result.json()["task_id"]
        self.child_root = self.root.parent / self.child_id
        # This is the old actual producer boundary: finalization published the
        # source pointer after parsing, before retain_subtitle_file was added.
        attempt = start_pipeline_attempt(self.child_id)
        transcript = processor.parse_subtitle_or_none(self.subtitle, source="page-subtitle")
        finish_caption_extraction(self.child_id, "Historical child", transcript, str(self.subtitle), attempt_id=attempt)
        self.child = storage.get_task(self.child_id)
        self.assertEqual((self.child.mode, self.child.summary_source), ("subtitle_only", "subtitle-extract"))
        self.assertEqual(self.child.source_task_id, self.source.id)
        self.assertNotEqual(self.child.media_integrity.sha256, storage.get_task(self.source.id).media_integrity.sha256)
        self.assertFalse((self.child_root / self.subtitle.name).exists())

    def admit_caption_child(self, source_id):
        with patch.object(main, "validate_local_upload_file", return_value=self.integrity), \
                patch("app.range_media.probe_duration", return_value=5), patch.object(main, "schedule_processing") as schedule:
            result = self.fixture.client.post(f"/api/tasks/{source_id}/rerun-from-media", json={"content_mode": "subtitles", "use_saved_connection": False})
        self.assertEqual(result.status_code, 200, result.text)
        schedule.assert_called_once()
        return storage.get_task(result.json()["task_id"])

    def source_snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def test_fresh_owned_caption_child_retains_range_media_ancestry(self):
        child = self.admit_caption_child(self.source.id)
        processor.process_local_video_task(child.id, self.media, child.title, child.options, subtitle_path=self.subtitle)
        child = storage.get_task(child.id)
        self.assertEqual(child.status, "success", child.error_detail)
        self.assertEqual(Path(child.subtitle_path).parent, self.root.parent / child.id)
        before = self.source_snapshot(), (self.root.parent / child.id / "task.json").read_bytes()
        result = self.fixture.client.get(f"/api/tasks/{child.id}/exports/subtitles")
        self.assertEqual(result.status_code, 200, result.text)
        with patch("app.range_media.probe_duration", return_value=5):
            self.assertEqual(task_reuse_media_path(child), self.media)
        self.admit_caption_child(child.id)
        self.assertEqual((self.source_snapshot(), (self.root.parent / child.id / "task.json").read_bytes()), before)

    def test_multihop_historical_chain_uses_exact_pointer_and_rejects_changed_middle(self):
        grandchild = self.admit_caption_child(self.child_id)
        transcript = processor.parse_subtitle_or_none(self.subtitle, source="page-subtitle")
        finish_caption_extraction(grandchild.id, grandchild.title, transcript, str(self.subtitle), attempt_id=start_pipeline_attempt(grandchild.id))
        before = self.source_snapshot(), (self.child_root / "task.json").read_bytes()
        result = self.fixture.client.get(f"/api/tasks/{grandchild.id}/exports/subtitles")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.content, self.subtitle.read_bytes())
        with patch("app.range_media.probe_duration", return_value=5):
            self.assertEqual(task_reuse_media_path(storage.get_task(grandchild.id)), self.media)
        self.admit_caption_child(grandchild.id)
        self.assertEqual((self.source_snapshot(), (self.child_root / "task.json").read_bytes()), before)
        storage.update_task(self.child_id, page_url="https://www.example.com/changed-part")
        with patch.object(main, "schedule_processing") as schedule:
            self.assertEqual(self.fixture.client.get(f"/api/tasks/{grandchild.id}/exports/subtitles").status_code, 409)
            self.assertEqual(self.fixture.client.post(f"/api/tasks/{grandchild.id}/rerun-from-media", json={"content_mode": "subtitles"}).status_code, 409)
            schedule.assert_not_called()

    def test_multihop_depth_overflow_is_recoverable_without_substitution(self):
        previous = self.child_id
        for index in range(16):
            task_id = f"historical-depth-{index}"
            root = self.root.parent / task_id
            root.mkdir()
            for name in ("captions.md", "transcript.json"):
                (root / name).write_bytes((self.child_root / name).read_bytes())
            task = self.child.model_copy(update={"id": task_id, "source_task_id": previous,
                "note_path": str(root / "captions.md"), "transcript_path": str(root / "transcript.json")})
            (root / "task.json").write_text(task.model_dump_json(), encoding="utf-8")
            previous = task_id
        before = self.source_snapshot()
        self.assertEqual(self.fixture.client.get(f"/api/tasks/{previous}/exports/subtitles").status_code, 409)
        self.assertEqual(self.source_snapshot(), before)

    def test_explicit_summary_retry_retains_alias_before_semantics_and_success_change(self):
        before = self.source_snapshot()
        initial = self.fixture.client.get(f"/api/tasks/{self.child_id}/exports/subtitles")
        self.assertEqual(initial.status_code, 200, initial.text)
        with patch.object(main, "require_ready_note_model"), patch.object(main, "schedule_processing") as schedule:
            response = self.fixture.client.post(f"/api/tasks/{self.child_id}/retry-summary", json={"content_mode": "text", "use_saved_connection": False})
        self.assertEqual(response.status_code, 200, response.text)
        schedule.assert_called_once()
        saved = storage.get_task(self.child_id)
        self.assertEqual(saved.options.content_mode, "text")
        self.assertEqual(Path(saved.subtitle_path).parent, self.child_root)
        self.assertEqual(self.fixture.client.get(f"/api/tasks/{self.child_id}/exports/subtitles").content, initial.content)
        note = "# Historical lesson\n\n## Key point\n\nA copied caption.\n\n## Review\n\nThe saved subtitle reads: A copied caption.\n"
        with patch.object(processor, "summarize_with_diagnostics", return_value=(note, "offline-fixture", "", [])):
            processor.process_saved_transcript_task(self.child_id, saved.options)
        final = storage.get_task(self.child_id)
        self.assertEqual(final.status, "success", final.error_detail)
        self.assertEqual(final.summary_source, "offline-fixture")
        self.assertEqual(self.fixture.client.get(f"/api/tasks/{self.child_id}/exports/subtitles").content, initial.content)
        with patch("app.range_media.probe_duration", return_value=5):
            self.assertEqual(task_reuse_media_path(final), self.media)
        self.assertEqual(self.source_snapshot(), before)

    def test_summary_retry_copy_failure_or_collision_rejects_before_mutation(self):
        for collision in (False, True):
            with self.subTest(collision=collision):
                target = self.child_root / self.subtitle.name
                if collision:
                    target.write_bytes(b"different existing child artifact")
                before = self.source_snapshot(), (self.child_root / "task.json").read_bytes(), (self.child_root / "task.json").stat().st_mtime_ns
                with patch.object(main, "require_ready_note_model"), patch.object(main, "schedule_processing") as schedule, \
                        patch.object(main, "_snapshot_before_retry") as snapshot, \
                        patch("app.subtitle_ownership.shutil.copyfileobj", side_effect=OSError("synthetic copy failure")):
                    response = self.fixture.client.post(f"/api/tasks/{self.child_id}/retry-summary", json={"content_mode": "text", "use_saved_connection": False})
                self.assertEqual(response.status_code, 409, response.text)
                schedule.assert_not_called(); snapshot.assert_not_called()
                self.assertEqual((self.source_snapshot(), (self.child_root / "task.json").read_bytes(), (self.child_root / "task.json").stat().st_mtime_ns), before)
                if collision:
                    self.assertEqual(target.read_bytes(), b"different existing child artifact")
                else:
                    self.assertFalse(target.exists())

    def assert_rejected(self):
        before = (self.child_root / "task.json").read_bytes(), (self.root / "task.json").read_bytes()
        with patch.object(main, "schedule_processing") as schedule, patch.object(main, "validate_local_upload_file") as validate:
            result = self.fixture.client.get(f"/api/tasks/{self.child_id}/exports/subtitles")
            self.assertEqual(result.status_code, 409, result.text)
            result = self.fixture.client.post(f"/api/tasks/{self.child_id}/rerun-from-media", json={"content_mode": "subtitles"})
            self.assertEqual(result.status_code, 409, result.text)
            schedule.assert_not_called(); validate.assert_not_called()
        self.assertEqual(((self.child_root / "task.json").read_bytes(), (self.root / "task.json").read_bytes()), before)

    def test_real_historical_range_child_exports_and_retries_without_rewriting_ancestors(self):
        before = self.fixture.fixture.hashes(self.root), self.fixture.fixture.hashes(self.child_root)
        result = self.fixture.client.get(f"/api/tasks/{self.child_id}/exports/subtitles")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.content, self.subtitle.read_bytes())
        result = self.fixture.client.get(f"/api/tasks/{self.child_id}/exports/bundle")
        self.assertEqual(result.status_code, 200, result.text)
        with ZipFile(BytesIO(result.content)) as archive:
            self.assertEqual(archive.read("subtitles/browser_subtitles.srt"), self.subtitle.read_bytes())
            self.assertEqual(json.loads(archive.read("task.json"))["subtitle_path"], str(self.subtitle))
        with patch("app.range_media.probe_duration", return_value=5), \
                patch.object(main, "validate_local_upload_file", return_value=self.integrity), patch.object(main, "schedule_processing") as schedule:
            self.assertEqual(task_reuse_media_path(storage.get_task(self.child_id)), self.media)
            result = self.fixture.client.post(f"/api/tasks/{self.child_id}/rerun-from-media", json={"content_mode": "subtitles", "use_saved_connection": False})
        self.assertEqual(result.status_code, 200, result.text)
        schedule.assert_called_once()
        self.assertEqual((self.fixture.fixture.hashes(self.root), self.fixture.fixture.hashes(self.child_root)), before)

    def test_changed_part_range_source_or_local_identity_rejects_both_boundaries(self):
        original = (self.child_root / "task.json").read_bytes()
        cases = [{"page_url": "https://www.example.com/lesson?part=3"}, {"learning_range": {"start": 0, "end": 5}},
            {"source_task_id": "unrelated"}, {"selected_resource": None}, {"active_video": None},
            {"source_identity": self.child.source_identity.model_copy(update={"media_sha256": "b" * 64})},
            {"source_media_path": str(self.root / "different.mp4")}, {"mode": "local"}]
        for changes in cases:
            with self.subTest(fields=list(changes)):
                (self.child_root / "task.json").write_bytes(original)
                storage.update_task(self.child_id, **changes)
                self.assert_rejected()

    def test_absent_optional_route_metadata_preserves_read_only_historical_export(self):
        for name in ("pipeline_metrics.json", "whole_attempt_duration_evidence.json"):
            (self.child_root / name).unlink(missing_ok=True)
        before = self.source_snapshot(), self.fixture.fixture.hashes(self.child_root), (self.child_root / "task.json").stat().st_mtime_ns
        result = self.fixture.client.get(f"/api/tasks/{self.child_id}/exports/subtitles")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.content, self.subtitle.read_bytes())
        self.assertEqual((self.source_snapshot(), self.fixture.fixture.hashes(self.child_root), (self.child_root / "task.json").stat().st_mtime_ns), before)

    def test_cycles_contradictory_entry_route_and_changed_source_identity_reject(self):
        source_original = (self.root / "task.json").read_bytes()
        storage.update_task(self.source.id, source_task_id=self.child_id)
        self.assert_rejected()
        (self.root / "task.json").write_bytes(source_original)
        storage.update_task(self.source.id, page_url="https://www.example.com/lesson?part=changed")
        self.assert_rejected()
        (self.root / "task.json").write_bytes(source_original)
        evidence = self.child_root / "whole_attempt_duration_evidence.json"
        evidence.write_text(json.dumps({"attempts": [{"context": {"entry_route": "current_page_media"}}]}), encoding="utf-8")
        self.assert_rejected()

    def test_foreign_and_linked_subtitle_or_manifest_never_probe_old_target(self):
        original = (self.child_root / "task.json").read_bytes()
        outside = self.fixture.old_file("old.srt")
        for pointer in (str(outside), ("/old/tasks/" + self.source.id + "/browser_subtitles.srt") if os.name == "nt" else "D:\\old\\tasks\\" + self.source.id + "\\browser_subtitles.srt"):
            (self.child_root / "task.json").write_bytes(original)
            storage.update_task(self.child_id, subtitle_path=pointer)
            with self.fixture.no_old_io(outside):
                self.assert_rejected()
        (self.child_root / "task.json").write_bytes(original)
        content = self.subtitle.read_bytes()
        self.subtitle.unlink()
        try:
            self.subtitle.symlink_to(outside)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.fixture.no_old_io(outside):
            self.assert_rejected()
        self.subtitle.unlink(); self.subtitle.write_bytes(content)
        manifest = self.root / "task.json"
        outside_manifest = self.fixture.old_file("linked-manifest.json", manifest.read_bytes())
        manifest.unlink(); manifest.symlink_to(outside_manifest)
        with self.fixture.no_old_io(outside_manifest), patch.object(main, "schedule_processing") as schedule:
            for path, method in (("exports/subtitles", "get"), ("rerun-from-media", "post")):
                self.assertEqual(getattr(self.fixture.client, method)(f"/api/tasks/{self.child_id}/{path}").status_code, 409)
            schedule.assert_not_called()


if __name__ == "__main__":
    unittest.main()
