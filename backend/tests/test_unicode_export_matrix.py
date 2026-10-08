"""Offline Unicode propagation and lossless local Notion request-plan contracts."""
from __future__ import annotations

import codecs
from contextlib import ExitStack
from io import BytesIO
import json
import unicodedata
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from docx import Document
from pypdf import PdfReader

from app.document_exports import build_docx_export, build_html_export, build_pdf_export
from app.integrations import notion_export_payload
from app.main import api_export_bundle, api_export_markdown, api_export_sanitized_bundle
from app.models import TaskRecord
from app.note_document import normalize_note_markdown
from app.text_cleanup import decode_text_bytes


MIXED_TEXT = "中文学习；日本語の勉強；English cafe\u0301；导航 🧭；公式 E = mc²"
NFC_TEXT = unicodedata.normalize("NFC", MIXED_TEXT)


def export_task(title: str = "Unicode 学习笔记") -> TaskRecord:
    return TaskRecord(
        id="unicode-export-fixture", source_type="local", mode="local", title=title,
        status="success", phase="completed",
        created_at="2026-09-01T00:00:00+00:00", updated_at="2026-09-01T00:00:00+00:00",
    )


def rich_text_value(pieces: list[dict]) -> str:
    return "".join(piece["text"]["content"] for piece in pieces)


def notion_blocks(payload: dict) -> list[dict]:
    return payload["children"] + [block for batch in payload["append_batches"] for block in batch["children"]]


def block_text(block: dict) -> str:
    return rich_text_value(block[block["type"]]["rich_text"])


