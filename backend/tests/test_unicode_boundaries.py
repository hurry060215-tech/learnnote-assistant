"""Synthetic boundary regressions: decoded HTML, review artifacts and diagnostics."""
from contextlib import ExitStack
from io import BytesIO
from zipfile import ZipFile
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app, api_export_bundle, api_export_support_package, api_export_diagnostics, task_payload
from app.library import material_source_path
from app.routers.knowledge_study import api_study_cards
from app.knowledge import extract_import_text_with_metadata
from app.library import transcript_evidence
from app.models import TaskOptions, TranscriptResult, TranscriptSegment
from app.note_document import normalize_note_markdown
from app.routers.notes import get_edition, api_note_document
from app.storage import create_task, get_task, task_dir, update_task, write_json
from app.study import propose_cards, quiz_evidence_eligible
from app.summary_diagnostics import build_summary_diagnostics
from app.summary_outcome import safe_summary_diagnostics, safe_summary_warning
from app.task_artifacts import public_summary_task
from app.summarizer import _record_llm_event
from app.task_artifacts import read_task_note
from app.text_cleanup import TextDecodingError, decode_text_bytes
from app.transcript_quality import preserve_transcript_review_draft


class UnicodeBoundaryTests(unittest.TestCase):
    def isolated_tasks(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        for module, attr, value in (("storage", "TASK_DIR", root / "tasks"),
                ("observability", "TASK_DIR", root / "tasks"),
                ("routers.notes", "DATA_DIR", root), ("library", "DATA_DIR", root),
                ("knowledge", "DATA_DIR", root), ("storage", "ensure_dirs", lambda: None)):
            stack.enter_context(patch(f"app.{module}.{attr}", value))
        return root

    def test_html_entities_cannot_hide_single_replacement_or_known_corruption(self):
        for text in ("正文 � 结尾", "这段锟斤拷内容应被阻断。", "测试鏂囧字幕。"):
            for entities in ("".join(f"&#{ord(c)};" for c in text), "".join(f"&#x{ord(c):x};" for c in text)):
                raw = f"<p>{entities}</p>".encode()
                original = bytes(raw)
                with self.subTest(text=text, html=entities), self.assertRaisesRegex(ValueError, "^text_mojibake_detected$"):
                    extract_import_text_with_metadata("fixture.html", raw, "text/html")
                self.assertEqual(raw, original)

    def test_html_import_api_rejects_entity_corruption_and_retains_clean_original(self):
        root = self.isolated_tasks()
        with patch("app.config.TEMP_DIR", root / "temp"), patch("app.library.TEMP_DIR", root / "temp"):
            client = TestClient(app)
            blocked = client.post("/api/library/materials/import", files={"file": ("bad.html", b"<p>&#xfffd;</p>", "text/html")})
            self.assertEqual(blocked.status_code, 422, blocked.text)
            self.assertEqual(blocked.json()["detail"]["code"], "text_mojibake_detected")
            raw = '<h1>合成课程</h1><p>中文 English &#x1f9ed;</p>'.encode()
            response = client.post("/api/library/materials/import", files={"file": ("clean.html", raw, "text/html")})
            self.assertEqual(response.status_code, 200, response.text)
            material = response.json()["material"]
            self.assertEqual(material_source_path(material["material_id"]).read_bytes(), raw)
            content = client.get(f"/api/library/materials/{material['material_id']}/content")
            self.assertEqual(content.status_code, 200)
            self.assertIn("中文 English 🧭", content.json()["text"])

    def test_visible_html_metadata_and_code_literals_survive_entity_expansion(self):
        raw = '<p>中文 日本語 English &amp; café &#x1f9ed;</p><pre>sample = "&#xfffd; 锟斤拷"</pre>'.replace('锟斤拷', '&#38175;&#26020;&#25335;').encode()
        text, kind, meta = extract_import_text_with_metadata("fixture.html", raw, "text/html")
        self.assertEqual(kind, "webpage")
        self.assertIn("中文 日本語 English & café 🧭", text)
        self.assertIn('sample = "� 锟斤拷"', text)
        self.assertEqual(meta["replacement_character_count"], 1)
        self.assertEqual(meta["mojibake_score"], 0)
        self.assertFalse(meta["encoding_repaired"])
        self.assertFalse(normalize_note_markdown("Fixture", text).report["blocking"])
        for literal in ("&#xfffd;", "`&#xfffd;`", "&#38175;&#26020;&#25335;"):
            text, _, meta = extract_import_text_with_metadata("fixture.html",
                f"<p>编码教学示例：<code>{literal}</code>，仅作为代码引用。</p>".encode(), "text/html")
            self.assertFalse(normalize_note_markdown("Fixture", text).report["blocking"])
            self.assertEqual(meta["mojibake_score"], 0)
        with self.assertRaisesRegex(ValueError, "text_mojibake_detected"):
            extract_import_text_with_metadata("fixture.html", b"<code>unclosed &#xfffd;", "text/html")


    def test_explicit_review_draft_is_readable_without_rewriting_or_publication(self):
        self.isolated_tasks()
        for text in ("锟斤拷 保留原词。", "测试鏂囧字幕。", "è¯ 原词需要核对。", "一个�字符。"):
            task = create_task("local", "合成课程")
            transcript = TranscriptResult(source="faster-whisper", full_text=text,
                segments=[TranscriptSegment(start=3, end=9, text=text)])
            raw = write_json(task.id, "transcript_raw.json", transcript.model_dump(mode="json"))
            original = raw.read_bytes()
            # The reversible marker case needs another suspicious marker to
            # require review; the draft reader must still not repair either.
            if text.startswith("è¯"):
                transcript.full_text += " 锟斤拷"
                transcript.segments[0].text += " 锟斤拷"
            self.assertTrue(preserve_transcript_review_draft(task.id, task.title, transcript,
                task_dir=task_dir, write_json=write_json, update_task=update_task))
            record = get_task(task.id)
            draft = Path(record.note_path).read_bytes()
            edition = get_edition("task", task.id)
            self.assertEqual(edition["text"].encode(), draft)
            self.assertFalse(edition["edited"])
            self.assertIn("待核对草稿", edition["text"])
            self.assertTrue(api_note_document(task.id)["normalization"]["blocking"])
            self.assertTrue(normalize_note_markdown(task.title, edition["text"]).report["blocking"])
            self.assertEqual(raw.read_bytes(), original)
            self.assertEqual(Path(record.note_path).read_bytes(), draft)
            self.assertFalse((task_dir(task.id) / "note.md").exists())

    def test_review_filename_alone_does_not_bypass_strict_formal_note_reader(self):
        self.isolated_tasks()
        task = create_task("local", "Normal task")
        path = task_dir(task.id) / "draft.review.md"
        path.write_text("# 正式笔记\n\n这段锟斤拷不可发布。", encoding="utf-8")
        update_task(task.id, note_path=str(path), summary_source="text-llm", status="success")
        with self.assertRaises(TextDecodingError):
            read_task_note(task.id)
        with self.assertRaises(HTTPException) as caught:
            get_edition("task", task.id)
        self.assertEqual(caught.exception.status_code, 404)
        path.write_text("# 正常\n\n中文 日本語 English 🧭", encoding="utf-8")
        self.assertIn("中文 日本語 English 🧭", read_task_note(task.id))

    def test_review_task_clean_segments_and_uncertain_markers_cannot_become_cards(self):
        self.isolated_tasks()
        task = create_task("local", "合成课程")
        text = "学习率决定参数的更新幅度，因此训练时需要根据损失变化谨慎调整学习率，避免更新幅度过大导致训练不稳定。"
        raw = json.dumps({"segments": [{"start": 3, "end": 9, "text": text}]}, ensure_ascii=False)
        normal = transcript_evidence(task, raw)[0]
        self.assertTrue(quiz_evidence_eligible(normal))
        self.assertEqual(len(propose_cards([normal])), 1)
        task.summary_diagnostics = {"review_required": True}
        review = transcript_evidence(task, raw)[0]
        self.assertEqual(review.text, text)
        self.assertFalse(quiz_evidence_eligible(review))
        self.assertEqual(propose_cards([review]), [])
        with patch("app.routers.knowledge_study.evidence_by_ids", return_value=[review.model_dump()]), \
             patch("app.routers.knowledge_study.save_cards") as save:
            with self.assertRaises(HTTPException) as caught:
                api_study_cards({"cards": [{"front": "Synthetic question", "back": text,
                    "source_evidence_ids": [review.evidence_id]}]})
            self.assertEqual(caught.exception.status_code, 422)
            save.assert_not_called()
        uncertain = normal.model_copy(update={"text": text + "【识别不清】"})
        self.assertFalse(quiz_evidence_eligible(uncertain))
        quoted = normal.model_copy(update={"text": text + " 示例：`【识别不清】`。"})
        self.assertTrue(quiz_evidence_eligible(quoted))
        # Rows indexed before the metadata flag existed still resolve their
        # owning task's current publication state at the canonical boundary.
        update_task(task.id, status="failed", summary_source="transcript-draft", summary_diagnostics={})
        self.assertNotIn("review_required", {k: v for k, v in normal.metadata.items() if v})
        self.assertFalse(quiz_evidence_eligible(normal))
        with patch("app.routers.knowledge_study.evidence_by_ids", return_value=[normal.model_dump()]), \
             patch("app.routers.knowledge_study.save_cards") as save:
            with self.assertRaises(HTTPException):
                api_study_cards({"cards": [{"front": "Legacy question", "back": text,
                    "source_evidence_ids": [normal.evidence_id]}]})
            save.assert_not_called()
        self.assertTrue(quiz_evidence_eligible(normal.model_copy(update={"task_id": ""})))
        update_task(task.id, status="success", summary_source="text-llm", summary_diagnostics={})
        self.assertTrue(quiz_evidence_eligible(normal))


    def test_bom_wins_over_conflicting_declaration_for_all_supported_bom_encodings(self):
        text = "中文 日本語 English 🧭"
        for encoding in ("utf-8-sig", "utf-16", "utf-32"):
            decoded = decode_text_bytes(text.encode(encoding), declared_encoding="gb18030")
            self.assertEqual(decoded.text, text)
            self.assertEqual(decoded.encoding_source, "bom")
            self.assertEqual(decoded.declared_encoding, "gb18030")
        with self.assertRaises(TextDecodingError):
            decode_text_bytes("中文内容".encode("gb18030"), declared_encoding="utf-8")


class SummaryDiagnosticPrivacyTests(unittest.TestCase):
    isolated_tasks = UnicodeBoundaryTests.isolated_tasks
    # Provider payloads and source text below are invented fixture markers.
    private = "Cookie: SESSION_SYNTHETIC https://private.example/lesson?token=TOKEN_SYNTHETIC SensitiveBodySynthetic"

    def diagnostics(self):
        events = []
        _record_llm_event(events, "vision_batch", "api_error", ValueError("HTTP 429 " + self.private),
            batch=2, duration_ms=12, issues=["unsupported_terms: " + self.private], body=self.private)
        with patch("app.summary_diagnostics.LLM_API_KEY", ""), patch("app.summary_diagnostics.connected_api_key", return_value=""):
            return build_summary_diagnostics("fixture", self.private, "https://private.example/lesson?token=PAGE_SYNTHETIC",
                TaskOptions(use_saved_connection=False, llm_base_url="https://private.example/api?token=TOKEN_SYNTHETIC"), [], [], "local-template",
                "provider=synthetic;stage=vision_batch;code=api_error;reason=" + self.private,
                llm_events=events, page_context="FULL_SOURCE_SYNTHETIC", frame_extraction_warning=self.private)

    def assert_private_absent(self, value):
        serialized = json.dumps(value, ensure_ascii=False)
        for marker in ("SESSION_SYNTHETIC", "private.example", "TOKEN_SYNTHETIC", "SensitiveBodySynthetic", "PAGE_SYNTHETIC", "FULL_SOURCE_SYNTHETIC"):
            self.assertNotIn(marker, serialized)

    def test_diagnostics_keep_counts_and_fixed_error_categories_without_source_or_body(self):
        diagnostics = self.diagnostics()
        self.assert_private_absent(diagnostics)
        self.assertEqual(diagnostics["llm_last_failure"]["message"], "HTTP 429")
        self.assertEqual(diagnostics["llm_last_failure"]["batch"], 2)
        self.assertEqual(diagnostics["llm_last_failure"]["issue_count"], 1)
        self.assertEqual(diagnostics["page_text_char_count"], len("FULL_SOURCE_SYNTHETIC"))
        self.assertEqual(diagnostics, safe_summary_diagnostics(diagnostics))

    def test_bare_provider_warning_is_not_persisted_or_exposed_as_legacy_text(self):
        self.isolated_tasks()
        task = create_task("local", "Synthetic")
        warning = "PRIVATE_BODY_SENTINEL lecture paragraph without any credential marker"
        record = update_task(task.id, summary_source="text-llm", summary_warning=warning)
        self.assertNotIn("PRIVATE_BODY_SENTINEL", record.summary_warning)
        path = task_dir(task.id) / "task.json"
        self.assertNotIn("PRIVATE_BODY_SENTINEL", path.read_text(encoding="utf-8"))
        legacy = record.model_copy(update={"summary_warning": warning})
        self.assertNotIn("PRIVATE_BODY_SENTINEL", public_summary_task(legacy).summary_warning)
        self.assertEqual(legacy.summary_warning, warning)
        internal = "缺少可信视频证据；结果仅基于页面文本和未经媒体校验的浏览器字幕线索。；3 条内容待回源核对，已在正文标记"
        self.assertEqual(safe_summary_warning(internal), internal)
        self.assertNotIn("PRIVATE_BODY_SENTINEL", safe_summary_warning(internal + "；" + warning))

    def test_local_success_and_unknown_events_are_not_reported_as_provider_failures(self):
        with patch("app.summary_diagnostics.LLM_API_KEY", ""):
            diagnostics = build_summary_diagnostics("fixture", "Synthetic", "", TaskOptions(use_saved_connection=False,
                llm_model="fixture-model", note_style="study"), [], [], "offline-fixture", "", llm_events=[
                    {"stage": "summary", "code": "offline_fixture"},
                    {"stage": "vision_batch", "code": "future_local_success"}])
        self.assertEqual(diagnostics["llm_events"][0], {"stage": "summary", "code": "offline_fixture"})
        self.assertEqual(diagnostics["llm_events"][1]["code"], "unclassified")
        self.assertEqual(diagnostics["llm_last_failure"], {})
        self.assertEqual(diagnostics["vision_failed_batch_count"], 0)
        self.assertEqual(diagnostics["llm_event_count"], 2)
        self.assertEqual(diagnostics["llm_model"], "fixture-model")
        self.assertEqual(diagnostics["summary_source"], "offline-fixture")
        self.assertIn("llm_provider", diagnostics)

    def test_new_json_and_task_diagnostic_writes_apply_the_same_projection(self):
        self.isolated_tasks()
        task = create_task("local", "Synthetic")
        value = self.diagnostics()
        value.update({"page_url": self.private, "title": self.private,
            "provider_body": {"message": self.private}, "llm_events": [{"stage": "text_summary", "code": "api_error", "message": self.private}]})
        original = json.loads(json.dumps(value))
        source = write_json(task.id, "transcript_raw.json", {"text": self.private})
        source_bytes = source.read_bytes()
        path = write_json(task.id, "summary_diagnostics.json", value)
        record = update_task(task.id, summary_diagnostics=value, summary_warning="provider=synthetic;reason=" + self.private,
            error_code="summary_unavailable", message=self.private, error_detail=self.private)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assert_private_absent(persisted)
        self.assertEqual(persisted, record.summary_diagnostics)
        self.assert_private_absent(json.loads((task_dir(task.id) / "task.json").read_text(encoding="utf-8")))
        self.assertEqual(value, original)
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_legacy_summary_diagnostics_are_redacted_in_payload_and_actual_zip_members(self):
        self.isolated_tasks()
        task = create_task("local", "Synthetic")
        note = task_dir(task.id) / "note.md"
        note.write_text("# Synthetic\n\n正常中文 English 🧭。", encoding="utf-8")
        update_task(task.id, note_path=str(note))
        path = task_dir(task.id) / "task.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["summary_diagnostics"] = {"page_url": self.private,
            "llm_events": [{"stage": "text_summary", "code": "api_error", "message": self.private}],
            "llm_last_failure": {"stage": "text_summary", "code": "api_error", "message": self.private},
            "llm_failure_reason": self.private, "page_text_char_count": 24}
        payload["summary_warning"] = "provider=synthetic;reason=" + self.private
        payload.update(error_code="summary_unavailable", message="SensitiveBodySynthetic", error_detail="SensitiveBodySynthetic")
        path.write_text(json.dumps(payload), encoding="utf-8")
        original = path.read_bytes()
        task = get_task(task.id)
        with patch("app.main.TASK_DIR", path.parent.parent):
            public = task_payload(task)
            self.assert_private_absent(public["summary_diagnostics"])
            self.assert_private_absent(public["summary_warning"])
            self.assert_private_absent(public["message"])
            self.assert_private_absent(public["error_detail"])
            for exporter in (api_export_bundle, api_export_support_package):
                response = exporter(task.id)
                with ZipFile(BytesIO(response.body)) as archive:
                    for name in archive.namelist():
                        self.assert_private_absent(archive.read(name).decode("utf-8"))
                    if exporter is api_export_bundle:
                        diagnostics = json.loads(archive.read("summary_diagnostics.json"))
                        self.assertEqual(diagnostics["page_text_char_count"], 24)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(task.summary_diagnostics, payload["summary_diagnostics"])
        self.assertIn("正常中文 English 🧭", note.read_text(encoding="utf-8"))

    def test_support_package_redacts_credentials_at_the_final_serialization_boundary(self):
        from app.models import ResourceCandidate
        self.isolated_tasks()
        task = create_task("local", "Synthetic", "https://source.example/lesson?v=public&token=SOURCE_TOKEN_SYNTHETIC")
        update_task(task.id, error_detail="Cookie: ERROR_COOKIE_SYNTHETIC", selected_resource=ResourceCandidate(
            url="https://media.example/file.mp4?token=MEDIA_TOKEN_SYNTHETIC", kind="video"))
        events = task_dir(task.id) / "events.jsonl"
        events.write_text(json.dumps({"timestamp": "2026-10-09T10:00:00Z", "event": "synthetic_failure", "phase": "summarizing",
            "message": "Authorization: Bearer EVENT_TOKEN_SYNTHETIC SensitiveBodySynthetic", "details": {"progress": 40, "cookie": "DETAIL_SECRET_SYNTHETIC"}}) + "\n", encoding="utf-8")
        original_task = (task_dir(task.id) / "task.json").read_bytes()
        original_events = events.read_bytes()
        direct = api_export_diagnostics(task.id).body.decode("utf-8")
        for marker in ("SOURCE_TOKEN_SYNTHETIC", "ERROR_COOKIE_SYNTHETIC", "MEDIA_TOKEN_SYNTHETIC"):
            self.assertNotIn(marker, direct)
        response = api_export_support_package(task.id)
        with ZipFile(BytesIO(response.body)) as archive:
            for name in archive.namelist():
                body = archive.read(name).decode("utf-8")
                for marker in ("SOURCE_TOKEN_SYNTHETIC", "ERROR_COOKIE_SYNTHETIC", "MEDIA_TOKEN_SYNTHETIC", "EVENT_TOKEN_SYNTHETIC", "SensitiveBodySynthetic", "DETAIL_SECRET_SYNTHETIC"):
                    self.assertNotIn(marker, body, name)
            self.assertIn("https://source.example/lesson?v=public", archive.read("diagnostics.md").decode())
            rows = json.loads(archive.read("events.json"))
            self.assertEqual(rows[0]["event"], "synthetic_failure")
            self.assertEqual(rows[0]["details"]["progress"], 40)
        self.assertEqual(events.read_bytes(), original_events)
        self.assertEqual((task_dir(task.id) / "task.json").read_bytes(), original_task)

    def test_unrelated_task_updates_do_not_rewrite_existing_diagnostics(self):
        self.isolated_tasks()
        task = create_task("local", "Synthetic")
        path = task_dir(task.id) / "task.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["summary_diagnostics"] = {"historical_fixture": self.private}
        path.write_text(json.dumps(payload), encoding="utf-8")
        diagnostic_path = task_dir(task.id) / "summary_diagnostics.json"
        diagnostic_path.write_text(json.dumps(payload["summary_diagnostics"]), encoding="utf-8")
        original = diagnostic_path.read_bytes()
        record = update_task(task.id, progress=30)
        self.assertEqual(record.summary_diagnostics, payload["summary_diagnostics"])
        self.assertEqual(diagnostic_path.read_bytes(), original)
