from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import assistant_skills as skills, main, storage
from app.assistant_stream import assistant_stream_response
from app.models import TaskOptions, TaskQuestionRequest
from app.routers.system import AssistantSkillRequest, assistant_skill_stream


def packet(text=None, reason=None):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(
        delta=types.SimpleNamespace(content=text, reasoning_content="private reasoning"), finish_reason=reason,
    )])


class FakeStream:
    def __init__(self, *, gate=None, failure=False, complete=True):
        self.gate, self.failure, self.complete = gate, failure, complete
        self.closed = threading.Event()
        self.finished = False

    def __iter__(self):
        yield packet("第一段")
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if self.closed.is_set():
                    return
        if self.failure:
            raise RuntimeError("sk-provider-private-key https://user:password@private.invalid")
        yield packet("，第二段。")
        if self.complete:
            yield packet(reason="stop")
        self.finished = True

    def close(self):
        self.closed.set()


class FakeClient:
    def __init__(self, stream):
        self.stream, self.calls = stream, []
        self.closed = threading.Event()
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.stream

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.closed.set()
        self.stream.close()


def decode(value):
    lines = value.splitlines()
    return lines[0][7:], json.loads(lines[1][6:])


class AssistantStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.history_patch = patch.object(skills, "DATA_DIR", self.data)
        self.history_patch.start()
        self.addCleanup(self.history_patch.stop)
        self.options = TaskOptions(llm_api_key="test-key", llm_model="test-model", llm_base_url="http://127.0.0.1:1234/v1")

    def response(self):
        return assistant_skill_stream(AssistantSkillRequest(
            skill="general.chat", question="你好", options=self.options,
        ))

    async def test_provider_delta_arrives_before_completion_and_history(self):
        gate = threading.Event()
        stream, client = FakeStream(gate=gate), None
        client = FakeClient(stream)
        with patch("openai.OpenAI", return_value=client):
            response = self.response()
            events = response.body_iterator
            self.assertEqual(decode(await anext(events))[0], "start")
            event, chunk = decode(await asyncio.wait_for(anext(events), 1))
            self.assertEqual((event, chunk["text"]), ("delta", "第一段"))
            self.assertFalse(stream.finished)
            self.assertEqual(skills.history(), [])
            self.assertTrue(client.calls[0]["stream"])
            gate.set()
            remaining = [decode(value) async for value in events]
        self.assertEqual(remaining[-1][0], "result")
        self.assertEqual(remaining[-1][1]["answer"], "第一段，第二段。")
        self.assertEqual(len(skills.history()), 1)
        self.assertNotIn("reasoning", json.dumps(remaining))
        self.assertTrue(stream.closed.is_set())
        self.assertTrue(client.closed.is_set())

    async def test_disconnect_closes_provider_and_does_not_store_partial_answer(self):
        stream = FakeStream(gate=threading.Event())
        client = FakeClient(stream)
        with patch("openai.OpenAI", return_value=client):
            response = self.response()
            disconnect = asyncio.Event()

            async def receive():
                await disconnect.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.body" and b"event: delta" in message.get("body", b""):
                    disconnect.set()

            await asyncio.wait_for(response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send), 2)
            self.assertTrue(await asyncio.to_thread(stream.closed.wait, 1))
            self.assertTrue(client.closed.is_set())
            self.assertEqual(skills.history(), [])

    async def test_partial_failure_is_safe_and_never_saved_as_a_complete_answer(self):
        client = FakeClient(FakeStream(failure=True))
        with patch("openai.OpenAI", return_value=client):
            events = [decode(value) async for value in self.response().body_iterator]
        self.assertEqual([kind for kind, _ in events], ["start", "delta", "error"])
        self.assertNotIn("password", json.dumps(events))
        self.assertNotIn("provider-private-key", json.dumps(events))
        self.assertEqual(skills.history(), [])

    async def test_truncated_stream_is_not_reported_as_success(self):
        with patch("openai.OpenAI", return_value=FakeClient(FakeStream(complete=False))):
            events = [decode(value) async for value in self.response().body_iterator]
        self.assertEqual(events[-1][1]["code"], "answer_incomplete")
        self.assertEqual(skills.history(), [])

    async def test_local_help_returns_immediate_result_without_fake_token_stream(self):
        with patch("openai.OpenAI") as provider:
            response = assistant_skill_stream(AssistantSkillRequest(skill="product.help", question="如何导出笔记"))
            events = [decode(value) async for value in response.body_iterator]
        self.assertEqual([kind for kind, _ in events], ["start", "result"])
        self.assertEqual(events[-1][1]["source"], "local")
        provider.assert_not_called()

    async def test_waiting_emits_status_and_timeout_stops_work(self):
        released = threading.Event()

        def work(emit, control):
            control.track(released.set)
            released.wait(1)
            control.check()
            return {"answer": "must not complete"}

        response = assistant_stream_response(work, timeout=0.13, heartbeat=0.03)
        events = [decode(value) async for value in response.body_iterator]
        self.assertIn("status", [kind for kind, _ in events])
        self.assertEqual(events[-1][1]["code"], "assistant_timeout")
        self.assertTrue(released.is_set())
        self.assertNotIn("result", [kind for kind, _ in events])

    async def test_unconsumed_chunks_have_bounded_backpressure_and_can_be_cancelled(self):
        count, stopped = [], threading.Event()

        def work(emit, control):
            try:
                for index in range(10000):
                    emit("delta", {"text": "x"})
                    count.append(index)
                return {"answer": "x" * len(count)}
            finally:
                stopped.set()

        events = assistant_stream_response(work).body_iterator
        await anext(events)  # start
        await anext(events)  # first chunk starts the producer
        await asyncio.sleep(0.05)
        self.assertLessEqual(len(count), 33)  # queue 32 plus the consumed chunk
        self.assertFalse(stopped.is_set())
        await events.aclose()
        self.assertTrue(await asyncio.to_thread(stopped.wait, 1))

    async def test_source_stream_never_sends_default_key_to_another_endpoint(self):
        with patch.object(storage, "TASK_DIR", self.data / "tasks"):
            task = storage.create_task("local", "递归")
            note = storage.task_dir(task.id) / "note.md"
            note.write_text("# 递归\n递归必须设置终止条件。", encoding="utf-8")
            storage.update_task(task.id, note_path=str(note))
            with patch.object(main, "LLM_API_KEY", "unrelated-secret"), patch("openai.OpenAI") as constructor:
                response = main.api_task_question_stream(task.id, TaskQuestionRequest(
                    question="说明终止条件", options=TaskOptions(llm_base_url="https://other.invalid/v1"),
                ))
                events = [decode(value) async for value in response.body_iterator]
            constructor.assert_not_called()
            self.assertEqual(events[-1][1]["source"], "local-extractive")
            with patch.object(main, "LLM_API_KEY", "unrelated-secret"), patch("openai.OpenAI", return_value=FakeClient(FakeStream())) as constructor:
                response = main.api_task_question_stream(task.id, TaskQuestionRequest(
                    question="说明终止条件", options=TaskOptions(llm_base_url="http://127.0.0.1:1234/v1"),
                ))
                events = [decode(value) async for value in response.body_iterator]
            self.assertEqual(constructor.call_args.kwargs["api_key"], "local-no-key")
            self.assertEqual(events[-1][1]["source"], "llm")

    async def test_source_skills_stream_and_only_then_commit_original_question_and_citations(self):
        with patch.object(storage, "TASK_DIR", self.data / "tasks"):
            task = storage.create_task("local", "递归")
            root = storage.task_dir(task.id)
            note = root / "note.md"
            note.write_text("# 递归\n递归必须设置终止条件。", encoding="utf-8")
            storage.update_task(task.id, note_path=str(note))
            for skill in ("note.qa", "note.summary", "study.quiz"):
                with patch("openai.OpenAI", return_value=FakeClient(FakeStream())):
                    response = main.api_task_question_stream(task.id, TaskQuestionRequest(
                        question="说明终止条件", skill_id=skill, options=self.options,
                    ))
                    events = [decode(value) async for value in response.body_iterator]
                result = events[-1][1]
                self.assertEqual(events[-1][0], "result")
                self.assertEqual(result["source"], "llm")
                self.assertTrue(result["citations"])
                self.assertEqual(result["history_item"]["question"], "说明终止条件")
                self.assertEqual(result["history_item"]["skill_id"], skill)
            with patch("openai.OpenAI", return_value=FakeClient(FakeStream(failure=True))):
                response = main.api_task_question_stream(task.id, TaskQuestionRequest(
                    question="为什么", options=self.options,
                ))
                events = [decode(value) async for value in response.body_iterator]
            self.assertEqual(events[-1][0], "error")
            self.assertEqual(len(main.read_task_qa_history(task.id)), 3)

    def test_http_endpoints_validate_payload_before_starting_stream(self):
        client = TestClient(main.app)
        self.assertEqual(client.post("/api/assistant/execute/stream", json={"skill": "unknown", "question": "你好"}).status_code, 422)
        self.assertEqual(client.post("/api/tasks/000000000000/qa/stream", json={"question": "你好"}).status_code, 404)
        response = client.post("/api/assistant/execute/stream", json={"skill": "product.help", "question": "怎么导出"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertIn("event: result", response.text)


if __name__ == "__main__":
    unittest.main()
