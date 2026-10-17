"""Content-free local exports with synthetic hostile/legacy fixtures only."""
from contextlib import ExitStack
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from app import main, storage
from app.diagnostic_report import build_report, render_markdown, project_events
from app.document_exports import _diagnostic_summary_markdown
from app.models import TaskOptions, TaskRecord


class DiagnosticReportTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.tasks = self.root / "tasks"
        self.directory = self.tasks / "abc123def456"
        self.directory.mkdir(parents=True)
        self.stack.enter_context(patch.object(storage, "TASK_DIR", self.tasks))
        self.task = TaskRecord(id=self.directory.name, title="PRIVATE_TITLE_MARKER", source_type="local",
            status="failed", phase="failed", error_code="summary_unavailable", created_at="private-time", updated_at="private-time",
            options=TaskOptions(content_mode="text", transcriber="faster-whisper", whisper_model="small"))
        self.write("task.json", self.task.model_dump(mode="json"))
        self.stack.enter_context(patch.object(main, "get_task", return_value=self.task))
        self.client = TestClient(main.app)

    def write(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def transcript(self, source="faster-whisper"):
        self.task.transcript_path = str(self.write("transcript.json", {"source": source,
            "full_text": "PRIVATE_TRANSCRIPT_MARKER", "segments": [{"start": 0, "end": 1, "text": "PRIVATE_SEGMENT_MARKER"}]}))

    def state(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob("*") if path.is_file() and not path.is_symlink()}

    def test_legacy_unknowns_distinguish_current_version_and_never_write(self):
        before = self.state()
        result = build_report(self.task)
        self.assertEqual(result["versions"]["current_app"], "0.2.15")
        self.assertIsNone(result["versions"]["task_run_app"])
        self.assertIsNone(result["versions"]["build_revision"])
        self.assertEqual(result["timings"], {"availability": "not_recorded", "attempts": []})
        for key in ("request_count", "input_tokens", "output_tokens", "total_tokens", "cost"):
            self.assertIsNone(result["model"][key])
        self.assertIsNone(result["asr"]["observed_source"])
        self.assertIsNone(result["resummary"]["saved_transcript_usable"])
        self.assertIn("未知", render_markdown(result))
        self.assertEqual(self.state(), before)

    def test_all_export_boundaries_exclude_hostile_content_including_names(self):
        markers = ["PRIVATE_TITLE_MARKER", "PRIVATE_TRANSCRIPT_MARKER", "PRIVATE_SEGMENT_MARKER", "PRIVATE_PROMPT_MARKER",
            "sk-PRIVATEKEYMARKER", "COOKIE_PRIVATE_MARKER", "BEARER_PRIVATE_MARKER", "PRIVATE_QUERY_MARKER",
            "PRIVATE_ACCOUNT_MARKER", "PRIVATE_DEVICE_MARKER", "PRIVATE_PROFILE_MARKER", "PRIVATE_ERROR_MARKER"]
        raw = " ".join(markers) + " https://source.example/private?token=PRIVATE_QUERY_MARKER C:\\Users\\PRIVATE_ACCOUNT_MARKER /home/PRIVATE_ACCOUNT_MARKER"
        self.task.page_url = "https://source.example/private?ordinary=PRIVATE_QUERY_MARKER"
        self.task.error_detail = self.task.message = self.task.summary_warning = raw
        self.task.source_media_path = "/home/PRIVATE_ACCOUNT_MARKER/private.mp4"
        self.task.options.llm_model = self.task.options.whisper_model = raw
        self.task.options.transcriber = raw
        self.task.options.llm_api_key = "sk-PRIVATEKEYMARKER"
        self.task.options.note_profile_name = "PRIVATE_PROFILE_MARKER"
        self.transcript(raw)
        self.task.summary_diagnostics = {"llm_model": raw, "llm_provider": raw, "llm_base_host": raw,
            "llm_failure_code": raw, "llm_failure_stage": raw, "device": raw, "profile": raw,
            "note_quality": {"issues": [{"code": "PRIVATE_ACCOUNT_MARKER", "message": raw}]},
            "llm_last_failure": {"stage": raw, "code": raw, "message": raw},
            "llm_events": [{"stage": "grounding_validation", "code": "rejected", "message": raw,
                "issues": ["unsupported_terms:" + raw], "prompt": raw, "duration_ms": float("inf"), "account": 123456789}]}
        self.write("events.jsonl", {"message": raw})
        before = self.state()
        with patch.object(main, "read_task_events", side_effect=AssertionError("raw events are not a support export")), \
             patch.object(main, "render_task_audit_markdown", side_effect=AssertionError("raw audit is not a support export")):
            responses = [self.client.get(f"/api/tasks/{self.task.id}/exports/diagnostics"),
                         self.client.get(f"/api/tasks/{self.task.id}/exports/diagnostics?format=json"),
                         self.client.get(f"/api/tasks/{self.task.id}/exports/support-package")]
        texts = [_diagnostic_summary_markdown(self.task)]
        for response in responses:
            self.assertEqual(response.status_code, 200, response.text if response.headers["content-type"] != "application/zip" else "zip")
            texts.append(str(response.headers))
            if response.headers["content-type"] == "application/zip":
                with ZipFile(BytesIO(response.content)) as archive:
                    self.assertEqual(archive.namelist(), ["manifest.json", "events.json", "diagnostics.md", "audit.md"])
                    texts += [archive.read(name).decode() for name in archive.namelist()]
            else:
                texts.append(response.text)
        for text in texts:
            for marker in markers + [self.task.id, "https://", "C:\\Users", "/home/", "source.example", "account"]:
                self.assertNotIn(marker, text)
        self.assertEqual(self.state(), before)

    def test_route_contract_same_snapshot_and_generic_names(self):
        report = build_report(self.task)
        markdown = self.client.get(f"/api/tasks/{self.task.id}/exports/diagnostics")
        structured = self.client.get(f"/api/tasks/{self.task.id}/exports/diagnostics?format=json")
        self.assertEqual(structured.json(), report)
        self.assertEqual(markdown.text, render_markdown(structured.json()))
        self.assertIn('filename="learnnote-diagnostics.md"', markdown.headers["content-disposition"])
        self.assertIn('filename="learnnote-diagnostics.json"', structured.headers["content-disposition"])
        self.assertEqual(markdown.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get(f"/api/tasks/{self.task.id}/exports/diagnostics?format=unsafe").status_code, 422)
        with patch.object(main, "get_task", side_effect=FileNotFoundError):
            self.assertEqual(self.client.get("/api/tasks/missing/exports/diagnostics").status_code, 404)

    def test_canonical_timings_win_over_stale_copy_with_attempts_bound(self):
        self.task.summary_diagnostics = {"pipeline_metrics": {"stages": {"summary": {"duration_ms": 9999}}}}
        attempts = [{"attempt_id": f"PRIVATE_ATTEMPT_{i}", "status": "completed", "started_at_unix_ms": 123456,
            "stages": {"verify": {"attempt_id": f"PRIVATE_ATTEMPT_{i}", "duration_ms": 20 + i, "status": "completed"},
                       "summary": {"attempt_id": "foreign", "duration_ms": 100, "status": "completed"},
                       "download": {"attempt_id": f"PRIVATE_ATTEMPT_{i}", "duration_ms": 0, "status": "skipped"},
                       "vision": {"attempt_id": f"PRIVATE_ATTEMPT_{i}", "duration_ms": True, "status": "failed"}}} for i in range(25)]
        self.write("pipeline_metrics.json", {"schema_version": 2, "current_attempt_id": "PRIVATE_ATTEMPT_24", "attempts": attempts})
        before = self.state()
        report = build_report(self.task)
        result = report["timings"]
        self.assertEqual(len(result["attempts"]), 20)
        self.assertEqual(result["attempts"][0]["position"], 1)
        self.assertIn("最近 20 次已记录尝试，position 仅为本报告内顺序", " ".join(report["limits"]))
        self.assertTrue(result["attempts"][-1]["current"])
        self.assertEqual(result["attempts"][-1]["position"], 20)
        stages = {row["stage"]: row for row in result["attempts"][-1]["stages"]}
        self.assertEqual(stages["verify"]["duration_ms"], 44)
        self.assertIsNone(stages["download"]["duration_ms"])
        self.assertIsNone(stages["vision"]["duration_ms"])
        self.assertNotIn("summary", stages)
        self.assertNotIn("PRIVATE_ATTEMPT", json.dumps(result))
        self.assertNotIn("123456", json.dumps(result))
        self.assertEqual(self.state(), before)

    def test_legacy_schema_one_does_not_invent_attempt_completion(self):
        self.write("pipeline_metrics.json", {"schema_version": 1, "stages": {"transcript": {"duration_ms": 12, "status": "completed"}}})
        row = build_report(self.task)["timings"]["attempts"][0]
        self.assertIsNone(row["status"])
        self.assertIsNone(row["current"])
        self.assertEqual(row["stages"][0]["duration_ms"], 12)

    def test_invalid_missing_oversized_and_symlink_reports_fail_closed(self):
        path = self.directory / "pipeline_metrics.json"
        for content in (b"{", b"[]", b'{"schema_version":99}', b" " * (256 * 1024 + 1)):
            path.write_bytes(content)
            before = self.state()
            self.assertEqual(build_report(self.task)["timings"], {"availability": "unavailable", "attempts": []})
            self.assertEqual(self.state(), before)
        path.unlink()
        outside = self.root / "foreign.json"; outside.write_text('{"schema_version":1,"stages":{}}')
        path.symlink_to(outside)
        with patch.object(Path, "open", side_effect=AssertionError("Must not open linked file")):
            self.assertEqual(build_report(self.task)["timings"]["availability"], "unavailable")
        path.unlink()
        self.directory.rename(self.directory.with_name("renamed"))
        self.assertEqual(build_report(self.task)["timings"]["availability"], "not_recorded")
        self.assertFalse(self.directory.exists())

    def test_foreign_saved_transcript_is_not_probed_and_missing_stays_unknown(self):
        outside = self.root / "old" / "transcript.json"
        self.task.transcript_path = str(outside)
        with patch.object(Path, "open", side_effect=AssertionError("Foreign path must not be opened")):
            result = build_report(self.task)
        self.assertEqual(result["resummary"]["transcript_record"], "unavailable")
        self.assertIsNone(result["resummary"]["saved_transcript_usable"])

    def test_asr_configuration_is_distinct_from_observed_subtitle_and_resume(self):
        self.transcript("embedded-subtitle")
        result = build_report(self.task)
        self.assertEqual(result["asr"]["configured_method"], "faster-whisper")
        self.assertEqual(result["asr"]["observed_source"], "embedded-subtitle")
        self.assertIsNone(result["asr"]["observed_model"])
        self.assertTrue(result["resummary"]["saved_transcript_usable"])
        self.assertTrue(result["resummary"]["text_retry_supported"])
        self.transcript("screen-ocr")
        self.assertTrue(build_report(self.task)["resummary"]["requires_media_validation"])
        self.write("transcript.json", {"source": "faster-whisper", "full_text": ""})
        self.assertFalse(build_report(self.task)["resummary"]["saved_transcript_usable"])

    def test_grounding_failure_preserves_codes_chunks_and_terminal_event(self):
        rows = [{"stage": "vision_cache", "code": "cache_hit"}] * 24
        rows += [{"stage": "grounding_repair", "code": "api_error", "repair_outcome": "api_error", "message": "PRIVATE_429"},
            {"stage": "grounding_validation", "code": "rejected", "issue_codes": ["unsupported_terms", "unsupported_quantity", "private"],
             "chunk_index": 2, "chunk_count": 8, "completed_chunks": 1, "request_stage": "text_summary", "repair_outcome": "rejected"}]
        events = project_events(rows)
        self.assertEqual(len(events), 20)
        self.assertEqual(events[-1]["completed_chunks"], 1)
        self.assertEqual(events[-1]["issue_codes"], ["unsupported_quantity", "unsupported_terms"])
        self.assertEqual(events[-2]["repair_outcome"], "api_error")
        self.assertNotIn("PRIVATE", json.dumps(events))
        self.assertEqual(project_events(events), events)

    def test_defaulted_options_are_not_historical_configuration_and_auto_is_supported(self):
        legacy = self.task.model_dump(mode="json")
        legacy.pop("options")
        report = build_report(TaskRecord.model_validate(legacy))
        self.assertIsNone(report["asr"]["configured_method"])
        self.assertIsNone(report["asr"]["configured_model"])
        self.assertIsNone(report["resummary"]["requires_text_mode"])
        self.assertIsNone(report["resummary"]["requires_media_validation"])
        self.task.options = TaskOptions(content_mode="auto", transcriber="faster-whisper", whisper_model="small")
        self.transcript()
        self.assertFalse(build_report(self.task)["resummary"]["requires_text_mode"])

    def test_numeric_projection_rejects_huge_nonfinite_boolean_and_wrong_types(self):
        for invalid in (10**1000, float("inf"), float("nan"), True, "12", -1):
            with self.subTest(value=repr(invalid)[:30]):
                event = project_events([{"stage": "vision_batch", "code": "api_error", "duration_ms": invalid}])[0]
                self.assertNotIn("duration_ms", event)
                self.write("pipeline_metrics.json", {"schema_version": 1, "stages": {"transcript": {"status": "completed", "duration_ms": invalid}}})
                self.assertIsNone(build_report(self.task)["timings"]["attempts"][0]["stages"][0]["duration_ms"])

    def test_error_categories_require_exact_known_values_never_reparse_prose(self):
        for raw, expected in (("HTTP 429", "HTTP 429"), ("timeout", "timeout"),
                              ("provider_error", "provider_error"), ("PRIVATE HTTP 429", None),
                              ("sk-PRIVATESECRET", None), ("legacy custom error", None)):
            self.task.summary_diagnostics = {"llm_failure_reason": raw,
                "llm_events": [{"stage": "text_summary", "code": "api_error", "message": raw}]}
            report = build_report(self.task)
            self.assertEqual(report["model"]["failure_category"], expected)
            self.assertEqual(report["model"]["events"][0].get("error_category"), expected)
            self.assertEqual(project_events(report["model"]["events"]), report["model"]["events"])
            if expected is None:
                self.assertNotIn(raw, json.dumps(report))

    def test_document_subset_preserves_known_codes_not_arbitrary_identifiers(self):
        self.task.summary_source = "text-llm"
        self.task.summary_diagnostics = {"note_quality": {"issues": [{"code": "internal_prompt_leak"}, {"code": "PRIVATE_PROFILE"}]}}
        result = _diagnostic_summary_markdown(self.task)
        self.assertIn("internal_prompt_leak", result)
        self.assertIn("text-llm", result)
        self.assertNotIn("PRIVATE", result)

    def test_caption_and_selected_range_sources_require_exact_internal_enums(self):
        for source in ("subtitle-extract", "screen-ocr-extract"):
            self.task.summary_source = source
            self.assertEqual(build_report(self.task)["task"]["summary_source"], source)
            self.assertIn(source, _diagnostic_summary_markdown(self.task))
            self.task.summary_source = source + "-PRIVATE"
            self.assertIsNone(build_report(self.task)["task"]["summary_source"])
            self.assertNotIn("PRIVATE", _diagnostic_summary_markdown(self.task))
        self.transcript("selected-range-source-subtitle")
        report = build_report(self.task)
        self.assertEqual(report["asr"]["observed_source"], "selected-range-source-subtitle")
        self.assertTrue(report["resummary"]["text_retry_supported"])
        self.transcript("selected-range-source-subtitle-PRIVATE")
        report = build_report(self.task)
        self.assertIsNone(report["asr"]["observed_source"])
        self.assertIsNone(report["resummary"]["text_retry_supported"])


if __name__ == "__main__":
    unittest.main()
