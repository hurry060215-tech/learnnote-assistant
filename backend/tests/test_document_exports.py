from __future__ import annotations

import unittest
from io import BytesIO
from zipfile import ZipFile

from pypdf import PdfReader

from app.document_exports import build_docx_export, build_pdf_export
from app.models import TaskRecord
from app.note_document import normalize_note_markdown


class DocumentExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = TaskRecord(
            id="export-task",
            source_type="local",
            mode="local",
            title="梯度下降课程",
            page_url="https://example.com/video?id=1",
            created_at="2026-08-31T00:00:00+00:00",
            updated_at="2026-08-31T00:00:00+00:00",
        )
        raw = """# 梯度下降课程

## 核心结论

学习率决定更新步长。[查看原始证据](https://example.com/video?t=31)

- 时间戳：00:31–00:45

```python
rate = 0.1
```
"""
        self.note = normalize_note_markdown(self.task.title, raw).markdown
        self.transcript = {"segments": [{"start": 31, "end": 45, "text": "学习率决定更新步长"}]}

    def test_docx_is_editable_and_does_not_repeat_normalized_title(self) -> None:
        artifact = build_docx_export(self.task, self.note, self.transcript)
        self.assertEqual(artifact.suffix, "docx")
        with ZipFile(BytesIO(artifact.content)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
            relations = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        self.assertEqual(document_xml.count("梯度下降课程"), 1)
        self.assertIn("核心结论", document_xml)
        self.assertIn("https://example.com/video?t=31", relations)

    def test_pdf_has_pages_and_clickable_evidence_link(self) -> None:
        long_note = self.note + "\n" + "\n\n".join(f"段落 {index}：这是用于分页验证的中文学习内容。" for index in range(120))
        artifact = build_pdf_export(self.task, long_note, self.transcript)
        self.assertEqual(artifact.suffix, "pdf")
        self.assertTrue(artifact.content.startswith(b"%PDF"))
        reader = PdfReader(BytesIO(artifact.content))
        self.assertGreaterEqual(len(reader.pages), 2)
        links = []
        for page in reader.pages:
            for annotation in page.get("/Annots", []):
                action = annotation.get_object().get("/A")
                if action and action.get("/URI"):
                    links.append(str(action.get("/URI")))
        self.assertIn("https://example.com/video?t=31", links)

    def test_exports_redact_signed_urls_cookies_and_media_paths(self) -> None:
        task = self.task.model_copy(update={"source_media_path": "C:/private/course.mp4"})
        note = normalize_note_markdown(
            task.title,
            "# 梯度下降课程\n\nCookie: session-secret\n\n[证据](https://cdn.example.com/a.mp4?token=secret&id=7)",
        ).markdown
        docx = build_docx_export(task, note)
        with ZipFile(BytesIO(docx.content)) as archive:
            docx_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if name.endswith((".xml", ".rels"))
            )
        self.assertNotIn("session-secret", docx_text)
        self.assertNotIn("token=secret", docx_text)
        self.assertNotIn("C:/private/course.mp4", docx_text)
        self.assertIn("https://cdn.example.com/a.mp4", docx_text)

        pdf = build_pdf_export(task, note)
        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf.content)).pages)
        self.assertNotIn("session-secret", pdf_text)
        self.assertNotIn("token=secret", pdf_text)
        self.assertNotIn("C:/private/course.mp4", pdf_text)

    def test_exports_redact_complete_secret_lines_private_hosts_and_invalid_urls(self) -> None:
        task = self.task.model_copy(update={"page_url": "http://127.0.0.1:9999/private?token=secret"})
        note = normalize_note_markdown(
            task.title,
            "# 梯度下降课程\n\nAuthorization: Bearer SUPERSECRET\n\n"
            "Cookie: sid=ONE; csrf=TWO\n\n"
            "[内网页面](http://192.168.1.5/a?token=THREE)\n\n"
            "[非法端口](https://example.com:bad/a)",
        ).markdown
        docx = build_docx_export(task, note)
        with ZipFile(BytesIO(docx.content)) as archive:
            payload = b"\n".join(archive.read(name) for name in archive.namelist() if name.endswith((".xml", ".rels")))
        for secret in (b"SUPERSECRET", b"sid=ONE", b"csrf=TWO", b"192.168.1.5", b"example.com:bad"):
            self.assertNotIn(secret, payload)

        pdf = build_pdf_export(task, note)
        reader = PdfReader(BytesIO(pdf.content))
        payload_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        for secret in ("SUPERSECRET", "sid=ONE", "csrf=TWO", "192.168.1.5", "example.com:bad"):
            self.assertNotIn(secret, payload_text)


if __name__ == "__main__":
    unittest.main()
