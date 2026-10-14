"""Offline chapter-review contracts; synthetic opinions do not measure model accuracy."""
import asyncio
from contextlib import ExitStack
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, model_connections, section_reviews as service, section_review_model as model
from app.chapter_sections import chapter_payload
from app.models import TranscriptResult, TranscriptSegment
from app.pipeline_progress import start_pipeline_attempt, write_progressive_draft
from app.progressive_sections import partial_section_callback
from app.reading_notes import source_block_entries
from app.routers.section_reviews import section_reviews_router
from app.section_evidence_status import evidence_status, section_claim_map
from app.section_review_sources import capture, chapter_list, select_inputs
from app.storage import create_task, get_task, read_json, task_dir, update_task, write_json
from app.task_artifacts import read_task_note


def answer(verdict="supported", quote="学习率为 0.01，并不保证收敛。", **changes):
    item = {"claim_alias": "C1", "verdict": verdict, "reason": "根据本次原文判断。",
            "citations": [{"source_alias": "E1", "quote": quote}]}
    item.update(changes)
    return {"judgments": [item]}


def response(value=None, **changes):
    result = NS(choices=[NS(finish_reason="stop", message=NS(content=json.dumps(value or answer()),
                tool_calls=None, refusal=None))], usage=NS(prompt_tokens=50, completion_tokens=20))
    for key, value in changes.items():
        setattr(result, key, value)
    return result


class SectionReviewTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.multiple(config, DATA_DIR=self.root, TASK_DIR=self.root / "tasks",
            UPLOAD_DIR=self.root / "uploads", STATIC_DIR=self.root / "static", MODEL_CACHE_DIR=self.root / "models", TEMP_DIR=self.root / "temp"))
        for name in ("storage", "library", "observability"):
            self.stack.enter_context(patch(f"app.{name}.TASK_DIR", self.root / "tasks"))
        for name in ("storage", "library", "knowledge", "token_usage", "model_connections"):
            self.stack.enter_context(patch(f"app.{name}.DATA_DIR", self.root))
        self.stack.enter_context(patch.object(model_connections, "connection_storage", return_value="session"))
        self.stack.enter_context(patch.object(model_connections, "PUBLIC_DEPLOYMENT", False))
        service._previews.clear(); service._inflight.clear(); model_connections._selected_sessions.clear()
        self.addCleanup(service._previews.clear); self.addCleanup(service._inflight.clear)
        self.addCleanup(model_connections._selected_sessions.clear)
        self.route = {"base_url": "http://127.0.0.1:19877/v1", "model": "synthetic-review"}
        model_connections.save_selected_connection("custom", **self.route)
        self.task = create_task("local", "Synthetic chapter")
        self.work = task_dir(self.task.id)
        self.transcript = TranscriptResult(source="fixture", full_text="学习率为 0.01，并不保证收敛。",
            segments=[TranscriptSegment(start=0, end=10, text="学习率为 0.01，并不保证收敛。")])
        self.transcript_path = write_json(self.task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        self.note_path = self.work / "note.md"
        self.note_path.write_text("# Synthetic chapter\n\n## 学习率\n\n学习率为 0.01，并不保证收敛。\n", encoding="utf-8")
        update_task(self.task.id, status="success", summary_source="llm", note_path=str(self.note_path), transcript_path=str(self.transcript_path))
        app = FastAPI(); app.include_router(section_reviews_router, prefix="/api/tasks")
        self.client = TestClient(app)

    def request(self, **changes):
        revision = hashlib.sha256(read_task_note(self.task.id).encode()).hexdigest()
        sections = chapter_list(self.task.id, revision)["sections"]
        return {"revision": revision, "section_id": sections[-1]["id"], "offset": 0, **self.route, **changes}

    def preview(self, **changes):
        return self.client.post(f"/api/tasks/{self.task.id}/section-review/preview", json=self.request(**changes))

    def confirm(self, value, task_id=None, **changes):
        return self.client.post(f"/api/tasks/{task_id or self.task.id}/section-review/confirm", json={
            "preview_id": value["preview_id"], "fingerprint": value["fingerprint"], "share_source": True, **changes})

    def hashes(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob("*") if path.is_file()}

    def test_preview_no_model_no_disk_changes_and_exact_bounded_payload(self):
        before = self.hashes()
        with patch.object(service, "complete") as call:
            result = self.preview()
        self.assertEqual(result.status_code, 200, result.text)
        value = result.json(); self.assertTrue(value["can_submit"]); call.assert_not_called()
        self.assertEqual(before, self.hashes())
        self.assertEqual(value["limits"], {"requests": 1, "claims": 12, "source_characters": 12000,
            "claim_characters": 6000, "output_tokens": 2000, "timeout_seconds": 30})
        payload = json.loads(model.messages(value)[1]["content"])
        self.assertEqual(payload["claims"], value["claims"])
        self.assertEqual(payload["sources"], [{k: v[k] for k in ("source_alias", "text", "locator")} for v in value["evidence"]])
        self.assertNotIn(self.task.id, json.dumps(payload)); self.assertIsNone(value["monetary_cost"])

    def test_strict_consent_and_task_binding(self):
        value = self.preview().json()
        with patch.object(service, "complete") as call:
            for changes in ({"share_source": False}, {"share_source": 1}, {"share_source": "true"},
                            {"fingerprint": "0" * 64}, {"api_key": "synthetic-secret"}):
                self.assertIn(self.confirm(value, **changes).status_code, (409, 422))
            self.assertEqual(self.confirm(value, task_id="another-task").status_code, 409)
            for changes in ({"offset": True}, {"offset": 1}, {"section_id": "foreign"}, {"revision": "0" * 64},
                            {"base_url": "https://foreign.invalid/v1"}, {"model": "foreign"}, {"api_key": "fake"}):
                self.assertIn(self.preview(**changes).status_code, (409, 422))
        call.assert_not_called()

    def test_main_app_auth_origin_pairing_and_structured_write_budget(self):
        from app import main
        client = TestClient(main.app)
        preview_path = f"/api/tasks/{self.task.id}/section-review/preview"
        confirm_path = f"/api/tasks/{self.task.id}/section-review/confirm"
        payload = self.request()
        with patch.object(service, "complete") as call:
            with patch.object(main, "PUBLIC_DEPLOYMENT", True), patch.object(main, "PUBLIC_USERNAME", "fixture"), patch.object(main, "PUBLIC_PASSWORD", "fixture-only"):
                for path in (preview_path, confirm_path):
                    self.assertEqual(client.post(path, json=payload).status_code, 401)
                    self.assertEqual(client.post(path, json=payload, auth=("fixture", "wrong")).status_code, 401)
                self.assertEqual(client.post(preview_path, json=payload, auth=("fixture", "fixture-only")).status_code, 200)
            with patch.object(main, "PUBLIC_DEPLOYMENT", False):
                for path in (preview_path, confirm_path):
                    self.assertEqual(client.post(path, json=payload, headers={"Origin": "https://evil.invalid"}).status_code, 403)
                    self.assertEqual(client.post(path, json=payload, headers={"Origin": "chrome-extension://abcdefghijklmnop"}).status_code, 401)
                    self.assertEqual(client.post(path, json=payload, headers={"Content-Length": str(main.MAX_STRUCTURED_WRITE_BYTES + 1)}).status_code, 413)
                self.assertEqual(client.post(preview_path, json=payload, headers={"Origin": "http://127.0.0.1:8765"}).status_code, 200)
        call.assert_not_called()

    def test_source_changes_during_mapping_are_detected_before_preview(self):
        from app.section_review_sources import select_inputs as original
        def changing(*args, **kwargs):
            result = original(*args, **kwargs)
            self.note_path.write_text("# Changed during mapping\n", encoding="utf-8")
            return result
        with patch.object(service, "select_inputs", side_effect=changing), patch.object(service, "complete") as call:
            result = self.preview()
        self.assertEqual(result.status_code, 409); call.assert_not_called()

    def test_candidate_sources_keep_adjacent_negation_and_do_not_send_generated_text_as_evidence(self):
        self.note_path.write_text("# 合成\n\nGradient guarantees convergence.\n", encoding="utf-8")
        rows = [TranscriptSegment(start=i, end=i + 1, text=text) for i, text in enumerate([
            "Previous unrelated context.", "Gradient controls the update direction.",
            "This does not guarantee convergence.", "Different topic follows."])]
        write_json(self.task.id, "transcript.json", self.transcript.model_copy(update={"segments": rows}).model_dump(mode="json"))
        value = self.preview().json()
        self.assertIn("This does not guarantee convergence.", [item["text"] for item in value["evidence"]])
        self.assertNotIn("Gradient guarantees convergence.", [item["text"] for item in value["evidence"]])

    def test_success_single_use_and_no_artifact_mutation(self):
        value = self.preview().json(); before = self.hashes()
        opinion = model.parse_response(response(), value, "local-no-key")
        with patch.object(service, "complete", AsyncMock(return_value=opinion)) as call:
            result = self.confirm(value)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertFalse(result.json()["fact_verified"])
            self.assertEqual(result.json()["fingerprint"], value["fingerprint"])
            self.assertEqual(self.confirm(value).status_code, 409)
        self.assertEqual(call.await_count, 1); self.assertEqual(before, self.hashes())

    def test_actual_sdk_loopback_success_malformed_redirect_and_500_are_single_attempts(self):
        requests, mode = [], ["success"]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(handler):
                request = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
                requests.append((handler.path, request, handler.headers.get("Authorization")))
                if mode[0] == "redirect":
                    handler.send_response(302); handler.send_header("Location", "/v1/redirect-target")
                    handler.send_header("Content-Length", "0"); handler.end_headers(); return
                value = {"id": "synthetic-review", "object": "chat.completion", "created": 0, "model": "synthetic-review",
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant",
                        "content": "not json" if mode[0] == "malformed" else json.dumps(answer())}}],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}}
                encoded = json.dumps(value).encode()
                handler.send_response(500 if mode[0] == "500" else 200)
                handler.send_header("Content-Type", "application/json"); handler.send_header("Content-Length", str(len(encoded)))
                handler.end_headers(); handler.wfile.write(encoded)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            self.route["base_url"] = f"http://127.0.0.1:{server.server_port}/v1"
            model_connections.save_selected_connection("custom", **self.route)
            original = {path.name: path.read_bytes() for path in self.work.iterdir() if path.is_file()}
            for value in ("success", "malformed", "redirect", "500"):
                with self.subTest(mode=value):
                    mode[0] = value; preview = self.preview().json(); before = len(requests)
                    with patch.dict("os.environ", {"OPENAI_API_KEY": "must-not-inherit", "OPENAI_ORG_ID": "must-not-inherit"}):
                        result = self.confirm(preview)
                    self.assertEqual(len(requests), before + 1)
                    self.assertEqual(requests[-1][0], "/v1/chat/completions")
                    self.assertEqual(requests[-1][2], "Bearer local-no-key")
                    sent = requests[-1][1]
                    self.assertEqual(sent["max_tokens"], 2000)
                    self.assertEqual(json.loads(sent["messages"][1]["content"])["claims"], preview["claims"])
                    self.assertEqual(result.status_code, 200 if value == "success" else 409, result.text)
                    if value == "success":
                        self.assertEqual(result.json()["usage"], {"input_tokens": 50, "output_tokens": 20})
                    self.assertEqual(self.confirm(preview).status_code, 409)
            self.assertEqual(original, {path.name: path.read_bytes() for path in self.work.iterdir() if path.is_file()})
        finally:
            server.shutdown(); server.server_close(); worker.join(5)

    def test_source_route_key_status_and_attempt_changes_before_and_after_call(self):
        mutations = {
            "note": lambda: self.note_path.write_text("# Changed\n\nDifferent source claims.\n", encoding="utf-8"),
            "transcript": lambda: write_json(self.task.id, "transcript.json", self.transcript.model_copy(update={"full_text": "Changed"}).model_dump(mode="json")),
            "status": lambda: update_task(self.task.id, status="cancelled"),
            "retry": lambda: update_task(self.task.id, retry_count=1),
            "control": lambda: update_task(self.task.id, control_generation="changed-generation"),
            "model": lambda: model_connections.save_selected_connection("custom", self.route["base_url"], "changed"),
            "key": lambda: model_connections.save_selected_connection("custom", **self.route, api_key="changed-synthetic-key"),
        }
        initial_task, note, transcript = get_task(self.task.id), self.note_path.read_bytes(), self.transcript_path.read_bytes()
        for when in ("before", "after"):
            for name, mutate in mutations.items():
                with self.subTest(when=when, mutation=name):
                    (self.work / "task.json").write_text(initial_task.model_dump_json(), encoding="utf-8")
                    self.note_path.write_bytes(note); self.transcript_path.write_bytes(transcript)
                    model_connections.save_selected_connection("custom", **self.route)
                    value = self.preview().json()
                    async def complete(*args):
                        mutate(); return {"judgments": []}
                    if when == "before": mutate()
                    with patch.object(service, "complete", AsyncMock(side_effect=complete)) as call:
                        result = self.confirm(value)
                    self.assertEqual(result.status_code, 409, result.text)
                    self.assertEqual(call.await_count, int(when == "after"))

    def test_expired_busy_rejected_timeout_never_retry(self):
        value = self.preview().json()
        service._previews[value["preview_id"]]["expires"] = 0
        with patch.object(service, "complete") as call:
            self.assertEqual(self.confirm(value).status_code, 409)
        call.assert_not_called()
        for error, code in ((RuntimeError("private diagnostic"), "review_model_rejected"),
                            (asyncio.TimeoutError(), "review_model_timeout")):
            value = self.preview().json()
            with patch.object(service, "complete", AsyncMock(side_effect=error)) as call:
                result = self.confirm(value)
                self.assertEqual(result.json()["detail"]["code"], code)
                self.assertNotIn("private diagnostic", result.text)
                self.assertEqual(self.confirm(value).status_code, 409)
            self.assertEqual(call.await_count, 1); self.assertFalse(service._inflight)

    def test_concurrent_requests_same_task_only_one_inflight(self):
        first, second = self.preview().json(), self.preview().json()
        async def run():
            entered, finish = asyncio.Event(), asyncio.Event()
            async def complete(*args):
                entered.set(); await finish.wait(); return {"judgments": []}
            with patch.object(service, "complete", side_effect=complete) as call:
                pending = asyncio.create_task(service.review(self.task.id, first["preview_id"], first["fingerprint"], True))
                await entered.wait()
                try:
                    with self.assertRaisesRegex(ValueError, "review_busy"):
                        await service.review(self.task.id, second["preview_id"], second["fingerprint"], True)
                    self.assertEqual(call.call_count, 1)
                finally:
                    finish.set(); await pending
        asyncio.run(run()); self.assertFalse(service._inflight)

    def test_private_paths_keys_urls_redacted_from_preview_and_model(self):
        key = "saved-synthetic-secret"
        model_connections.save_selected_connection("custom", **self.route, api_key=key)
        private = "原文指出参数不一定收敛。 https://private.invalid/course?token=secret /home/private/file API_KEY=secret-value " + key
        self.note_path.write_text("# 合成\n\n" + private, encoding="utf-8")
        write_json(self.task.id, "transcript.json", self.transcript.model_copy(update={
            "segments": [TranscriptSegment(start=0, end=1, text=private)]}).model_dump(mode="json"))
        value = self.preview().json()
        for encoded in (json.dumps(value), json.dumps(model.messages(value))):
            for secret in (key, "secret-value", "https://private.invalid", "/home/private"):
                self.assertNotIn(secret, encoded)
            self.assertIn("[redacted]", encoded)

    def test_budget_and_pagination_never_automatically_call_or_cut_cues(self):
        self.note_path.write_text("# 合成\n\n" + "\n\n".join(f"结论 {i} 仍然有待核对。" for i in range(25)), encoding="utf-8")
        with patch.object(service, "complete") as call:
            for offset, count, next_offset in ((0, 12, 12), (12, 12, 24), (24, 1, None)):
                value = self.preview(offset=offset).json()
                self.assertEqual(len(value["claims"]), count)
                self.assertEqual(value["coverage"]["next_offset"], next_offset)
            write_json(self.task.id, "transcript.json", self.transcript.model_copy(update={
                "segments": [TranscriptSegment(start=0, end=1, text="字" * 12001)]}).model_dump(mode="json"))
            value = self.preview().json()
            self.assertFalse(value["can_submit"]); self.assertIsNone(value["preview_id"])
            self.assertEqual(value["evidence"], []); self.assertTrue(value["coverage"]["source_truncated"])
        call.assert_not_called()

    def test_ocr_foreign_symlink_and_missing_artifacts_never_call(self):
        with patch.object(service, "complete") as call:
            write_json(self.task.id, "transcript.json", self.transcript.model_copy(update={"source": "screen-ocr"}).model_dump(mode="json"))
            revision = hashlib.sha256(read_task_note(self.task.id).encode()).hexdigest()
            self.assertEqual(self.client.get(f"/api/tasks/{self.task.id}/section-review?revision={revision}").json()["detail"]["code"], "review_ocr_unreviewed")
            foreign = self.root / "foreign.json"; foreign.write_text(self.transcript.model_dump_json(), encoding="utf-8")
            update_task(self.task.id, transcript_path=str(foreign))
            self.assertEqual(self.client.get(f"/api/tasks/{self.task.id}/section-review?revision={revision}").status_code, 409)
            self.transcript_path.unlink(); self.transcript_path.symlink_to(foreign)
            update_task(self.task.id, transcript_path=str(self.transcript_path))
            self.assertEqual(self.client.get(f"/api/tasks/{self.task.id}/section-review?revision={revision}").status_code, 409)
        call.assert_not_called()

    def test_partial_prose_unmodified_scoped_matches_and_stale_attempt(self):
        start_pipeline_attempt(self.task.id)
        draft = write_progressive_draft(self.task.id, self.task.title, self.transcript)
        update_task(self.task.id, status="running", phase="summarizing", note_path=str(draft), summary_source="transcript-draft")
        prose = "学习率为 0.01，并不保证收敛。\n\n学习率为 0.10，保证收敛。"
        partial_section_callback(self.task.id, self.transcript)(chapter_payload({"title": "学习率", "source_blocks": [0],
            "markdown": prose}, 0, source_block_entries(self.transcript), "a" * 64))
        document = read_json(self.task.id, "partial_note.json", {})
        item = document["sections"][0]
        self.assertIn(prose, item["markdown"]); self.assertNotIn("【待核对", item["markdown"])
        self.assertEqual(item["evidence_status"]["matching_count"], 1)
        self.assertEqual(item["evidence_status"]["review_count"], 1)
        self.assertFalse(item["verified"])
        value = self.preview().json(); start_pipeline_attempt(self.task.id)
        with patch.object(service, "complete") as call:
            self.assertEqual(self.confirm(value).status_code, 409)
        call.assert_not_called()

    def test_mapping_scope_negation_digits_paraphrase_and_code_are_not_fact_proof(self):
        transcript = self.transcript.model_copy(update={"segments": [*self.transcript.segments,
            TranscriptSegment(start=10, end=20, text="外部章节才有这条结论。") ]})
        section = {"source_windows": [{"index": 0, "start": 0, "end": 10}]}
        mapped = section_claim_map(self.task.id, section, "\n\n".join([
            "学习率为 0.01，并不保证收敛。", "学习率为 0.10，并不保证收敛。", "学习率为 0.01，保证收敛。",
            "步长设为百分之一，也未必趋于稳定。", "外部章节才有这条结论。", "```python\nprint('code is not prose')\n```"]), transcript, [])
        status = evidence_status(mapped, transcript)
        self.assertEqual(status, {"schema_version": 1, "method": "literal_prose", "claim_count": 5, "matching_count": 1, "review_count": 4})
        self.assertEqual(len(mapped["evidence"]), 1)
        self.assertEqual(evidence_status(mapped, transcript.model_copy(update={"source": "screen-ocr"}))["matching_count"], 0)


