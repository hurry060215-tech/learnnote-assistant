"""Recover real local document projections while keeping canonical references."""
from contextlib import ExitStack, closing
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from app import config, library
from app.knowledge import evidence_by_ids, search_evidence
from app.main import app
from app.models import StudyCard
from app.study import export_study_data, save_cards


def pdf_bytes(text="gradient first page"):
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(50, 750, text)
    canvas.showPage()
    canvas.drawString(50, 750, "gradient second page")
    canvas.save()
    return output.getvalue()


class MaterialRebuildTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.multiple(config, DATA_DIR=self.root, UPLOAD_DIR=self.root / "uploads",
                                              TASK_DIR=self.root / "tasks", STATIC_DIR=self.root / "static",
                                              MODEL_CACHE_DIR=self.root / "models", TEMP_DIR=self.root / "temp"))
        for module in ("library", "knowledge", "study"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        self.stack.enter_context(patch("app.library.TASK_DIR", self.root / "tasks"))

    def sql(self, command, parameters=()):
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as db, db:
            return db.execute(command, parameters).fetchall()

    def erase_evidence(self, material):
        for key in material["evidence_ids"]:
            self.sql("DELETE FROM source_evidence WHERE evidence_id=?", (key,))
            self.sql("DELETE FROM source_evidence_fts WHERE evidence_id=?", (key,))

    def test_document_formats_restore_exact_anchors_search_and_card_backlinks(self):
        inputs = [("lesson.txt", b"gradient first\n\ngradient second", "text/plain"),
                  ("lesson.md", b"# gradient first\n\ngradient second", "text/markdown"),
                  ("lesson.html", b"<p>gradient first</p><p>gradient second</p>", "text/html"),
                  ("lesson.pdf", pdf_bytes(), "application/pdf")]
        for filename, raw, mime in inputs:
            with self.subTest(filename=filename):
                material = library.import_document_material(filename, raw, mime)
                anchors = library.material_anchors(material["material_id"])
                card = save_cards([StudyCard(front=filename, back="answer", source_evidence_ids=material["evidence_ids"])])[0]
                before_study = export_study_data()
                self.erase_evidence(material)
                self.assertEqual(library.material_anchors(material["material_id"]), [])
                repaired = library.rebuild_document_material(material["material_id"])
                restored = library.material_anchors(material["material_id"])
                self.assertEqual([(x["evidence_id"], x["locator"], x["text"]) for x in restored],
                                 [(x["evidence_id"], x["locator"], x["text"]) for x in anchors])
                self.assertEqual(repaired["evidence_ids"], material["evidence_ids"])
                self.assertEqual(library.material_source_path(material["material_id"]).read_bytes(), raw)
                after_study = export_study_data()
                before_study.pop("exported_at", None)
                after_study.pop("exported_at", None)
                self.assertEqual(after_study, before_study)
                self.assertEqual(len(evidence_by_ids(card.source_evidence_ids)), len(anchors))
                self.assertTrue(set(material["evidence_ids"]) <= {x["evidence_id"] for x in search_evidence("gradient", 100)})

    def test_rebuild_recreates_missing_evidence_tables_with_original_encoding(self):
        raw = "课程编码：学习率决定步长。".encode("gb18030")
        material = library.import_document_material("课程.txt", raw, "text/plain", encoding="gb18030")
        self.sql("DROP TABLE source_evidence_fts")
        self.sql("DROP TABLE source_evidence")
        repaired = library.rebuild_document_material(material["material_id"])
        self.assertEqual(repaired["evidence_ids"], material["evidence_ids"])
        self.assertEqual(library.material_anchors(material["material_id"])[0]["text"], raw.decode("gb18030"))
        self.assertEqual(repaired["metadata"]["encoding"], "gb18030")

    def test_rebuild_uses_verified_cached_ocr_without_rerunning_recognition(self):
        material = library.import_document_material("scan.pdf", pdf_bytes(), "application/pdf")
        material = library.apply_material_ocr(material["material_id"], {
            "engine": "synthetic-local-fixture", "pages": [{"page": 1, "text": "gradient OCR", "confidence": 0.8}],
            "missing_page_range": [2, 2], "page_count": 2, "processed_page_count": 1,
        })
        self.erase_evidence(material)
        with patch("app.pdf_ocr.ocr_pdf", side_effect=AssertionError("OCR must not run during index repair")):
            repaired = library.rebuild_document_material(material["material_id"])
        self.assertEqual(repaired["status"], "ocr_partial")
        self.assertFalse(repaired["metadata"]["ocr_verified"])
        self.assertEqual(repaired["evidence_ids"], material["evidence_ids"])
        self.assertEqual(library.material_anchors(material["material_id"])[0]["text"], "gradient OCR")

    def test_changed_original_and_changed_ocr_cache_preserve_existing_rows(self):
        material = library.import_document_material("lesson.txt", b"gradient original", "text/plain")
        before = self.sql("SELECT * FROM source_evidence")
        library.material_source_path(material["material_id"]).write_bytes(b"different bytes")
        with self.assertRaisesRegex(ValueError, "integrity_mismatch"):
            library.rebuild_document_material(material["material_id"])
        self.assertEqual(self.sql("SELECT * FROM source_evidence"), before)
        scan = library.import_document_material("scan.pdf", pdf_bytes(), "application/pdf")
        scan = library.apply_material_ocr(scan["material_id"], {"pages": [{"page": 1, "text": "OCR text"}]})
        before = self.sql("SELECT * FROM source_evidence")
        Path(scan["metadata"]["ocr_path"]).write_text('{"pages":[]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ocr_cache_invalid"):
            library.rebuild_document_material(scan["material_id"])
        self.assertEqual(self.sql("SELECT * FROM source_evidence"), before)

    def test_foreign_evidence_identity_and_sql_failure_roll_back(self):
        material = library.import_document_material("lesson.txt", b"gradient first\n\ngradient second", "text/plain")
        original = self.sql("SELECT * FROM source_evidence ORDER BY evidence_id")
        self.sql("UPDATE source_evidence SET task_id='other-task' WHERE evidence_id=?", (material["evidence_ids"][1],))
        before = self.sql("SELECT * FROM source_evidence ORDER BY evidence_id")
        with self.assertRaisesRegex(ValueError, "identity_invalid"):
            library.rebuild_document_material(material["material_id"])
        self.assertEqual(self.sql("SELECT * FROM source_evidence ORDER BY evidence_id"), before)
        self.sql("UPDATE source_evidence SET task_id='' WHERE evidence_id=?", (material["evidence_ids"][1],))
        self.sql("CREATE TRIGGER reject_material_rebuild BEFORE UPDATE ON library_materials BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            library.rebuild_document_material(material["material_id"])
        self.assertEqual(self.sql("SELECT * FROM source_evidence ORDER BY evidence_id"), original)
        self.assertNotIn("reindexed_at", library.get_material(material["material_id"])["metadata"])

    def test_http_repair_and_missing_source_report_the_real_outcome(self):
        material = library.import_document_material("lesson.txt", b"gradient source", "text/plain")
        self.erase_evidence(material)
        client = TestClient(app)
        endpoint = f"/api/library/materials/{material['material_id']}/rebuild"
        response = client.post(endpoint)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["material"]["evidence_ids"], material["evidence_ids"])
        source = library.material_source_path(material["material_id"])
        source.rename(source.with_suffix(".unavailable"))
        response = client.post(endpoint)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "material_source_missing")
        self.assertEqual(client.post("/api/library/materials/missing/rebuild").status_code, 404)

    def test_concurrent_material_update_is_not_overwritten(self):
        material = library.import_document_material("lesson.txt", b"gradient source", "text/plain")
        original_extract = library._material_sections
        def extract_then_change(*args, **kwargs):
            result = original_extract(*args, **kwargs)
            self.sql("UPDATE library_materials SET updated_at='newer-operation' WHERE material_id=?", (material["material_id"],))
            return result
        before = self.sql("SELECT * FROM source_evidence")
        with patch("app.library._material_sections", side_effect=extract_then_change), self.assertRaisesRegex(ValueError, "changed_reload_required"):
            library.rebuild_document_material(material["material_id"])
        self.assertEqual(library.get_material(material["material_id"])["updated_at"], "newer-operation")
        self.assertEqual(self.sql("SELECT * FROM source_evidence"), before)


if __name__ == "__main__":
    unittest.main()
