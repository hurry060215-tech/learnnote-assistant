"""Fixture-only consent/dataflow contracts; no provider or browser network calls."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import community, config, main, model_connections, selected_opinion_qa as service, storage
from app.assistant_stream import StreamCancelled, StreamControl
from app.models import TaskQuestionRequest, TaskRecord, TranscriptResult, TranscriptSegment

URL = "https://www.bilibili.com/video/BV1xx411c7mD?p=2"
KEY = "sk-fixture-private-selected-key"
MIXED = "Mixed opinion-only answer <img src=x onerror=alert(1)> [E1]"


class Provider:
    def __init__(self):
        self.calls, self.closed, self.on_create, self.reject_options = [], False, None, False
        self.finish_reason, self.text = "stop", MIXED
        self.base_url = "http://127.0.0.1:19877/v1"
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.on_create:
            self.on_create()
        if self.reject_options and "stream_options" in kwargs:
            exc = RuntimeError("stream_options rejected")
            exc.status_code = 400
            raise exc
        if kwargs.get("stream"):
            return Stream(self.text, self.finish_reason)
        return NS(choices=[NS(message=NS(content=MIXED))], usage=None)

    def close(self):
        self.closed = True


class Stream:
    def __init__(self, text, finish_reason):
        self.text, self.finish_reason = text, finish_reason

    def __iter__(self):
        yield NS(choices=[NS(delta=NS(content=self.text, reasoning_content="hidden reasoning"), finish_reason=None)])
        yield NS(choices=[NS(delta=NS(content=None), finish_reason=self.finish_reason)])

    def close(self):
        pass


class SelectedOpinionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.multiple(config, DATA_DIR=self.root, TASK_DIR=self.root / "tasks",
            UPLOAD_DIR=self.root / "uploads", STATIC_DIR=self.root / "static", MODEL_CACHE_DIR=self.root / "models", TEMP_DIR=self.root / "temp"))
        for name in ("storage", "library", "observability", "main"):
            self.stack.enter_context(patch(f"app.{name}.TASK_DIR", self.root / "tasks"))
        for name in ("storage", "library", "knowledge", "community", "token_usage", "model_connections", "main",
                     "assistant_skills"):
            self.stack.enter_context(patch(f"app.{name}.DATA_DIR", self.root))
        self.stack.enter_context(patch.object(model_connections, "connection_storage", return_value="session"))
        self.stack.enter_context(patch.object(model_connections, "PUBLIC_DEPLOYMENT", False))
        model_connections._selected_sessions.clear(); service._previews.clear(); service._inflight.clear()
        self.addCleanup(model_connections._selected_sessions.clear)
        self.addCleanup(service._previews.clear); self.addCleanup(service._inflight.clear)
        self.route = {"base_url": "http://127.0.0.1:19877/v1", "model": "synthetic-opinion"}
        model_connections.save_selected_connection("custom", **self.route, api_key=KEY)
        self.task = storage.create_task("current_page", "Private title must not be sent", page_url=URL)
        self.task_dir = storage.task_dir(self.task.id)
        self.transcript = TranscriptResult(source="fixture", full_text="原始内容。",
            segments=[TranscriptSegment(start=0, end=10, text="原始内容并不保证收敛。"),
                      TranscriptSegment(start=10, end=20, text=f"API_KEY={KEY} Cookie=private-session 这是相邻原文。")],
            provenance={"private_page_context": "PROVENANCE_MUST_NOT_LEAK"})
        self.transcript_path = storage.write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        self.note_path = self.task_dir / "note.md"; self.note_path.write_text("NOTE_MUST_NOT_LEAK", encoding="utf-8")
        storage.update_task(self.task.id, status="success", transcript_path=str(self.transcript_path),
                            note_path=str(self.note_path), summary_source="llm")
        community.set_community_enabled(True)
        saved = community.add_community_context(self.task.id, [
            {"kind": "comment", "text": "Selected opinion one", "source_uri": URL},
            {"kind": "danmaku", "text": "Selected opinion two", "timestamp_seconds": 12, "source_uri": URL}])
        self.ids = [item["item_id"] for item in saved["items"]]
        self.body = {"question": "这些观点与原始内容有什么区别？", "selected_item_ids": self.ids, **self.route}
        self.client = TestClient(main.app)
        self.endpoint = f"/api/tasks/{self.task.id}/qa"
        self.provider = Provider()
        self.factory = self.stack.enter_context(patch("openai.OpenAI", return_value=self.provider))
        self.stack.enter_context(patch("app.assistant_stream.record_usage"))
        self.stack.enter_context(patch("app.token_usage.record_usage"))

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def preview(self, **changes):
        response = self.client.post(self.endpoint + "/preview", json={**self.body, **changes})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def submit(self, preview, *, stream=False, nonstream=False, **changes):
        payload = {"question": preview["question"], "selected_opinions": {"preview_id": preview["preview_id"],
                   "fingerprint": preview["fingerprint"], "selected_item_ids": preview["selected_item_ids"],
                   **preview["connection"], "confirm_send": True}, **changes}
        response = self.client.post(self.endpoint + ("" if nonstream else "/stream"), json=payload)
        if stream or nonstream or response.status_code != 200:
            return response
        # Most assertions inspect the terminal SSE envelope; explicit stream
        # tests below retain the raw HTTP response and event framing.
        for event in response.text.split("\n\n"):
            if event.startswith("event: result\n"):
                return type(response)(200, json=json.loads(event.split("data: ", 1)[1]))
            if event.startswith("event: error\n"):
                return type(response)(409, json={"detail": json.loads(event.split("data: ", 1)[1])})
        self.fail("No terminal SSE event")

    def rewrite_source(self):
        self.transcript.segments[0].text += " source changed"
        self.transcript_path.write_text(self.transcript.model_dump_json(), encoding="utf-8")

    def test_one_new_preview_route_and_strict_optional_schema(self):
        schema = main.app.openapi()
        path = schema["paths"]["/api/tasks/{task_id}/qa/preview"]
        self.assertEqual(set(path), {"post"})
        types = schema["components"]["schemas"]
        for name, fields in (("SelectedOpinionPreviewRequest", {"question", "selected_item_ids", "base_url", "model"}),
                             ("SelectedOpinionConsent", {"preview_id", "fingerprint", "selected_item_ids", "base_url", "model", "confirm_send"})):
            self.assertFalse(types[name]["additionalProperties"])
            self.assertEqual(set(types[name]["properties"]), fields)
            self.assertEqual(set(types[name]["required"]), fields)
        self.assertNotIn("selected_opinions", types["TaskQuestionRequest"]["required"])
        self.assertIn({"type": "null"}, types["TaskQuestionRequest"]["properties"]["selected_opinions"]["anyOf"])
        self.assertIsNone(TaskQuestionRequest(question="ordinary").selected_opinions)
        response = self.client.post(self.endpoint + "/preview", json={**self.body, "cookies": KEY})
        self.assertEqual(response.status_code, 422); self.assertNotIn(KEY, response.text)
        self.factory.assert_not_called()

    def test_optional_nonstream_rejects_without_consuming_preview_or_calling_model(self):
        preview = self.preview()
        response = self.submit(preview, nonstream=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "opinion_stream_required")
        self.factory.assert_not_called()
        self.assertFalse(service._previews[preview["preview_id"]]["used"])
        self.assertEqual(self.submit(preview).status_code, 200)

    def test_preview_is_read_only_exact_redacted_and_zero_provider(self):
        before = self.snapshot(); preview = self.preview(question=f"Question api_key={KEY}")
        self.assertEqual(before, self.snapshot()); self.factory.assert_not_called()
        text = json.dumps(preview)
        for secret in (KEY, "private-session", "PAGE_MUST_NOT_LEAK", "NOTE_MUST_NOT_LEAK", "PROVENANCE_MUST_NOT_LEAK", str(self.root)):
            self.assertNotIn(secret, text)
        self.assertNotEqual(preview["question"], f"Question api_key={KEY}")
        self.assertEqual([item["item_id"] for item in preview["opinions"]], self.ids)
        self.assertTrue(preview["can_submit"]); self.assertFalse(preview["persisted"])
        self.assertEqual(preview["limits"]["stream_compatibility_retries"], 1)
        self.assertNotIn("最多一次", preview["warning"])

    def test_approved_payload_exact_whole_unverified_no_content_persistence(self):
        preview = self.preview(); before = self.snapshot(); result = self.submit(preview)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.provider.calls[0]["messages"], preview["messages"])
        body = result.json()
        self.assertEqual(body["answer"], MIXED); self.assertEqual(body["citations"], [])
        for field in ("fact_verified", "evidence_eligible", "persisted"):
            self.assertIs(body[field], False)
        self.assertEqual(body["source"], "selected-opinions-unverified")
        self.assertNotIn("history_item", body); self.assertNotIn("history_count", body)
        self.assertEqual(self.client.get(self.endpoint).json()["items"], [])
        self.assertEqual(community.list_community_context(self.task.id)["items"][0]["text"], "Selected opinion one")
        self.assertEqual(self.submit(preview).status_code, 409)
        self.assertEqual(len(self.provider.calls), 1)

    def test_stream_uses_existing_completion_policy_and_final_only(self):
        preview = self.preview(); before = self.snapshot(); self.provider.reject_options = True
        result = self.submit(preview, stream=True)
        self.assertIn("event: result", result.text); self.assertNotIn("event: delta", result.text)
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual(self.provider.calls[0]["messages"], preview["messages"])
        self.assertNotIn("stream_options", self.provider.calls[1])
        self.assertEqual(self.factory.call_args.kwargs["max_retries"], 0)
        self.assertEqual(self.factory.call_args.kwargs["timeout"], 30)
        self.assertEqual(before, self.snapshot()); self.assertTrue(self.provider.closed)

    def test_default_off_invalid_selection_and_unapproved_are_zero_calls(self):
        community.set_community_enabled(False)
        self.assertEqual(self.client.post(self.endpoint + "/preview", json=self.body).status_code, 409)
        community.set_community_enabled(True)
        for ids in ([], [self.ids[0]] * 2, ["0" * 32], self.ids * 11):
            with self.subTest(ids=ids):
                self.assertIn(self.client.post(self.endpoint + "/preview", json={**self.body, "selected_item_ids": ids}).status_code, {409, 422})
        preview = self.preview()
        response = self.submit(preview, selected_opinions={"preview_id": preview["preview_id"], "fingerprint": preview["fingerprint"],
                 "selected_item_ids": self.ids, **self.route, "confirm_send": False})
        self.assertEqual(response.status_code, 409); self.factory.assert_not_called()
        response = self.submit(preview, skill_id="study.quiz")
        self.assertEqual(response.status_code, 409); self.factory.assert_not_called()
        response = self.submit(preview, options={})
        self.assertEqual(response.status_code, 409); self.factory.assert_not_called()

    def test_request_question_selection_recipient_and_fingerprint_changes_consume(self):
        for field, value in (("question", "changed"), ("selected_item_ids", self.ids[:1]), ("model", "changed"),
                             ("base_url", "http://127.0.0.1:1/v1"), ("fingerprint", "0" * 64)):
            preview = self.preview()
            changes = {"question": value} if field == "question" else {"selected_opinions": {
                "preview_id": preview["preview_id"], "fingerprint": preview["fingerprint"],
                "selected_item_ids": self.ids, **self.route, "confirm_send": True, field: value}}
            self.assertEqual(self.submit(preview, **changes).status_code, 409)
            self.assertEqual(self.submit(preview).status_code, 409)
        self.factory.assert_not_called()

    def test_source_model_key_generation_deletion_and_roots_invalidate_before_dispatch(self):
        mutations = [self.rewrite_source,
            lambda: storage.update_task(self.task.id, retry_count=1),
            lambda: storage.update_task(self.task.id, control_generation="replacement-generation"),
            lambda: model_connections.save_selected_connection("custom", **self.route, api_key="replacement-key"),
            lambda: community.set_community_enabled(False),
            lambda: community.clear_community_context(self.task.id),
            lambda: community.delete_community_item(self.task.id, self.ids[0])]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                preview = self.preview(); saved = self.snapshot(); mutate()
                self.assertEqual(self.submit(preview).status_code, 409)
                for relative, (raw, _) in saved.items():
                    (self.root / relative).write_bytes(raw)
        preview = self.preview()
        with patch.object(storage, "TASK_DIR", self.root / "other-tasks"):
            self.assertIn(self.submit(preview).status_code, {404, 409})
        preview = self.preview()
        with patch.object(community, "DATA_DIR", self.root / "other-community"):
            self.assertEqual(self.submit(preview).status_code, 409)
        self.factory.assert_not_called()

    def test_post_dispatch_changes_and_cancel_suppress_entire_result(self):
        for mutation in (self.rewrite_source, lambda: community.delete_community_item(self.task.id, self.ids[0]),
                         lambda: community.set_community_enabled(False)):
            preview = self.preview(); saved = self.snapshot(); keys = dict(model_connections._selected_sessions)
            self.provider.on_create = mutation
            result = self.submit(preview, stream=True)
            self.assertIn("event: error", result.text); self.assertNotIn(MIXED, result.text)
            self.assertNotIn("event: delta", result.text); self.assertNotIn("event: result", result.text)
            for relative, (raw, _) in saved.items():
                (self.root / relative).write_bytes(raw)
        preview = self.preview(); control = StreamControl(); self.provider.on_create = control.cancel
        request = TaskQuestionRequest(question=preview["question"], selected_opinions={"preview_id": preview["preview_id"],
            "fingerprint": preview["fingerprint"], "selected_item_ids": self.ids, **self.route, "confirm_send": True})
        with self.assertRaises(StreamCancelled):
            service.answer(self.task.id, request, emit=lambda *_: None, control=control)
        self.assertFalse(service._inflight)

    def test_incomplete_overlong_and_provider_error_never_leak_or_persist_partial_answer(self):
        for reason, text in (("length", MIXED), (None, MIXED), ("stop", "Partial private answer" * 2000)):
            preview = self.preview(); before = self.snapshot()
            self.provider.finish_reason, self.provider.text = reason, text
            response = self.submit(preview, stream=True)
            self.assertIn("event: error", response.text); self.assertNotIn("event: delta", response.text)
            self.assertNotIn("event: result", response.text); self.assertNotIn(text, response.text)
            self.assertNotIn("已保留收到的内容", response.text)
            self.assertEqual(before, self.snapshot())
        preview = self.preview(); self.provider.on_create = lambda: (_ for _ in ()).throw(RuntimeError(KEY))
        response = self.submit(preview, stream=True)
        self.assertIn("event: error", response.text); self.assertNotIn(KEY, response.text)

    def test_revocation_blocks_existing_compatibility_retry(self):
        preview = self.preview(); self.provider.reject_options = True
        self.provider.on_create = lambda: community.set_community_enabled(False)
        result = self.submit(preview, stream=True)
        self.assertEqual(len(self.provider.calls), 1); self.assertIn("event: error", result.text)
        self.assertNotIn(MIXED, result.text)

    def test_manual_origin_missing_source_and_wrong_part(self):
        manual = community.add_community_context(self.task.id, [{"kind": "comment", "text": "Manual input"}])["items"][0]
        preview = self.preview(selected_item_ids=[manual["item_id"]])
        self.assertEqual(preview["opinions"][0]["origin_label"], "手动添加，原始出处未核实")
        self.assertEqual(preview["opinions"][0]["capture_method"], "unknown")
        wrong = community.add_community_context(self.task.id, [{"kind": "comment", "text": "Other part", "source_uri": URL.replace("p=2", "p=3")}])["items"][0]
        self.assertEqual(self.client.post(self.endpoint + "/preview", json={**self.body, "selected_item_ids": [wrong["item_id"]]}).status_code, 409)
        self.transcript.segments = [TranscriptSegment(start=0, end=1, text="x" * 13000)]
        self.transcript_path.write_text(self.transcript.model_dump_json(), encoding="utf-8")
        preview = self.preview(); self.assertFalse(preview["can_submit"]); self.assertIsNone(preview["preview_id"])
        self.assertEqual(preview["coverage"]["omitted_sources"], 1)
        self.factory.assert_not_called()

    def test_new_preview_expiry_and_pre_cancel_prevent_dispatch(self):
        old = self.preview(); current = self.preview()
        self.assertEqual(self.submit(old).status_code, 409)
        service._previews[current["preview_id"]]["expires"] = 0
        self.assertEqual(self.submit(current).status_code, 409)
        preview = self.preview(); control = StreamControl(); control.cancel()
        request = TaskQuestionRequest(question=preview["question"], selected_opinions={"preview_id": preview["preview_id"],
            "fingerprint": preview["fingerprint"], "selected_item_ids": self.ids, **self.route, "confirm_send": True})
        with self.assertRaises(StreamCancelled):
            service.answer(self.task.id, request, emit=lambda *_: None, control=control)
        self.factory.assert_not_called()

    def test_range_parent_and_review_required_diagnostics_fail_closed(self):
        for field, value in (("learning_range", {"start": 3, "end": 8}), ("source_task_id", "different-source"),
                             ("summary_diagnostics", {"review_required": True}),
                             ("summary_diagnostics", {"evidence_quality": "review_required"}),
                             ("summary_diagnostics", {"transcript_quality": {"review_required": True}})):
            with self.subTest(field=field, value=value):
                preview = self.preview(); saved = self.snapshot()
                storage.update_task(self.task.id, **{field: value})
                self.assertEqual(self.submit(preview).status_code, 409)
                for name, (content, _) in saved.items():
                    (self.root / name).write_bytes(content)
                preview = self.preview()
                self.provider.on_create = lambda: storage.update_task(self.task.id, **{field: value})
                result = self.submit(preview, stream=True)
                self.assertIn("event: error", result.text); self.assertNotIn(MIXED, result.text)
                for name, (content, _) in saved.items():
                    (self.root / name).write_bytes(content)
                self.provider.on_create = None

    def test_linked_urls_require_recoverable_exact_identity_and_manual_rows_do_not_invent_it(self):
        manual = community.add_community_context(self.task.id, [{"kind": "comment", "text": "Manual unknown origin"}])["items"][0]
        for index, url in enumerate(("https://www.youtube.com/watch?v=videoA", "https://www.youtube.com/watch?v=videoB",
                                    "https://example.test/course?part=2", "https://example.test/course#part2",
                                    "https://example.test/" + "a" * 810,
                                    URL.replace("p=2", "p=invalid"), URL.replace("p=2", "p=2&p=3"))):
            with self.subTest(url=url):
                storage.update_task(self.task.id, page_url=url)
                item = community.add_community_context(self.task.id, [{"kind": "comment", "text": f"Linked opinion {index}", "source_uri": url}])["items"][0]
                self.assertTrue(item["source_uri"])
                result = self.client.post(self.endpoint + "/preview", json={**self.body, "selected_item_ids": [item["item_id"]]})
                self.assertEqual(result.status_code, 409)
                preview = self.preview(selected_item_ids=[manual["item_id"]])
                self.assertEqual(preview["opinions"][0]["source_uri"], "")
        storage.update_task(self.task.id, page_url="https://example.test/course/lesson-2")
        item = community.add_community_context(self.task.id, [{"kind": "comment", "text": "Exact generic origin", "source_uri": "https://example.test/course/lesson-2"}])["items"][0]
        self.assertTrue(self.preview(selected_item_ids=[item["item_id"]])["can_submit"])
        self.factory.assert_not_called()

    def test_invalid_timing_cannot_drop_an_original_qualifier(self):
        for start, end in ((-1, 5), (10, 5), (float("inf"), 10)):
            self.transcript.segments = [TranscriptSegment(start=0, end=1, text="看似肯定的内容。"),
                TranscriptSegment(start=start, end=end, text="但这个条件并不成立。"),
                TranscriptSegment(start=20, end=25, text="另一个不相邻的例子。")]
            raw = self.transcript.model_dump(mode="python")
            self.transcript_path.write_text(json.dumps(raw), encoding="utf-8")
            result = self.client.post(self.endpoint + "/preview", json=self.body)
            self.assertEqual(result.status_code, 409)
        self.factory.assert_not_called()

    def test_owned_read_brackets_source_identity_and_never_relabels_notes(self):
        from app import selected_opinion_sources as sources
        original_read = sources.read_anchor_artifact
        def changed_read(*args):
            raw = original_read(*args)
            storage.update_task(self.task.id, source_task_id="rebound-source")
            return raw
        with patch.object(sources, "read_anchor_artifact", side_effect=changed_read):
            result = self.client.post(self.endpoint + "/preview", json=self.body)
        self.assertEqual(result.status_code, 409); self.factory.assert_not_called()
        storage.update_task(self.task.id, source_task_id="")
        self.transcript.source = "screen-ocr"
        self.transcript_path.write_text(self.transcript.model_dump_json(), encoding="utf-8")
        self.assertEqual(self.client.post(self.endpoint + "/preview", json=self.body).status_code, 409)
        outside = self.root / "outside.json"; outside.write_text(self.transcript.model_dump_json(), encoding="utf-8")
        storage.update_task(self.task.id, transcript_path=str(outside))
        self.assertEqual(self.client.post(self.endpoint + "/preview", json=self.body).status_code, 409)
        self.factory.assert_not_called()

    def test_late_model_key_root_and_superseding_preview_suppress_result(self):
        mutations = [lambda: model_connections.save_selected_connection("custom", **self.route, api_key="changed-key"),
                     lambda: model_connections.save_selected_connection("custom", base_url=self.route["base_url"], model="changed"),
                     lambda: self.preview()]
        for mutation in mutations:
            preview = self.preview(); saved = self.snapshot(); keys = dict(model_connections._selected_sessions)
            self.provider.on_create = mutation
            result = self.submit(preview, stream=True)
            self.assertIn("event: error", result.text); self.assertNotIn(MIXED, result.text)
            for name, (content, _) in saved.items():
                (self.root / name).write_bytes(content)
            model_connections._selected_sessions.clear(); model_connections._selected_sessions.update(keys)
            self.provider.on_create = None
        preview = self.preview()
        with patch.object(service, "_scope", wraps=service._scope) as scope:
            initial = scope()
            self.provider.on_create = lambda: setattr(scope, "return_value", (*initial[:2], "changed-model-root"))
            result = self.submit(preview, stream=True)
            self.assertIn("event: error", result.text); self.assertNotIn(MIXED, result.text)

    def test_persistence_writers_and_public_history_exports_never_receive_optional_output(self):
        targets = ["app.main.append_task_qa_history", "app.assistant_skills.record_turn", "app.assistant_run_store.save",
                   "app.assistant_runs._save", "app.assistant_operation_store.save", "app.storage.save_task",
                   "app.storage.write_json", "app.observability.record_task_event", "app.knowledge.add_evidence"]
        with ExitStack() as guards:
            writers = [guards.enter_context(patch(target, side_effect=AssertionError("Unexpected content persistence"))) for target in targets]
            preview = self.preview(); result = self.submit(preview)
            self.assertEqual(result.status_code, 200, result.text)
            for writer in writers:
                writer.assert_not_called()
        paths = [self.endpoint, "/api/assistant/history", f"/api/tasks/{self.task.id}/claims",
                 f"/api/tasks/{self.task.id}/events", f"/api/tasks/{self.task.id}/exports/markdown",
                 f"/api/tasks/{self.task.id}/exports/manifest", f"/api/tasks/{self.task.id}/exports/qa"]
        for path in paths:
            result = self.client.get(path)
            self.assertNotIn(MIXED, result.text); self.assertNotIn("Selected opinion one", result.text)
        self.assertFalse((self.root / "assistant-runs").exists())
        self.assertFalse((self.root / "assistant-operations").exists())
        self.assertFalse((self.task_dir / "qa_history.json").exists())

    def test_cache_capacity_and_concurrent_replay_are_bounded(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        preview = self.preview(); entered, release = threading.Event(), threading.Event()
        def hold():
            entered.set(); release.wait(3)
        self.provider.on_create = hold
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.submit, preview)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.submit(preview).status_code, 409)
            release.set(); self.assertEqual(first.result(3).status_code, 200)
        self.assertEqual(len(self.provider.calls), 1)
        with patch.object(service, "MAX_PENDING_PREVIEWS", 0):
            response = self.client.post(self.endpoint + "/preview", json=self.body)
            self.assertEqual(response.status_code, 409)
        self.assertFalse(service._inflight)

    def test_ordinary_qa_retains_payload_output_error_fallback_and_history(self):
        result = self.client.post(self.endpoint, json={"question": "原始内容是什么？", "options": {
            "llm_api_key": KEY, "llm_base_url": self.route["base_url"], "llm_model": self.route["model"]}})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["source"], "llm"); self.assertIn("history_item", result.json())
        self.assertEqual(result.json()["history_count"], 1)
        self.assertNotIn("opinions", self.provider.calls[0]["messages"][-1]["content"])
        self.assertEqual(self.factory.call_args.kwargs["max_retries"], main.LLM_MAX_RETRIES)
        self.provider.on_create = lambda: (_ for _ in ()).throw(RuntimeError("provider failed"))
        result = self.client.post(self.endpoint, json={"question": "原始内容？", "options": {
            "llm_api_key": KEY, "llm_base_url": self.route["base_url"], "llm_model": self.route["model"]}})
        self.assertEqual(result.status_code, 200); self.assertEqual(result.json()["source"], "local-extractive")
        self.assertEqual(result.json()["history_count"], 2)
        preview = self.preview(); result = self.submit(preview)
        self.assertEqual(result.status_code, 409); self.assertNotIn("local-extractive", result.text)
        self.assertEqual(len(self.client.get(self.endpoint).json()["items"]), 2)


if __name__ == "__main__":
    unittest.main()
