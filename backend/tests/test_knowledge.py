from __future__ import annotations

import tempfile
import unittest
import os
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from app.knowledge import add_evidence, answer_from_evidence, evidence_for_task, extract_import_text, remove_evidence, search_evidence
from app.models import SourceEvidence


class KnowledgeEvidenceTests(unittest.TestCase):
    def test_import_and_cited_local_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.knowledge.DATA_DIR", root):
                stored = add_evidence(SourceEvidence(
                    source_type="markdown",
                    title="梯度下降",
                    source_uri="local://lesson.md",
                    locator="paragraph 2",
                    text="学习率决定每一步参数更新的步长。",
                ))
                self.assertEqual(stored.schema_version, 1)
                hits = search_evidence("学习率")
                self.assertEqual(hits[0]["evidence_id"], stored.evidence_id)
                answer = answer_from_evidence("学习率")
                self.assertTrue(answer["grounded"])
                self.assertEqual(answer["citations"][0]["locator"], "paragraph 2")

                self.assertEqual(evidence_for_task(""), [])
                self.assertTrue(remove_evidence(stored.evidence_id))
                self.assertEqual(search_evidence("学习率"), [])

    def test_missing_evidence_is_explicitly_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.knowledge.DATA_DIR", Path(tmp)):
                answer = answer_from_evidence("不存在的主题")
                self.assertFalse(answer["grounded"])
                self.assertEqual(answer["citations"], [])

    def test_html_import_strips_script_and_markup(self) -> None:
        text, source_type = extract_import_text("page.html", "<script>secret()</script><h1>标题</h1><p>正文</p>".encode(), "text/html")
        self.assertEqual(source_type, "webpage")
        self.assertIn("标题", text)
        self.assertIn("正文", text)
        self.assertNotIn("secret", text)

    def test_gb18030_markdown_import_preserves_chinese(self) -> None:
        text, source_type = extract_import_text("课程.md", "编码正确的学习资料".encode("gb18030"), "text/markdown")
        self.assertEqual(source_type, "markdown")
        self.assertEqual(text, "编码正确的学习资料")

    def test_invalid_text_encoding_is_blocked(self) -> None:
        with self.assertRaisesRegex(ValueError, "text_encoding_unsupported"):
            extract_import_text("broken.txt", b"\x81\xff\x80", "text/plain")

    def test_pdf_upload_bytes_win_over_same_named_cwd_file(self) -> None:
        from reportlab.pdfgen import canvas

        def pdf_bytes(text: str) -> bytes:
            buffer = BytesIO()
            document = canvas.Canvas(buffer)
            document.drawString(72, 760, text)
            document.save()
            return buffer.getvalue()

        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                Path("lesson.pdf").write_bytes(pdf_bytes("SERVER PRIVATE PDF"))
                text, source_type = extract_import_text("lesson.pdf", pdf_bytes("UPLOADED PDF"), "application/pdf")
            finally:
                os.chdir(previous)
        self.assertEqual(source_type, "pdf")
        self.assertIn("UPLOADED PDF", text)
        self.assertNotIn("SERVER PRIVATE PDF", text)

    def test_like_fallback_is_used_when_fts_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.knowledge.DATA_DIR", Path(tmp)), patch("app.knowledge._fts_available", return_value=False):
                stored = add_evidence(SourceEvidence(title="Fallback", text="本地检索回退内容"))
                hits = search_evidence("回退")
                self.assertEqual(hits[0]["evidence_id"], stored.evidence_id)


if __name__ == "__main__":
    unittest.main()
