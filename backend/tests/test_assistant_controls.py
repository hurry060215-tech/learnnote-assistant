from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import assistant_operations as operations, assistant_operation_store as journal
from app import courses, course_episodes, storage, library, knowledge, config, study, community
from app.assistant_operation_types import OperationRequest
from app.assistant_operation_planner import PlanRequest, plan
from app.models import TaskOptions
from app.routers import notes


class AssistantControlTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in (journal, courses, course_episodes, storage, library, knowledge, config, study, community, notes):
            self.stack.enter_context(patch.object(module, "DATA_DIR", self.root))
        self.stack.enter_context(patch.object(storage, "TASK_DIR", self.root / "tasks"))
        self.stack.enter_context(patch.object(storage, "ensure_dirs", lambda: None))
        self.stack.enter_context(patch.object(course_episodes, "ensure_dirs", lambda: None))
        self.course = courses.save_course("Synthetic private course", [])
        self.source = {"kind": "course", "id": self.course["id"], "revision": 1}

    def request(self, tool="set_course_paused", arguments=None):
        return OperationRequest(operation_id=uuid4().hex, source=self.source, tool=tool,
                                arguments=arguments if arguments is not None else {"paused": True})

    def test_course_requires_confirmation_replay_and_later_manual_changes_are_safe(self):
        from app.main import app
        client = TestClient(app); request = self.request()
        response = client.post("/api/assistant/operations/prepare", json=request.model_dump())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(courses.get_course(self.course["id"])["paused"])
        url = f"/api/assistant/operations/{request.operation_id}/execute"
        self.assertEqual(client.post(url, json={"confirm": False}).status_code, 422)
        result = client.post(url, json={"confirm": True}).json()
        self.assertEqual(result["status"], "completed")
        self.assertTrue(courses.get_course(self.course["id"])["paused"])
        self.assertEqual(result["result"]["new_tasks_started"], 0)
        self.assertEqual(operations.execute(request.operation_id), result)
        manual = courses.save_course("Manual title", [], False, self.course["id"], 2)
        operations.execute(request.operation_id)
        self.assertEqual(courses.get_course(self.course["id"]), manual)
        with self.assertRaises(HTTPException): operations.undo(uuid4().hex, request.operation_id)

    def test_old_course_confirmation_and_cancelled_preview_never_write(self):
        request = self.request(); operations.prepare(request)
        manual = courses.save_course("Changed course", [], False, self.course["id"], 1)
        self.assertEqual(operations.execute(request.operation_id)["status"], "conflict")
        self.source["revision"] = 2
        request = self.request(); operations.prepare(request); operations.cancel(request.operation_id)
        self.assertEqual(operations.execute(request.operation_id)["status"], "cancelled")
        self.assertEqual(courses.get_course(self.course["id"]), manual)

    def test_lost_receipt_reconciles_marker_without_a_second_course_write(self):
        request = self.request(); operations.prepare(request); save = journal.save
        def fail_receipt(value):
            if value["status"] == "completed": raise OSError("synthetic receipt loss")
            return save(value)
        with patch.object(journal, "save", side_effect=fail_receipt):
            self.assertEqual(operations.execute(request.operation_id)["status"], "completed")
        with patch.object(courses, "set_course_paused", wraps=courses.set_course_paused) as setter:
            result = operations.execute(request.operation_id)
        self.assertEqual(result["status"], "completed"); self.assertTrue(result["result"]["recovered"])
        setter.assert_not_called(); self.assertEqual(courses.get_course(self.course["id"])["revision"], 2)

    def test_lost_course_receipt_after_later_manual_change_is_not_replayed(self):
        request = self.request(); operations.prepare(request); save = journal.save
        def fail_receipt(value):
            if value["status"] == "completed": raise OSError("synthetic receipt loss")
            return save(value)
        with patch.object(journal, "save", side_effect=fail_receipt): operations.execute(request.operation_id)
        manual = courses.save_course("Manual title", [], False, self.course["id"], 2)
        self.assertEqual(operations.execute(request.operation_id)["status"], "conflict")
        self.assertEqual(courses.get_course(self.course["id"]), manual)

    def test_deleting_course_cleans_its_status_receipt_and_keeps_other_sources(self):
        request = self.request("inspect_course", {}); operations.prepare(request); operations.execute(request.operation_id)
        original = self.root / "original.md"; original.write_bytes(b"Synthetic source preserved")
        courses.delete_course(self.course["id"])
        self.assertIsNone(journal.load(request.operation_id)); self.assertEqual(original.read_bytes(), b"Synthetic source preserved")

    def test_control_status_routes_do_not_create_a_queue_or_repair_source_data(self):
        from app.main import app
        client = TestClient(app)
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        listed = client.get("/api/assistant/operations/targets?kind=course")
        self.assertEqual(listed.status_code, 200)
        response = client.get(f"/api/assistant/operations/targets/course/{self.course['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], self.source)
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def model_response(self, name, args, calls=1):
        tool = SimpleNamespace(type="function", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(tool_calls=[tool]*calls, content=None))])

    def test_structured_course_plan_is_scoped_and_status_sharing_requires_opt_in(self):
        request = PlanRequest(question="Pause this course", source=self.source, options=TaskOptions(llm_base_url="http://127.0.0.1:1234/v1"))
        with patch("openai.OpenAI"), patch("app.summarizer._compatible_completion", return_value=self.model_response("set_course_paused", {"paused": True})) as completion:
            result = plan(request)
            self.assertEqual(result["source"], self.source); self.assertFalse(result["executed"])
            self.assertEqual({t["function"]["name"] for t in completion.call_args.kwargs["tools"]}, {"inspect_course", "set_course_paused"})
            self.assertNotIn("Synthetic private course", json.dumps(completion.call_args.kwargs["messages"]))
            plan(request.model_copy(update={"share_source": True}))
            self.assertIn("Synthetic private course", json.dumps(completion.call_args.kwargs["messages"]))
        self.assertFalse(courses.get_course(self.course["id"])["paused"])

    def test_model_wrong_target_extra_identifier_and_parallel_calls_cannot_execute(self):
        request = PlanRequest(question="Operate", source=self.source, options=TaskOptions(llm_base_url="http://127.0.0.1:1234/v1"))
        for response in (self.model_response("cancel_task", {}), self.model_response("set_course_paused", {"paused": True, "id": "other"}), self.model_response("set_course_paused", {"paused": True}, 2)):
            with patch("openai.OpenAI"), patch("app.summarizer._compatible_completion", return_value=response):
                with self.assertRaises(HTTPException): plan(request)
        self.assertFalse(courses.get_course(self.course["id"])["paused"])
