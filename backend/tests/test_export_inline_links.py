"""Legal CommonMark link syntax must agree across actual export formats."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest import TestCase
from zipfile import ZipFile

from lxml import etree
from pypdf import PdfReader

from app.document_exports import (
    _linkify_video_timestamps, build_docx_export, build_html_export, build_pdf_export,
)
from app.export_inline import export_inline_tokens, export_links
from app.models import TaskRecord


class ExportInlineLinkTests(TestCase):
    def setUp(self):
        self.task = TaskRecord(id="inline-link", title="Inline link fixture", source_type="local",
                               created_at="2026-10-10", updated_at="2026-10-10")

    def artifacts(self, note):
        for builder in (build_docx_export, build_pdf_export, build_html_export):
            artifact = builder(self.task, note)
            if artifact.suffix == "docx":
                with ZipFile(BytesIO(artifact.content)) as package:
                    root = etree.fromstring(package.read("word/document.xml"))
                    rels = etree.fromstring(package.read("word/_rels/document.xml.rels"))
                links = {item.get("Target") for item in rels if item.get("Type", "").endswith("/hyperlink")}
                text = "".join(root.itertext())
            elif artifact.suffix == "pdf":
                reader = PdfReader(BytesIO(artifact.content))
                annotations = [item.get_object() for page in reader.pages for item in page.get("/Annots", [])]
                links = {str(item["/A"]["/URI"]) for item in annotations
                         if item.get("/A", {}).get("/S") == "/URI"}
                text = "".join(page.extract_text() for page in reader.pages)
            else:
                root = etree.HTML(artifact.content)
                links = set(root.xpath("//a/@href"))
                text = "".join(root.itertext())
                self.assertFalse(root.xpath("//script|//iframe|//img"))
            yield artifact.suffix, links, text

    def test_escaped_nested_and_formatted_labels_preserve_readable_text(self):
        cases = [
            (r"source \[x\]", "source [x]"),
            (r"folder \\ notes", "folder \\ notes"),
            ("source [nested [text]]", "source [nested [text]]"),
            ("**bold** `code` [nested] &amp;", "bold code [nested] &"),
            ("来源 <script>literal</script>", "来源 <script>literal</script>"),
            ("![alt [nested]](https://example.org/image)", "alt [nested]"),
        ]
        for label, expected in cases:
            note = "Before [" + label + "](https://example.org/spec?page=3) after."
            for kind, links, text in self.artifacts(note):
                with self.subTest(label=label, format=kind):
                    self.assertEqual(links, {"https://example.org/spec?page=3"})
                    self.assertIn("Before " + expected + " after.", text)
            self.assertEqual(note, "Before [" + label + "](https://example.org/spec?page=3) after.")

    def test_balanced_escaped_and_titled_destinations_are_not_truncated(self):
        cases = [
            ("https://example.org/part(one(two))?v=clip&p=2", "https://example.org/part(one(two))?v=clip&p=2"),
            (r"https://example.org/part\(one\)?v=clip", "https://example.org/part(one)?v=clip"),
            ('<https://example.org/资料(一)?page=3> "optional title"', "https://example.org/资料(一)?page=3"),
            ("https://example.org/spec?v=1&amp;p=2", "https://example.org/spec?v=1&p=2"),
        ]
        for destination, expected in cases:
            for kind, links, text in self.artifacts("Read [source] (literal) and [linked](" + destination + ")."):
                with self.subTest(destination=destination, format=kind):
                    self.assertEqual(links, {expected})
                    self.assertIn("Read [source] (literal) and linked.", text)
                    self.assertNotIn("optional title", text)

    def test_unsafe_destinations_never_become_active_links(self):
        destinations = ["javascript:alert(1)", "javascript&#58;alert(1)", "data:text/html,hello",
                        "file:///tmp/source", "vbscript:message", "mailto:user@example.org",
                        "https://user:password@example.org/spec", "http://127.0.0.1/private", "https://host.local/x"]
        for destination in destinations:
            for kind, links, text in self.artifacts(r"[source \[x\]](" + destination + ")"):
                with self.subTest(destination=destination, format=kind):
                    self.assertFalse(links)
                    self.assertIn("source", text)

    def test_literal_code_math_and_escaped_openers_do_not_gain_links(self):
        cases = [r"\[literal](https://example.org/x)", "`[code](https://example.org/x)`",
                 "``[code](https://example.org/x) ` literal``", "$[math](https://example.org/x)$",
                 "[unterminated](https://example.org/part(one)"]
        for note in cases:
            for kind, links, text in self.artifacts(note):
                with self.subTest(note=note, format=kind):
                    self.assertFalse(links)
                    self.assertTrue(text)

    def test_timecodes_inside_links_images_code_and_math_are_opaque(self):
        protected = [r"[source \[x\] 00:12](https://example.org/x)",
                     "![image [nested] 00:12](https://example.org/image)",
                     "``code ` 00:12``", "$00:12 + [math](https://example.org/x)$"]
        for value in protected:
            with self.subTest(value=value):
                self.assertEqual(_linkify_video_timestamps(value, "https://example.com/video"), value)
        mixed = protected[0] + " then 00:15."
        self.assertEqual(_linkify_video_timestamps(mixed, "https://example.com/video"),
                         protected[0] + " then [00:15](https://example.com/video?t=15).")

    def test_multiline_links_keep_their_source_when_timecodes_are_enabled(self):
        self.task = self.task.model_copy(update={"page_url": "https://example.com/video"})
        cases = [r"[source \[x\]" + "\n00:12](https://example.org/spec?page=3)",
                 "[source 00:12](\nhttps://example.org/spec?page=3\n)"]
        for note in cases:
            self.assertEqual(_linkify_video_timestamps(note, self.task.page_url), note)
            for kind, links, text in self.artifacts(note):
                with self.subTest(note=note, format=kind):
                    self.assertIn("https://example.org/spec?page=3", links)
                    self.assertFalse(any("t=12" in value for value in links))
                    self.assertIn("00:12", text)

    def test_invalid_link_cannot_suppress_timecodes_across_block_boundaries(self):
        for gap in ("\n\n", "\n```text\ncode\n```\n"):
            note = "[unfinished" + gap + "00:12](https://example.org/spec)"
            self.assertIn("[00:12](https://example.com/video?t=12)",
                          _linkify_video_timestamps(note, "https://example.com/video"))

    def test_surrounding_emphasis_and_heading_links_remain_editable(self):
        note = "## [Source \\[one\\]](https://example.org/heading)\n\n**Before [link](https://example.org/body) after.**"
        for kind, links, text in self.artifacts(note):
            with self.subTest(format=kind):
                self.assertEqual(links, {"https://example.org/heading", "https://example.org/body"})
                self.assertIn("Source [one]", text)
                self.assertIn("Before link after.", text)
                self.assertNotIn("**", text)
        tokens = list(export_inline_tokens("**Before [link](https://example.org/body) after.**"))
        self.assertTrue(all(token.bold for token in tokens if token.text))

    def test_title_deduplication_preserves_a_source_bearing_heading(self):
        note = f"# [{self.task.title}](https://example.org/source)\n\nBody."
        for kind, links, text in self.artifacts(note):
            with self.subTest(format=kind):
                self.assertIn("https://example.org/source", links)
                self.assertIn("Body.", text)

    def test_html_heading_and_toc_apply_existing_text_projection(self):
        note = "## [https://example.org/label?token=DUMMY](https://example.org/source)\n\nBody."
        artifact = build_html_export(self.task, note, export_options={"include_toc": True})
        root = etree.HTML(artifact.content)
        self.assertNotIn("DUMMY", "".join(root.itertext()))
        self.assertIn("https://example.org/source", root.xpath("//a/@href"))

    def test_owned_unicode_anchors_and_independent_parse_state(self):
        source = r"[来源 \[一\]](#section-来源)"
        expected = export_links(source)
        self.assertEqual(expected[0].destination, "#section-来源")
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertTrue(all(value == expected for value in pool.map(export_links, [source] * 64)))

    def test_many_short_links_and_malformed_brackets_remain_bounded(self):
        source = " ".join(f"[source {index}](https://example.org/spec?page={index})" for index in range(2000))
        links = export_links(source)
        self.assertEqual(len(links), 2000)
        self.assertEqual(links[-1].label, "source 1999")
        malformed = "[" * 2000 + "literal"
        self.assertEqual(export_links(malformed), [])
        self.assertEqual("".join(item.text for item in export_inline_tokens(malformed)), malformed)