class SectionReviewModelTests(unittest.TestCase):
    inputs = {"claims": [{"claim_alias": "C1", "text": "步长设为百分之一，也未必趋于稳定。"}],
        "evidence": [{"source_alias": "E1", "text": "学习率为 0.01，并不保证收敛。", "locator": "0-10s"}], "coverage": {}}

    def test_semantic_opinions_preserved_but_never_promoted_to_facts(self):
        for verdict in ("supported", "contradicted", "insufficient"):
            value = model.parse_response(response(answer(verdict)), self.inputs, "fake-secret")
            self.assertEqual(value["judgments"][0]["verdict"], verdict)
            self.assertFalse(value["fact_verified"])
        prompt = model.messages(self.inputs)[0]["content"]
        for requirement in ("negation", "numbers", "paraphrases", "untrusted data", "causal direction"):
            self.assertIn(requirement, prompt)

    def test_malformed_or_partial_quotes_and_provider_metadata_rejected(self):
        invalid = [answer(quote="保证收敛。"), answer(quote="学习率为 0.10，并不保证收敛。"), answer(citations=[]),
            answer(citations=[{"source_alias": "E2", "quote": self.inputs["evidence"][0]["text"]}]),
            answer(claim_alias="C2"), answer(reason="fake-secret"), answer(extra="forbidden"),
            {"judgments": [*answer()["judgments"], *answer()["judgments"]]}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                model.parse_response(response(value), self.inputs, "fake-secret")
        for field, value in (("content", '{"judgments":[],"judgments":[]}'), ("content", '{"judgments":NaN}'),
                             ("content", "```json\n{}\n```"), ("content", "x" * 40001),
                             ("tool_calls", [NS()]), ("refusal", "refused")):
            item = response(); setattr(item.choices[0].message, field, value)
            with self.assertRaises(ValueError): model.parse_response(item, self.inputs, "fake-secret")
        item = response(); item.choices[0].finish_reason = "length"
        with self.assertRaises(ValueError): model.parse_response(item, self.inputs, "fake-secret")

    def test_sdk_one_call_no_redirect_proxy_fallback_retry_and_usage_only(self):
        for output in (response(), response(answer(quote="invented"))):
            completion = AsyncMock(return_value=output)
            client = NS(chat=NS(completions=NS(create=completion)))
            manager = AsyncMock(); manager.__aenter__.return_value = client
            with patch("openai.AsyncOpenAI", return_value=manager) as factory, \
                 patch("openai.DefaultAsyncHttpxClient") as http, patch.object(model, "record_usage") as usage:
                if output.choices[0].message.content == response().choices[0].message.content:
                    result = asyncio.run(model.complete({"key": "fake-secret", "base_url": "http://127.0.0.1/v1", "model": "synthetic"}, self.inputs))
                    self.assertEqual(result["request_count"], 1)
                else:
                    with self.assertRaises(ValueError):
                        asyncio.run(model.complete({"key": "fake-secret", "base_url": "http://127.0.0.1/v1", "model": "synthetic"}, self.inputs))
            self.assertEqual(completion.await_count, 1); self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
            self.assertEqual(factory.call_args.kwargs["organization"], ""); self.assertEqual(factory.call_args.kwargs["project"], "")
            self.assertFalse(http.call_args.kwargs["follow_redirects"]); self.assertFalse(http.call_args.kwargs["trust_env"])
            self.assertEqual(completion.call_args.kwargs["max_tokens"], 2000)
            self.assertEqual(usage.call_count, 1)

    def test_model_deadline_cancels_locally_without_retry_and_records_failed_attempt(self):
        async def slow(**kwargs): await asyncio.sleep(1)
        completion = AsyncMock(side_effect=slow)
        manager = AsyncMock(); manager.__aenter__.return_value = NS(chat=NS(completions=NS(create=completion)))
        with patch("openai.AsyncOpenAI", return_value=manager), patch("openai.DefaultAsyncHttpxClient"), \
             patch.object(model, "MODEL_TIMEOUT_SECONDS", .01), patch.object(model, "record_usage") as usage:
            with self.assertRaises(asyncio.TimeoutError):
                asyncio.run(model.complete({"key": "fake-secret", "base_url": "http://127.0.0.1/v1", "model": "synthetic"}, self.inputs))
        self.assertEqual(completion.await_count, 1); self.assertEqual(usage.call_count, 1)
        self.assertEqual(usage.call_args.args[-1], "failed")


if __name__ == "__main__":
    unittest.main()