class NotionUnicodeBatchTests(unittest.TestCase):
    def assert_request_limits(self, payload: dict) -> None:
        requests = [{key: payload[key] for key in ("parent", "properties", "children")}, *payload["append_batches"]]
        self.assertEqual(payload["metadata"]["batch_count"], len(requests))
        self.assertEqual(payload["metadata"]["block_count"], len(notion_blocks(payload)))
        self.assertFalse(payload["metadata"]["content_truncated"])
        self.assertFalse(payload["privacy"]["network_request_performed"])
        for request in requests:
            self.assertLessEqual(len(request["children"]), 100)
            # Check the larger escaped, pretty-printed representation as well
            # as UTF-8 output, including create-page parent and title overhead.
            for ensure_ascii in (False, True):
                self.assertLess(len(json.dumps(request, ensure_ascii=ensure_ascii, indent=2).encode("utf-8")), 450_000)
            for block in request["children"]:
                pieces = block[block["type"]]["rich_text"]
                self.assertLessEqual(len(pieces), 8)
                for piece in pieces:
                    content = piece["text"]["content"]
                    self.assertLessEqual(len(content.encode("utf-16-le")) // 2, 2000)
                    self.assertNotIn("\ufffd", content)
        title = payload["properties"]["title"]["title"]
        self.assertLessEqual(len(title), 100)
        for piece in title:
            self.assertLessEqual(len(piece["text"]["content"].encode("utf-16-le")) // 2, 2000)

    def test_long_unicode_paragraph_and_title_are_not_silently_truncated(self) -> None:
        paragraph = MIXED_TEXT * 550
        title = MIXED_TEXT * 80
        payload = notion_export_payload(export_task(title), paragraph, {"segments": [{"text": "local"}]})
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual("".join(map(block_text, notion_blocks(payload))), unicodedata.normalize("NFC", paragraph))
        self.assertEqual(rich_text_value(payload["properties"]["title"]["title"]), unicodedata.normalize("NFC", title))
        self.assertGreater(len(notion_blocks(payload)), 1)
        self.assertEqual(payload["metadata"]["transcript_segment_count"], 1)
        self.assert_request_limits(payload)

    def test_astral_characters_at_chunk_boundary_remain_complete(self) -> None:
        paragraph = "中" * 1999 + "🧭" + "文" * 1998 + "🧭尾"
        payload = notion_export_payload(export_task(), paragraph)
        pieces = payload["children"][0]["paragraph"]["rich_text"]
        self.assertEqual(pieces[0]["text"]["content"], "中" * 1999)
        self.assertTrue(pieces[1]["text"]["content"].startswith("🧭"))
        self.assertEqual(rich_text_value(pieces), paragraph)
        self.assert_request_limits(payload)

    def test_more_than_one_thousand_blocks_remain_ordered_in_append_batches(self) -> None:
        paragraphs = [f"第 {index:04d} 段：{NFC_TEXT}" for index in range(1205)]
        payload = notion_export_payload(export_task(), "\n\n".join(paragraphs))
        self.assertEqual(list(map(block_text, notion_blocks(payload))), paragraphs)
        self.assertEqual(payload["metadata"]["block_count"], 1205)
        self.assertEqual(payload["metadata"]["batch_count"], 13)
        self.assertEqual(len(payload["children"]), 100)
        self.assert_request_limits(payload)

    def test_byte_budget_splits_before_the_block_count_limit(self) -> None:
        paragraphs = [f"{index:02d}:" + "中🧭" * 4000 for index in range(40)]
        payload = notion_export_payload(export_task(), "\n\n".join(paragraphs))
        self.assertGreater(len(payload["append_batches"]), 1)
        self.assertLess(len(payload["children"]), 100)
        self.assertEqual(list(map(block_text, notion_blocks(payload))), paragraphs)
        self.assert_request_limits(payload)

    def test_create_page_budget_includes_large_title(self) -> None:
        title = "中" * 65_000
        paragraphs = ["文" * 15_000 for _ in range(3)]
        payload = notion_export_payload(export_task(title), "\n\n".join(paragraphs))
        self.assertEqual(payload["children"], [])
        self.assertEqual(rich_text_value(payload["properties"]["title"]["title"]), title)
        self.assertEqual(list(map(block_text, notion_blocks(payload))), paragraphs)
        self.assert_request_limits(payload)

    def test_unrepresentable_title_is_rejected_instead_of_truncated(self) -> None:
        for title, reason in (("a" * 200_001, "rich_text"), ("中" * 80_000, "request")):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, f"notion_title_exceeds_{reason}_limit"):
                notion_export_payload(export_task(title), "正文")

    def test_shared_structure_preserves_code_indentation_and_block_kinds(self) -> None:
        note = (
            "---\nsource: machine-only metadata\n---\n\n"
            "# 标题\n\n## 章节\n\n### 小节\n\n#### 深层标题\n\n"
            "- 中文要点\n1. 顺序步骤\n> 日本語の引用\n\n"
            "```python\nif ready:\n    print('中文 🧭')  \n\n    return value\n```\n\n"
            "    if nested:\n        print('indented café')  \n\n"
            "| Column | Value |\n| --- | --- |\n| Unicode | 中文 🧭 |\n"
        )
        payload = notion_export_payload(export_task(), note)
        blocks = notion_blocks(payload)
        self.assertEqual([block["type"] for block in blocks[:7]], [
            "heading_1", "heading_2", "heading_3", "heading_3", "bulleted_list_item", "numbered_list_item", "quote",
        ])
        code = [block for block in blocks if block["type"] == "code"]
        self.assertEqual(block_text(code[0]), "if ready:\n    print('中文 🧭')  \n\n    return value")
        self.assertIn("if nested:\n    print('indented café')  ", block_text(code[1]))
        self.assertTrue(all(block["code"]["language"] == "plain text" for block in code))
        self.assertIn("| Unicode | 中文 🧭 |", block_text(blocks[-1]))
        self.assertNotIn("machine-only metadata", json.dumps(payload))
        self.assert_request_limits(payload)

    def test_redaction_happens_before_chunking_and_applies_to_later_batches(self) -> None:
        lines = ["中" * 1994 + " Authorization: Bearer BOUNDARY_SECRET"]
        lines.extend(f"段落 {index}" for index in range(105))
        lines.extend([
            "Cookie: SESSION_SECRET\nSafe study content after the credential line.",
            "[source](https://example.com/video?v=public&token=SIGNED_SECRET)",
            "```text\n    api_key = CODE_SECRET\n    visible = '中文 🧭'\n```",
        ])
        payload = notion_export_payload(export_task("Authorization: Bearer TITLE_SECRET"), "\n\n".join(lines))
        serialized = json.dumps(payload, ensure_ascii=False)
        for secret in ("BOUNDARY_SECRET", "SESSION_SECRET", "SIGNED_SECRET", "CODE_SECRET", "TITLE_SECRET"):
            self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertIn("https://example.com/video?v=public", serialized)
        self.assertIn("中文 🧭", serialized)
        self.assertIn("Safe study content after the credential line.", serialized)
        self.assertTrue(payload["append_batches"])
        self.assert_request_limits(payload)

    def test_empty_note_still_has_an_explicit_nontruncated_plan(self) -> None:
        payload = notion_export_payload(export_task(), "")
        self.assertEqual(payload["children"], [])
        self.assertEqual(payload["append_batches"], [])
        self.assertEqual(payload["metadata"], {"block_count": 0, "batch_count": 1, "content_truncated": False})
        self.assert_request_limits(payload)


class UnicodeCrossOutputMatrixTests(unittest.TestCase):
    def test_authoritative_decodings_reach_every_export_from_one_normalized_note(self) -> None:
        inputs = [
            ("utf-8", MIXED_TEXT.encode("utf-8"), {}, "strict-utf8"),
            ("utf-8-bom", MIXED_TEXT.encode("utf-8-sig"), {}, "bom"),
            ("utf-16-le-bom", codecs.BOM_UTF16_LE + MIXED_TEXT.encode("utf-16-le"), {}, "bom"),
            ("utf-16-be-bom", codecs.BOM_UTF16_BE + MIXED_TEXT.encode("utf-16-be"), {}, "bom"),
            ("declared-gb18030", MIXED_TEXT.encode("gb18030"), {"declared_encoding": "gb18030"}, "declared-charset"),
        ]
        normalized_notes: list[str] = []
        task = export_task()
        for label, raw, kwargs, encoding_source in inputs:
            with self.subTest(encoding=label):
                decoded = decode_text_bytes(raw, source=label, **kwargs)
                self.assertEqual(decoded.text, NFC_TEXT)
                self.assertEqual(decoded.encoding_source, encoding_source)
                self.assertEqual(decoded.replacement_character_count, 0)
                note = normalize_note_markdown(task.title, "## 混合文字\n\n" + decoded.text).markdown
                normalized_notes.append(note)
                self.assertTrue(unicodedata.is_normalized("NFC", note))
                transcript = {"segments": [{"start": 0, "end": 3, "text": decoded.text}]}
                # Exercise the actual download handlers with only local task
                # and artifact reads replaced. No provider or browser is used.
                with ExitStack() as stack:
                    for name, result in {
                        "get_task": task, "read_note": note, "read_transcript": transcript,
                        "read_visual_index": {"windows": []}, "read_task_qa_history": [],
                        "read_json": {}, "read_resource_inventory": {}, "read_page_preflight_report": {},
                    }.items():
                        stack.enter_context(patch(f"app.main.{name}", return_value=result))
                    markdown = api_export_markdown(task.id)
                    bundle = api_export_bundle(task.id)
                    sanitized = api_export_sanitized_bundle(task.id)
                self.assertEqual(markdown.body.decode("utf-8"), note)
                self.assertIn("charset=utf-8", markdown.headers["content-type"])
                for response in (bundle, sanitized):
                    with ZipFile(BytesIO(response.body)) as archive:
                        self.assertEqual(archive.read("note.md").decode("utf-8"), note)
                        self.assertEqual(json.loads(archive.read("transcript.json"))["segments"][0]["text"], NFC_TEXT)
                notion = notion_export_payload(task, note, transcript)
                self.assertIn(NFC_TEXT, "\n".join(map(block_text, notion_blocks(notion))))
                html = build_html_export(task, note).content.decode("utf-8")
                self.assertIn(NFC_TEXT, html)
                docx = build_docx_export(task, note)
                self.assertIn(NFC_TEXT, "\n".join(paragraph.text for paragraph in Document(BytesIO(docx.content)).paragraphs))
                pdf = build_pdf_export(task, note)
                extracted = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf.content)).pages)
                for expected in ("中文学习", "日本語の勉強", "English café", "导航", "[compass]", "E = mc²"):
                    self.assertIn(expected, extracted)
                self.assertIn(
                    "".join(NFC_TEXT.replace("🧭", "[compass]").split()),
                    "".join(extracted.split()),
                )
                self.assertNotIn("\ufffd", extracted)
                self.assertIn("non_bmp_symbols_rendered_as_unicode_names", pdf.warnings)
        self.assertEqual(len(set(normalized_notes)), 1)


if __name__ == "__main__":
    unittest.main()
