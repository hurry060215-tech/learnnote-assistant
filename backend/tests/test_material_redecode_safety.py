"""Real local re-decoding API, preserved bytes and stale-reader preconditions."""
from contextlib import ExitStack, closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, library
from app.knowledge import evidence_by_ids
from app.main import app
from app.models import StudyCard
from app.study import export_study_data, save_cards


class MaterialRedecodeSafetyTests(unittest.TestCase):
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
        self.stack.enter_context(patch("app.library.TEMP_DIR", self.root / "temp"))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.text = "课程编码样本：学习率决定步长。"
        self.raw = self.text.encode("gb18030")
        self.material = library.import_document_material("lesson.txt", self.raw, "text/plain", encoding="big5")
        self.endpoint = f"/api/library/materials/{self.material['material_id']}/redecode"

    def sql(self, command, parameters=()):
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as db, db:
            return db.execute(command, parameters).fetchall()

    def snapshot(self):
        return {table: self.sql(f"SELECT * FROM {table} ORDER BY 1")
                for table in ("library_materials", "source_evidence", "source_evidence_fts")}

    def test_all_text_formats_keep_raw_bytes_and_existing_card_references(self):
        for suffix, text, mime in [("txt", self.text, "text/plain"),
                                   ("md", f"# Markdown\n\n{self.text}", "text/markdown"),
                                   ("html", f"<h1>HTML</h1><p>{self.text}</p>", "text/html")]:
            with self.subTest(suffix=suffix):
                raw = text.encode("gb18030")
                material = library.import_document_material(f"lesson.{suffix}", raw, mime, encoding="big5")
                card = save_cards([StudyCard(front=suffix, back="Synthetic answer", source_evidence_ids=material["evidence_ids"])])[0]
                before_study = export_study_data()
                response = self.client.post(f"/api/library/materials/{material['material_id']}/redecode", json={
                    "encoding": "gb18030", "expected_updated_at": material["updated_at"],
                })
                self.assertEqual(response.status_code, 200, response.text)
                updated = response.json()["material"]
                self.assertEqual(updated["evidence_ids"], material["evidence_ids"])
                self.assertEqual(updated["metadata"]["encoding"], "gb18030")
                self.assertEqual(updated["metadata"]["raw_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(library.material_source_path(material["material_id"]).read_bytes(), raw)
                self.assertIn(self.text, library.material_content(material["material_id"]))
                self.assertTrue(any(self.text in evidence["text"] for evidence in evidence_by_ids(card.source_evidence_ids)))
                after_study = export_study_data()
                before_study.pop("exported_at", None)
                after_study.pop("exported_at", None)
                self.assertEqual(before_study, after_study)

    def test_stale_reader_rejected_and_legacy_payload_still_works(self):
        payload = {"encoding": "gb18030", "expected_updated_at": self.material["updated_at"]}
        first = self.client.post(self.endpoint, json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        before = self.snapshot()
        response = self.client.post(self.endpoint, json={**payload, "encoding": "big5"})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "material_redecode_changed_reload_required")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(library.material_source_path(self.material["material_id"]).read_bytes(), self.raw)
        legacy = self.client.post(self.endpoint, json={"encoding": "gb18030"})
        self.assertEqual(legacy.status_code, 200, legacy.text)

    def test_invalid_encoding_integrity_failure_and_missing_original_never_replace_rows(self):
        source = library.material_source_path(self.material["material_id"])
        before = self.snapshot()
        response = self.client.post(self.endpoint, json={"encoding": "utf-8"})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "text_encoding_unsupported")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(source.read_bytes(), self.raw)
        source.write_bytes(b"different original bytes")
        response = self.client.post(self.endpoint, json={"encoding": "gb18030"})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "material_source_integrity_mismatch")
        self.assertEqual(self.snapshot(), before)
        source.rename(source.with_suffix(".unavailable"))
        response = self.client.post(self.endpoint, json={"encoding": "gb18030"})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "material_source_missing")
        self.assertEqual(self.snapshot(), before)

    def test_write_failure_rolls_back_material_evidence_and_search(self):
        before = self.snapshot()
        self.sql("CREATE TRIGGER reject_redecode BEFORE UPDATE ON library_materials BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        response = self.client.post(self.endpoint, json={"encoding": "gb18030"})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "material_redecode_failed")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(library.material_source_path(self.material["material_id"]).read_bytes(), self.raw)

    def test_unknown_exception_text_never_reaches_the_response(self):
        private_text = "material_private_error: C:/SyntheticPrivate/lesson.txt contains SyntheticPrivateContent"
        before = self.snapshot()
        for error in (ValueError(private_text), OSError(private_text), sqlite3.Error(private_text)):
            with self.subTest(error=type(error).__name__), patch("app.routers.library.redecode_document_material", side_effect=error):
                response = self.client.post(self.endpoint, json={"encoding": "gb18030"})
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()["detail"], {
                "code": "material_redecode_failed", "message": "资料重解码失败，当前内容未改变。",
            })
            self.assertNotIn("SyntheticPrivate", response.text)
            self.assertNotIn("material_private_error", response.text)
            self.assertEqual(self.snapshot(), before)
        missing = self.client.post("/api/library/materials/missing/redecode", json={"encoding": "gb18030"})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "material_not_found")

    def test_pdf_and_video_projections_cannot_be_redecoded(self):
        for field, value, code in [("source_type", "pdf", "material_redecode_pdf_unsupported"),
                                   ("linked_task_id", "synthetic-video", "material_rebuild_requires_document")]:
            with self.subTest(field=field):
                old = self.sql(f"SELECT {field} FROM library_materials WHERE material_id=?", (self.material["material_id"],))[0][0]
                self.sql(f"UPDATE library_materials SET {field}=? WHERE material_id=?", (value, self.material["material_id"]))
                before = self.snapshot()
                response = self.client.post(self.endpoint, json={"encoding": "gb18030"})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["detail"]["code"], code)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(library.material_source_path(self.material["material_id"]).read_bytes(), self.raw)
                self.sql(f"UPDATE library_materials SET {field}=? WHERE material_id=?", (old, self.material["material_id"]))

    def test_update_during_decode_is_not_overwritten(self):
        original_extract = library._material_sections
        before = self.snapshot()
        def extract_then_change(*args, **kwargs):
            result = original_extract(*args, **kwargs)
            self.sql("UPDATE library_materials SET updated_at='another-operation' WHERE material_id=?", (self.material["material_id"],))
            return result
        with patch("app.library._material_sections", side_effect=extract_then_change):
            response = self.client.post(self.endpoint, json={"encoding": "gb18030", "expected_updated_at": self.material["updated_at"]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(library.get_material(self.material["material_id"])["updated_at"], "another-operation")
        after = self.snapshot()
        self.assertEqual(after["source_evidence"], before["source_evidence"])
        self.assertEqual(after["source_evidence_fts"], before["source_evidence_fts"])
        self.assertEqual(library.material_source_path(self.material["material_id"]).read_bytes(), self.raw)


if __name__ == "__main__":
    unittest.main()
