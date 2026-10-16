import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks
from pydantic import ValidationError

from app.model_data_consent import approved_page_context, model_source_text, page_data_preview, page_data_fingerprint
from app.models import ActiveVideoInfo, BrowserSubtitleCue, CurrentPageTaskRequest, TaskOptions, TranscriptResult
from app.storage import create_task, get_task, read_json, task_dir, update_task


class ModelDataConsentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch("app.storage.TASK_DIR", self.root / "tasks"),
                        patch("app.observability.TASK_DIR", self.root / "tasks"),
                        patch("app.storage.ensure_dirs", lambda: None)]
        for item in self.patches:
            item.start()
        self.request = CurrentPageTaskRequest(page_url="https://course.example.com/lesson?p=2&token=private-query",
            title="Synthetic source title", page_text="Synthetic chapter context\nAuthorization: Bearer private-token\n" + "x" * 6000,
            browser_subtitles=[{"start": 0, "end": 2, "text": "Synthetic caption."}],
            options=TaskOptions(content_mode="text", llm_base_url="https://models.invalid/v1", llm_model="fixture", llm_api_key="synthetic-fixture"))

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def task(self, request=None):
        request = request or self.request
        return create_task("current_page", request.title, request.page_url, options=request.options)

    def test_default_false_strict_scopes_are_not_task_options(self):
        self.assertFalse(self.request.allow_model_page_context)
        self.assertFalse(self.request.allow_page_text_fallback)
        for field in ("allow_model_page_context", "allow_page_text_fallback"):
            with self.assertRaises(ValidationError):
                CurrentPageTaskRequest(page_url="https://example.com", **{field: "true"})
            with self.assertRaises(ValidationError):
                TaskOptions(**{field: True})

    def test_preview_is_local_redacted_and_exactly_matches_optional_excerpt(self):
        factory = Mock(side_effect=AssertionError("Preview must not construct a model client"))
        with patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}):
            preview = page_data_preview(self.request)
        factory.assert_not_called()
        self.assertEqual(preview["source_url"], "https://course.example.com/lesson?p=2")
        self.assertLessEqual(len(preview["context_excerpt"]), 4000)
        self.assertNotIn("private-token", json.dumps(preview))
        self.assertEqual(approved_page_context(self.request), "")
        approved = self.request.model_copy(update={"allow_model_page_context": True})
        from app.summarizer import _page_context_excerpt
        self.assertEqual(_page_context_excerpt(approved_page_context(approved), 4000), preview["context_excerpt"])
        self.assertIn("private-query", self.request.page_url)
        self.assertIn("private-token", self.request.page_text)

    def test_existing_redaction_removes_url_credentials_and_tokens_without_altering_original(self):
        source = "https://viewer:secret@example.com/video?token=secret#private\nhttps://example.com/v?p=3&access_token=hidden#private\nsk-syntheticsecret\npassword: hidden"
        safe = model_source_text(source)
        self.assertNotIn("viewer", safe)
        self.assertNotIn("hidden", safe)
        self.assertNotIn("syntheticsecret", safe)
        self.assertIn("https://example.com/v?p=3", safe)
        self.assertIn("viewer", source)

    def test_legacy_failed_download_and_excerpt_only_consent_never_call_provider(self):
        from app.downloader import DownloadError
        from app.processor import process_current_page_task
        for excerpt in (False, True):
            request = self.request.model_copy(update={"allow_model_page_context": excerpt, "browser_subtitles": []})
            task = self.task(request)
            existing = task_dir(task.id) / "kept-transcript.json"
            existing.write_text('{"text":"already acquired"}')
            update_task(task.id, transcript_path=str(existing))
            factory = Mock(side_effect=AssertionError("No fallback provider request without its own consent"))
            with patch("app.processor.MediaDownloader") as downloader, \
                 patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}), \
                 patch("app.processor.write_page_text_artifacts") as fallback:
                downloader.return_value.attempts = []
                downloader.return_value.download_subtitle.return_value = None
                downloader.return_value.download.side_effect = DownloadError("download_forbidden", "synthetic failure")
                process_current_page_task(task.id, request)
            factory.assert_not_called(); fallback.assert_not_called()
            done = get_task(task.id)
            self.assertEqual(done.status, "failed")
            self.assertEqual(done.error_code, "download_forbidden")
            self.assertIn("未授权", done.error_detail)
            self.assertIn("重新发送", done.error_detail)
            self.assertEqual(existing.read_text(), '{"text":"already acquired"}')
            self.assertEqual(read_json(task.id, "request.json")["page_text"], request.page_text)

    def test_explicit_fallback_uses_real_pipeline_with_bounded_redacted_text(self):
        from app.downloader import DownloadError
        from app.processor import process_current_page_task
        request = self.request.model_copy(update={"allow_page_text_fallback": True,
            "active_video": ActiveVideoInfo(duration=1000),
            "page_text": self.request.page_text + "\n" + "Page body material. " * 4000,
            "browser_subtitles": [BrowserSubtitleCue(start=0, end=2, text="Synthetic caption. " * 1000)]})
        request = CurrentPageTaskRequest.model_validate(request.model_dump())
        task = self.task(request)
        create = Mock(return_value=types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="# Synthetic result\n\nSource text."))]))
        factory = Mock(return_value=types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))))
        with patch("app.processor.MediaDownloader") as downloader, \
             patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}):
            downloader.return_value.attempts = []
            downloader.return_value.download_subtitle.return_value = None
            downloader.return_value.download.side_effect = DownloadError("download_forbidden", "synthetic failure")
            process_current_page_task(task.id, request)
        payload = create.call_args.kwargs
        text = payload["messages"][0]["content"]
        preview = page_data_preview(request)
        self.assertIsInstance(text, str)
        for value in (preview["title"], preview["source_url"], "Synthetic chapter context", "Synthetic caption."):
            self.assertIn(value, text)
        page_part = text.split("页面 DOM 文本（低可信上下文）：\n", 1)[1].split("\n\n浏览器字幕线索", 1)[0]
        subtitle_part = text.split("浏览器字幕线索（未经媒体校验）：\n", 1)[1]
        self.assertEqual(len(page_part), 50000)
        self.assertEqual(len(subtitle_part), 10000)
        self.assertNotIn("private-query", text); self.assertNotIn("private-token", text)
        self.assertNotIn("image_url", text); self.assertNotIn("cookies", payload)
        self.assertEqual(payload["model"], "fixture")
        self.assertEqual(read_json(task.id, "request.json")["page_text"], request.page_text)
        self.assertIn("Synthetic caption.", (task_dir(task.id) / "browser_subtitles.srt").read_text())

    def test_video_summary_prompt_uses_the_declared_preview_metadata_and_excerpt(self):
        from app.summarizer import summarize_with_llm
        request = self.request.model_copy(update={"allow_model_page_context": True})
        create = Mock(side_effect=RuntimeError("Synthetic provider fixture stops after capturing the payload"))
        factory = Mock(return_value=types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))))
        with patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}):
            summarize_with_llm(request.title, TranscriptResult(full_text="Synthetic spoken material", source="fixture"), [],
                request.options, request.page_url, approved_page_context(request))
        text = create.call_args.kwargs["messages"][0]["content"][0]["text"]
        preview = page_data_preview(request)
        for field in ("title", "source_url", "context_excerpt"):
            self.assertIn(preview[field], text)
        self.assertNotIn("private-query", text); self.assertNotIn("private-token", text)

    def test_explicit_page_text_route_does_not_require_video_scopes(self):
        from app.processor import process_page_text_task
        request = self.request.model_copy(update={"mode": "page_text"})
        task = self.task(request)
        artifact = types.SimpleNamespace(note_path="", subtitle_path="", transcript_path="", summary_source="local-template",
            summary_warning="", summary_diagnostics_path="", summary_diagnostics={})
        with patch("app.processor.write_page_text_artifacts", return_value=artifact) as generate:
            process_page_text_task(task.id, request)
        generate.assert_called_once()
        self.assertEqual(get_task(task.id).status, "success")

    def test_deferred_start_uses_fresh_scopes_and_never_inherits_previous_choices(self):
        from app import main
        for scopes in ({}, {"allow_model_page_context": True}, {"allow_page_text_fallback": True}):
            request = self.request.model_copy(update={"allow_model_page_context": True, "allow_page_text_fallback": True})
            task = self.task(request)
            update_task(task.id, awaiting_confirmation=True)
            main._deferred_handoffs[task.id] = request
            with patch("app.main.task_payload", return_value={}), patch("app.main.schedule_processing") as schedule:
                main.start_deferred_current_page_task(task.id, BackgroundTasks(), request.options, review_fingerprint=page_data_fingerprint(request), **scopes)
            actual = schedule.call_args.args[-1]
            self.assertEqual(actual.allow_model_page_context, scopes.get("allow_model_page_context", False))
            self.assertEqual(actual.allow_page_text_fallback, scopes.get("allow_page_text_fallback", False))
            self.assertEqual(actual.page_text, request.page_text)

    def test_api_scope_schema_and_changed_options_bind_the_fresh_start(self):
        from fastapi.testclient import TestClient
        from app import main
        task = self.task()
        update_task(task.id, awaiting_confirmation=True)
        main._deferred_handoffs[task.id] = self.request
        schema = main.app.openapi()
        parameters = schema["paths"]["/api/tasks/{task_id}/start"]["post"]["parameters"]
        for field in ("allow_model_page_context", "allow_page_text_fallback"):
            declaration = next(item for item in parameters if item["name"] == field)
            self.assertEqual(declaration["in"], "query")
            self.assertEqual(declaration["schema"]["type"], "boolean")
            self.assertFalse(declaration["schema"]["default"])
            self.assertNotIn(field, schema["components"]["schemas"]["TaskOptions"]["properties"])
            source_field = schema["components"]["schemas"]["CurrentPageTaskRequest"]["properties"][field]
            self.assertEqual(source_field["type"], "boolean")
            self.assertFalse(source_field["default"])
        fingerprint = next(item for item in parameters if item["name"] == "review_fingerprint")
        self.assertEqual(fingerprint["in"], "query")
        self.assertEqual(fingerprint["schema"]["type"], "string")
        self.assertEqual(fingerprint["schema"]["default"], "")
        changed = self.request.options.model_dump()
        changed.update(llm_base_url="https://changed-model.invalid/v1", llm_model="new-fixture", transcriber="groq")
        with TestClient(main.app) as client, patch("app.main.task_payload", return_value={}), \
             patch("app.main.schedule_processing") as schedule:
            rejected = client.post(f"/api/tasks/{task.id}/start", json={**changed, "allow_model_page_context": True})
            self.assertEqual(rejected.status_code, 422)
            schedule.assert_not_called()
            response = client.post(f"/api/tasks/{task.id}/start?allow_model_page_context=true&allow_page_text_fallback=false&review_fingerprint={page_data_fingerprint(self.request)}", json=changed)
            self.assertEqual(response.status_code, 200, response.text)
        actual = schedule.call_args.args[-1]
        self.assertEqual(actual.options.llm_base_url, changed["llm_base_url"])
        self.assertEqual(actual.options.llm_model, "new-fixture")
        self.assertEqual(actual.options.transcriber, "groq")
        self.assertTrue(actual.allow_model_page_context)
        self.assertFalse(actual.allow_page_text_fallback)

    def test_same_handoff_replacement_invalidates_review_without_enqueuing(self):
        from fastapi.testclient import TestClient
        from app import main
        request = self.request.model_copy(update={"handoff_id": "disclosure-fixture-0001"})
        factory = Mock(side_effect=AssertionError("Preview and stale confirmation must not call a provider"))
        def payload(task):
            return {"model_data_preview": page_data_preview(main._deferred_handoffs.get(task.id))}
        with TestClient(main.app) as client, patch("app.main.task_payload", side_effect=payload), \
             patch("app.main.schedule_processing") as schedule, \
             patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=factory)}):
            first = client.post("/api/tasks/from-current-page?defer=true", json=request.model_dump())
            self.assertEqual(first.status_code, 200, first.text)
            task_id = first.json()["task_id"]
            reviewed = first.json()["task"]["model_data_preview"]["fingerprint"]
            replacement = request.model_copy(update={"title": "Changed title", "page_text": "Changed private context"})
            second = client.post("/api/tasks/from-current-page?defer=true", json=replacement.model_dump())
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["task_id"], task_id)
            self.assertNotEqual(second.json()["task"]["model_data_preview"]["fingerprint"], reviewed)
            for query in (f"review_fingerprint={reviewed}&allow_model_page_context=true",
                          f"review_fingerprint={reviewed}&allow_page_text_fallback=true",
                          f"review_fingerprint={reviewed}", "allow_model_page_context=true", "allow_page_text_fallback=true"):
                denied = client.post(f"/api/tasks/{task_id}/start?{query}", json=request.options.model_dump())
                self.assertEqual(denied.status_code, 409, denied.text)
                self.assertEqual(denied.json()["detail"]["code"], "model_data_review_changed")
                self.assertTrue(get_task(task_id).awaiting_confirmation)
            schedule.assert_not_called(); factory.assert_not_called()
            self.assertEqual(read_json(task_id, "deferred_preflight.json")["page_text"], replacement.page_text)
            # Compatibility callers may still start without optional sharing.
            legacy = client.post(f"/api/tasks/{task_id}/start", json=request.options.model_dump())
            self.assertEqual(legacy.status_code, 200, legacy.text)
            actual = schedule.call_args.args[-1]
            self.assertFalse(actual.allow_model_page_context); self.assertFalse(actual.allow_page_text_fallback)


