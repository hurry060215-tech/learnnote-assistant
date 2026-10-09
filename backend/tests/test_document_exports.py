from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from io import BytesIO
from zipfile import ZipFile

from pypdf import PdfReader

from app.document_exports import build_docx_export, build_html_export, build_pdf_export, build_structured_export
from app.models import TaskRecord, FrameGrid
from app.note_document import build_note_document, normalize_note_markdown


class DocumentExportTests(unittest.TestCase):
    def test_pdf_toc_has_real_page_numbers_and_destinations(self):
        note = "## Beginning\n\n" + "\n\n".join("中英混排段落 English words " * 12 for _ in range(120)) + "\n\n## Final section\n\n末尾验收内容。"
        artifact = build_pdf_export(self.task, note, export_options={"include_toc": True})
        reader = PdfReader(BytesIO(artifact.content))
        last_page_number = next(index for index, page in enumerate(reader.pages, 1)
                                if "Final section" in page.extract_text() and index > 1)
        toc = reader.pages[0].extract_text()
        self.assertIn("目录", toc)
        self.assertRegex(toc, rf"{last_page_number}\nFinal section")
        destinations = [annotation.get_object().get("/Dest") for annotation in reader.pages[0].get("/Annots", [])]
        self.assertTrue(any(destination and destination[0] == reader.pages[last_page_number - 1].indirect_reference
                            for destination in destinations))

    def test_long_pdf_toc_starts_on_first_page_instead_of_leaving_a_blank_cover(self):
        note = "\n\n".join(f"## Chapter {index}\n\nShort section content." for index in range(1, 41))
        artifact = build_pdf_export(self.task, note, export_options={"template": "academic"})
        reader = PdfReader(BytesIO(artifact.content))
        first_page = reader.pages[0].extract_text()
        self.assertIn("目录", first_page)
        self.assertIn("Chapter 1", first_page)
        self.assertGreater(len(reader.pages[0].get("/Annots", [])), 5)

    def test_word_toc_is_a_real_updateable_field_and_has_bookmarks(self):
        artifact = build_docx_export(self.task, self.note, export_options={"include_toc": True})
        with ZipFile(BytesIO(artifact.content)) as package:
            xml = package.read("word/document.xml").decode("utf-8")
            settings = package.read("word/settings.xml").decode("utf-8")
            styles = package.read("word/styles.xml").decode("utf-8")
        self.assertIn('TOC \\o "1-3" \\h', xml)
        self.assertIn("w:bookmarkStart", xml)
        self.assertIn('w:updateFields w:val="true"', settings)
        self.assertIn("w:widowControl", styles)
        self.assertIn("docx_toc_page_numbers_require_field_update", artifact.warnings)

    def test_word_numbered_steps_preserve_start_and_restart_as_editable_lists(self):
        from lxml import etree
        note = "7. First step\n8. Second step\n\nA paragraph ends the first list.\n\n1. Restarted step"
        artifact = build_docx_export(self.task, note)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with ZipFile(BytesIO(artifact.content)) as package:
            document = etree.fromstring(package.read("word/document.xml"))
            numbering = etree.fromstring(package.read("word/numbering.xml"))
        ids = document.xpath("//w:pPr/w:numPr/w:numId/@w:val", namespaces=ns)
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[1], ids[2])
        first_abstract = numbering.xpath(f'//w:num[@w:numId="{ids[0]}"]/w:abstractNumId/@w:val', namespaces=ns)[0]
        start = numbering.xpath(f'//w:abstractNum[@w:abstractNumId="{first_abstract}"]/w:lvl/w:start/@w:val', namespaces=ns)
        self.assertEqual(start, ["7"])

    def test_wide_cjk_code_wraps_to_pdf_frame_width_and_numbered_steps_stay_numbered(self):
        from app.document_exports import _pdf_font, _wrap_pdf_code
        from reportlab.pdfbase.pdfmetrics import stringWidth
        font_name, _ = _pdf_font()
        original = "变量名称" * 80
        wrapped = _wrap_pdf_code(original, font_name, 9, 220)
        self.assertEqual(wrapped.replace("\n", ""), original)
        self.assertTrue(all(stringWidth(line, font_name, 9) <= 220 for line in wrapped.splitlines()))
        pdf = build_pdf_export(self.task, "7. First step\n8. Second step\n\n```text\n" + original + "\n```", export_options={"orientation": "landscape", "margin_left": 50, "margin_right": 50})
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        self.assertIn("7.", text)
        self.assertIn("8.", text)
        self.assertIn("First step", text)
        self.assertIn("Second step", text)

    def test_tables_keep_code_pipes_quotes_and_hard_breaks_across_renderers(self):
        from app.document_exports import _table_rows
        note = "## Syntax\n\n| Expression | Meaning |\n| --- | --- |\n| `a|b` | choice |\n| left\\|right | escaped |\n\n> A quoted source statement.\n\nFirst line  \nSecond line\n"
        rows = _table_rows(note.split("## Syntax\n\n", 1)[1].split("\n\n", 1)[0])
        self.assertEqual(rows, [["Expression", "Meaning"], ["`a|b`", "choice"], ["left|right", "escaped"]])
        projection = build_structured_export(self.task, note)
        self.assertTrue(any(block["kind"] == "quote" for block in projection["blocks"]))
        self.assertTrue(any(block["text"] == "First line\nSecond line" for block in projection["blocks"]))
        html = build_html_export(self.task, note).content.decode("utf-8")
        self.assertIn("<blockquote>A quoted source statement.</blockquote>", html)
        self.assertIn("First line<br>Second line", html)
        docx = build_docx_export(self.task, note)
        with ZipFile(BytesIO(docx.content)) as package:
            xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn('w:pStyle w:val="Quote"', xml)
        self.assertIn("<w:br/>", xml)
        self.assertIn("a|b", xml)

    def test_pdf_cid_fallback_uses_latin_font_for_superscripts_and_accents(self):
        from app.document_exports import _pdf_inline
        self.assertIn('<font name="Helvetica">²</font>', _pdf_inline("E = mc²"))
        note = "## 公式\n\nE = mc²；café；± 2。\n\n```text\n面积 = 2²\n```"
        artifact = build_pdf_export(self.task, note)
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(artifact.content)).pages)
        self.assertIn("²", text)
        self.assertIn("café", text)
        self.assertIn("面积", text)

    def test_html_retains_full_unicode_and_pdf_inline_cjk_uses_cjk_font(self):
        from app.document_exports import _pdf_inline
        note = "## 示例\n\n导航 🧭 使用 `中文变量` 与 `café`。"
        html_text = build_html_export(self.task, note).content.decode("utf-8")
        self.assertIn("🧭", html_text)
        self.assertIn("<code>中文变量</code>", html_text)
        self.assertIn("<code>café</code>", html_text)
        self.assertNotIn("Courier", _pdf_inline("`中文变量`"))
        self.assertIn("Courier", _pdf_inline("`variable`"))
        pdf = build_pdf_export(self.task, note)
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        self.assertIn("中文变量", text)

    def test_named_templates_are_bounded_and_explicit_overrides_win(self):
        from app.document_exports import normalize_export_options
        academic = normalize_export_options({"template": "academic"})
        compact = normalize_export_options({"template": "compact", "font_size": 12})
        self.assertTrue(academic["include_toc"])
        self.assertEqual(academic["margin_left"], 25)
        self.assertEqual(compact["font_size"], 12)
        self.assertEqual(compact["margin_left"], 12)
        self.assertEqual(normalize_export_options({"template": "unknown"})["template"], "print")

    def test_html_toc_uses_the_same_stable_anchor_as_note_document(self):
        note = normalize_note_markdown(
            self.task.title,
            "## 核心结论\n\n更新步长由学习率控制。[00:31]\n\n## 复习\n\n回忆关键定义。[01:05]",
        ).markdown
        document = build_note_document(self.task.title, note)
        expected = next(item["section_id"] for item in document["sections"] if item["heading"] == "核心结论")
        html = build_html_export(
            self.task,
            note,
            export_options={"include_toc": True, "include_source_link": False},
        ).content.decode("utf-8")
        self.assertIn(f'id="{expected}"', html)
        self.assertIn(f'href="#{expected}"', html)

        inserted = normalize_note_markdown(
            self.task.title,
            "## 新增背景\n\n新增内容。[00:10]\n\n" + note.split("# ", 1)[1].split("\n", 1)[1],
        ).markdown
        inserted_document = build_note_document(self.task.title, inserted)
        actual = next(item["section_id"] for item in inserted_document["sections"] if item["heading"] == "核心结论")
        self.assertEqual(expected, actual)

    def test_structured_export_preserves_code_trailing_spaces(self):
        note = self.note + "\n\n```python\nvalue = 1  \nprint(value)\n```\n\n    print('indented')  \n"
        payload = build_structured_export(self.task, note)
        code_blocks = [block["text"] for block in payload["blocks"] if block["kind"] == "code"]
        code = next(block for block in code_blocks if "value = 1" in block)
        self.assertIn("value = 1  \nprint(value)", code)
        self.assertTrue(any("print('indented')  " in block for block in code_blocks))

    def test_frontmatter_is_metadata_and_not_rendered_as_note_content(self):
        note = "---\ntitle: export fixture\nsource: local lesson\n---\n\n## Findings\n\nEvidence is available at 00:10."
        payload = build_structured_export(self.task, note)
        self.assertNotIn("source: local lesson", payload["markdown"])
        self.assertNotIn("title: export fixture", payload["markdown"])
        self.assertNotIn("---", payload["markdown"])
        self.assertIn("Findings", payload["markdown"])

    def test_non_bmp_symbols_retain_word_and_pdf_unicode(self):
        note = normalize_note_markdown(self.task.title, "## Compass\n\nThe navigation symbol is 🧭. [00:10]").markdown
        docx = build_docx_export(self.task, note)
        with ZipFile(BytesIO(docx.content)) as package:
            xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn("🧭", xml)
        self.assertIn("Segoe UI Emoji", xml)

        pdf = build_pdf_export(self.task, note)
        extracted = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf.content)).pages)
        self.assertIn("🧭", extracted)
        self.assertNotIn("non_bmp_symbols_rendered_as_unicode_names", pdf.warnings)

    def test_generated_notes_retain_review_notice_in_word_pdf_and_shared_structure(self):
        task = self.task.model_copy(update={'summary_source':'text-llm'})
        structured = build_structured_export(task,self.note)
        self.assertIn('来源核对提示', structured['markdown'])
        self.assertIn('[00:31–00:45](https://example.com/video?t=31)', structured['markdown'])
        docx = build_docx_export(task,self.note)
        with ZipFile(BytesIO(docx.content)) as package:
            xml = package.read('word/document.xml').decode('utf-8')
            self.assertIn('来源核对提示', xml)
            self.assertEqual(xml.count(task.title),1)
            self.assertGreaterEqual(xml.count('<w:hyperlink'), 2)
        pdf = build_pdf_export(task,self.note)
        self.assertIn('来源核对提示', ''.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages))

    def test_incomplete_table_separator_does_not_break_export(self) -> None:
        note = self.note + "\n\n| --- | --- |\n"
        self.assertTrue(build_docx_export(self.task, note).content.startswith(b"PK"))
        self.assertTrue(build_pdf_export(self.task, note).content.startswith(b"%PDF"))
    def test_tables_and_local_keyframes_are_editable_and_embedded(self) -> None:
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_dir = root / "export-task"
            task_dir.mkdir()
            frame = task_dir / "grid.jpg"
            Image.new("RGB", (400, 220), "white").save(frame)
            task = self.task.model_copy(update={"frame_grids": [FrameGrid(path=str(frame), start=0, end=10, frame_count=1, url="/api/tasks/export-task/assets/grid.jpg")]})
            note = self.note + "\n| 概念 | 含义 |\n| --- | --- |\n| 学习率 | 更新步长 |\n\n![00:10 关键画面](/api/tasks/export-task/assets/grid.jpg)\n"
            with patch("app.document_exports.TASK_DIR", root):
                docx = build_docx_export(task, note)
                pdf = build_pdf_export(task, note, export_options={"orientation": "landscape", "margin_top": 50, "margin_bottom": 50})
            with ZipFile(BytesIO(docx.content)) as archive:
                xml = archive.read("word/document.xml").decode()
                self.assertIn("<w:tbl>", xml)
                self.assertIn('descr="00:10 关键画面"', xml)
                self.assertTrue(any(name.startswith("word/media/") for name in archive.namelist()))
            reader = PdfReader(BytesIO(pdf.content))
            self.assertIn("更新步长", "".join(page.extract_text() for page in reader.pages))
            self.assertTrue(any(page.images for page in reader.pages))

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
            footer_xml = archive.read("word/footer1.xml").decode("utf-8")
        self.assertEqual(document_xml.count("梯度下降课程"), 1)
        self.assertIn("核心结论", document_xml)
        self.assertIn("https://example.com/video?t=31", relations)
        self.assertIn("PAGE", footer_xml)
        self.assertIn("NUMPAGES", footer_xml)

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
        self.assertGreaterEqual(len(links), 2)

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

    def test_unified_export_keeps_content_and_layout_options_across_formats(self) -> None:
        note = self.note + "\n\n## 关键点\n\n**粗体结论**，代码是 `rate = 0.1`，并见 [来源](https://example.com/lesson?t=31)。\n\n| 项目 | 值 |\n| --- | --- |\n| 学习率 | 0.1 |"
        options = {"include_toc": True, "include_transcript": True, "include_practice": True, "font_size": 12, "line_height": 1.8, "orientation": "landscape"}
        structured = build_structured_export(self.task, note, self.transcript, annotations="我的补充", practice=[{"question": "问题", "answer": "答案"}], options=options)
        self.assertIn("## 目录", structured["markdown"])
        html_artifact = build_html_export(self.task, note, self.transcript, annotations="我的补充", practice=[{"question": "问题", "answer": "答案"}], export_options=options)
        html_text = html_artifact.content.decode("utf-8")
        self.assertIn("粗体结论", html_text)
        self.assertIn("<strong>", html_text)
        self.assertIn("完整字幕", html_text)
        self.assertIn("练习", html_text)
        docx_artifact = build_docx_export(self.task, note, self.transcript, annotations="我的补充", practice=[{"question": "问题", "answer": "答案"}], export_options=options)
        with ZipFile(BytesIO(docx_artifact.content)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("粗体结论", document_xml)
        self.assertIn("w:b", document_xml)
        self.assertIn("我的补充", document_xml)
        self.assertIn("目录", document_xml)
        self.assertIn("答案", document_xml)
        pdf_artifact = build_pdf_export(self.task, note, self.transcript, annotations="我的补充", practice=[{"question": "问题", "answer": "答案"}], export_options=options)
        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_artifact.content)).pages)
        self.assertIn("粗体结论", pdf_text)
        self.assertIn("我的补充", pdf_text)
        self.assertIn("答案", pdf_text)


if __name__ == "__main__":
    unittest.main()
