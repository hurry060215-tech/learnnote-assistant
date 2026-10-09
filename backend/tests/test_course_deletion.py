from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from pathlib import Path
import sqlite3
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app
from app import config, storage, library, knowledge, study, community, courses, course_episodes
from app.course_deletion import preview_course_deletion


class CourseDeletionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        paths = {"DATA_DIR": self.root, "TASK_DIR": self.root / "tasks", "UPLOAD_DIR": self.root / "uploads",
                 "TEMP_DIR": self.root / "temp", "MODEL_CACHE_DIR": self.root / "models", "STATIC_DIR": self.root / "static"}
        for module in (config, storage, library, knowledge, study, community, courses, course_episodes):
            for key, value in paths.items():
                if hasattr(module, key):
                    self.stack.enter_context(patch.object(module, key, value))
        config.ensure_dirs()
        self.client = TestClient(app)

    def task(self, title="Synthetic task", **changes):
        task = storage.create_task("local", title)
        return storage.update_task(task.id, status="success", **changes)

    def course(self, *tasks, sources=()):
        return courses.save_course("Synthetic course", [{"kind": "task", "id": task.id} for task in tasks] + list(sources))

    def preview(self, course):
        response = self.client.get(f"/api/courses/{course['id']}/deletion-preview")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def delete(self, course, ids=(), preview=None):
        preview = preview or self.preview(course)
        return self.client.request("DELETE", f"/api/courses/{course['id']}", json={
            "confirm": "delete_course", "revision": preview["revision"], "snapshot": preview["snapshot"], "task_ids": list(ids)})

    def test_default_delete_preserves_tasks_materials_and_originals(self):
        original = self.root / "original.mp4"
        original.write_bytes(b"synthetic original")
        task = self.task(source_media_path=str(original))
        material = library.import_document_material("independent.md", b"# Independent\n\nDocument evidence.")
        course = self.course(task, sources=[{"kind": "material", "id": material["material_id"]}])
        response = self.client.delete(f"/api/courses/{course['id']}")
        self.assertEqual(response.json(), {"deleted": True, "sources_deleted": False})
        self.assertEqual(storage.get_task(task.id).id, task.id)
        self.assertEqual(library.get_material(material["material_id"])["evidence_ids"], material["evidence_ids"])
        self.assertEqual(original.read_bytes(), b"synthetic original")

    def test_preview_and_cancel_equivalent_are_read_only_and_deduplicate_children(self):
        course = self.course(sources=[{"kind": "url", "url": "https://www.youtube.com/watch?v=abcdefghijk"}])
        episode = course_episodes.course_episodes(course)[0]
        self.assertFalse((self.root / "course-episodes.sqlite3").exists(), "reading does not create episode bindings")
        task = storage.create_task("current_page", "Bound episode", page_url=episode["url"])
        task = storage.update_task(task.id, status="success", handoff_id=episode["handoff_id"])
        course = courses.save_course(course["title"], course["sources"] + [{"kind": "task", "id": task.id}], course_id=course["id"], revision=course["revision"])
        stale = self.task("Synthetic stale task")
        stale_path = storage.task_file(stale.id)
        stale_payload = json.loads(stale_path.read_text())
        stale_payload.update(status="cancelling", updated_at="2020-01-01T00:00:00Z")
        stale_path.write_text(json.dumps(stale_payload))
        material = library.import_document_material("keep.md", b"# Keep this document")
        self.course(sources=[{"kind": "material", "id": material["material_id"]}])
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        preview = self.preview(course)
        self.assertEqual([item["task_id"] for item in preview["tasks"]], [task.id])
        self.assertTrue(preview["tasks"][0]["eligible"])
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_selected_child_uses_existing_cleanup_and_preserves_independent_data(self):
        original = self.root / "original.mp4"
        original.write_bytes(b"synthetic original")
        child, kept = self.task(source_media_path=str(original)), self.task("Keep")
        generated = storage.task_dir(child.id) / "note.md"
        generated.write_text("Synthetic generated note")
        storage.update_task(child.id, note_path=str(generated))
        material = library.import_document_material("independent.md", b"# Independent\n\nKeep this document.")
        alias = library.register_task_material(storage.get_task(child.id))
        course = self.course(child, kept, sources=[{"kind": "material", "id": material["material_id"]}])
        response = self.delete(course, [child.id, child.id])
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result["deleted"])
        self.assertEqual(result["deleted_task_ids"], [child.id])
        self.assertEqual(len(result["task_outcomes"]), 1)
        self.assertFalse(generated.exists())
        self.assertEqual(storage.get_task(kept.id).id, kept.id)
        self.assertEqual(original.read_bytes(), b"synthetic original")
        self.assertEqual(library.get_material(material["material_id"])["evidence_ids"], material["evidence_ids"])
        with self.assertRaisesRegex(ValueError, "material_not_found"):
            library.get_material(alias["material_id"])

    def test_corrupt_url_manifest_cannot_select_or_delete_unrelated_task(self):
        course = self.course(sources=[{"kind": "url", "url": "https://www.youtube.com/watch?v=abcdefghijk"}])
        episode = course_episodes.course_episodes(course)[0]
        unrelated = self.task("Unrelated task")
        source = storage.create_task("current_page", "Course task", page_url=episode["url"], handoff_id=episode["handoff_id"])
        storage.update_task(source.id, status="success")
        path = storage.task_file(source.id)
        payload = json.loads(path.read_text())
        payload["id"] = unrelated.id
        path.write_text(json.dumps(payload))
        before = {item: item.read_bytes() for item in (path, storage.task_file(unrelated.id))}
        self.assertEqual(course_episodes.course_episodes(course)[0]["status"], "identity_conflict")
        preview = self.preview(course)
        self.assertEqual(preview["tasks"], [])
        self.assertEqual(self.delete(course, [unrelated.id], preview).status_code, 409)
        self.assertEqual(before, {item: item.read_bytes() for item in before})

    def test_range_and_file_dependencies_protect_source_even_outside_courses(self):
        for by_id in (True, False):
            with self.subTest(by_id=by_id):
                source = self.task("Original media")
                media = storage.task_dir(source.id) / "source.mp4"
                media.write_bytes(b"Synthetic source media")
                storage.update_task(source.id, media_path=str(media))
                dependent = self.task("Dependent clip", source_task_id=source.id if by_id else "", source_media_path="" if by_id else str(media))
                course = self.course(source)
                preview = self.preview(course)
                self.assertEqual(preview["tasks"][0]["reason"], "dependent_task")
                self.assertEqual(self.delete(course, [source.id], preview).status_code, 409)
                self.assertTrue(media.exists())
                self.assertEqual(storage.get_task(dependent.id).id, dependent.id)

    def test_confirmation_and_exact_snapshot_required_for_child_delete(self):
        task = self.task()
        course = self.course(task)
        for payload in ({"task_ids": [task.id]}, {"confirm": "yes", "revision": 1, "snapshot": "a" * 64, "task_ids": [task.id]}):
            response = self.client.request("DELETE", f"/api/courses/{course['id']}", json=payload)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(storage.get_task(task.id).id, task.id)
        outsider = self.task("Not in this course")
        response = self.delete(course, [outsider.id])
        self.assertEqual(response.status_code, 409)
        self.assertTrue(courses.get_course(course["id"]))

    def test_unexpected_deletion_error_never_exposes_internal_exception(self):
        task = self.task()
        course = self.course(task)
        preview = self.preview(course)
        with patch("app.routers.courses.delete_reviewed_course", side_effect=ValueError("synthetic private storage detail")):
            response = self.delete(course, [task.id], preview)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "course_unavailable")
        self.assertNotIn("synthetic private storage detail", response.text)
        self.assertEqual(storage.get_task(task.id).id, task.id)

    def test_partial_cleanup_only_returns_fixed_public_error_codes(self):
        task = self.task()
        course = self.course(task)
        preview = self.preview(course)
        for message, expected in (("active_task", "active_task"), ("task_index_cleanup_failed", "task_index_cleanup_failed"),
                                  ("synthetic private storage detail", "task_cleanup_failed")):
            with self.subTest(message=message), patch.object(storage, "delete_task", side_effect=RuntimeError(message)):
                response = self.delete(course, [task.id], preview)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["deleted"])
            self.assertEqual(response.json()["task_outcomes"][0]["error"], expected)
            self.assertNotIn("synthetic private storage detail", response.text)
            self.assertEqual(storage.get_task(task.id).id, task.id)

    def test_shared_direct_url_handoff_and_material_alias_are_protected(self):
        for other_kind in ("task", "material", "url"):
            with self.subTest(other_kind=other_kind):
                owner = self.course(sources=[{"kind": "url", "url": "https://www.youtube.com/watch?v=abcdefghijk"}])
                episode = course_episodes.course_episodes(owner)[0]
                task = storage.create_task("current_page", "Episode", page_url=episode["url"])
                task = storage.update_task(task.id, status="success", handoff_id=episode["handoff_id"])
                course_episodes.bind_course_episode(owner, episode["episode_id"], task.id)
                target = self.course(task)
                if other_kind == "task":
                    courses.delete_course(owner["id"])
                    self.course(task)
                elif other_kind == "material":
                    courses.delete_course(owner["id"])
                    alias = library.register_task_material(task)
                    self.course(sources=[{"kind": "material", "id": alias["material_id"]}])
                preview = self.preview(target)
                self.assertEqual(preview["tasks"][0]["reason"], "shared_task")
                self.assertEqual(self.delete(target, [task.id], preview).status_code, 409)
                self.assertTrue(self.delete(target, preview=preview).json()["deleted"])
                self.assertTrue(storage.get_task(task.id))

    def test_new_course_reference_after_preview_rejects_entire_request(self):
        first, second = self.task("First"), self.task("Second")
        course = self.course(first, second)
        preview = self.preview(course)
        self.course(second)
        response = self.delete(course, [first.id, second.id], preview)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(storage.get_task(first.id))
        self.assertTrue(storage.get_task(second.id))

    def test_changed_revision_replaced_identity_and_new_binding_reject_stale_preview(self):
        task = self.task()
        course = self.course(task, sources=[{"kind": "url", "url": "https://www.youtube.com/watch?v=abcdefghijk"}])
        preview = self.preview(course)
        changed = courses.save_course("Changed", course["sources"], course_id=course["id"], revision=course["revision"])
        self.assertEqual(self.delete(course, [task.id], preview).status_code, 409)
        preview = self.preview(changed)
        storage.update_task(task.id, created_at="2026-01-01T00:00:00Z")
        self.assertEqual(self.delete(changed, [task.id], preview).status_code, 409)
        preview = self.preview(changed)
        episode = course_episodes.course_episodes(changed)[1]
        linked = storage.create_task("current_page", "New episode", page_url=episode["url"])
        storage.update_task(linked.id, status="success", handoff_id=episode["handoff_id"])
        course_episodes.bind_course_episode(changed, episode["episode_id"], linked.id)
        self.assertEqual(self.delete(changed, [task.id], preview).status_code, 409)
        self.assertTrue(storage.get_task(task.id))
        self.assertTrue(storage.get_task(linked.id))

    def test_active_busy_missing_and_unreadable_reference_fail_closed(self):
        active, busy, missing, free = [self.task(name) for name in ("Active", "Busy", "Missing", "Free")]
        course = self.course(active, busy, missing, free)
        preview = self.preview(course)
        storage.update_task(active.id, status="running")
        storage.delete_task(missing.id)
        with closing(sqlite3.connect(self.root / "task-queue.sqlite3")) as db:
            db.execute("CREATE TABLE jobs(task_id TEXT,state TEXT)")
            db.execute("INSERT INTO jobs VALUES (?, 'recovering')", (busy.id,))
            db.commit()
        self.assertEqual(self.delete(course, [free.id], preview).status_code, 409)
        current = self.preview(course)
        reasons = {item["task_id"]: item["reason"] for item in current["tasks"]}
        self.assertEqual(reasons, {active.id: "active_task", busy.id: "busy_task", missing.id: "source_missing", free.id: ""})
        for task in (active, busy, missing):
            self.assertEqual(self.delete(course, [task.id], current).status_code, 409)
        (self.root / "courses" / ("a" * 32 + ".json")).write_text("broken")
        current = self.preview(course)
        self.assertEqual(current["tasks"][-1]["reason"], "references_unavailable")
        self.assertTrue(self.delete(course, preview=current).json()["deleted"])
        self.assertEqual(storage.get_task(active.id).status, "running")

    def test_partial_failure_reports_exact_outcomes_and_retains_course_for_retry(self):
        first, second = self.task("First"), self.task("Second")
        course = self.course(first, second)
        real_delete = storage.delete_task
        def remove(task_id):
            if task_id == second.id:
                raise RuntimeError("task_index_cleanup_failed")
            return real_delete(task_id)
        with patch("app.storage.delete_task", side_effect=remove):
            response = self.delete(course, [first.id, second.id])
        result = response.json()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(result["deleted"])
        self.assertEqual(result["deleted_task_ids"], [first.id])
        self.assertEqual(result["task_outcomes"][1], {"task_id": second.id, "deleted": False, "error": "task_index_cleanup_failed"})
        self.assertEqual(courses.get_course(course["id"]), course)
        preview = self.preview(course)
        self.assertEqual(preview["tasks"][0]["reason"], "source_missing")
        self.assertTrue(self.delete(course, [second.id], preview).json()["deleted"])

    def test_unreadable_task_and_unavailable_queue_are_never_selectable(self):
        task, other = self.task(), self.task("Other")
        course = self.course(task, other)
        storage.task_file(task.id).write_text("corrupt synthetic record")
        (self.root / "task-queue.sqlite3").write_bytes(b"corrupt synthetic journal")
        preview = self.preview(course)
        self.assertEqual([item["reason"] for item in preview["tasks"]], ["source_unreadable", "references_unavailable"])
        self.assertEqual(self.delete(course, [other.id], preview).status_code, 409)
        self.assertTrue(self.delete(course, preview=preview).json()["deleted"])
        self.assertTrue(storage.task_file(task.id).exists())
        self.assertTrue(storage.get_task(other.id))

    def test_error_after_task_removal_still_reports_the_removal(self):
        task = self.task()
        course = self.course(task)
        real_delete = storage.delete_task
        def remove(task_id):
            real_delete(task_id)
            raise OSError("synthetic late cleanup failure")
        with patch("app.storage.delete_task", side_effect=remove):
            result = self.delete(course, [task.id]).json()
        self.assertFalse(result["deleted"])
        self.assertEqual(result["deleted_task_ids"], [task.id])
        self.assertEqual(result["task_outcomes"], [{"task_id": task.id, "deleted": True, "error": "task_cleanup_failed"}])
        self.assertTrue(courses.get_course(course["id"]))

    def test_course_cleanup_failure_keeps_manifest_and_completed_child_outcomes(self):
        task = self.task()
        course = self.course(task)
        with patch("app.course_episodes.clear_course_episode_links", side_effect=OSError("synthetic busy index")):
            result = self.delete(course, [task.id]).json()
        self.assertFalse(result["deleted"])
        self.assertEqual(result["error"], "course_cleanup_failed")
        self.assertEqual(result["deleted_task_ids"], [task.id])
        self.assertTrue(courses.get_course(course["id"]))
        self.assertTrue(self.delete(course).json()["deleted"])

    def test_owned_upload_cleanup_does_not_repair_unrelated_tasks(self):
        upload = self.root / "uploads" / "synthetic.mp4"
        upload.write_bytes(b"owned synthetic upload")
        chosen = self.task(source_media_path=str(upload))
        stale = self.task("Unrelated stale task")
        path = storage.task_file(stale.id)
        payload = json.loads(path.read_text())
        payload.update(status="cancelling", updated_at="2020-01-01T00:00:00Z")
        path.write_text(json.dumps(payload))
        before = path.read_bytes()
        course = self.course(chosen)
        self.assertTrue(self.delete(course, [chosen.id]).json()["deleted"])
        self.assertFalse(upload.exists())
        self.assertEqual(path.read_bytes(), before)

    def test_stale_binding_cannot_recreate_deleted_course_links(self):
        course = self.course(sources=[{"kind": "url", "url": "https://www.youtube.com/watch?v=abcdefghijk"}])
        episode = course_episodes.course_episodes(course)[0]
        task = storage.create_task("current_page", "Episode", page_url=episode["url"])
        storage.update_task(task.id, handoff_id=episode["handoff_id"], status="success")
        courses.delete_course(course["id"])
        for function, args in ((course_episodes.prepare_course_episode, (course, episode["episode_id"])),
                               (course_episodes.bind_course_episode, (course, episode["episode_id"], task.id))):
            with self.assertRaises(FileNotFoundError):
                function(*args)
        self.assertFalse((self.root / "course-episodes.sqlite3").exists())

    def test_concurrent_share_waits_for_deletion_then_rejects_missing_task(self):
        task = self.task()
        course = self.course(task)
        preview = self.preview(course)
        entered, release, saving = threading.Event(), threading.Event(), threading.Event()
        real_delete = storage.delete_task
        def remove(task_id):
            entered.set()
            self.assertTrue(release.wait(5))
            return real_delete(task_id)
        def share():
            saving.set()
            return self.course(task)
        with patch("app.storage.delete_task", side_effect=remove), ThreadPoolExecutor(max_workers=2) as pool:
            deleting = pool.submit(self.delete, course, [task.id], preview)
            self.assertTrue(entered.wait(5))
            sharing = pool.submit(share)
            self.assertTrue(saving.wait(5))
            self.assertFalse(sharing.done())
            release.set()
            self.assertTrue(deleting.result().json()["deleted"])
            with self.assertRaisesRegex(ValueError, "course_source_missing"):
                sharing.result()


if __name__ == "__main__":
    unittest.main()