class LifecycleTaskLookupTests(unittest.TestCase):
    def test_shared_lookup_preserves_all_five_handler_errors_and_injected_lookup(self):
        from fastapi import HTTPException
        from app import main
        cases = (
            (main.create_from_existing_media, (BackgroundTasks(), None), "Task not found"),
            (main.api_task_study_proposals, (), "Task not found"),
            (main.api_cancel_task, (), {"code": "task_not_found", "message": "任务不存在"}),
            (main.api_retry_task, (BackgroundTasks(), None), {"code": "task_not_found", "message": "任务不存在"}),
            (main.api_task_pipeline_status, (), {"code": "task_not_found", "message": "任务不存在。"}),
        )
        for handler, arguments, detail in cases:
            with self.subTest(handler=handler.__name__):
                missing = FileNotFoundError("synthetic missing task")
                with patch.object(main, "get_task", side_effect=missing) as lookup, \
                     patch.object(main, "schedule_processing") as schedule:
                    with self.assertRaises(HTTPException) as raised:
                        handler("missing-fixture", *arguments)
                lookup.assert_called_once_with("missing-fixture")
                schedule.assert_not_called()
                self.assertEqual(raised.exception.status_code, 404)
                self.assertEqual(raised.exception.detail, detail)
                self.assertIs(raised.exception.__cause__, missing)

    def test_registered_lifecycle_404_payloads_preserve_route_specific_details(self):
        from fastapi.testclient import TestClient
        from app import main
        cases = (
            ("post", "rerun-from-media", "Task not found"),
            ("post", "cancel", {"code": "task_not_found", "message": "任务不存在"}),
            ("post", "retry", {"code": "task_not_found", "message": "任务不存在"}),
            ("get", "pipeline-status", {"code": "task_not_found", "message": "任务不存在。"}),
        )
        with TestClient(main.app) as client, \
             patch.object(main, "get_task", side_effect=FileNotFoundError("synthetic missing task")), \
             patch.object(main, "schedule_processing") as schedule:
            for method, route, detail in cases:
                with self.subTest(route=route):
                    response = getattr(client, method)(f"/api/tasks/missing-fixture/{route}")
                    self.assertEqual(response.status_code, 404, response.text)
                    self.assertEqual(response.json(), {"detail": detail})
            schedule.assert_not_called()
