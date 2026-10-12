"""Synthetic dependency and submission/deletion ordering regressions."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

from app import course_episodes, courses, main, range_learning, storage
from app.models import MediaIntegrity, TaskOptions
from backend.tests import test_course_deletion as deletion_fixtures
from backend.tests import test_course_media_reuse as reuse_fixtures


class CourseRangeDependencyTests(unittest.TestCase):
    def test_course_write_error_returns_the_reviewed_constant(self):
        from app.routers.courses import _course_write_error_code

        class ChangingMessage(ValueError):
            calls = 0

            def __str__(self):
                self.calls += 1
                return "course_busy" if self.calls == 1 else "synthetic private details"

        error = ChangingMessage()
        self.assertEqual(_course_write_error_code(error), "course_busy")
        self.assertEqual(error.calls, 1)

    def setUp(self):
        self.fixture = deletion_fixtures.CourseDeletionTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def check_retained_range_dependency(self, scope):
        fixture = self.fixture
        source = fixture.task("Synthetic source video")
        media = storage.task_dir(source.id) / "source.mp4"
        media.write_bytes(b"synthetic media; processing is mocked")
        source = storage.update_task(
            source.id, media_path=str(media), media_integrity=MediaIntegrity(duration=60)
        )
        owner = fixture.course(source)
        with patch.object(range_learning, "DATA_DIR", fixture.root), patch.object(
            range_learning, "schedule_processing"
        ) as schedule:
            child = range_learning.create_range_task(source.id, 0, 10, TaskOptions(), None)
        self.assertEqual(schedule.call_count, 1)
        self.assertEqual(child.status, "queued")
        self.assertEqual(child.source_task_id, source.id)
        self.assertEqual(child.source_media_path, str(media.resolve()))

        other = None
        if scope == "other_course":
            other = fixture.course(child)
        elif scope == "same_course":
            owner = courses.save_course(
                owner["title"], owner["sources"] + [{"kind": "task", "id": child.id}],
                course_id=owner["id"], revision=owner["revision"]
            )

        preview = fixture.preview(owner)
        candidate = next(item for item in preview["tasks"] if item["task_id"] == source.id)
        self.assertFalse(candidate["eligible"])
        self.assertEqual(candidate["reason"], "dependent_task")
        self.assertEqual(fixture.delete(owner, [source.id], preview).status_code, 409)
        self.assertEqual(storage.get_task(source.id).id, source.id)
        self.assertEqual(storage.get_task(child.id).status, "queued")
        self.assertEqual(media.read_bytes(), b"synthetic media; processing is mocked")
        self.assertEqual(courses.get_course(owner["id"]), owner)
        if other is not None:
            self.assertEqual(courses.get_course(other["id"]), other)

        # Removing the grouping remains allowed without breaking the retained child.
        result = fixture.delete(owner, preview=preview)
        self.assertTrue(result.json()["deleted"], result.text)
        self.assertEqual(result.json()["deleted_task_ids"], [])
        self.assertEqual(storage.get_task(child.id).status, "queued")
        self.assertTrue(media.is_file())

    def test_active_range_in_another_course_protects_source(self):
        self.check_retained_range_dependency("other_course")

    def test_unselected_active_range_in_same_course_protects_source(self):
        self.check_retained_range_dependency("same_course")

    def test_active_range_without_course_protects_source(self):
        self.check_retained_range_dependency("unassigned")

    def test_range_admission_persists_dependency_before_reviewed_deletion(self):
        fixture = self.fixture
        source = fixture.task()
        media = storage.task_dir(source.id) / "source.mp4"
        media.write_bytes(b"synthetic media")
        source = storage.update_task(source.id, media_path=str(media), media_integrity=MediaIntegrity(duration=60))
        owner = fixture.course(source)
        preview = fixture.preview(owner)
        creating, release, deleting = (threading.Event() for _ in range(3))
        real_create = range_learning.create_task

        def delayed_create(*args, **kwargs):
            creating.set()
            if not release.wait(5):
                raise TimeoutError("Synthetic range gate was not released")
            return real_create(*args, **kwargs)

        def remove():
            deleting.set()
            return fixture.delete(owner, [source.id], preview)

        with patch.object(range_learning, "DATA_DIR", fixture.root), patch.object(range_learning, "schedule_processing") as schedule, patch.object(range_learning, "create_task", side_effect=delayed_create):
            with ThreadPoolExecutor(max_workers=2) as pool:
                admission = pool.submit(range_learning.create_range_task, source.id, 0, 10, TaskOptions(), None)
                try:
                    self.assertTrue(creating.wait(5))
                    deletion = pool.submit(remove)
                    self.assertTrue(deleting.wait(5))
                    self.assertFalse(deletion.done())
                finally:
                    release.set()
                child = admission.result(timeout=5)
                self.assertEqual(deletion.result(timeout=5).status_code, 409)
        self.assertEqual(child.source_task_id, source.id)
        self.assertEqual(schedule.call_count, 1)
        self.assertTrue(media.is_file())
        self.assertEqual(storage.get_task(source.id).id, source.id)

    def test_range_admission_after_deletion_cannot_create_an_orphan(self):
        fixture = self.fixture
        source = fixture.task()
        media = storage.task_dir(source.id) / "source.mp4"
        media.write_bytes(b"synthetic media")
        storage.update_task(source.id, media_path=str(media), media_integrity=MediaIntegrity(duration=60))
        owner = fixture.course(source)
        preview = fixture.preview(owner)
        removing, release, creating = (threading.Event() for _ in range(3))
        real_delete = storage.delete_task

        def delayed_delete(task_id):
            removing.set()
            if not release.wait(5):
                raise TimeoutError("Synthetic deletion gate was not released")
            return real_delete(task_id)

        def admit():
            creating.set()
            return range_learning.create_range_task(source.id, 0, 10, TaskOptions(), None)

        with patch.object(range_learning, "DATA_DIR", fixture.root), patch.object(range_learning, "schedule_processing") as schedule, patch.object(storage, "delete_task", side_effect=delayed_delete):
            with ThreadPoolExecutor(max_workers=2) as pool:
                deletion = pool.submit(fixture.delete, owner, [source.id], preview)
                try:
                    self.assertTrue(removing.wait(5))
                    admission = pool.submit(admit)
                    self.assertTrue(creating.wait(5))
                    self.assertFalse(admission.done())
                finally:
                    release.set()
                self.assertTrue(deletion.result(timeout=5).json()["deleted"])
                with self.assertRaises(FileNotFoundError):
                    admission.result(timeout=5)
        self.assertEqual(storage.list_tasks_snapshot(), [])
        schedule.assert_not_called()


class CourseCorruptStorageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = deletion_fixtures.CourseDeletionTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_invalid_course_identity_and_structure_reject_stale_delete_without_writes(self):
        fixture = self.fixture
        task = fixture.task()
        owner = fixture.course(task)
        preview = fixture.preview(owner)
        path = courses._path(owner["id"])
        invalid = [[], {**owner, "id": "a" * 32}, {**owner, "schema_version": True}, {**owner, "sources": [None]},
                   {**owner, "sources": [{"kind": [], "id": task.id, "title": "Invalid"}]},
                   {**owner, "sources": [{"kind": "task", "id": "../outside", "title": "Invalid"}]}]
        for payload in invalid:
            with self.subTest(payload=payload):
                path.write_text(json.dumps(payload))
                before = path.read_bytes()
                response = fixture.client.get(f"/api/courses/{owner['id']}/deletion-preview")
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(fixture.delete(owner, [task.id], preview).status_code, 409)
                self.assertEqual(path.read_bytes(), before)
                self.assertTrue(storage.task_file(task.id).is_file())

    def test_corrupt_other_course_and_nonobject_task_manifest_protect_all_children(self):
        fixture = self.fixture
        task = fixture.task()
        owner = fixture.course(task)
        other = fixture.course()
        courses._path(other["id"]).write_text(json.dumps({**other, "sources": [None]}))
        preview = fixture.preview(owner)
        self.assertEqual(preview["tasks"][0]["reason"], "references_unavailable")
        self.assertEqual(fixture.delete(owner, [task.id], preview).status_code, 409)
        courses._path(other["id"]).write_text(json.dumps(other))
        broken = fixture.task("Broken")
        storage.task_file(broken.id).write_text("42")
        preview = fixture.preview(owner)
        self.assertEqual(preview["tasks"][0]["reason"], "references_unavailable")
        self.assertEqual(fixture.delete(owner, [task.id], preview).status_code, 409)

    def test_unknown_queue_state_is_protected(self):
        fixture = self.fixture
        task = fixture.task()
        owner = fixture.course(task)
        with sqlite3.connect(fixture.root / "task-queue.sqlite3") as db:
            db.execute("CREATE TABLE jobs(task_id TEXT,state TEXT)")
            db.execute("INSERT INTO jobs VALUES (?, 'unknown')", (task.id,))
        preview = fixture.preview(owner)
        self.assertEqual(preview["tasks"][0]["reason"], "busy_task")
        self.assertEqual(fixture.delete(owner, [task.id], preview).status_code, 409)


class CourseMediaCloneDeletionRaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = reuse_fixtures.CourseMediaReuseTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_deleted_source_during_media_validation_cannot_create_a_clone(self):
        fixture = self.fixture
        source = storage.create_task("local", "Synthetic source")
        media = storage.task_dir(source.id) / "source.mp4"
        media.write_bytes(b"synthetic media")
        storage.update_task(source.id, status="success", media_path=str(media))
        owner = courses.save_course("Synthetic owner", [{"kind": "task", "id": source.id}])
        preview = fixture.client.get(f"/api/courses/{owner['id']}/deletion-preview").json()
        validating, release = threading.Event(), threading.Event()

        def validate(path):
            self.assertEqual(path, media)
            validating.set()
            if not release.wait(5):
                raise TimeoutError("Synthetic validation gate was not released")
            return MediaIntegrity(duration=60)

        with patch.object(main, "validate_local_upload_file", side_effect=validate), ThreadPoolExecutor(max_workers=1) as pool:
            cloning = pool.submit(fixture.client.post, f"/api/tasks/{source.id}/rerun-from-media", json={})
            try:
                self.assertTrue(validating.wait(5))
                deletion = fixture.client.request("DELETE", f"/api/courses/{owner['id']}", json={
                    "confirm": "delete_course", "revision": preview["revision"], "snapshot": preview["snapshot"], "task_ids": [source.id]})
                self.assertEqual(deletion.status_code, 200, deletion.text)
                self.assertTrue(deletion.json()["deleted"])
            finally:
                release.set()
            response = cloning.result(timeout=5)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "media_source_changed")
        self.assertEqual(storage.list_tasks_snapshot(), [])
        fixture.schedule.assert_not_called()

    def test_clone_dependency_is_durable_before_deletion_can_recheck(self):
        fixture = self.fixture
        source = storage.create_task("local", "Synthetic source")
        media = storage.task_dir(source.id) / "source.mp4"
        media.write_bytes(b"synthetic media")
        storage.update_task(source.id, status="success", media_path=str(media))
        owner = courses.save_course("Synthetic owner", [{"kind": "task", "id": source.id}])
        preview = fixture.client.get(f"/api/courses/{owner['id']}/deletion-preview").json()
        creating, release, deleting = (threading.Event() for _ in range(3))
        real_create = main.create_task

        def create(*args, **kwargs):
            task = real_create(*args, **kwargs)
            creating.set()
            if not release.wait(5):
                raise TimeoutError("Synthetic clone gate was not released")
            return task

        def remove():
            deleting.set()
            return fixture.client.request("DELETE", f"/api/courses/{owner['id']}", json={
                "confirm": "delete_course", "revision": preview["revision"], "snapshot": preview["snapshot"], "task_ids": [source.id]})

        with patch.object(main, "validate_local_upload_file", return_value=MediaIntegrity(duration=60)), patch.object(main, "create_task", side_effect=create), ThreadPoolExecutor(max_workers=2) as pool:
            cloning = pool.submit(fixture.client.post, f"/api/tasks/{source.id}/rerun-from-media", json={})
            try:
                self.assertTrue(creating.wait(5))
                deletion = pool.submit(remove)
                self.assertTrue(deleting.wait(5))
                self.assertFalse(deletion.done())
            finally:
                release.set()
            response = cloning.result(timeout=5)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(deletion.result(timeout=5).status_code, 409)
        child = storage.get_task(response.json()["task_id"])
        self.assertEqual(child.source_task_id, source.id)
        self.assertTrue(media.is_file())
        self.assertEqual(fixture.schedule.call_count, 1)


class CourseReservationDeletionRaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = reuse_fixtures.CourseMediaReuseTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_deletion_waits_until_validated_submission_persists_identity(self):
        fixture = self.fixture
        course = fixture.course()
        prepared = fixture.prepare(course)
        creating, release, deleting, deleted = (threading.Event() for _ in range(4))
        real_create = main.create_task

        def delayed_create(*args, **kwargs):
            creating.set()
            if not release.wait(5):
                raise TimeoutError("Synthetic creation gate was not released")
            return real_create(*args, **kwargs)

        def delete_course():
            deleting.set()
            courses.delete_course(course["id"])
            deleted.set()

        with patch.object(main, "create_task", side_effect=delayed_create):
            with ThreadPoolExecutor(max_workers=2) as pool:
                submission = pool.submit(fixture.submit, prepared)
                removal = None
                try:
                    self.assertTrue(creating.wait(5))
                    removal = pool.submit(delete_course)
                    self.assertTrue(deleting.wait(5))
                    self.assertFalse(deleted.wait(.1), "Deletion passed an in-flight validated submission")
                finally:
                    release.set()
                response = submission.result(timeout=5)
                self.assertIsNotNone(removal)
                removal.result(timeout=5)

        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        self.assertEqual(storage.get_task(task_id).handoff_id, prepared["handoff_id"])
        self.assertFalse(courses._path(course["id"]).exists())
        self.assertEqual(fixture.schedule.call_count, 1)
        self.assertEqual(fixture.submit(prepared).status_code, 409)
        self.assertEqual(fixture.schedule.call_count, 1)
        self.assertEqual(len(storage.list_tasks_snapshot()), 1)

    def test_submission_waits_for_deletion_then_rejects_removed_reservation(self):
        fixture = self.fixture
        course = fixture.course()
        prepared = fixture.prepare(course)
        clearing, release, submitting, submitted = (threading.Event() for _ in range(4))
        real_clear = course_episodes.clear_course_episode_links

        def delayed_clear(course_id):
            clearing.set()
            if not release.wait(5):
                raise TimeoutError("Synthetic deletion gate was not released")
            return real_clear(course_id)

        def submit():
            submitting.set()
            response = fixture.submit(prepared)
            submitted.set()
            return response

        with patch.object(course_episodes, "clear_course_episode_links", side_effect=delayed_clear):
            with ThreadPoolExecutor(max_workers=2) as pool:
                removal = pool.submit(courses.delete_course, course["id"])
                submission = None
                try:
                    self.assertTrue(clearing.wait(5))
                    submission = pool.submit(submit)
                    self.assertTrue(submitting.wait(5))
                    self.assertFalse(submitted.wait(.1), "Submission passed an in-flight deletion")
                finally:
                    release.set()
                removal.result(timeout=5)
                self.assertIsNotNone(submission)
                response = submission.result(timeout=5)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse(courses._path(course["id"]).exists())
        self.assertEqual(storage.list_tasks_snapshot(), [])
        self.assertEqual(fixture.schedule.call_count, 0)


if __name__ == "__main__":
    unittest.main()
