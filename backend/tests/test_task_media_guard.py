"""Copied-path media admissions cannot consume the still-existing original."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from app import storage
from app.models import TaskRecord
from app.task_inputs import task_media_path, task_reuse_media_path
from app.task_media_guard import require_current_media_provenance, validate_current_media_file
from app.task_paths import TaskArtifactUnavailable
from app.task_queue import LocalTaskQueue, recover_processing, queue_for
import test_task_export_boundary as export_fixtures


class TaskMediaGuardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = export_fixtures.TaskExportBoundaryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.task = self.fixture.root, self.fixture.task

    def require_current_media_provenance(self, task):
        return require_current_media_provenance(task, self.root)

    def validate_current_media_file(self, task, value):
        return validate_current_media_file(task, value, self.root)

    def native_task(self, **changes):
        fields = {"note_path": str(self.root / "note.md"), "transcript_path": str(self.root / "transcript.json"),
                  "subtitle_path": str(self.root / "browser_subtitles.srt"), "visual_index_path": str(self.root / "visual_index.json")}
        fields.update(changes)
        return self.task.model_copy(update=fields)

    def test_copied_task_media_preview_export_retries_and_ocr_never_probe_old_copy(self):
        outside = self.fixture.old_file("media.mp4")
        self.fixture.manifest(media_path=str(outside), source_media_path=str(outside))
        before = self.fixture.fixture.hashes(self.root)
        task = storage.get_task(self.task.id)
        with self.fixture.no_old_io(outside):
            self.assertIsNone(task_media_path(task))
            with self.assertRaises(TaskArtifactUnavailable):
                task_reuse_media_path(task)
            with patch("app.main.schedule_processing") as schedule, patch("app.screen_subtitle_routes.schedule_processing") as ocr:
                for endpoint in ("media", "exports/media", "resume", "retry", "rerun-from-media", "screen-subtitles/preview"):
                    with self.subTest(endpoint=endpoint):
                        path = f"/api/tasks/{task.id}/{endpoint}"
                        result = self.fixture.client.get(path) if endpoint in {"media", "exports/media"} else self.fixture.client.post(path, json={})
                        self.assertEqual(result.status_code, 409, result.text)
                        self.assertTrue(result.json()["detail"]["requires_preview"])
                schedule.assert_not_called(); ocr.assert_not_called()
        self.assertEqual(self.fixture.fixture.hashes(self.root), before)
        self.assertEqual(outside.read_bytes(), b"OLD PRIVATE SYNTHETIC COPY")

    def test_owned_current_media_upload_and_explicit_cross_task_source_keep_working(self):
        current = self.root / "media.mp4"; current.write_bytes(b"current media")
        self.assertEqual(task_reuse_media_path(self.native_task(media_path=str(current))), current)
        upload = self.root.parent.parent / "uploads" / "selected.mp4"
        upload.parent.mkdir(); upload.write_bytes(b"user selected upload")
        self.assertEqual(task_reuse_media_path(self.native_task(source_media_path=str(upload))), upload)
        source = self.root.parent / "source-task" / "media.mp4"
        source.parent.mkdir(); source.write_bytes(b"explicit source dependency")
        self.assertEqual(task_reuse_media_path(self.native_task(source_task_id="source-task", source_media_path=str(source))), source)
        self.assertEqual(upload.read_bytes(), b"user selected upload")
        self.assertEqual(source.read_bytes(), b"explicit source dependency")

    def test_same_id_old_root_is_exact_and_foreign_media_is_rejected_without_probe(self):
        for value in (f"/old/tasks/{self.task.id}/media.mp4", f"D:\\old\\tasks\\{self.task.id}\\media.mp4",
                      f"/old/tasks/{self.task.id}/../media.mp4", r"\\server\share\media.mp4"):
            with self.subTest(value=value), self.assertRaises(TaskArtifactUnavailable):
                self.require_current_media_provenance(self.native_task(source_media_path=value))
        # A prefix-similar sibling is not silently classified/remapped as our ID.
        sibling = self.fixture.old_file("media.mp4").parent.with_name(self.task.id + "-sibling") / "media.mp4"
        sibling.parent.mkdir(); sibling.write_bytes(b"explicit sibling original")
        original = self.native_task(source_task_id=self.task.id + "-sibling", source_media_path=str(sibling))
        self.assertEqual(task_reuse_media_path(original), sibling)

    def test_windows_owner_casefold_is_host_independent_but_posix_is_case_sensitive(self):
        for owner in (self.task.id, self.task.id.upper()):
            for directory in ("tasks", "TASKS", "Tasks"):
                value = f"D:\\old\\{directory}\\{owner}\\media.mp4"
                with self.subTest(value=value), patch("app.task_media_guard._native", return_value=True), self.assertRaises(TaskArtifactUnavailable):
                    self.require_current_media_provenance(self.native_task(source_media_path=value))
        # POSIX case remains exact and must not conflate a distinct external root.
        with patch("app.task_media_guard._native", return_value=True):
            self.require_current_media_provenance(self.native_task(source_media_path=f"/old/TASKS/{self.task.id.upper()}/media.mp4"))
            self.require_current_media_provenance(self.native_task(source_media_path=f"D:\\old\\TASKS\\{self.task.id.upper()}-SIBLING\\media.mp4"))

    @unittest.skipUnless(os.name == "nt", "Native Windows case-insensitive filesystem coverage")
    def test_native_windows_old_owner_case_is_rejected_before_read(self):
        outside = self.fixture.old_file("media.mp4")
        with self.fixture.no_old_io(outside), self.assertRaises(TaskArtifactUnavailable):
            task_reuse_media_path(self.native_task(source_media_path=str(outside).upper()))

    def test_current_media_symlink_and_linked_parent_never_read_target(self):
        outside = self.fixture.old_file("media.mp4")
        for candidate, target in ((self.root / "media.mp4", outside), (self.root / "media-dir", outside.parent)):
            try:
                candidate.symlink_to(target, target_is_directory=target.is_dir())
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlink creation unsupported: {exc}")
            value = candidate / "media.mp4" if target.is_dir() else candidate
            try:
                with self.fixture.no_old_io(outside), self.assertRaises(TaskArtifactUnavailable) as failure:
                    self.validate_current_media_file(self.native_task(media_path=str(value)), str(value))
                self.assertEqual(failure.exception.reason, "linked_destination")
            finally:
                candidate.unlink()
        self.assertEqual(outside.read_bytes(), b"OLD PRIVATE SYNTHETIC COPY")

    def test_restart_moves_copied_media_to_explicit_source_reselection_without_old_probe(self):
        outside = self.fixture.old_file("media.mp4")
        self.fixture.manifest(source_media_path=str(outside), status="running", phase="processing_video")
        queue_root = self.root.parent.parent
        queue = LocalTaskQueue(queue_root)
        self.addCleanup(queue.stop)
        with closing(sqlite3.connect(queue.path)) as db:
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES (?, 'local',0,'running',0)", (self.task.id,))
            db.commit()
        with self.fixture.no_old_io(outside), patch("app.processor.process_local_video_task") as process:
            result = recover_processing(queue_root)
            queue_for(queue_root).stop()
        self.assertEqual(result, {"recovered": 0, "waiting_for_context": 1})
        self.assertEqual(storage.get_task(self.task.id).error_code, "resume_source_required")
        process.assert_not_called()
        self.assertEqual(outside.read_bytes(), b"OLD PRIVATE SYNTHETIC COPY")

    def test_missing_current_subtitle_does_not_mutate_retry_admission(self):
        media = self.root / "media.mp4"; media.write_bytes(b"media fixture")
        task = self.native_task(media_path=str(media), subtitle_path=str(self.root / "missing.srt"))
        self.fixture.manifest(**task.model_dump(mode="json"))
        before = (self.root / "task.json").read_bytes()
        result = self.fixture.client.post(f"/api/tasks/{task.id}/retry", json={})
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual((self.root / "task.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
