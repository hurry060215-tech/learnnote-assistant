"""Pre-extraction ZIP bytes and public contracts, using synthetic artifacts only."""
from __future__ import annotations

from contextlib import ExitStack, chdir
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app import main
from app.models import FrameGrid, TaskRecord


FIXTURE = Path(__file__).parent / "fixtures" / "task_archives_v1.json"
EXPORTS = ("bundle", "sanitized-bundle", "support-package")
CASES = (("bundle", True, False), ("bundle", True, True), ("bundle", False, False),
         ("sanitized-bundle", True, False), ("sanitized-bundle", False, False),
         ("support-package", True, False))
NOTE = "# Synthetic café 中文 🧭\r\n\r\n**【待核对：未找到支持来源】** 保留原文。\r\n"
ANNOTATION = {"id": "synthetic-annotation", "text": "\r\n  const cafe\u0301 = '🧭';\r\n\treturn x;\r\n",
              "quote": "原文", "anchor": {"source_id": "archive-fixture", "target_id": "claim-fixture"}}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def member_bytes(member):
    return member["text"].encode("utf-8") if "text" in member else bytes.fromhex(member["hex"])


def member_content(content):
    try:
        return {"text": content.decode("utf-8")}
    except UnicodeDecodeError:
        return {"hex": content.hex()}


def public_contract():
    schema = main.app.openapi()
    return {
        "paths": {f"/api/tasks/{{task_id}}/exports/{name}": schema["paths"][f"/api/tasks/{{task_id}}/exports/{name}"] for name in EXPORTS},
        "openapi_sha256": digest(schema),
        "task_schema_sha256": digest(TaskRecord.model_json_schema()),
        # FastAPI may retain included routers as lazy route containers. The
        # ordered public operations include their routes on every supported version.
        "routes_sha256": digest([(path, method, operation["operationId"])
                                  for path, methods in schema["paths"].items()
                                  for method, operation in methods.items()
                                  if isinstance(operation, dict) and "operationId" in operation]),
    }


def archive_case(kind, rich, annotations=False):
    """Exercise the legacy handlers and real ZIP file copying with fixed inputs."""
    with tempfile.TemporaryDirectory() as tmp, chdir(tmp), ExitStack() as stack:
        assets = {"artifacts/captions.vtt": b"WEBVTT\r\n\r\n00:00.000 --> 00:03.000\r\nSynthetic\r\n",
                  "artifacts/grid.png": b"synthetic-grid\x00\xff", "artifacts/note.md": NOTE.encode(),
                  "artifacts/task.json.bak": b"untouched-backup", "artifacts/events.jsonl": b"untouched-events"}
        for name, content in assets.items():
            path = Path(name)
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(content)
            os.utime(path, (1780000000, 1780000000))
        task = TaskRecord(id="archive-fixture", title="Synthetic 中文 café 🧭", source_type="local",
                          created_at="2026-10-09T00:00:00+00:00", updated_at="2026-10-09T00:00:00+00:00",
                          note_path="artifacts/note.md", subtitle_path="artifacts/captions.vtt" if rich else "",
                          frame_grids=[FrameGrid(path="artifacts/grid.png", url="/synthetic-grid", start=0, end=3, frame_count=1),
                                       FrameGrid(path="artifacts/missing.png", url="/missing", start=3, end=6, frame_count=1)] if rich else [],
                          summary_diagnostics={"page_text_char_count": 12} if rich else {})
        transcript = {"source": "synthetic", "segments": [{"start": 0, "end": 3, "text": "中文 café 🧭"}]}
        visual_index = {"windows": [{"id": "W001", "text": "合成画面"}]} if rich else {"windows": []}
        history = [{"id": "qa-fixture", "answer": "Synthetic answer", "citations": []}] if rich else []
        claims = {"schema_version": 6, "claims": [{"id": "claim-fixture", "text": "保留待核对文字", "status": "pending_review"}],
                  "counts": {"pending_review": 1}, "quality": {"review_required": True}} if rich else {}
        patches = {"get_task": task, "read_note": NOTE if rich else "", "read_transcript": transcript,
                   "read_visual_index": visual_index, "read_task_qa_history": history, "read_json": claims,
                   "read_resource_inventory": {"candidate_count": 2} if rich else {},
                   "read_page_preflight_report": {"ready": False, "code": "synthetic"} if rich else {},
                   "render_bundle_manifest": {"schema_version": 1, "task": {"id": task.id}},
                   "render_diagnostics_markdown": "Synthetic diagnostics\n", "render_task_audit_markdown": "Synthetic audit\n",
                   "render_visual_windows_markdown": "Synthetic windows\n", "render_qa_history_markdown": "Synthetic QA\n",
                   "read_task_events": [{"event": "synthetic", "message": "Authorization: Bearer SYNTHETIC_PRIVATE", "details": {"progress": 12}}]}
        for name, value in patches.items():
            stack.enter_context(patch.object(main, name, return_value=value))
        stack.enter_context(patch("app.personal_notes.list_annotations", return_value=[ANNOTATION]))
        # ZipFile stores local timestamps. Freeze both generated and file-backed
        # entries so local before/after whole-archive byte comparison is exact.
        stack.enter_context(patch("zipfile.time.localtime", return_value=(2026, 10, 9, 0, 0, 0, 4, 282, 0)))
        exporter = {"bundle": main.api_export_bundle, "sanitized-bundle": main.api_export_sanitized_bundle,
                    "support-package": main.api_export_support_package}[kind]
        response = exporter(task.id, include_annotations=annotations) if kind == "bundle" else exporter(task.id)
        assert {name: Path(name).read_bytes() for name in assets} == assets
        with ZipFile(io.BytesIO(response.body)) as archive:
            snapshot = {"status": response.status_code, "headers": dict(response.headers),
                        "members": [{"name": info.filename, **member_content(archive.read(info)), "compression": info.compress_type}
                                    for info in archive.infolist()]}
        return snapshot, response.body


