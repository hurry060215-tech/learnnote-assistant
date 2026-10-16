"""End-to-end saved-path boundaries, including reads outside artifact endpoints."""
import hashlib
import json
import os
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch

from app import document_exports, learning_spaces, processor, storage
from app.models import FrameGrid, TaskOptions
from app.range_media import range_media_preview_state
from app.task_paths import TaskArtifactUnavailable
import test_task_export_boundary as export_fixtures


class TaskPathCallerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = export_fixtures.TaskExportBoundaryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.task = self.fixture.root, self.fixture.task

    def test_stale_copied_task_listing_preserves_manifest_hash_mtime_and_good_task(self):
        outside = self.fixture.old_file("media.mp4")
        self.fixture.manifest(media_path=str(outside), status="running", updated_at="2020-01-01T00:00:00Z")
        good_root, good = self.fixture.fixture.copied_foreign("good-task")
        manifest = self.root / "task.json"
        before = manifest.read_bytes(), manifest.stat().st_mtime_ns
        with self.fixture.no_old_io(outside), patch("app.media.probe_duration", side_effect=AssertionError("No probe in listing")):
            result = self.fixture.client.get("/api/tasks")
        self.assertEqual(result.status_code, 200, result.text)
        tasks = {item["id"]: item for item in result.json()["tasks"]}
        self.assertIn(good.id, tasks)
        self.assertEqual(tasks[self.task.id]["status"], "running")
        self.assertEqual((manifest.read_bytes(), manifest.stat().st_mtime_ns), before)
        self.assertIn("media_path", tasks[self.task.id]["artifact_status"]["path_diagnostics"])
        self.assertEqual(outside.read_bytes(), b"OLD PRIVATE SYNTHETIC COPY")

    def test_real_caption_only_child_retains_owned_subtitle_and_source_bytes(self):
        source = self.root / "browser_subtitles.srt"
        original = source.read_bytes()
        media = self.root / "media.mp4"; media.write_bytes(b"synthetic never decoded")
        options = TaskOptions(content_mode="subtitles", use_saved_connection=False)
        child = storage.create_task("local", "Caption child", options=options, mode="rerun_from_media")
        storage.update_task(child.id, source_task_id=self.task.id, source_media_path=str(media))
        with patch("app.processor.extract_embedded_subtitle", side_effect=AssertionError("No media decode")), patch("app.processor.summarize_with_diagnostics", side_effect=AssertionError("No model")):
            processor.process_local_video_task(child.id, media, child.title, options, subtitle_path=source)
        saved = storage.get_task(child.id)
        self.assertEqual(saved.status, "success", saved.error_detail)
        self.assertEqual(Path(saved.subtitle_path).parent, self.root.parent / child.id)
        self.assertNotEqual(saved.subtitle_path, str(source))
        result = self.fixture.client.get(f"/api/tasks/{child.id}/exports/subtitles")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.content, original)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.fixture.client.get(f"/api/tasks/{child.id}/note").status_code, 200)

    def test_caption_parses_retained_snapshot_when_original_changes_after_parse(self):
        source = self.root / "browser_subtitles.srt"
        original = source.read_bytes()
        options = TaskOptions(content_mode="subtitles", use_saved_connection=False)
        child = storage.create_task("local", "Caption snapshot", options=options, mode="rerun_from_media")
        parse = processor.parse_subtitle_or_none
        def changed_after_parse(path, **kwargs):
            self.assertEqual(path.parent, self.root.parent / child.id)
            result = parse(path, **kwargs)
            source.write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nCHANGED ORIGINAL\n")
            return result
        with patch.object(processor, "parse_subtitle_or_none", side_effect=changed_after_parse):
            processor.process_local_video_task(child.id, self.root / "unused.mp4", child.title, options, subtitle_path=source)
        saved = storage.get_task(child.id)
        self.assertEqual(saved.status, "success", saved.error_detail)
        result = self.fixture.client.get(f"/api/tasks/{child.id}/exports/subtitles")
        self.assertEqual(result.content, original)
        self.assertNotIn("CHANGED ORIGINAL", (self.root.parent / child.id / "transcript.json").read_text())

    def test_caption_copy_failure_never_publishes_success_or_cross_task_pointer(self):
        source = self.root / "browser_subtitles.srt"
        original = source.read_bytes()
        options = TaskOptions(content_mode="subtitles", use_saved_connection=False)
        child = storage.create_task("local", "Caption copy failure", options=options, mode="rerun_from_media")
        with patch("app.subtitle_ownership.shutil.copyfileobj", side_effect=OSError("synthetic full disk")):
            processor.process_local_video_task(child.id, self.root / "unused.mp4", child.title, options, subtitle_path=source)
        saved = storage.get_task(child.id)
        self.assertEqual(saved.status, "failed")
        self.assertEqual(saved.subtitle_path, "")
        self.assertFalse((self.root.parent / child.id / source.name).exists())
        self.assertEqual(source.read_bytes(), original)

    def test_screen_ocr_summary_api_and_worker_never_hash_old_copied_media(self):
        outside = self.fixture.old_file("media.mp4")
        digest = hashlib.sha256(outside.read_bytes()).hexdigest()
        transcript = json.loads((self.root / "transcript.json").read_text())
        transcript.update(source="screen-ocr", provenance={"status": "ready", "coverage": {"complete": True}, "media_sha256": digest})
        (self.root / "transcript.json").write_text(json.dumps(transcript))
        self.fixture.manifest(media_path=str(outside), screen_subtitles_media_sha256=digest)
        before = (self.root / "task.json").read_bytes()
        with self.fixture.no_old_io(outside), patch("app.screen_subtitles.media_hash") as media_hash, patch("app.main.schedule_processing") as schedule:
            result = self.fixture.client.post(f"/api/tasks/{self.task.id}/retry-summary", json={"content_mode": "text"})
            self.assertEqual(result.status_code, 409, result.text)
            with patch("app.processor._fail"), patch("app.processor.summarize_with_diagnostics") as model:
                processor.process_saved_transcript_task(self.task.id, TaskOptions(content_mode="text"))
                model.assert_not_called()
            media_hash.assert_not_called(); schedule.assert_not_called()
        self.assertEqual((self.root / "task.json").read_bytes(), before)

    def test_learning_source_resource_usage_grid_and_range_preview_never_probe_old_paths(self):
        outside = self.fixture.old_file("report.json", b'{"outside":true}')
        with self.fixture.no_old_io(outside):
            self.fixture.manifest(note_path=str(outside))
            with self.assertRaises(TaskArtifactUnavailable):
                learning_spaces._live_source("task", self.task.id)
            self.fixture.manifest(resource_usage_path=str(outside))
            result = self.fixture.client.get(f"/api/tasks/{self.task.id}/exports/resource-usage")
            self.assertEqual(result.status_code, 409, result.text)
            task = self.task.model_copy(update={"frame_grids": [FrameGrid(path=str(outside), url=f"/api/tasks/{self.task.id}/assets/report.json", start=0, end=5, frame_count=1)]})
            with patch.object(document_exports, "TASK_DIR", self.root.parent):
                image, _ = document_exports._task_image(task, f"![caption](/api/tasks/{task.id}/assets/report.json)")
            self.assertIsNone(image)
            task = self.task.model_copy(update={"media_path": str(outside), "learning_range": {"start": 0, "end": 5}, "screen_subtitles_media_sha256": "known"})
            self.assertFalse(range_media_preview_state(task)["range_media_ready"])

    def test_deletion_preview_and_owned_cleanup_never_probe_copied_original(self):
        from app.course_deletion import _dependency_owners
        outside = self.fixture.old_file("media.mp4")
        self.fixture.manifest(source_media_path=str(outside))
        before = (self.root / "task.json").read_bytes()
        with self.fixture.no_old_io(outside), self.assertRaises(TaskArtifactUnavailable):
            _dependency_owners()
        self.assertEqual((self.root / "task.json").read_bytes(), before)
        with self.fixture.no_old_io(outside), patch.object(storage, "DATA_DIR", self.root.parent.parent), patch.object(storage, "UPLOAD_DIR", self.root.parent.parent / "uploads"):
            result = storage.delete_task(self.task.id)
        self.assertEqual(result["task_id"], self.task.id)
        self.assertEqual(outside.read_bytes(), b"OLD PRIVATE SYNTHETIC COPY")

    def test_dependency_preview_rejects_selected_symlink_without_reading_target(self):
        from app.task_paths import lexical_task_dependency
        outside = self.fixture.old_file("private.mp4")
        linked = self.root / "linked.mp4"
        try:
            linked.symlink_to(outside)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.fixture.no_old_io(outside), self.assertRaises(TaskArtifactUnavailable) as caught:
            lexical_task_dependency(self.root.parent, str(linked))
        self.assertEqual(caught.exception.reason, "linked_destination")
        self.assertEqual(outside.read_bytes(), b"OLD PRIVATE SYNTHETIC COPY")

    def test_optional_upload_cleanup_preserves_ambiguous_or_unvalidated_survivors(self):
        data = self.root.parent.parent
        uploads = data / "uploads"
        uploads.mkdir(exist_ok=True)
        for kind in ("dot_alias", "media_reference", "symlink_alias", "outside_reference", "broken", "linked"):
            with self.subTest(kind=kind), patch.object(storage, "DATA_DIR", data), patch.object(storage, "UPLOAD_DIR", uploads):
                upload = uploads / (kind + ".mp4")
                upload.write_bytes(b"shared synthetic upload")
                task = storage.create_task("local", "Delete own task")
                storage.update_task(task.id, status="success", source_media_path=str(upload))
                survivor = storage.create_task("local", "Surviving task")
                manifest = self.root.parent / survivor.id / "task.json"
                if kind == "dot_alias":
                    storage.update_task(survivor.id, source_media_path=str(uploads) + "/./" + upload.name)
                elif kind == "media_reference":
                    storage.update_task(survivor.id, media_path=str(upload))
                elif kind == "symlink_alias":
                    alias = uploads / "alias.mp4"
                    try:
                        alias.symlink_to(upload)
                    except OSError as exc:
                        self.skipTest(str(exc))
                    storage.update_task(survivor.id, source_media_path=str(alias))
                elif kind == "outside_reference":
                    storage.update_task(survivor.id, source_media_path=str(data / "outside" / "unavailable.mp4"))
                elif kind == "broken":
                    manifest.write_text("{broken")
                else:
                    outside = self.fixture.old_file("linked-task.json", manifest.read_bytes())
                    manifest.unlink()
                    try:
                        manifest.symlink_to(outside)
                    except OSError as exc:
                        self.skipTest(str(exc))
                before = manifest.lstat().st_mtime_ns
                storage.delete_task(task.id)
                self.assertEqual(upload.read_bytes(), b"shared synthetic upload")
                self.assertEqual(manifest.lstat().st_mtime_ns, before)
                manifest.unlink()
                manifest.parent.rmdir()  # Do not let an empty survivor mask the next uncertainty case.

    def test_optional_cleanup_preserves_upload_for_linked_surviving_task_directory(self):
        data = self.root.parent.parent
        uploads = data / "uploads"
        uploads.mkdir(exist_ok=True)
        for dangling in (False, True):
            with self.subTest(dangling=dangling), patch.object(storage, "DATA_DIR", data), patch.object(storage, "UPLOAD_DIR", uploads):
                upload = uploads / ("linked-dir-" + str(dangling) + ".mp4")
                upload.write_bytes(b"shared synthetic upload")
                task = storage.create_task("local", "Delete own task")
                storage.update_task(task.id, status="success", source_media_path=str(upload))
                survivor = storage.create_task("local", "Surviving task")
                storage.update_task(survivor.id, source_media_path=str(upload))
                folder = self.root.parent / survivor.id
                detached = data / ("detached-" + survivor.id)
                folder.rename(detached)
                original = (detached / "task.json").read_bytes()
                target = detached / "unavailable" if dangling else detached
                try:
                    folder.symlink_to(target, target_is_directory=True)
                except OSError as exc:
                    self.skipTest(str(exc))
                with self.fixture.no_old_io(detached):
                    storage.delete_task(task.id)
                self.assertEqual(upload.read_bytes(), b"shared synthetic upload")
                self.assertEqual((detached / "task.json").read_bytes(), original)
                folder.unlink()

    def test_optional_cleanup_uses_validated_file_identity_not_lexical_inequality(self):
        from app import task_media_guard
        data = self.root.parent.parent
        uploads = data / "uploads"
        uploads.mkdir(exist_ok=True)
        for kind in ("hard_link", "unknown_identity", "independent_file"):
            with self.subTest(kind=kind), patch.object(storage, "DATA_DIR", data), patch.object(storage, "UPLOAD_DIR", uploads):
                upload = uploads / (kind + ".mp4")
                upload.write_bytes(b"shared synthetic upload")
                alias = uploads / (kind + "-alias.mp4")
                if kind == "hard_link":
                    os.link(upload, alias)
                else:
                    alias.write_bytes(b"independent synthetic upload")
                task = storage.create_task("local", "Delete own task")
                storage.update_task(task.id, status="success", source_media_path=str(upload))
                survivor = storage.create_task("local", "Surviving task")
                storage.update_task(survivor.id, source_media_path=str(alias))
                manifest = self.root.parent / survivor.id / "task.json"
                before = manifest.read_bytes(), manifest.stat().st_mtime_ns, alias.read_bytes()
                original_check = task_media_guard._check_node
                def checked(path, *, file):
                    node = original_check(path, file=file)
                    return SimpleNamespace(st_dev=node.st_dev, st_ino=0) if kind == "unknown_identity" and path == alias else node
                with patch.object(task_media_guard, "_check_node", side_effect=checked):
                    storage.delete_task(task.id)
                self.assertEqual(upload.exists(), kind != "independent_file")
                self.assertEqual((manifest.read_bytes(), manifest.stat().st_mtime_ns, alias.read_bytes()), before)
                manifest.unlink(); manifest.parent.rmdir()

    def test_unshared_current_upload_retains_existing_optional_cleanup(self):
        data = self.root.parent.parent
        uploads = data / "uploads"
        uploads.mkdir(exist_ok=True)
        upload = uploads / "unshared.mp4"
        upload.write_bytes(b"unshared synthetic upload")
        with patch.object(storage, "DATA_DIR", data), patch.object(storage, "UPLOAD_DIR", uploads):
            task = storage.create_task("local", "Delete own task")
            storage.update_task(task.id, status="success", source_media_path=str(upload))
            storage.delete_task(task.id)
        self.assertFalse(upload.exists())

    def test_saved_visual_cache_linked_ancestor_is_rejected_before_old_read(self):
        import test_visual_sampling_safety as visual_fixtures
        from app.visual_pipeline import _preserved_visual_evidence
        from app.media import MediaProcessingError
        visual = visual_fixtures.SamplingSafetyTests()
        visual.setUp()
        self.addCleanup(visual.doCleanups)
        visual.legacy_index()
        cache = visual.root / "frames" / "frame_cache.json"
        outside = self.fixture.old_file("frame_cache.json", cache.read_bytes())
        cache.unlink()
        (visual.root / "frames" / "frame_0000_000000.jpg").unlink()
        (visual.root / "frames").rmdir()
        try:
            (visual.root / "frames").symlink_to(outside.parent, target_is_directory=True)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.fixture.no_old_io(outside), self.assertRaises(MediaProcessingError):
            _preserved_visual_evidence(visual.root, visual.video)

    def test_saved_visual_frame_outside_task_is_rejected_before_probe(self):
        import test_visual_sampling_safety as visual_fixtures
        from app.visual_pipeline import _preserved_visual_evidence
        from app.media import MediaProcessingError
        visual = visual_fixtures.SamplingSafetyTests()
        visual.setUp()
        self.addCleanup(visual.doCleanups)
        visual.legacy_index()
        outside = self.fixture.old_file("frame.jpg", b"old frame")
        index = visual.root / "visual_index.json"
        payload = json.loads(index.read_text())
        payload["frames"][0]["path"] = str(outside)
        index.write_text(json.dumps(payload))
        before = index.read_bytes()
        with self.fixture.no_old_io(outside), self.assertRaises(MediaProcessingError):
            _preserved_visual_evidence(visual.root, visual.video)
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(outside.read_bytes(), b"old frame")


if __name__ == "__main__":
    unittest.main()
