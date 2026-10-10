"""Inspect real portable-document destinations for generated time links."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from lxml import etree
from PIL import Image
from pypdf import PdfReader

from app.claims import build_claim_evidence_map
from app.document_exports import (
    build_docx_export, build_html_export, build_pdf_export, build_structured_export,
)
from app.models import FrameGrid, TaskRecord, TranscriptResult, TranscriptSegment


class ExportTimestampDestinationTests(TestCase):
    def setUp(self):
        self.task = TaskRecord(
            id="timestamp-export", title="Timestamp source fixture", source_type="local",
            page_url="https://example.com/lesson(part-1)?v=clip&p=2&token=DUMMY",
            created_at="2026-10-10", updated_at="2026-10-10",
        )

    def destinations(self, builder, task, note, **kwargs):
        artifact = builder(task, note, **kwargs)
        if artifact.suffix == "docx":
            with ZipFile(BytesIO(artifact.content)) as package:
                rels = etree.fromstring(package.read("word/_rels/document.xml.rels"))
                root = etree.fromstring(package.read("word/document.xml"))
            return {item.get("Target") for item in rels
                    if item.get("Type", "").endswith("/hyperlink")}, "".join(root.itertext())
        if artifact.suffix == "pdf":
            reader = PdfReader(BytesIO(artifact.content))
            links = [item.get_object() for page in reader.pages for item in page.get("/Annots", [])]
            return {str(item["/A"]["/URI"]) for item in links
                    if item.get("/A", {}).get("/S") == "/URI"}, "".join(page.extract_text() for page in reader.pages)
        root = etree.HTML(artifact.content)
        return set(root.xpath("//a/@href")), "".join(root.itertext())

    def test_generated_links_preserve_literal_nested_encoded_and_unicode_paths(self):
        note = "## Source evidence\n\nEvidence starts at 00:12.\n\nLater interval 01:03–01:09."
        for path in ("/lesson(part-1)", "/lesson(part(1))", "/lesson%28part-1%29", "/课程(第1节)"):
            task = self.task.model_copy(update={"page_url": "https://example.com" + path + "?v=clip&p=2&token=DUMMY"})
            expected_path = path.replace("(", "%28").replace(")", "%29")
            expected = {"https://example.com" + expected_path + "?v=clip&p=2&t=" + value for value in ("12", "63")}
            structured = build_structured_export(task, note)
            for url in expected:
                self.assertIn("](" + url + ")", structured["markdown"])
            for builder in (build_docx_export, build_pdf_export, build_html_export):
                with self.subTest(path=path, format=builder.__name__):
                    links, text = self.destinations(builder, task, note)
                    self.assertTrue(expected.issubset(links), links)
                    self.assertIn("Evidence starts at 00:12.", text)
                    self.assertIn("Later interval 01:03–01:09.", text)
                    self.assertFalse(any("DUMMY" in value or "%2528" in value for value in links))
            self.assertEqual(task.page_url, "https://example.com" + path + "?v=clip&p=2&token=DUMMY")

    def test_generated_keyframe_caption_uses_complete_timestamp_destination(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / self.task.id
            folder.mkdir()
            frame = folder / "frame.jpg"
            Image.new("RGB", (160, 90), "white").save(frame)
            url = f"/api/tasks/{self.task.id}/assets/frame.jpg"
            task = self.task.model_copy(update={"frame_grids": [FrameGrid(
                path=str(frame), url=url, start=12, end=18, frame_count=1,
            )]})
            note = f"## Frame evidence\n\n![Frame 00:12]({url})"
            expected = "https://example.com/lesson%28part-1%29?v=clip&p=2&t=12"
            with patch("app.document_exports.TASK_DIR", root):
                for builder in (build_docx_export, build_pdf_export):
                    with self.subTest(format=builder.__name__):
                        links, text = self.destinations(builder, task, note)
                        self.assertIn(expected, links)
                        self.assertIn("Frame 00:12", text)
                        self.assertNotIn("?v=clip&p=2&t=12)", text)

    def test_options_and_existing_links_or_code_are_preserved(self):
        note = "Evidence 00:12.\n\n`00:13`\n\n```text\n00:14\n```\n\n[00:15](https://example.org/other?t=15)"
        value = build_structured_export(self.task, note)["markdown"]
        self.assertIn("`00:13`", value)
        self.assertIn("```text\n00:14\n```", value)
        self.assertIn("[00:15](https://example.org/other?t=15)", value)
        for options in ({"include_source_link": False}, {"include_timestamps": False}):
            for builder in (build_docx_export, build_pdf_export, build_html_export):
                with self.subTest(options=options, format=builder.__name__):
                    links, _ = self.destinations(builder, self.task, "Evidence 00:12.", export_options=options)
                    self.assertFalse(any("t=12" in link for link in links))

    def test_claim_appendix_time_links_match_explicit_evidence_links(self):
        note = "## Evidence\n\nWater freezes at zero degrees Celsius."
        transcript = TranscriptResult(segments=[TranscriptSegment(
            start=12, end=18, text="Water freezes at zero degrees Celsius.",
        )])
        claims = build_claim_evidence_map(self.task.id, self.task.title, note, transcript)
        expected = "https://example.com/lesson%28part-1%29?v=clip&p=2&t=12"
        for builder in (build_docx_export, build_pdf_export, build_html_export):
            with self.subTest(format=builder.__name__):
                links, text = self.destinations(builder, self.task, note, claim_map=claims)
                self.assertIn(expected, links)
                self.assertNotIn("https://example.com/lesson(part-1", links)
                self.assertNotIn("?v=clip&p=2&t=12)", text)
