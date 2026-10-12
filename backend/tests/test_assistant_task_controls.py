"""HTTP adapter contracts against synthetic manifests and the real local queue."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app import assistant_operation_store as journal
from app import community, config, course_episodes, courses, knowledge, library
from app import model_connections, observability, storage, study, task_control
from app.main import app
from app.queue_controls import set_queue_paused
from app.routers import notes
from app.task_control import task_generation
from app.task_queue import LocalTaskQueue, read_queue_job


BASE = "/api/assistant/operations"


class AssistantTaskControlTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in (journal, community, config, course_episodes, courses,
                       knowledge, library, model_connections, storage, study, notes):
            self.stack.enter_context(patch.object(module, "DATA_DIR", self.root))
        for name, directory in (("TASK_DIR", "tasks"), ("UPLOAD_DIR", "uploads"),
                                ("TEMP_DIR", "temp"), ("STATIC_DIR", "static"),
                                ("MODEL_CACHE_DIR", "model-cache")):
            for module in (config, storage, library, observability):
                if hasattr(module, name):
                    self.stack.enter_context(patch.object(module, name, self.root / directory))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.queues = []
        self.addCleanup(self.stop_queues)
        self.task = storage.create_task("local", "Synthetic private task")
        self.source = self.source_for(self.task)

    def stop_queues(self):
        if self.queues:
            set_queue_paused(self.root, False)
        for queue in self.queues:
            queue.stop()

    @staticmethod
    def source_for(task):
        return {"kind": "task_control", "id": task.id, "revision": task_generation(task)}

    def request(self, tool="cancel_task", source=None):
        return {"operation_id": uuid4().hex, "source": source or self.source,
                "tool": tool, "arguments": {}}

    def prepare(self, request):
        response = self.client.post(BASE + "/prepare", json=request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "prepared")
        return response.json()

    def execute(self, request):
        response = self.client.post(BASE + f"/{request['operation_id']}/execute", json={"confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def queue_task(self, task=None):
        task = task or self.task
        if not self.queues:
            self.queues.append(LocalTaskQueue(self.root))
            set_queue_paused(self.root, True)
        called = threading.Event()
        future = self.queues[0].enqueue(task.id, "local", called.set, generation=task_generation(task))
        return future, called

    def disk_snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes() if path.is_file() else None
                for path in self.root.rglob("*")}

    def lose_completion_receipt(self, request):
        save = journal.save

        def fail_completion(value):
            if value["status"] == "completed":
                raise OSError("synthetic completion journal failure")
            return save(value)

        with patch.object(journal, "save", side_effect=fail_completion):
            result = self.execute(request)
        self.assertEqual(result["status"], "completed")
        self.assertIn("receipt_warning", result)
        self.assertEqual(journal.load(request["operation_id"])["status"], "running")
        return result

    def assert_historical_request(self, result, request):
        self.assertEqual(result["historical_request"], {
            "generation": request["source"]["revision"],
            "operation_id": request["operation_id"], "recorded": True,
        })

    def test_queued_cancel_requires_explicit_confirmation_and_retains_files(self):
        assets = {
            storage.task_dir(self.task.id) / "note.md": b"# Synthetic saved note\r\n",
            storage.task_dir(self.task.id) / "transcript.json": b'{"segments": []}',
            self.root / "original.mp4": b"synthetic original bytes",
        }
        for path, content in assets.items():
            path.write_bytes(content)
        future, called = self.queue_task()
        before = storage.task_file(self.task.id).read_bytes()
        request = self.request()
        prepared = self.prepare(request)
        self.assertEqual(prepared["preview"]["before"]["generation"], self.source["revision"])
        self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)
        url = BASE + f"/{request['operation_id']}/execute"
        for body in ({}, {"confirm": False}, {"confirm": "true"}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post(url, json=body).status_code, 422)
        self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)
        self.assertEqual(read_queue_job(self.root, self.task.id)["state"], "queued")

        completed = self.execute(request)
        future.result(3)
        self.assertEqual(completed["status"], "completed")
        result = completed["result"]
        self.assert_historical_request(result, request)
        self.assertTrue(result["files_preserved"])
        self.assertFalse(result["undo_available"])
        observation = result["observation"]
        self.assertEqual(observation["status"], "cancelled")
        self.assertTrue(observation["cancellation_requested"])
        self.assertTrue(observation["queued_job_cancelled"])
        self.assertFalse(observation["worker_acknowledged"])
        self.assertIs(observation["callback_finished"], False)
        self.assertFalse(called.is_set())
        row = read_queue_job(self.root, self.task.id)
        self.assertEqual(row["state"], "cancelled")
        self.assertEqual(row["cancel_operation_id"], request["operation_id"])
        self.assertEqual(row["generation"], self.source["revision"])
        self.assertEqual(self.execute(request), completed)
        for path, content in assets.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.client.post(BASE + f"/{request['operation_id']}/undo",
                                         json={"operation_id": uuid4().hex}).status_code, 409)

    def test_cancelled_preview_never_requests_task_cancellation(self):
        self.queue_task()
        request = self.request()
        self.prepare(request)
        before = storage.task_file(self.task.id).read_bytes()
        row = read_queue_job(self.root, self.task.id)
        cancelled = self.client.post(BASE + f"/{request['operation_id']}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(self.execute(request)["status"], "cancelled")
        self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)
        self.assertEqual(read_queue_job(self.root, self.task.id), row)

    def test_stale_confirmation_cannot_cancel_a_queued_replacement(self):
        self.queue_task()
        request = self.request()
        self.prepare(request)
        task_control.cancel_task_generation(self.task.id, expected_generation=self.source["revision"],
                                            operation_id=uuid4().hex)
        retry = storage.admit_task_retry(self.task.id, expected_generation=self.source["revision"])
        future, called = self.queue_task(retry)
        before = storage.task_file(self.task.id).read_bytes()
        row = read_queue_job(self.root, self.task.id)
        self.assertEqual(self.execute(request)["status"], "conflict")
        self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)
        self.assertEqual(read_queue_job(self.root, self.task.id), row)
        self.assertFalse(storage.get_task(self.task.id).cancel_requested)
        set_queue_paused(self.root, False)
        future.result(3)
        self.assertTrue(called.is_set())

    def test_lost_completion_journal_recovers_without_another_task_write(self):
        future, called = self.queue_task()
        request = self.request()
        self.prepare(request)
        self.lose_completion_receipt(request)
        future.result(3)
        before = storage.task_file(self.task.id).read_bytes()
        row = read_queue_job(self.root, self.task.id)
        with patch.object(storage, "update_task", wraps=storage.update_task) as update:
            response = self.client.get(BASE + f"/{request['operation_id']}")
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["result"]["recovered"])
            self.assert_historical_request(result["result"], request)
            self.assertEqual(self.execute(request), result)
        update.assert_not_called()
        self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)
        self.assertEqual(read_queue_job(self.root, self.task.id), row)
        self.assertFalse(called.is_set())

    def test_lost_completion_journal_recovers_history_after_retry_without_cancelling_it(self):
        self.queue_task()
        request = self.request()
        self.prepare(request)
        self.lose_completion_receipt(request)
        retry = storage.admit_task_retry(self.task.id, expected_generation=self.source["revision"])
        self.queue_task(retry)
        before = storage.task_file(self.task.id).read_bytes()
        row = read_queue_job(self.root, self.task.id)
        result = self.execute(request)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["recovered"])
        self.assert_historical_request(result["result"], request)
        observation = result["result"]["observation"]
        self.assertEqual(observation["generation"], task_generation(retry))
        self.assertEqual(observation["status"], "queued")
        self.assertFalse(observation["cancellation_requested"])
        self.assertFalse(observation["queued_job_cancelled"])
        self.assertEqual(self.execute(request), result)
        self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)
        self.assertEqual(read_queue_job(self.root, self.task.id), row)

    def advance_after_cancellation(self, request):
        """Retain A's returned snapshot while another cancellation becomes current."""
        cancel = task_control.cancel_task_generation
        newer = {}

        def cancel_and_advance(*args, **kwargs):
            observation = cancel(*args, **kwargs)
            retry = storage.admit_task_retry(self.task.id, expected_generation=request["source"]["revision"])
            self.queue_task(retry)
            newer.update(generation=task_generation(retry), operation_id=uuid4().hex)
            cancel(self.task.id, expected_generation=newer["generation"], operation_id=newer["operation_id"])
            return observation

        return cancel_and_advance, newer

    def assert_distinct_receipts(self, result, request, newer):
        self.assertTrue(newer, "The later-generation observation must be exercised")
        self.assertEqual(result["status"], "completed")
        self.assert_historical_request(result["result"], request)
        receipt_observation = result["result"]["observation"]
        self.assertEqual(receipt_observation["generation"], request["source"]["revision"])
        self.assertEqual(receipt_observation["cancellation_operation_id"], request["operation_id"])
        response = self.client.get(BASE + f"/targets/task_control/{self.task.id}")
        self.assertEqual(response.status_code, 200, response.text)
        observation = response.json()["observation"]
        self.assertEqual(observation["generation"], newer["generation"])
        self.assertEqual(observation["cancellation_operation_id"], newer["operation_id"])

    def test_execute_keeps_its_own_receipt_when_observation_sees_a_later_cancellation(self):
        self.queue_task()
        request = self.request()
        self.prepare(request)
        cancel_and_advance, newer = self.advance_after_cancellation(request)
        with patch.object(task_control, "cancel_task_generation", side_effect=cancel_and_advance):
            result = self.execute(request)
        self.assert_distinct_receipts(result, request, newer)

    def test_recovery_keeps_its_own_receipt_when_observation_sees_a_later_cancellation(self):
        self.queue_task()
        request = self.request()
        self.prepare(request)
        self.lose_completion_receipt(request)
        cancel_and_advance, newer = self.advance_after_cancellation(request)
        with patch.object(task_control, "cancel_task_generation", side_effect=cancel_and_advance):
            result = self.execute(request)
        self.assert_distinct_receipts(result, request, newer)
        self.assertTrue(result["result"]["recovered"])

    def test_committed_cancellation_does_not_depend_on_a_fresh_status_read(self):
        self.queue_task()
        request = self.request()
        self.prepare(request)
        read = task_control.read_task_control
        calls = 0

        def fail_after_precondition(task_id):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise OSError("synthetic post-commit status read failure")
            return read(task_id)

        with patch.object(task_control, "read_task_control", side_effect=fail_after_precondition):
            result = self.execute(request)
        self.assertEqual(result["status"], "completed")
        self.assert_historical_request(result["result"], request)
        self.assertEqual(result["result"]["observation"]["status"], "cancelled")
        self.assertEqual(journal.load(request["operation_id"])["status"], "completed")

    def test_unprovable_old_receipt_conflicts_without_replaying_after_later_cancellation(self):
        self.queue_task()
        request = self.request()
        self.prepare(request)
        self.lose_completion_receipt(request)
        retry = storage.admit_task_retry(self.task.id, expected_generation=self.source["revision"])
        self.queue_task(retry)
        task_control.cancel_task_generation(self.task.id, expected_generation=task_generation(retry),
                                            operation_id=uuid4().hex)
        before = storage.task_file(self.task.id).read_bytes()
        row = read_queue_job(self.root, self.task.id)
        self.assertEqual(self.execute(request)["status"], "conflict")
        self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)
        self.assertEqual(read_queue_job(self.root, self.task.id), row)

    def test_cancellation_without_queue_evidence_reports_request_only(self):
        request = self.request()
        self.prepare(request)
        result = self.execute(request)
        self.assertEqual(result["status"], "completed")
        self.assert_historical_request(result["result"], request)
        observation = result["result"]["observation"]
        self.assertEqual(observation["status"], "cancelling")
        self.assertTrue(observation["cancellation_requested"])
        self.assertFalse(observation["queued_job_cancelled"])
        self.assertFalse(observation["worker_acknowledged"])
        self.assertIsNone(observation["callback_finished"])
        self.assertFalse((self.root / "task-queue.sqlite3").exists())

    def test_deleting_task_cleans_control_and_note_aliases_but_keeps_other_sources(self):
        original = self.root / "original.md"
        original.write_bytes(b"Synthetic original outside the task")
        note = storage.task_dir(self.task.id) / "note.md"
        note.write_text("# Synthetic note\n", encoding="utf-8")
        storage.update_task(self.task.id, status="success", note_path=str(note))
        control = self.request("inspect_task")
        note_request = self.request("read_note", {"kind": "task", "id": self.task.id,
                                                "revision": journal.digest(note.read_text(encoding="utf-8"))})
        other = storage.create_task("local", "Other synthetic source")
        other_request = self.request("inspect_task", self.source_for(other))
        for request in (control, note_request, other_request):
            self.prepare(request)
            self.assertEqual(self.execute(request)["status"], "completed")
        response = self.client.delete(f"/api/tasks/{self.task.id}")
        self.assertEqual(response.status_code, 200, response.text)
        for request in (control, note_request):
            self.assertIsNone(journal.load(request["operation_id"]))
            self.assertEqual(self.client.get(BASE + f"/{request['operation_id']}").status_code, 404)
        self.assertEqual(self.client.get(BASE + f"/{other_request['operation_id']}").status_code, 200)
        self.assertEqual(storage.get_task(other.id).id, other.id)
        self.assertEqual(original.read_bytes(), b"Synthetic original outside the task")

    def test_task_status_routes_do_not_create_queue_repair_manifests_or_expose_content(self):
        raw = json.loads(storage.task_file(self.task.id).read_text(encoding="utf-8"))
        raw.update(status="running", phase="transcribing", updated_at="2000-01-01T00:00:00+00:00",
                   message="PRIVATE_SYNTHETIC_MESSAGE", source_media_path="/synthetic/private/original.mp4")
        raw.pop("control_generation", None)
        raw.pop("control_retry_count", None)
        storage.task_file(self.task.id).write_text(json.dumps(raw), encoding="utf-8")
        before = self.disk_snapshot()
        listed = self.client.get(BASE + "/targets", params={"kind": "task_control"})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["targets"][0]["id"], self.task.id)
        response = self.client.get(BASE + f"/targets/task_control/{self.task.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["observation"]["status"], "running")
        self.assertNotIn("PRIVATE_SYNTHETIC_MESSAGE", response.text)
        self.assertNotIn("/synthetic/private", response.text)
        self.assertEqual(self.client.get(BASE + "/targets/task_control/missing-task").status_code, 404)
        self.assertEqual(self.disk_snapshot(), before)
        self.assertFalse((self.root / "task-queue.sqlite3").exists())

    def test_course_status_with_unresolved_handoff_reads_manifests_without_binding_or_repair(self):
        course = courses.save_course("Synthetic course", [{"kind": "url", "url": "https://example.test/lesson"}])
        episode = course_episodes.course_episodes(course, read_only=True)[0]
        storage.update_task(self.task.id, source_type="current_page", mode="video",
                            page_url=episode["url"], handoff_id=episode["handoff_id"],
                            status="running", phase="transcribing")
        raw = json.loads(storage.task_file(self.task.id).read_text(encoding="utf-8"))
        raw["updated_at"] = "2000-01-01T00:00:00+00:00"
        storage.task_file(self.task.id).write_text(json.dumps(raw), encoding="utf-8")
        before = self.disk_snapshot()
        listed = self.client.get(BASE + "/targets", params={"kind": "course"})
        self.assertEqual(listed.status_code, 200, listed.text)
        response = self.client.get(BASE + f"/targets/course/{course['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["observation"]["status_counts"], {"running": 1})
        self.assertNotIn(episode["url"], response.text)
        self.assertEqual(self.disk_snapshot(), before)
        self.assertFalse((self.root / "course-episodes.sqlite3").exists())
        self.assertFalse((self.root / "task-queue.sqlite3").exists())

    def test_deferred_and_terminal_tasks_reject_cancellation_without_mutation(self):
        for changes in ({"awaiting_confirmation": True},
                        {"awaiting_confirmation": False, "status": "success"},
                        {"status": "failed"}, {"status": "cancelled"}):
            with self.subTest(changes=changes):
                storage.update_task(self.task.id, **changes)
                before = storage.task_file(self.task.id).read_bytes()
                response = self.client.post(BASE + "/prepare", json=self.request())
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)

    @staticmethod
    def model_response(name, arguments, count=1):
        tool = SimpleNamespace(type="function", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls",
            message=SimpleNamespace(tool_calls=[tool] * count, content=None))])

    def plan_request(self):
        return {"question": "Cancel the selected task", "source": self.source,
                "options": {"llm_base_url": "http://127.0.0.1:1234/v1", "llm_model": "synthetic-model",
                            "use_saved_connection": False}}

    def test_structured_task_plan_scopes_tools_and_only_shares_status_on_explicit_opt_in(self):
        before = storage.task_file(self.task.id).read_bytes()
        request = self.plan_request()
        with patch("openai.OpenAI"), patch("app.summarizer._compatible_completion",
                return_value=self.model_response("cancel_task", {})) as completion:
            response = self.client.post(BASE + "/plan", json=request)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["source"], self.source)
            self.assertFalse(response.json()["executed"])
            self.assertEqual(response.json()["shared_characters"], 0)
            kwargs = completion.call_args.kwargs
            self.assertEqual({item["function"]["name"] for item in kwargs["tools"]}, {"inspect_task", "cancel_task"})
            self.assertIs(kwargs["parallel_tool_calls"], False)
            context = json.loads(kwargs["messages"][1]["content"])
            self.assertEqual(context, {"source": self.source, "reading": None})
            response = self.client.post(BASE + "/plan", json={**request, "share_source": True})
            self.assertEqual(response.status_code, 200, response.text)
            context = json.loads(completion.call_args.kwargs["messages"][1]["content"])
            shared = json.loads(context["untrusted_selected_status"])
            self.assertEqual(shared["generation"], self.source["revision"])
            self.assertEqual(shared["status"], "queued")
            self.assertGreater(response.json()["shared_characters"], 0)
            self.assertNotIn("Synthetic private task", json.dumps(context))
            self.assertNotIn(str(self.root), json.dumps(context))
            self.assertNotIn("options", shared)
        self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)
        self.assertFalse(list((self.root / "assistant-operations").glob("*.json")))

    def test_model_wrong_tool_target_override_and_multiple_calls_cannot_execute(self):
        before = storage.task_file(self.task.id).read_bytes()
        responses = (self.model_response("set_course_paused", {"paused": True}),
                     self.model_response("cancel_task", {"id": "other-task"}),
                     self.model_response("cancel_task", {"generation": "0" * 64}),
                     self.model_response("cancel_task", {}, count=2))
        for model_response in responses:
            with self.subTest(response=model_response), patch("openai.OpenAI"), patch(
                    "app.summarizer._compatible_completion", return_value=model_response):
                response = self.client.post(BASE + "/plan", json=self.plan_request())
                self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(storage.task_file(self.task.id).read_bytes(), before)
        self.assertFalse(list((self.root / "assistant-operations").glob("*.json")))


if __name__ == "__main__":
    unittest.main()
