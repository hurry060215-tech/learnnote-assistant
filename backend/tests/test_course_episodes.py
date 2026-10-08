from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import TaskOptions
from app.storage import create_task, update_task, get_task
from app.courses import save_course, get_course, course_evidence_ids, delete_course
from app.course_episodes import course_episodes, prepare_course_episode, bind_course_episode


class CourseEpisodeTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for target,value in (("app.storage.DATA_DIR",self.root),("app.storage.TASK_DIR",self.root/"tasks"),("app.courses.DATA_DIR",self.root),("app.course_episodes.DATA_DIR",self.root)):
            self.stack.enter_context(patch(target,value))
        self.course=save_course("Public episodes",[{"kind":"url","url":"https://www.youtube.com/watch?v=abcdefghijk"},{"kind":"url","url":"https://www.bilibili.com/video/BV1xx?p=2"}])
        self.episode=course_episodes(self.course)[0]

    def make_task(self,episode=None,**updates):
        episode=episode or self.episode
        task=create_task("current_page","Episode",page_url=episode["url"],options=TaskOptions(content_mode="text"))
        return update_task(task.id,handoff_id=episode["handoff_id"],**updates)

    def test_lost_acknowledgement_reconciles_from_manifest_without_new_submission(self):
        self.assertTrue(prepare_course_episode(self.course,self.episode["episode_id"])["new_submission_required"])
        task=self.make_task(status="success",checkpoint="summarized")
        resumed=prepare_course_episode(get_course(self.course["id"]),self.episode["episode_id"])
        self.assertFalse(resumed["new_submission_required"]);self.assertEqual(resumed["task_id"],task.id)
        self.assertEqual(resumed["checkpoint"],"summarized")
        with closing(sqlite3.connect(self.root/"course-episodes.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT task_id FROM course_episodes").fetchone()[0],task.id)
        self.assertEqual(get_course(self.course["id"])["sources"][0]["kind"],"url")

    def test_concurrent_prepare_and_bind_are_idempotent(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            prepared=list(pool.map(lambda _:prepare_course_episode(self.course,self.episode["episode_id"]),range(12)))
        self.assertEqual(len({item["handoff_id"] for item in prepared}),1)
        task=self.make_task(status="queued")
        with ThreadPoolExecutor(max_workers=8) as pool:
            bound=list(pool.map(lambda _:bind_course_episode(self.course,self.episode["episode_id"],task.id),range(12)))
        self.assertEqual({item["task_id"] for item in bound},{task.id})
        with closing(sqlite3.connect(self.root/"course-episodes.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM course_episodes").fetchone()[0],1)

    def test_pause_reorder_and_course_delete_preserve_task_identity(self):
        task=self.make_task(status="failed",checkpoint="transcribed")
        bind_course_episode(self.course,self.episode["episode_id"],task.id)
        changed=save_course("Reordered",list(reversed(self.course["sources"])),True,self.course["id"],self.course["revision"])
        current=next(item for item in course_episodes(changed) if item["episode_id"]==self.episode["episode_id"])
        self.assertEqual(current["position"],1);self.assertEqual(current["task_id"],task.id);self.assertTrue(current["retryable"])
        with self.assertRaisesRegex(ValueError,"course_paused"):prepare_course_episode(changed,current["episode_id"])
        delete_course(self.course["id"]);self.assertEqual(get_task(task.id).id,task.id)
        with closing(sqlite3.connect(self.root/"course-episodes.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM course_episodes").fetchone()[0],0)

    def test_stale_prepare_cannot_erase_a_completed_binding(self):
        pending=prepare_course_episode(self.course,self.episode["episode_id"])
        task=self.make_task(status="success")
        bind_course_episode(self.course,self.episode["episode_id"],task.id)
        with patch("app.course_episodes.course_episodes",return_value=[pending]):
            result=prepare_course_episode(self.course,self.episode["episode_id"])
        self.assertEqual(result["task_id"],task.id)
        self.assertFalse(result["new_submission_required"])

    def test_wrong_part_and_ambiguous_handoffs_fail_closed(self):
        task=self.make_task();other=course_episodes(self.course)[1]
        with self.assertRaisesRegex(ValueError,"identity_conflict"):bind_course_episode(self.course,other["episode_id"],task.id)
        self.make_task()
        with self.assertRaisesRegex(ValueError,"identity_conflict"):prepare_course_episode(self.course,self.episode["episode_id"])

    def test_linked_url_episode_contributes_canonical_course_evidence(self):
        task=self.make_task(status="success");bind_course_episode(self.course,self.episode["episode_id"],task.id)
        with patch("app.courses.evidence_ids_for_task",return_value={"canonical-cue"}) as evidence:
            self.assertEqual(course_evidence_ids(self.course["id"]),{"canonical-cue"});evidence.assert_called_once_with(task.id)

    def test_resume_keeps_task_id_and_repeat_cannot_enqueue_twice(self):
        media=self.root/"owned.mp4";media.write_bytes(b"owned synthetic media")
        task=self.make_task(status="failed",source_media_path=str(media),checkpoint="transcribed")
        bind_course_episode(self.course,self.episode["episode_id"],task.id);client=TestClient(app)
        with patch("app.main.require_ready_note_model"),patch("app.main.schedule_processing") as schedule:
            response=client.post(f"/api/tasks/{task.id}/resume",json={"content_mode":"text"})
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()["task_id"],task.id)
            self.assertEqual(client.post(f"/api/tasks/{task.id}/resume",json={"content_mode":"text"}).status_code,409)
            self.assertEqual(schedule.call_count,1)
        self.assertEqual(course_episodes(self.course)[0]["task_id"],task.id)

    def test_save_response_reprojects_episode_positions_for_ui_reorder(self):
        task=self.make_task(status="success");bind_course_episode(self.course,self.episode["episode_id"],task.id)
        response=TestClient(app).put(f"/api/courses/{self.course['id']}",json={"title":"Reordered","sources":list(reversed(self.course["sources"])),"revision":self.course["revision"]})
        self.assertEqual(response.status_code,200,response.text)
        episodes=response.json()["episodes"]
        self.assertEqual(episodes[1]["task_id"],task.id);self.assertEqual(episodes[1]["position"],1)
        self.assertEqual(episodes[0]["task_id"],"")
