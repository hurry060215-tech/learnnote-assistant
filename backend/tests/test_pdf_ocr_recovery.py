"""Synthetic scanned PDFs and substitute recognizers; never load OCR models."""
from contextlib import ExitStack, closing
from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app import config, library
from app.knowledge import evidence_by_ids
from app.main import app
from app.material_ocr import continue_material_ocr, get_material_ocr
from app.pdf_ocr import ocr_pdf


def scan_bytes(count=26):
    output = BytesIO()
    canvas = Canvas(output, pagesize=(32, 32))
    for number in range(1, count + 1):
        image = Image.new("RGB", (32, 32), (number, number, number))
        canvas.drawImage(ImageReader(image), 0, 0, 32, 32)
        canvas.showPage()
    canvas.save()
    return output.getvalue()


class Recognizer:
    def __init__(self, *, fail=(), blank=()):
        self.calls, self.fail, self.blank = [], set(fail), set(blank)

    def __call__(self, image):
        page = int(image[0, 0, 0])
        self.calls.append(page)
        if page in self.fail:
            raise RuntimeError("synthetic private runtime detail")
        if page in self.blank:
            return None, None
        box = [[0, 0], [20, 0], [20, 10], [0, 10]]
        return [[box, f"Synthetic page {page}", 0.92], [box, "Uncertain synthetic line", 0.72]], None


