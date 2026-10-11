from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import courses, course_episodes


class CourseControlTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in (courses, course_episodes):
            self.stack.enter_context(patch.object(module, "DATA_DIR", self.root))
        self.course = courses.save_course("Synthetic course", [{"kind": "url", "url": "https://example.test/lesson"}])
        self.episode = course_episodes._episode(self.course["id"], self.course["sources"][0], 0)

    def test_pause_preserves_membership_and_replay_does_not_overwrite_later_work(self):
        before = self.course
        after = courses.set_course_paused(before["id"], before["revision"], True, "pause-operation-1")
        self.assertEqual(after["title"], before["title"])
        self.assertEqual(after["sources"], before["sources"])
        self.assertTrue(after["paused"])
        self.assertEqual(after["revision"], before["revision"] + 1)
        self.assertEqual(courses.set_course_paused(before["id"], before["revision"], True, "pause-operation-1"), after)
        with self.assertRaisesRegex(ValueError, "course_operation_conflict"):
            courses.set_course_paused(before["id"], before["revision"], False, "pause-operation-1")
        manual = courses.save_course("Manual title", after["sources"], False, after["id"], after["revision"])
        with self.assertRaisesRegex(ValueError, "course_changed_reload_required"):
            courses.set_course_paused(before["id"], before["revision"], True, "pause-operation-1")
        self.assertEqual(courses.get_course(before["id"]), manual)

    def test_stale_unpaused_snapshot_cannot_prepare_after_pause(self):
        courses.set_course_paused(self.course["id"], self.course["revision"], True, "pause-operation-2")
        with self.assertRaisesRegex(ValueError, "course_changed_reload_required"):
            course_episodes.prepare_course_episode(self.course, self.episode["episode_id"])
        self.assertFalse((self.root / "course-episodes.sqlite3").exists())
        with self.assertRaisesRegex(ValueError, "course_paused"):
            course_episodes.prepare_course_episode(courses.get_course(self.course["id"]), self.episode["episode_id"])

    def test_resume_only_allows_future_admission_and_does_not_create_tasks(self):
        paused = courses.set_course_paused(self.course["id"], self.course["revision"], True, "pause-operation-3")
        resumed = courses.set_course_paused(paused["id"], paused["revision"], False, "resume-operation-3")
        self.assertFalse(resumed["paused"])
        self.assertFalse((self.root / "tasks").exists())
        self.assertFalse((self.root / "course-episodes.sqlite3").exists())
        prepared = course_episodes.prepare_course_episode(resumed, self.episode["episode_id"])
        self.assertTrue(prepared["new_submission_required"])
        self.assertFalse((self.root / "tasks").exists())

    def test_deleted_course_cannot_be_recreated_by_stale_admission(self):
        courses.delete_course(self.course["id"])
        with self.assertRaises(FileNotFoundError):
            course_episodes.prepare_course_episode(self.course, self.episode["episode_id"])
        self.assertFalse((self.root / "course-episodes.sqlite3").exists())

    def test_two_processes_cannot_commit_the_same_course_revision(self):
        script = """
import sys, time
from pathlib import Path
from app import courses
root, identifier, operation = sys.argv[1:]
courses.DATA_DIR = Path(root)
gate = Path(root) / 'start'
deadline = time.monotonic() + 10
while not gate.exists():
    if time.monotonic() > deadline: raise RuntimeError('gate timeout')
    time.sleep(.01)
try:
    courses.set_course_paused(identifier, 1, True, operation)
    print('committed')
except ValueError as exc:
    print(str(exc))
"""
        processes = [subprocess.Popen([sys.executable, "-c", script, str(self.root), self.course["id"], f"process-operation-{index}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for index in range(2)]
        try:
            (self.root / "start").write_text("go")
            results = [process.communicate(timeout=15) for process in processes]
            self.assertEqual(sorted(stdout.strip() for stdout, _ in results), ["committed", "course_changed_reload_required"], results)
            self.assertTrue(all(process.returncode == 0 for process in processes), results)
            self.assertEqual(courses.get_course(self.course["id"])["revision"], 2)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)

    def test_question_and_identity_edit_keep_membership_at_the_validated_revision(self):
        for action in ("question", "identity"):
            with self.subTest(action=action):
                course = courses.save_course("Original scope", [{"kind": "url", "url": "https://example.test/first"}])
                entered, attempted, changed = threading.Event(), threading.Event(), threading.Event()
                captured, failures = [], []
                def writer():
                    try:
                        if not entered.wait(5): raise RuntimeError("read gate timeout")
                        attempted.set()
                        courses.save_course("Replacement scope", [{"kind": "url", "url": "https://example.test/second"}], False, course["id"], 1)
                        changed.set()
                    except Exception as exc:
                        failures.append(exc)
                def inspect(identifier):
                    entered.set()
                    if not attempted.wait(5): raise RuntimeError("write gate timeout")
                    self.assertFalse(changed.wait(.05), "membership changed inside the scoped read")
                    value=courses.get_course(identifier)
                    captured.append(value)
                    return set() if action == "question" else []
                worker=threading.Thread(target=writer);worker.start()
                try:
                    if action == "question":
                        with patch.object(courses, "course_evidence_ids", side_effect=inspect), patch.object(courses, "answer_from_evidence", return_value={"grounded":False}):
                            result=courses.ask_course(course["id"], "synthetic", 1)
                            self.assertEqual(result["scope"]["revision"], 1)
                    else:
                        with patch.object(courses, "course_evidence", side_effect=inspect), patch.object(courses, "edit_identity", return_value={"ok":True}):
                            courses.edit_course_identity(course["id"], "synthetic-request", {})
                finally:
                    entered.set();worker.join(5)
                self.assertFalse(worker.is_alive());self.assertEqual(failures, [])
                self.assertEqual(captured[0]["revision"], 1)
                self.assertEqual(captured[0]["sources"][0]["url"], "https://example.test/first")
                self.assertTrue(changed.is_set())