class TaskArchiveContracts(unittest.TestCase):
    def test_complete_openapi_operation_order_and_task_schema_unchanged(self):
        self.assertEqual(public_contract(), json.loads(FIXTURE.read_text(encoding="utf-8"))["api"])

    def test_actual_member_bytes_order_headers_and_unchanged_source_backups(self):
        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))["archives"]
        for case in CASES:
            with self.subTest(case=case):
                snapshot, _ = archive_case(*case)
                self.assertEqual(snapshot, expected[str(case)])

    def test_missing_task_errors_and_query_validation_keep_http_contract(self):
        client = TestClient(main.app)
        with patch.object(main, "get_task", side_effect=FileNotFoundError):
            for export in EXPORTS:
                response = client.get(f"/api/tasks/missing/exports/{export}")
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Task not found"})
            self.assertEqual(client.get("/api/tasks/missing/exports/bundle?include_annotations=invalid").status_code, 422)

    def test_no_artifacts_and_annotation_default_remain_explicit(self):
        task = TaskRecord(id="empty", title="Synthetic", source_type="local", created_at="fixed", updated_at="fixed")
        with ExitStack() as stack:
            for name, value in {"get_task": task, "read_note": "", "read_transcript": {}, "read_visual_index": {},
                                "read_task_qa_history": [], "read_json": {}, "read_resource_inventory": {},
                                "read_page_preflight_report": {}}.items():
                stack.enter_context(patch.object(main, name, return_value=value))
            client = TestClient(main.app)
            for kind, detail in (("bundle", "Task artifacts not found"), ("sanitized-bundle", "Shareable study artifacts not found")):
                response = client.get(f"/api/tasks/empty/exports/{kind}")
                self.assertEqual((response.status_code, response.json()), (404, {"detail": detail}))
        plain, _ = archive_case("bundle", True)
        personal, _ = archive_case("bundle", True, True)
        self.assertNotIn("personal_annotations.json", [item["name"] for item in plain["members"]])
        member = next(item for item in personal["members"] if item["name"] == "personal_annotations.json")
        self.assertEqual(json.loads(member_bytes(member)), {"schema_version": 2, "task_id": "archive-fixture", "annotations": [ANNOTATION]})

    def test_support_privacy_and_sanitized_member_allowlist(self):
        support, _ = archive_case("support-package", True)
        self.assertEqual([item["name"] for item in support["members"]], ["manifest.json", "events.json", "diagnostics.md", "audit.md"])
        self.assertNotIn(b"SYNTHETIC_PRIVATE", b"".join(member_bytes(item) for item in support["members"]))
        safe, _ = archive_case("sanitized-bundle", True)
        self.assertEqual([item["name"] for item in safe["members"]], ["manifest.json", "note.md", "transcript.json", "visual_index.json", "qa_history.json", "claim_evidence_map.json"])
        self.assertEqual(member_bytes(next(item for item in safe["members"] if item["name"] == "note.md")), NOTE.encode())

    def test_main_file_writer_alias_and_history_filename_stay_patchable(self):
        with patch.object(main, "_write_file_if_exists") as writer, patch.object(main, "QA_HISTORY_FILE", "legacy-qa.json"):
            archive, _ = archive_case("bundle", True)
        self.assertEqual([call.args[1:] for call in writer.call_args_list], [
            ("artifacts/captions.vtt", "subtitles/captions.vtt"),
            ("artifacts/grid.png", "grids/grid.png"), ("artifacts/missing.png", "grids/missing.png")])
        self.assertIn("legacy-qa.json", [item["name"] for item in archive["members"]])

    def test_serializer_imports_without_api_processor_or_storage(self):
        subprocess.run([sys.executable, "-c", "import sys; import app.task_archives; "
                        "assert not {'app.main', 'app.processor', 'app.downloader', 'app.storage', 'app.personal_notes'} & sys.modules.keys()"],
                       check=True, capture_output=True, text=True)

    def test_serializer_uses_only_supplied_data_and_does_not_mutate_it(self):
        from app.task_archives import StudyArchive, build_sanitized_archive
        task = TaskRecord(id="pure", title="Synthetic", source_type="local", created_at="fixed", updated_at="fixed")
        transcript = {"segments": [{"text": "Unmodified café 中文 🧭", "start": 0, "end": 1}]}
        data = StudyArchive(task=task, note=NOTE, transcript=transcript, visual_index={}, qa_history=[], claim_map={})
        original = task.model_dump(mode="json"), json.dumps(transcript)
        with patch("app.storage.get_task", side_effect=AssertionError("Unexpected storage read")):
            content = build_sanitized_archive(data)
        with ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(archive.read("note.md"), NOTE.encode())
            self.assertEqual(json.loads(archive.read("transcript.json")), transcript)
        self.assertEqual((task.model_dump(mode="json"), json.dumps(transcript)), original)


if __name__ == "__main__":
    unittest.main()