@unittest.skipUnless(importlib.util.find_spec("fitz") and importlib.util.find_spec("numpy"), "Optional PDF rasterization libraries are unavailable")
class PdfOcrRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.multiple(config, DATA_DIR=self.root, UPLOAD_DIR=self.root / "uploads",
                                              TASK_DIR=self.root / "tasks", STATIC_DIR=self.root / "static",
                                              MODEL_CACHE_DIR=self.root / "models", TEMP_DIR=self.root / "temp"))
        for module in ("library", "knowledge", "personal_notes", "routers.notes"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        self.client = TestClient(app)
        self.raw = scan_bytes()
        self.material = library.import_document_material("synthetic-scan.pdf", self.raw, "application/pdf")
        self.id = self.material["material_id"]
        self.endpoint = f"/api/library/materials/{self.id}/ocr"
        self.engine = Recognizer()
        self.stack.enter_context(patch("app.pdf_ocr.ocr_available", return_value=True))
        self.factory = self.stack.enter_context(patch("app.pdf_ocr.create_ocr_engine", side_effect=lambda: self.engine))

    def post(self):
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def sql(self, sql, parameters=()):
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as db, db:
            return db.execute(sql, parameters).fetchall()

    def snapshot(self):
        material = library.get_material(self.id)
        cache = Path(material["metadata"]["ocr_path"])
        return (material, cache.read_bytes(), self.sql("SELECT * FROM source_evidence ORDER BY evidence_id"),
                self.sql("SELECT * FROM source_evidence_fts ORDER BY evidence_id"))

    def test_batches_continue_after_reopen_with_same_ids_confidence_and_original_bytes(self):
        self.assertEqual(library.material_content(self.id), "", "A valid scan must have a reader before OCR")
        self.assertEqual(self.client.get(self.endpoint).json()["ocr"]["status"], "not_started")
        self.factory.assert_not_called()
        first = self.post()
        self.assertEqual(self.engine.calls, list(range(1, 25)))
        self.assertEqual(first["ocr"]["missing_pages"], [25, 26])
        self.assertEqual(first["material"]["status"], "ocr_partial")
        self.assertEqual(first["ocr"]["pages"][0]["confidence"], 0.82)
        self.assertFalse(first["material"]["metadata"]["ocr_verified"])
        original_ids = first["material"]["evidence_ids"]
        original_rows = evidence_by_ids(original_ids)
        self.client = TestClient(app)
        cached = self.client.get(self.endpoint)
        self.assertEqual(cached.status_code, 200)
        self.assertEqual(cached.json()["ocr"]["pages"][0]["lines"][1]["confidence"], 0.72)
        self.assertEqual(self.factory.call_count, 1, "Reading cache must not initialize a recognizer")
        second = self.post()
        self.assertEqual(self.engine.calls, list(range(1, 27)))
        self.assertEqual(second["ocr"]["processed_page_count"], 26)
        self.assertEqual(second["material"]["status"], "ready")
        self.assertEqual(second["material"]["evidence_ids"][:24], original_ids)
        self.assertEqual(evidence_by_ids(original_ids), original_rows)
        self.assertEqual(library.material_source_path(self.id).read_bytes(), self.raw)
        self.assertEqual(second["material"]["sha256"], hashlib.sha256(self.raw).hexdigest())
        self.post()
        self.assertEqual(self.factory.call_count, 2, "Completed OCR is a no-op without model initialization")
        rebuilt = library.rebuild_document_material(self.id)
        self.assertEqual(rebuilt["evidence_ids"], second["material"]["evidence_ids"])
        self.assertFalse(library.material_anchors(self.id)[0]["metadata"]["ocr_verified"])
        self.assertEqual(library.material_anchors(self.id)[0]["metadata"]["ocr_confidence"], 0.82)
        self.assertIn("Synthetic page 26", library.material_content(self.id))

    def test_page_failure_and_blank_page_are_distinguished_and_retry_skips_successes(self):
        self.engine = Recognizer(fail={2}, blank={3})
        first = self.post()
        self.assertEqual(first["ocr"]["missing_pages"], [2, 25, 26])
        self.assertEqual(first["ocr"]["missing_page_ranges"], [[2, 2], [25, 26]])
        self.assertEqual(first["ocr"]["failed_pages"], [2])
        blank = next(page for page in first["ocr"]["pages"] if page["page"] == 3)
        self.assertEqual(blank["text"], "")
        self.assertIsNone(blank["confidence"])
        self.engine.fail.clear()
        second = self.post()
        self.assertEqual(self.engine.calls[24:], [2, 25, 26])
        self.assertEqual(second["ocr"]["status"], "ready")
        self.assertEqual(len(second["ocr"]["pages"]), 26)
        self.assertNotIn("synthetic private runtime detail", json.dumps(second))

    def test_successful_blank_scan_remains_readable_and_does_not_repeat_completed_pages(self):
        self.engine.blank = set(range(1, 27))
        first = self.post()
        self.assertEqual(first["material"]["status"], "ocr_partial")
        self.assertEqual(first["material"]["evidence_ids"], [])
        self.assertEqual(library.material_content(self.id), "")
        second = self.post()
        self.assertEqual(second["ocr"]["status"], "ready")
        self.assertEqual(second["material"]["evidence_ids"], [])
        self.assertEqual(library.material_content(self.id), "")
        self.assertEqual(self.engine.calls, list(range(1, 27)))
        self.post()
        self.assertEqual(len(self.engine.calls), 26)

    def test_legacy_ocr_json_is_read_and_migrated_without_losing_ids_or_unknown_scores(self):
        legacy = {"schema_version": 1, "status": "partial", "engine": "synthetic-legacy", "page_count": 26,
                  "processed_page_count": 1, "missing_page_range": [2, 26],
                  "pages": [{"page": 1, "text": "Legacy synthetic text", "lines": [{"text": "Legacy synthetic text"}]}]}
        initial = library.apply_material_ocr(self.id, legacy)
        cache_path = library.material_source_path(self.id).parent / "ocr.json"
        cache_path.write_text(json.dumps(legacy), encoding="utf-8")
        metadata = {**initial["metadata"], "ocr_path": str(cache_path),
                    "source_revision": hashlib.sha256(json.dumps(legacy, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
        self.sql("UPDATE library_materials SET metadata_json=? WHERE material_id=?", (json.dumps(metadata), self.id))
        cached = get_material_ocr(self.id)
        self.assertIsNone(cached["pages"][0]["confidence"])
        updated = self.post()
        self.assertEqual(self.engine.calls, list(range(2, 26)))
        self.assertEqual(updated["material"]["evidence_ids"][0], initial["evidence_ids"][0])
        self.assertEqual(updated["ocr"]["pages"][0]["text"], "Legacy synthetic text")
        self.assertIsNone(updated["ocr"]["pages"][0]["lines"][0]["confidence"])

    def test_empty_reader_does_not_hide_missing_original_corruption_or_lost_index(self):
        source = library.material_source_path(self.id)
        source.unlink()
        self.assertEqual(self.client.get(f"/api/library/materials/{self.id}/content").status_code, 404)
        source.write_bytes(b"synthetic invalid PDF")
        with self.assertRaises(ValueError):
            library.material_content(self.id)
        source.write_bytes(scan_bytes(1))
        with self.assertRaisesRegex(ValueError, "integrity_mismatch"):
            library.material_content(self.id)
        source.write_bytes(self.raw)
        self.assertEqual(library.material_content(self.id), "")
        self.post()
        self.sql("DELETE FROM source_evidence")
        self.sql("DELETE FROM source_evidence_fts")
        self.assertEqual(self.client.get(f"/api/library/materials/{self.id}/content").status_code, 404)
        library.rebuild_document_material(self.id)
        self.assertIn("Synthetic page 1", library.material_content(self.id))

    def test_bound_is_enforced_and_holey_completed_pages_are_skipped(self):
        source = library.material_source_path(self.id)
        result = ocr_pdf(source, page_limit=99999, completed_pages=[1, 3], engine=self.engine)
        self.assertEqual(len(result["pages"]), 24)
        self.assertEqual(self.engine.calls, [2, *range(4, 27)])

    def test_unavailable_engine_and_entire_batch_failure_retain_cached_results(self):
        self.post()
        before = self.snapshot()
        with patch("app.pdf_ocr.ocr_available", return_value=False):
            response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.snapshot(), before)
        with patch("app.pdf_ocr.create_ocr_engine", side_effect=ValueError("material_private_fixture_path")):
            response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "material_ocr_failed")
        self.assertNotIn("private_fixture_path", response.text)
        self.assertEqual(self.snapshot(), before)
        self.engine.fail = {25, 26}
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "material_ocr_batch_failed")
        self.assertEqual(self.snapshot(), before)
        self.engine.fail.clear()
        self.assertEqual(self.post()["ocr"]["status"], "ready")

    def test_cache_write_failure_and_sql_failure_do_not_destroy_previous_cache_or_evidence(self):
        self.post()
        before = self.snapshot()
        with patch("app.library._atomic_text", side_effect=OSError("fixture disk failure")):
            response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.snapshot(), before)
        self.sql("CREATE TRIGGER fail_ocr_update BEFORE UPDATE ON library_materials BEGIN SELECT RAISE(ABORT, 'synthetic sql failure'); END")
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.snapshot(), before)
        self.sql("DROP TRIGGER fail_ocr_update")
        self.assertEqual(self.post()["ocr"]["status"], "ready")

    def test_interrupted_publication_leaves_prior_revision_readable_and_retryable(self):
        self.post()
        before = self.snapshot()
        write = library._atomic_text
        class Interrupted(BaseException):
            pass
        def interrupt_after_cache(path, content):
            write(path, content)
            raise Interrupted()
        with patch("app.library._atomic_text", side_effect=interrupt_after_cache), self.assertRaises(Interrupted):
            continue_material_ocr(self.id)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(get_material_ocr(self.id)["processed_page_count"], 24)
        self.assertEqual(self.post()["ocr"]["status"], "ready")

    def test_stale_batch_merges_without_replacing_previously_completed_pages(self):
        first = self.post()
        previous = first["ocr"]["pages"][0]
        updated = library.apply_material_ocr(self.id, {"page_count": 26, "pages": [
            {"page": 1, "text": "stale changed recognition", "confidence": 1},
            {"page": 25, "text": "Synthetic continuation", "lines": [{"text": "Unknown confidence", "confidence": None}]},
        ]})
        cached = get_material_ocr(self.id)
        self.assertEqual(cached["pages"][0], previous)
        self.assertEqual(cached["missing_pages"], [26])
        self.assertIsNone(cached["pages"][-1]["lines"][0]["confidence"])
        self.assertEqual(updated["evidence_ids"][:24], first["material"]["evidence_ids"])

    def test_non_finite_recognizer_data_cannot_replace_a_usable_cache(self):
        self.post()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            library.apply_material_ocr(self.id, {"page_count": 26, "pages": [{
                "page": 25, "text": "Invalid synthetic box", "lines": [{
                    "text": "Invalid synthetic box", "confidence": 0.95, "bbox": [[float("nan"), 0]],
                }],
            }]})
        self.assertEqual(self.snapshot(), before)

    def test_changed_source_or_cache_cannot_overwrite_usable_rows(self):
        self.post()
        before = self.snapshot()
        source = library.material_source_path(self.id)
        source.write_bytes(scan_bytes(2))
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.snapshot(), before)
        source.write_bytes(self.raw)
        cache = Path(before[0]["metadata"]["ocr_path"])
        cache.write_text('{"pages":[]}', encoding="utf-8")
        self.assertEqual(self.client.get(self.endpoint).status_code, 422)
        self.assertEqual(self.client.post(self.endpoint).status_code, 422)
        self.assertEqual(self.sql("SELECT * FROM source_evidence ORDER BY evidence_id"), before[2])
        self.assertIn("Synthetic page 1", library.material_content(self.id))

    def test_get_and_post_hide_unknown_exception_paths_and_content(self):
        self.post()
        before = self.snapshot()
        private = r"C:\synthetic-private\lesson.pdf: synthetic-secret-content"
        for method, target in ((self.client.get, "get_material_ocr"), (self.client.post, "continue_material_ocr")):
            for error_type in (ValueError, OSError, sqlite3.OperationalError):
                with self.subTest(method=method.__name__, error=error_type.__name__):
                    with patch(f"app.material_ocr.{target}", side_effect=error_type(private)):
                        response = method(self.endpoint)
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(response.json()["detail"]["code"], "material_ocr_failed")
                    self.assertNotIn("synthetic-private", response.text)
                    self.assertNotIn("synthetic-secret-content", response.text)
                    self.assertNotIn("lesson.pdf", response.text)
        self.assertEqual(self.snapshot(), before)

    def test_missing_and_non_pdf_materials_are_rejected_without_engine(self):
        other = library.import_document_material("synthetic.txt", b"Synthetic text", "text/plain")
        for suffix in ("", "/ocr"):
            self.assertEqual(self.client.get("/api/library/materials/missing" + suffix).status_code, 404)
        response = self.client.post(f"/api/library/materials/{other['material_id']}/ocr")
        self.assertEqual(response.status_code, 422)
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
