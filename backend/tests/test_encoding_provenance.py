from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.downloader import MediaDownloader, _filename_from_content_disposition
from app.knowledge import extract_import_text_with_metadata
from app.main import app
from app.text_cleanup import TextDecodingError, decode_text_bytes


class TextDecoderProvenanceTests(unittest.TestCase):
    def test_declared_charset_is_used_before_automatic_detection(self) -> None:
        source = "第一节\n\n课程介绍中文文本。"
        text, source_type, metadata = extract_import_text_with_metadata(
            "lesson.txt", source.encode("gb18030"), "text/plain; charset=gb18030"
        )

        self.assertEqual(text, source)
        self.assertEqual(source_type, "task")
        self.assertEqual(metadata["encoding"], "gb18030")
        self.assertEqual(metadata["declared_encoding"], "gb18030")
        self.assertEqual(metadata["encoding_source"], "declared-charset")
        self.assertEqual(metadata["encoding_confidence"], "high")
        self.assertEqual(metadata["replacement_character_count"], 0)
        self.assertEqual(metadata["normalization_version"], "nfc-newlines-controls-v1")

    def test_bom_takes_precedence_over_conflicting_declared_charset(self) -> None:
        source = "章节标题\n\nUTF-16 内容。"
        decoded = decode_text_bytes(
            source.encode("utf-16"), declared_encoding="gb18030"
        )

        self.assertEqual(decoded.text, source)
        self.assertEqual(decoded.encoding, "utf-16")
        self.assertEqual(decoded.encoding_source, "bom")
        self.assertEqual(decoded.declared_encoding, "gb18030")
        self.assertEqual(decoded.encoding_confidence, "high")

    def test_explicit_encoding_is_recorded_and_invalid_bytes_are_rejected(self) -> None:
        source = "手动选择的 GB18030 编码。"
        decoded = decode_text_bytes(source.encode("gb18030"), encoding="gb18030")
        self.assertEqual(decoded.text, source)
        self.assertEqual(decoded.encoding_source, "user-selected")
        self.assertEqual(decoded.encoding_confidence, "user_selected")

        with self.assertRaises(TextDecodingError):
            decode_text_bytes(b"valid prefix\xff", encoding="utf-8")

    def test_invalid_percent_encoded_filename_is_not_replaced_silently(self) -> None:
        self.assertEqual(
            _filename_from_content_disposition("attachment; filename*=UTF-8''%FFlesson.mp4"),
            "",
        )
        self.assertEqual(
            _filename_from_content_disposition("attachment; filename*=UTF-8''lesson%20one.mp4"),
            "lesson one.mp4",
        )

    def test_html_meta_charset_is_used_when_http_header_has_none(self) -> None:
        source = '<meta charset="gb18030"><p>网页资料的中文正文。</p>'
        text, source_type, metadata = extract_import_text_with_metadata(
            "page.html", source.encode("gb18030"), "text/html"
        )
        self.assertEqual(source_type, "webpage")
        self.assertEqual(text, "网页资料的中文正文。")
        self.assertEqual(metadata["declared_encoding"], "gb18030")
        self.assertEqual(metadata["encoding_source"], "declared-charset")

    def test_page_scan_respects_http_charset_instead_of_replacing_bad_bytes(self) -> None:
        page_url = "https://course.example/lesson"
        html = '<meta charset="gb18030"><title>中文课程</title><video src="https://cdn.example/lesson.m3u8">'
        body = html.encode("gb18030")

        class Response:
            status_code = 200
            url = page_url
            headers = {"content-type": "text/html; charset=gb18030", "content-length": str(len(body))}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def iter_content(self, chunk_size=0):
                yield body

        with tempfile.TemporaryDirectory() as tmp, patch("app.downloader.requests.request", return_value=Response()):
            downloader = MediaDownloader(Path(tmp) / "task")
            resources = downloader._discover_page_resources(page_url, [], None)

        self.assertTrue(any(item.url == "https://cdn.example/lesson.m3u8" for item in resources))

    def test_page_scan_skips_corrupt_text_instead_of_replacing_bytes(self) -> None:
        page_url = "https://course.example/lesson"
        body = b'<html><body>bad byte \xff <video src="https://cdn.example/lesson.m3u8"></body></html>'

        class Response:
            status_code = 200
            url = page_url
            headers = {"content-type": "text/html; charset=utf-8", "content-length": str(len(body))}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def iter_content(self, chunk_size=0):
                yield body

        with tempfile.TemporaryDirectory() as tmp, patch("app.downloader.requests.request", return_value=Response()):
            downloader = MediaDownloader(Path(tmp) / "task")
            resources = downloader._discover_page_resources(page_url, [], None)

        self.assertEqual(resources, [])
        self.assertEqual(downloader.attempts[-1].code, "text_encoding_unsupported")

    def test_import_form_applies_manual_charset_and_preserves_material_content(self) -> None:
        source = "第一章\n\n手动重选 GB18030 后，资料原文保持完整。"
        raw = source.encode("gb18030")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.config.DATA_DIR", root), \
                 patch("app.config.TASK_DIR", root / "tasks"), \
                 patch("app.config.TEMP_DIR", root / "temp"), \
                 patch("app.library.DATA_DIR", root), \
                 patch("app.library.TASK_DIR", root / "tasks"), \
                 patch("app.library.TEMP_DIR", root / "temp"), \
                 patch("app.knowledge.DATA_DIR", root):
                client = TestClient(app)
                response = client.post(
                    "/api/library/materials/import",
                    data={"encoding": "gb18030"},
                    files={"file": ("lesson.txt", raw, "text/plain")},
                )

                self.assertEqual(response.status_code, 200, response.text)
                material = response.json()["material"]
                self.assertEqual(material["metadata"]["encoding_source"], "user-selected")
                self.assertEqual(material["metadata"]["encoding"], "gb18030")
                self.assertEqual(material["metadata"]["raw_byte_count"], len(raw))
                self.assertEqual(material["metadata"]["normalization_version"], "nfc-newlines-controls-v1")
                content = client.get(f"/api/library/materials/{material['material_id']}/content")
                self.assertEqual(content.status_code, 200, content.text)
                self.assertIn(source, content.json()["text"])

                declared_source = "声明字符集可以供旧导入客户端自动读取。"
                declared_response = client.post(
                    "/api/library/materials/import",
                    files={"file": (
                        "declared.txt",
                        declared_source.encode("gb18030"),
                        "text/plain; charset=gb18030",
                    )},
                )
                self.assertEqual(declared_response.status_code, 200, declared_response.text)
                declared_material = declared_response.json()["material"]
                self.assertEqual(declared_material["metadata"]["encoding_source"], "declared-charset")
                self.assertEqual(declared_material["metadata"]["encoding"], "gb18030")


if __name__ == "__main__":
    unittest.main()
