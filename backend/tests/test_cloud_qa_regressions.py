"""Offline regressions discovered by real cloud runs, including actual audio decoding."""
from contextlib import ExitStack
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from app.main import app, local_upload_filename, _existing_local_task_for_fingerprint
from app.models import MediaIntegrity, TaskOptions, TaskRecord
from app.library import _safe_material_filename, material_content
from app.routers.notes import _edition_path, get_edition, put_edition, EditionRequest
from app.transcriber import transcript_from_subtitle


class ImportRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("app.library", "app.knowledge", "app.routers.library"):
            self.stack.enter_context(patch(f"{module}.DATA_DIR", self.root))
        self.client = TestClient(app)

    def test_long_ascii_and_multibyte_filenames_keep_extension_and_roundtrip(self):
        for filename in ("a" * 190 + ".txt", "学" * 90 + ".md", "📝" * 80 + ".markdown"):
            with self.subTest(filename=filename[:20]):
                text = "# 本地课程\n\n保留导入资料的原文。" + filename[:2]
                response = self.client.post("/api/library/materials/import", files={"file": (filename, text.encode(), "text/plain")})
                self.assertEqual(response.status_code, 200, response.text)
                record = response.json()["material"]
                self.assertEqual(Path(record["filename"]).suffix, Path(filename).suffix)
                self.assertLessEqual(len(record["filename"].encode()), 201)
                self.assertIn("保留导入资料的原文", material_content(record["material_id"]))
                repeated = self.client.post("/api/library/materials/import", files={"file": (filename, text.encode(), "text/plain")})
                self.assertEqual(repeated.json()["material"]["material_id"], record["material_id"])

    def test_filename_still_sanitizes_reserved_names_and_separators(self):
        self.assertEqual(_safe_material_filename("CON.txt"), "_CON.txt")
        self.assertNotIn("\\", _safe_material_filename("folder\\lesson.md"))
        self.assertEqual(_safe_material_filename("../lesson.md"), "lesson.md")

    def test_corrupt_pdf_reports_file_problem_not_missing_dependency(self):
        response = self.client.post("/api/library/materials/import", files={"file": ("broken.pdf", b"%PDF-1.4\nnot a PDF document", "application/pdf")})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "pdf_file_invalid")
        self.assertIsNone(response.json()["detail"]["recovery"])

    def test_password_protected_pdf_requests_unlocked_local_copy(self):
        document = PdfWriter()
        document.add_blank_page(width=100, height=100)
        document.encrypt("fixture-password")
        output = BytesIO()
        document.write(output)
        response = self.client.post("/api/library/materials/import", files={"file": ("locked.pdf", output.getvalue(), "application/pdf")})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "pdf_password_required")

    def test_blank_pdf_remains_available_for_optional_ocr(self):
        document = PdfWriter()
        document.add_blank_page(width=100, height=100)
        output = BytesIO()
        document.write(output)
        response = self.client.post("/api/library/materials/import", files={"file": ("scan.pdf", output.getvalue(), "application/pdf")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["material"]["status"], "ocr_required")


class SubtitleTimelineTests(unittest.TestCase):
    def read(self, cues):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lesson.srt"
            path.write_text(cues, encoding="utf-8")
            return transcript_from_subtitle(path)

    def test_repeated_phrase_after_pause_keeps_both_source_locations(self):
        result = self.read("1\n00:00:01,000 --> 00:00:03,000\n重复的课程原话。\n\n2\n00:02:00,000 --> 00:02:03,000\n重复的课程原话。\n")
        self.assertEqual([(row.start, row.end) for row in result.segments], [(1, 3), (120, 123)])
        self.assertEqual(result.full_text.count("重复的课程原话"), 2)

    def test_overlapping_rolling_caption_merges_without_shortening_end(self):
        result = self.read("1\n00:00:01,000 --> 00:00:05,000\n字幕\n\n2\n00:00:02,000 --> 00:00:03,000\n字幕\n\n3\n00:00:04,000 --> 00:00:08,000\n字幕\n")
        self.assertEqual([(row.start, row.end) for row in result.segments], [(1, 8)])

    def test_backwards_time_range_is_not_source_evidence(self):
        result = self.read("1\n00:00:05,000 --> 00:00:02,000\n无效字幕\n\n2\n00:00:06,000 --> 00:00:08,000\n有效字幕\n")
        self.assertEqual(result.full_text, "有效字幕")


class LocalVideoImportTests(unittest.TestCase):
    def test_multibyte_video_filename_fits_staged_and_pending_paths(self):
        name = local_upload_filename("学" * 120 + ".mp4")
        self.assertTrue(name.endswith(".mp4"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ("staged_" + "a" * 32 + "_" + name)
            path.write_bytes(b"local fixture")
            self.assertEqual(path.read_bytes(), b"local fixture")

    def test_same_video_reuses_only_equivalent_processing_options(self):
        digest = "a" * 64
        options = TaskOptions(content_mode="subtitles")
        previous = TaskRecord(id="abc123", source_type="local", status="success", title="Lesson", created_at="2026-10-07T00:00:00Z", updated_at="2026-10-07T00:00:00Z", options=options, media_integrity=MediaIntegrity(sha256=digest))
        with patch("app.main.list_tasks", return_value=[previous]):
            self.assertIs(_existing_local_task_for_fingerprint(digest, options), previous)
            self.assertIsNone(_existing_local_task_for_fingerprint(digest, TaskOptions()))
            self.assertIsNone(_existing_local_task_for_fingerprint(digest, TaskOptions(content_mode="text")))
            self.assertIsNone(_existing_local_task_for_fingerprint(digest, options.model_copy(update={"whisper_model": "tiny"})))

    @unittest.skipUnless(importlib.util.find_spec("faster_whisper"), "optional local ASR not installed")
    def test_installed_asr_decodes_real_wav_without_downloading_a_model(self):
        from faster_whisper.audio import decode_audio
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speech.wav"
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(b"\0\0" * 8000)
            self.assertEqual(len(decode_audio(str(path))), 8000)


class PersonalEditionRecoveryTests(unittest.TestCase):
    def test_damaged_saved_editions_report_conflict_and_preserve_bytes(self):
        for contents in ("[]", "null", "{", json.dumps({"text": "private", "revision": "wrong", "edited": True})):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory, patch("app.routers.notes.DATA_DIR", Path(directory)), patch("app.routers.notes._edition_source", return_value="generated source"):
                path = _edition_path("task", "sample")
                path.parent.mkdir()
                path.write_text(contents, encoding="utf-8")
                for operation in (lambda: get_edition("task", "sample"), lambda: put_edition("task", "sample", EditionRequest(text="new", revision="old"))):
                    with self.assertRaises(HTTPException) as caught:
                        operation()
                    self.assertEqual(caught.exception.status_code, 409)
                    self.assertEqual(path.read_text(encoding="utf-8"), contents)
