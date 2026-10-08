from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pypdf import PdfWriter
from app.library import preview_document_material


class MaterialPreflightTests(unittest.TestCase):
    def test_document_preview_does_not_save_or_index_user_bytes(self):
        with tempfile.TemporaryDirectory() as tmp, patch("app.library.DATA_DIR", Path(tmp)), patch("app.knowledge.DATA_DIR", Path(tmp)):
            text = "# My original 讲义\n\nPreserve this explanation."
            result = preview_document_material("my notes.markdown", text.encode(), "text/markdown")
            self.assertEqual(result["filename"], "my notes.markdown")
            self.assertEqual(result["preview"], text)
            self.assertEqual(result["route"], "local_text_extraction")
            self.assertGreater(result["estimated_storage_bytes"], len(text.encode()))
            self.assertFalse(result["saved"])
            self.assertFalse(result["external_transmission"])
            self.assertEqual(list(Path(tmp).rglob("*")), [])

    def test_scanned_pdf_preview_has_page_count_and_optional_local_ocr_route(self):
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=100, height=100)
        data = BytesIO(); writer.write(data)
        result = preview_document_material("scanned.pdf", data.getvalue(), "application/pdf")
        self.assertEqual(result["page_count"], 3)
        self.assertTrue(result["ocr_required"])
        self.assertEqual(result["route"], "local_pdf_ocr_optional")

    def test_preflight_rejects_invalid_empty_or_oversized_inputs(self):
        with self.assertRaisesRegex(ValueError, "material_type_unsupported"):
            preview_document_material("script.exe", b"payload")
        with self.assertRaisesRegex(ValueError, "material_file_empty"):
            preview_document_material("empty.txt", b"")
        with patch("app.library.MATERIAL_IMPORT_MAX_BYTES", 2), self.assertRaisesRegex(ValueError, "material_file_too_large"):
            preview_document_material("large.txt", b"123")
