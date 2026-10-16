"""Saved-media callers reject uncertain copies before any old-path I/O."""
from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import course_upgrade_links, library, range_learning, storage
from app.models import MediaIntegrity, SourceIdentity, TaskOptions, TaskRecord


class TaskMediaCallerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.sandbox = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = self.sandbox / "selected"
        self.tasks = self.root / "tasks"
        self.owned = self.tasks / "child"
        self.owned.mkdir(parents=True)
        self.old = self.sandbox / "old"
        self.old_media = self.old / "tasks" / "child" / "media.mp4"
        self.old_media.parent.mkdir(parents=True)
        self.old_media.write_bytes(b"old synthetic media must never be opened")
        self.stack.enter_context(patch.object(storage, "TASK_DIR", self.tasks))
        self.stack.enter_context(patch.object(range_learning, "DATA_DIR", self.root))
        self.stack.enter_context(patch.multiple(library, DATA_DIR=self.root, TASK_DIR=self.tasks))
        self.stack.enter_context(patch.object(library, "ensure_dirs"))
        self.stack.enter_context(patch("app.knowledge.evidence_for_task", return_value=[]))
        self.source = TaskRecord(id="source", source_type="current_page", title="Synthetic source",
            page_url="https://www.youtube.com/watch?v=abcdefghijk", created_at="", updated_at="")
        self.episode = {"episode_id": "episode"}
        self.task = TaskRecord(id="child", source_type="current_page", mode="video", title="Synthetic child",
            page_url=self.source.page_url, source_task_id=self.source.id, status="failed", created_at="", updated_at="",
            handoff_id=course_upgrade_links.upgrade_prefix("course", "episode", "source") + "a" * 32,
            media_integrity=MediaIntegrity(duration=60))

    @contextmanager
    def no_old_io(self):
        with ExitStack() as stack:
            for method in ("stat", "lstat", "is_file", "exists", "resolve", "read_bytes", "read_text", "open"):
                original = getattr(Path, method)
                def guarded(path, *args, _original=original, **kwargs):
                    if path == self.old or self.old in path.parents:
                        raise AssertionError("Saved old path must be rejected before filesystem access")
                    return _original(path, *args, **kwargs)
                stack.enter_context(patch.object(Path, method, guarded))
            yield

    def course_available(self, task):
        result = course_upgrade_links.episode_upgrades("course", self.episode, self.source, [task])
        self.assertEqual(len(result), 1)
        return result[0]["media_available"]

    def create_range(self, task):
        child = task.model_copy(update={"id": "new-range"})
        with patch.object(range_learning, "get_task", return_value=task), \
                patch.object(range_learning, "create_task", return_value=child) as create, \
                patch.object(range_learning, "update_task", side_effect=lambda key, **changes: child.model_copy(update=changes)), \
                patch.object(range_learning, "schedule_processing") as schedule:
            result = range_learning._create_range_task(task.id, 5, 10, TaskOptions(), None)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(schedule.call_count, 1)
        self.assertEqual(result.source_task_id, task.id)
        return result

    def assert_range_rejected(self, task):
        with patch.object(range_learning, "get_task", return_value=task), \
                patch.object(range_learning, "create_task") as create, \
                patch.object(range_learning, "schedule_processing") as schedule, \
                patch.object(range_learning, "completed_range_media") as completed:
            with self.assertRaises(HTTPException) as failure:
                range_learning._create_range_task(task.id, 5, 10, TaskOptions(), None)
        self.assertEqual(failure.exception.status_code, 409)
        self.assertEqual(failure.exception.detail["code"], "task_artifact_unavailable")
        self.assertTrue(failure.exception.detail["requires_preview"])
        create.assert_not_called()
        schedule.assert_not_called()
        completed.assert_not_called()

    def test_course_range_and_material_do_not_probe_still_existing_old_media(self):
        task = self.task.model_copy(update={"media_path": str(self.old_media)})
        with self.no_old_io(), patch.object(library, "_file_sha256") as digest:
            self.assertFalse(self.course_available(task))
            self.assert_range_rejected(task)
            material = library.register_task_material(task)
            digest.assert_not_called()
        self.assertEqual(material["byte_size"], 0)
        self.assertEqual(material["filename"], "media.mp4")
        self.assertEqual(material["sha256"], hashlib.sha256(b"task\0child").hexdigest())
        self.assertEqual(self.old_media.read_bytes(), b"old synthetic media must never be opened")

    def test_copied_artifact_provenance_blocks_even_a_current_native_media_pointer(self):
        media = self.owned / "media.mp4"
        media.write_bytes(b"current selected copy")
        task = self.task.model_copy(update={"media_path": str(media), "note_path": str(self.old_media.parent / "note.md")})
        with self.no_old_io(), patch.object(library, "_file_sha256") as digest:
            self.assertFalse(self.course_available(task))
            self.assert_range_rejected(task)
            self.assertEqual(library.register_task_material(task)["byte_size"], 0)
            digest.assert_not_called()

    def test_foreign_media_does_not_become_a_host_relative_file(self):
        raw = "/foreign/tasks/child/media.mp4" if os.name == "nt" else r"D:\foreign\tasks\child\media.mp4"
        task = self.task.model_copy(update={"source_media_path": raw})
        with patch.object(Path, "stat", side_effect=AssertionError("foreign path must not be probed")), \
                patch.object(Path, "lstat", side_effect=AssertionError("foreign path must not be probed")), \
                patch.object(Path, "resolve", side_effect=AssertionError("foreign path must not be resolved")):
            self.assertFalse(self.course_available(task))
            self.assert_range_rejected(task)
        with patch.object(library, "_file_sha256") as digest:
            self.assertEqual(library.register_task_material(task)["byte_size"], 0)
            digest.assert_not_called()

    def test_copied_range_stops_before_duration_probe(self):
        task = self.task.model_copy(update={"media_path": str(self.old_media), "learning_range": {"start": 0, "end": 60}})
        with self.no_old_io():
            self.assert_range_rejected(task)

    def test_linked_current_media_never_opens_the_old_target(self):
        media = self.owned / "media.mp4"
        try:
            media.symlink_to(self.old_media)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlink creation unsupported: {exc}")
        task = self.task.model_copy(update={"media_path": str(media)})
        with self.no_old_io(), patch.object(library, "_file_sha256") as digest:
            self.assertFalse(self.course_available(task))
            self.assert_range_rejected(task)
            self.assertEqual(library.register_task_material(task)["byte_size"], 0)
            digest.assert_not_called()

    def test_current_media_uploads_and_explicit_source_dependencies_remain_available(self):
        for label, media in (("owned", self.owned / "media.mp4"),
                             ("upload", self.root / "uploads" / "selected.mp4"),
                             ("dependency", self.tasks / "source" / "media.mp4")):
            with self.subTest(kind=label):
                media.parent.mkdir(parents=True, exist_ok=True)
                content = ("current synthetic " + label).encode()
                media.write_bytes(content)
                task = self.task.model_copy(update={"source_media_path": str(media)})
                self.assertTrue(self.course_available(task))
                self.assertEqual(self.create_range(task).source_media_path, str(media))
                material = library.register_task_material(task)
                self.assertEqual(material["sha256"], hashlib.sha256(content).hexdigest())
                self.assertEqual(material["byte_size"], len(content))
                self.assertEqual(media.read_bytes(), content)

    def test_missing_current_media_falls_back_to_the_explicit_current_upload(self):
        upload = self.root / "uploads" / "fallback.mp4"
        upload.parent.mkdir()
        upload.write_bytes(b"current fallback upload")
        task = self.task.model_copy(update={"media_path": str(self.owned / "missing.mp4"), "source_media_path": str(upload)})
        self.assertTrue(self.course_available(task))
        self.assertEqual(self.create_range(task).source_media_path, str(upload))
        self.assertEqual(library.register_task_material(task)["byte_size"], len(b"current fallback upload"))

    def test_known_material_digest_does_not_authorize_old_media_stat(self):
        task = self.task.model_copy(update={"media_path": str(self.old_media), "source_identity": SourceIdentity(media_sha256="a" * 64)})
        with self.no_old_io(), patch.object(library, "_file_sha256") as digest:
            material = library.register_task_material(task)
            digest.assert_not_called()
        self.assertEqual(material["sha256"], "a" * 64)
        self.assertEqual(material["byte_size"], 0)


if __name__ == "__main__":
    unittest.main()
