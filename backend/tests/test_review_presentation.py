from io import BytesIO
from types import SimpleNamespace
import unittest
from zipfile import ZipFile
from unittest.mock import patch

from pypdf import PdfReader
from app.document_exports import build_docx_export, build_html_export, build_pdf_export, build_structured_export
from app.review_presentation import LOCATION_MARKER, project_source_reviews


class SourceReviewPresentationTests(unittest.TestCase):
    note = ("# 合成笔记\n\n## 关键概念\n\n"
            + LOCATION_MARKER + " 这是来源改写，仍需核对。[00:12](https://example.com/watch?t=12)\n\n"
            "**【待核对：未找到支持来源】** 这个数字缺少证据。\n\n"
            "**【推断：需回源核对】** 这是一种推断。\n")

    def test_moves_only_location_warnings_and_retains_body_source_and_stronger_warnings(self):
        result = project_source_reviews(self.note)
        self.assertEqual(len(result["entries"]), 1)
        self.assertNotIn(LOCATION_MARKER, result["body"])
        self.assertIn("这是来源改写，仍需核对。", result["body"])
        self.assertIn("https://example.com/watch?t=12", result["body"])
        self.assertIn("[来源 1](#section-来源核对-1)", result["body"])
        self.assertIn("尚未验证来源是否支持结论", result["markdown"])
        for warning in ("**【待核对：未找到支持来源】**", "**【推断：需回源核对】**"):
            self.assertIn(warning, result["body"])
        self.assertEqual(project_source_reviews(result["markdown"])["markdown"], result["markdown"])

    def test_marker_examples_in_code_links_quotes_and_frontmatter_are_unchanged(self):
        marker = LOCATION_MARKER
        untouched = (f"---\nexample: {marker}\n---\n\n```markdown\n{marker} 示例\n```\n\n"
                     f"    {marker} 缩进代码\n\n`{marker}`\n\n> {marker} 引用\n\n"
                     f"[{marker}](https://example.com)\n\n\\{marker} 转义\n")
        self.assertEqual(project_source_reviews(untouched)["markdown"], untouched)

    def test_repeated_statements_remain_distinct_and_do_not_collide_with_existing_headings(self):
        note = f"# 原稿\n\n### 来源核对 1\n\n{LOCATION_MARKER} 第一条。[00:01] {LOCATION_MARKER} 第二条。[00:02]\n"
        result = project_source_reviews(note)
        self.assertEqual(len(result["entries"]), 2)
        self.assertEqual(result["entries"][0]["anchor"], "section-来源核对-1-2")
        self.assertIn("第一条", result["entries"][0]["text"])
        self.assertNotIn("第二条", result["entries"][0]["text"])
        self.assertIn("第二条", result["entries"][1]["text"])

    def test_dense_review_projection_preserves_each_statement_and_reports_every_notice(self):
        note = "# 长笔记\n\n" + "\n\n".join(f"{LOCATION_MARKER} 原文{i} [00:12]。" for i in range(1000))
        result = project_source_reviews(note)
        self.assertEqual(len(result["entries"]), 1000)
        self.assertEqual(result["body"].count("原文"), 1000)
        self.assertNotIn(LOCATION_MARKER, result["body"])
        self.assertIn("来源核对 · 1000 条定位提示", result["markdown"])

    def test_all_document_formats_preserve_review_status_and_clickable_source(self):
        task = SimpleNamespace(id="synthetic-review", title="合成笔记", page_url="https://example.com/watch")
        options = {"include_toc": False, "include_transcript": False}
        structured = build_structured_export(task, self.note, options=options)
        self.assertNotIn(LOCATION_MARKER, structured["markdown"])
        self.assertIn("未找到支持来源", structured["markdown"])
        html = build_html_export(task, self.note, export_options=options).content.decode()
        self.assertIn('<details class="source-review"', html)
        self.assertIn('href="#section-来源核对-1"', html)
        self.assertIn('https://example.com/watch?t=12', html)
        self.assertNotIn(LOCATION_MARKER, html)
        with ZipFile(BytesIO(build_docx_export(task, self.note, export_options=options).content)) as archive:
            xml = archive.read("word/document.xml").decode()
            rels = archive.read("word/_rels/document.xml.rels").decode()
        self.assertIn("尚未验证支持", xml)
        self.assertIn("未找到支持来源", xml)
        self.assertIn("https://example.com/watch?t=12", rels)
        pdf = PdfReader(BytesIO(build_pdf_export(task, self.note, export_options=options).content))
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        self.assertIn("尚未验证支持", text)
        self.assertIn("未找到支持来源", text)
        actions = [annotation.get_object() for page in pdf.pages for annotation in page.get("/Annots", [])]
        self.assertTrue(any(value.get("/A", {}).get("/URI") == "https://example.com/watch?t=12" for value in actions))
        self.assertTrue(any(value.get("/Dest") or value.get("/A", {}).get("/S") == "/GoTo" for value in actions))

    def test_excluding_note_excludes_its_review_appendix(self):
        task = SimpleNamespace(id="synthetic-review", title="合成笔记", page_url="")
        result = build_structured_export(task, self.note, options={"include_note": False, "include_toc": False})
        self.assertEqual(result["source_review_anchor"], "")
        self.assertNotIn("来源核对 1", result["markdown"])

    def test_saved_edition_and_task_markdown_routes_project_without_saving(self):
        from app import main
        from app.routers import notes
        original = {"text": self.note, "revision": "a" * 64}
        with patch.object(notes, "get_edition", return_value=original), \
             patch.object(notes, "atomic_write_text") as save:
            response = notes.export_edition("task", "synthetic-review", "markdown")
        self.assertIn("来源核对 · 1 条定位提示", response.body.decode())
        self.assertEqual(original["text"], self.note)
        save.assert_not_called()
        task = SimpleNamespace(id="synthetic-review", title="合成笔记", summary_source="", summary_warning="")
        with patch.object(main, "get_task", return_value=task), \
             patch.object(main, "read_note", return_value=self.note):
            response = main.api_export_markdown("synthetic-review")
        self.assertIn("来源核对 · 1 条定位提示", response.body.decode())
        self.assertIn("未找到支持来源", response.body.decode())

