"""Synthetic course batches exercise the real handoff handler without processing."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import community, config, course_episodes, courses, knowledge, library, main, storage, study
from app.models import SourceIdentity, TaskOptions


class CourseMediaReuseTests(unittest.TestCase):
    URL = "https://www.youtube.com/watch?v=abcdefghijk"

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "data"
        paths = {"DATA_DIR": self.root, "TASK_DIR": self.root / "tasks", "UPLOAD_DIR": self.root / "uploads",
                 "TEMP_DIR": self.root / "temp", "MODEL_CACHE_DIR": self.root / "models", "STATIC_DIR": self.root / "static"}
        for module in (config, storage, library, knowledge, study, community, courses, course_episodes, main):
            for key, value in paths.items():
                if hasattr(module, key):
                    self.stack.enter_context(patch.object(module, key, value))
        config.ensure_dirs()
        self.stack.enter_context(patch.dict(main._handoff_task_ids, clear=True))
        self.stack.enter_context(patch.dict(main._deferred_handoffs, clear=True))
        self.stack.enter_context(patch.object(main, "resolve_model_options", side_effect=lambda options: options))
        self.stack.enter_context(patch.object(main, "require_ready_note_model"))
        self.schedule = self.stack.enter_context(patch.object(main, "schedule_processing"))
        self.index = self.stack.enter_context(patch.object(storage, "index_task", wraps=library.index_task))
        self.client = TestClient(main.app)

    def course(self, url=URL):
        return courses.save_course("Synthetic course", [{"kind": "url", "url": url}])

    def episode(self, course):
        return course_episodes.course_episodes(course)[0]

    def prepare(self, course):
        episode = self.episode(course)
        response = self.client.post(f"/api/courses/{course['id']}/episodes/{episode['episode_id']}/prepare")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["episode"]

    def payload(self, episode, **changes):
        return {"page_url": episode["url"], "handoff_id": episode["handoff_id"],
                "options": {"content_mode": "text", "visual_understanding": False}, **changes}

    def submit(self, episode, **changes):
        return self.client.post("/api/tasks/from-current-page", json=self.payload(episode, **changes))

    def bind(self, course, episode, task_id):
        response = self.client.post(f"/api/courses/{course['id']}/episodes/{episode['episode_id']}/bind", json={"task_id": task_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["episode"]

    def legacy_task(self, course, **changes):
        # Build an existing manifest independently of the resolver, including
        # when another historical task already has the same media URL.
        handoff = "course-" + hashlib.sha256(f"{course['id']}:{course['sources'][0]['url']}".encode()).hexdigest()[:40]
        task = storage.create_task("current_page", "Synthetic legacy task", page_url=course["sources"][0]["url"], options=TaskOptions(content_mode="text"))
        return storage.update_task(task.id, **{"handoff_id": handoff, **changes})

    def test_concurrent_cross_course_submissions_schedule_and_index_only_once(self):
        first, second = self.course(), self.course()
        prepared = [self.prepare(first), self.prepare(second)]
        self.assertNotEqual(prepared[0]["handoff_id"], prepared[1]["handoff_id"])
        self.index.reset_mock()
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(self.submit, prepared * 6))
        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
        task_ids = {response.json()["task_id"] for response in responses}
        self.assertEqual(len(task_ids), 1)
        self.assertEqual(sum(not response.json()["deduplicated"] for response in responses), 1)
        self.assertEqual(self.schedule.call_count, 1)
        self.assertEqual(self.index.call_count, 1)
        self.assertEqual(len(storage.list_tasks(read_only=True)), 1)
        task_id = task_ids.pop()
        indexed_ids = {call.args[0].id for call in self.index.call_args_list}
        self.assertEqual(indexed_ids, {task_id})
        index_calls = self.index.call_count
        for course, episode in zip((first, second), prepared):
            self.bind(course, episode, task_id)
            self.assertFalse(self.prepare(course)["new_submission_required"])
            self.assertEqual(self.submit(episode).json()["task_id"], task_id)
        self.assertEqual(self.index.call_count, index_calls, "reuse must not reindex task evidence")
        with closing(sqlite3.connect(self.root / "course-episodes.sqlite3")) as db:
            rows = db.execute("SELECT course_id,episode_id,handoff_id,task_id FROM course_episodes").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row[2] for row in rows}, {item["handoff_id"] for item in prepared})
        self.assertEqual({row[3] for row in rows}, {task_id})

    def test_identity_is_present_in_first_write_and_lost_http_reply_does_not_reschedule(self):
        prepared = self.prepare(self.course())
        client = TestClient(main.app, raise_server_exceptions=False)
        with patch.object(main, "_handoff_response", side_effect=RuntimeError("Synthetic lost reply")):
            response = client.post("/api/tasks/from-current-page", json=self.payload(prepared))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.index.call_count, 1)
        indexed = self.index.call_args.args[0]
        self.assertEqual(indexed.handoff_id, prepared["handoff_id"])
        self.assertEqual(indexed.source_identity.page_url, prepared["url"])
        self.assertEqual(indexed.learning_range, {})
        self.assertEqual(storage.get_task(indexed.id).handoff_id, prepared["handoff_id"])
        main._handoff_task_ids.clear()
        retry = self.submit(prepared)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["task_id"], indexed.id)
        self.assertTrue(retry.json()["deduplicated"])
        self.assertEqual(self.index.call_count, 1)
        self.assertEqual(self.schedule.call_count, 1)

    def test_lost_acknowledgement_restart_reuses_manifest_and_evidence(self):
        first, second = self.course(), self.course()
        prepared = [self.prepare(first), self.prepare(second)]
        result = self.submit(prepared[0])
        self.assertEqual(result.status_code, 200, result.text)
        task_id = result.json()["task_id"]
        transcript = storage.task_dir(task_id) / "transcript.json"
        transcript.write_text(json.dumps({"segments": [{"start": 0, "end": 10, "text": "Synthetic shared source evidence."}]}))
        storage.update_task(task_id, status="success", checkpoint="summarized", transcript_path=str(transcript))
        before_task = storage.task_file(task_id).read_bytes()
        index_calls = self.index.call_count
        # Neither course received its bind acknowledgement. Drop process-local
        # lookup state and use fresh clients with the same on-disk manifests.
        main._handoff_task_ids.clear()
        main._deferred_handoffs.clear()
        self.client = TestClient(main.app)
        for course, episode in zip((first, second), prepared):
            recovered = self.prepare(courses.get_course(course["id"]))
            self.assertEqual(recovered["task_id"], task_id)
            self.assertEqual(recovered["checkpoint"], "summarized")
            self.assertFalse(recovered["new_submission_required"])
            self.assertEqual(self.submit(episode).json()["task_id"], task_id)
        self.assertEqual(storage.task_file(task_id).read_bytes(), before_task)
        self.assertEqual(self.index.call_count, index_calls)
        self.assertEqual(self.schedule.call_count, 1)
        first_ids, second_ids = [courses.course_evidence_ids(course["id"]) for course in (first, second)]
        self.assertTrue(first_ids)
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(len(courses.course_evidence(first["id"])), 1)
        self.assertEqual(len(courses.course_evidence(second["id"])), 1)
        with closing(sqlite3.connect(library._db_path())) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM library_tasks").fetchone()[0], 1)
        # A separate interpreter has no inherited handoff map or monkeypatched
        # path state. It must find the same task solely from durable data.
        code = """
