"""Synthetic dependency and submission/deletion ordering regressions."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

from app import course_episodes, courses, main, range_learning, storage
from app.models import MediaIntegrity, TaskOptions
from backend.tests import test_course_deletion as deletion_fixtures
from backend.tests import test_course_media_reuse as reuse_fixtures


class CourseRangeDependencyTests(unittest.TestCase):
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
        self.assertEqual(len(storage.list_tasks(read_only=True)), 1)

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
        self.assertEqual(storage.list_tasks(read_only=True), [])
        self.assertEqual(fixture.schedule.call_count, 0)


if __name__ == "__main__":
    unittest.main()