import json, sys
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import main, storage
payload = json.load(sys.stdin)
with patch.object(main, 'resolve_model_options', side_effect=lambda value: value), patch.object(main, 'require_ready_note_model'), patch.object(main, 'schedule_processing') as schedule, patch.object(storage, 'index_task') as index:
    response = TestClient(main.app).post('/api/tasks/from-current-page', json=payload)
    print(json.dumps({'status': response.status_code, 'task_id': response.json().get('task_id'), 'schedules': schedule.call_count, 'indexes': index.call_count}))
"""
        env = {**os.environ, "LEARNNOTE_DATA_DIR": str(self.root), "ORT_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}
        result = subprocess.run([sys.executable, "-c", code], input=json.dumps(self.payload(prepared[1])),
                                text=True, capture_output=True, env=env, check=True, timeout=30)
        self.assertEqual(json.loads(result.stdout), {"status": 200, "task_id": task_id, "schedules": 0, "indexes": 0})

    def test_distinct_parts_videos_and_exact_urls_remain_separate(self):
        urls = ["https://www.bilibili.com/video/BV1xx411c7mD?p=1",
                "https://www.bilibili.com/video/BV1xx411c7mD?p=2", self.URL,
                "https://www.youtube.com/watch?v=zyxwvutsrqp",
                "https://example.test/media.mp4?lesson=1", "https://example.test/media.mp4?lesson=2"]
        ids = []
        for url in urls:
            response = self.submit(self.prepare(self.course(url)))
            self.assertEqual(response.status_code, 200, response.text)
            ids.append(response.json()["task_id"])
        self.assertEqual(len(set(ids)), len(urls))
        self.assertEqual(self.schedule.call_count, len(urls))

    def test_same_course_duplicate_sources_and_bilibili_default_part_reuse(self):
        course = courses.save_course("Repeated source", [{"kind": "url", "url": "BV1xx411c7mD"},
                                                         {"kind": "url", "url": "https://www.bilibili.com/video/BV1xx411c7mD?p=1"}])
        self.assertEqual(len(course["sources"]), 1)
        first = self.submit(self.prepare(course)).json()["task_id"]
        second = self.prepare(self.course("https://www.bilibili.com/video/BV1xx411c7mD"))
        self.assertEqual(second["task_id"], first)
        self.assertFalse(second["new_submission_required"])
        self.assertEqual(self.schedule.call_count, 1)

    def test_ranged_or_other_mode_work_is_not_used_for_full_course(self):
        for index, changes in enumerate(({"learning_range": {"start": 5, "end": 20}}, {"mode": "download_only"},
                                         {"options": TaskOptions(content_mode="visual")}, {"handoff_id": "browser-handoff-12345678"})):
            with self.subTest(changes=changes):
                url = f"https://www.youtube.com/watch?v=scenario{index:03}"
                legacy = self.legacy_task(self.course(url), **changes)
                target = self.course(url)
                prepared = self.prepare(target)
                self.assertTrue(prepared["new_submission_required"])
                response = self.submit(prepared)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotEqual(response.json()["task_id"], legacy.id)

    def test_prepared_handoff_rejects_changed_part_range_and_mode(self):
        prepared = self.prepare(self.course("https://www.bilibili.com/video/BV1xx411c7mD?p=1"))
        for change in ({"page_url": "https://www.bilibili.com/video/BV1xx411c7mD?p=2"},
                       {"learning_range": {"start": 10, "end": 20}}, {"mode": "download_only"},
                       {"options": {"content_mode": "visual"}},
                       {"resources": [{"url": "https://example.test/other.mp4", "kind": "video"}]}):
            response = self.submit(prepared, **change)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.schedule.call_count, 0)
        self.assertEqual(storage.list_tasks(read_only=True), [])

    def test_deleted_or_unprepared_course_cannot_submit_a_late_handoff(self):
        course = self.course()
        episode = self.episode(course)
        self.assertEqual(self.submit(episode).status_code, 409)
        prepared = self.prepare(course)
        courses.delete_course(course["id"])
        self.assertEqual(self.submit(prepared).status_code, 409)
        self.assertEqual(self.schedule.call_count, 0)
        self.assertEqual(storage.list_tasks(read_only=True), [])

    def test_corrupt_manifest_alias_cannot_reuse_an_unrelated_task(self):
        course = self.course()
        prepared = self.prepare(course)
        source = self.legacy_task(course, status="success")
        unrelated = storage.create_task("local", "Unrelated task")
        path = storage.task_file(source.id)
        payload = json.loads(path.read_text())
        payload["id"] = unrelated.id
        path.write_text(json.dumps(payload))
        self.assertEqual(self.episode(course)["status"], "identity_conflict")
        self.assertEqual(self.submit(prepared).status_code, 409)
        self.assertEqual(self.schedule.call_count, 0)
        self.assertTrue(path.exists())
        self.assertTrue(storage.task_file(unrelated.id).exists())

    def test_legacy_links_and_handoffs_are_preserved_without_migration(self):
        first, second = self.course(), self.course()
        first_episode = self.prepare(first)
        legacy = self.legacy_task(first, status="success")
        self.bind(first, first_episode, legacy.id)
        before_task = storage.task_file(legacy.id).read_bytes()
        before_course = courses._path(first["id"]).read_bytes()
        with closing(sqlite3.connect(self.root / "course-episodes.sqlite3")) as db:
            schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
            old_row = db.execute("SELECT * FROM course_episodes WHERE course_id=?", (first["id"],)).fetchone()
        shared = self.prepare(second)
        self.assertEqual(shared["task_id"], legacy.id)
        self.assertNotEqual(shared["handoff_id"], legacy.handoff_id)
        self.assertEqual(self.submit(shared).json()["task_id"], legacy.id)
        self.assertEqual(storage.task_file(legacy.id).read_bytes(), before_task)
        self.assertEqual(courses._path(first["id"]).read_bytes(), before_course)
        with closing(sqlite3.connect(self.root / "course-episodes.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall(), schema)
            self.assertEqual(db.execute("SELECT * FROM course_episodes WHERE course_id=?", (first["id"],)).fetchone(), old_row)
        self.assertEqual(self.schedule.call_count, 0)

    def test_historical_duplicates_keep_links_but_new_course_fails_closed(self):
        first, second, target = self.course(), self.course(), self.course()
        prepared = self.prepare(target)
        tasks = [self.legacy_task(course, status="success") for course in (first, second)]
        for course, task in zip((first, second), tasks):
            episode = self.prepare(course)
            self.assertEqual(episode["task_id"], task.id)
        self.assertEqual(self.episode(target)["status"], "identity_conflict")
        response = self.submit(prepared)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.schedule.call_count, 0)
        self.assertEqual({task.id for task in storage.list_tasks(read_only=True)}, {task.id for task in tasks})

    def test_conflicting_source_identity_and_duplicate_handoff_fail_closed(self):
        owner, target = self.course(), self.course()
        prepared = self.prepare(target)
        task = self.legacy_task(owner, source_identity=SourceIdentity(page_url="https://www.youtube.com/watch?v=other-video"))
        self.assertEqual(self.episode(target)["status"], "identity_conflict")
        self.assertEqual(self.submit(prepared).status_code, 409)
        storage.update_task(task.id, source_identity=SourceIdentity())
        self.legacy_task(owner)
        self.assertEqual(self.submit(prepared).status_code, 409)
        self.assertEqual(self.schedule.call_count, 0)

    def test_unreadable_bound_task_cannot_create_replacement(self):
        course = self.course()
        prepared = self.prepare(course)
        task = self.legacy_task(course)
        self.bind(course, prepared, task.id)
        storage.task_file(task.id).write_text("broken manifest")
        self.assertEqual(self.episode(course)["status"], "source_unreadable")
        response = self.client.post(f"/api/courses/{course['id']}/episodes/{prepared['episode_id']}/prepare")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.submit(prepared).status_code, 409)
        self.assertEqual(self.schedule.call_count, 0)

    def test_unreadable_shared_manifest_blocks_new_course_submission(self):
        owner, target = self.course(), self.course()
        prepared = self.prepare(target)
        task = self.legacy_task(owner)
        self.bind(owner, self.episode(owner), task.id)
        storage.task_file(task.id).write_text("broken manifest")
        self.assertEqual(self.episode(target)["status"], "source_unreadable")
        self.assertEqual(self.submit(prepared).status_code, 409)
        self.assertEqual(self.schedule.call_count, 0)

    def test_corrupt_reservation_and_paused_or_removed_source_fail_closed(self):
        for state in ("corrupt", "paused", "removed"):
            with self.subTest(state=state):
                course = self.course(f"https://example.test/{state}.mp4")
                prepared = self.prepare(course)
                if state == "corrupt":
                    with closing(sqlite3.connect(self.root / "course-episodes.sqlite3")) as db:
                        db.execute("UPDATE course_episodes SET source_url=? WHERE course_id=?", (self.URL, course["id"]))
                        db.commit()
                else:
                    courses.save_course(course["title"], [] if state == "removed" else course["sources"],
                                        state == "paused", course["id"], course["revision"])
                self.assertEqual(self.submit(prepared).status_code, 409)
        self.assertEqual(self.schedule.call_count, 0)

    def test_existing_shared_binding_survives_explicit_learning_option_change(self):
        owner, target = self.course(), self.course()
        task = self.legacy_task(owner, status="success")
        shared = self.prepare(target)
        self.assertEqual(shared["task_id"], task.id)
        storage.update_task(task.id, options=TaskOptions(content_mode="visual"))
        self.assertEqual(self.episode(target)["task_id"], task.id)
        self.bind(target, shared, task.id)
        self.assertEqual(self.prepare(target)["task_id"], task.id)

    def test_saved_course_adopts_reuse_before_any_prepare_or_batch_action(self):
        owner = self.course()
        task = self.legacy_task(owner, status="success")
        response = self.client.post("/api/courses", json={"title": "Saved reused course", "sources": [{"kind": "url", "url": self.URL}]})
        self.assertEqual(response.status_code, 200, response.text)
        target = response.json()["course"]
        self.assertEqual(response.json()["episodes"][0]["task_id"], task.id)
        storage.update_task(task.id, options=TaskOptions(content_mode="visual"))
        self.assertEqual(self.episode(target)["task_id"], task.id)
        self.assertFalse(self.prepare(target)["new_submission_required"])
        self.assertEqual(self.schedule.call_count, 0)

    def test_shared_failed_task_resumes_once_with_original_identity(self):
        owner, target = self.course(), self.course()
        media = self.root / "synthetic.mp4"
        media.write_bytes(b"synthetic media")
        task = self.legacy_task(owner, status="failed", checkpoint="transcribed", source_media_path=str(media))
        first, second = self.prepare(owner), self.prepare(target)
        self.assertEqual(first["task_id"], second["task_id"])
        for index, episode in enumerate((first, second)):
            response = self.client.post(episode["resume_endpoint"], json={"content_mode": "text"})
            self.assertEqual(response.status_code, 200 if index == 0 else 409, response.text)
        self.assertEqual(self.schedule.call_count, 1)
        self.assertEqual(self.episode(owner)["task_id"], task.id)
        self.assertEqual(self.episode(target)["task_id"], task.id)

    def test_shared_task_and_evidence_survive_deleting_one_course(self):
        first, second = self.course(), self.course()
        prepared = self.prepare(first)
        task_id = self.submit(prepared).json()["task_id"]
        transcript = storage.task_dir(task_id) / "transcript.json"
        transcript.write_text(json.dumps({"segments": [{"start": 0, "end": 10, "text": "Retained synthetic evidence."}]}))
        storage.update_task(task_id, status="success", transcript_path=str(transcript))
        shared = self.prepare(second)
        self.bind(second, shared, task_id)
        evidence_ids = courses.course_evidence_ids(second["id"])
        self.assertTrue(evidence_ids)
        preview = self.client.get(f"/api/courses/{first['id']}/deletion-preview").json()
        self.assertEqual(preview["tasks"][0]["reason"], "shared_task")
        response = self.client.request("DELETE", f"/api/courses/{first['id']}", json={
            "confirm": "delete_course", "revision": preview["revision"], "snapshot": preview["snapshot"], "task_ids": [task_id]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.delete(f"/api/courses/{first['id']}").status_code, 200)
        self.assertEqual(storage.get_task(task_id).id, task_id)
        self.assertEqual(self.prepare(second)["task_id"], task_id)
        self.assertEqual(courses.course_evidence_ids(second["id"]), evidence_ids)
        self.assertTrue(transcript.exists())
        self.assertEqual(self.submit(shared).json()["task_id"], task_id)
        self.assertEqual(self.schedule.call_count, 1)
