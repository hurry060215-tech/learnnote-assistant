"""HTTP subtitle decoding uses only mocked responses and synthetic bytes."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.downloader import DownloadError, MediaDownloader, _preserve_raw_text_artifact
from app.models import ResourceCandidate
from app.text_cleanup import decode_text_bytes, declared_text_encoding


class SubtitleDecodeProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.downloader = MediaDownloader(Path(self.temp.name) / "synthetic-task")
        self.candidate = ResourceCandidate(url="https://example.test/captions.vtt", kind="subtitle")
        self.text = "WEBVTT\r\n\r\n00:00:00.000 --> 00:00:02.000\r\n课程原文，English café 🧭。\r\n"

    def download(self, raw, content_type):
        response = SimpleNamespace(status_code=200, content=raw, headers={"Content-Type": content_type})
        with patch("app.downloader.requests.get", return_value=response) as request:
            output = self.downloader._download_text_file(self.candidate, [], "https://example.test/course", "Synthetic")
        request.assert_called_once()
        return output

    def test_http_charset_and_all_defined_decode_metadata_are_retained_with_original_bytes(self):
        for codec, content_type in (("gb18030", "text/vtt; charset=gb18030"),
                                    ("utf-8", "text/vtt; charset=utf-8"),
                                    ("utf-16", "text/vtt; charset=gb18030")):
            with self.subTest(codec=codec):
                raw = self.text.encode(codec)
                output = self.download(raw, content_type)
                self.assertEqual(output.with_name(output.name + ".raw").read_bytes(), raw)
                expected = decode_text_bytes(raw, declared_encoding=declared_text_encoding(content_type))
                self.assertEqual(output.read_text(encoding="utf-8"), expected.text.strip() + "\n")
                metadata = json.loads(output.with_name(output.name + ".decode.json").read_text(encoding="utf-8"))
                expected_metadata = asdict(expected)
                expected_metadata.pop("text")
                self.assertEqual(metadata, {"schema_version": 1, **expected_metadata, "canonicalized": True})
                self.assertEqual(metadata["encoding_source"], "bom" if codec == "utf-16" else "declared-charset")
                self.assertEqual(metadata["encoding_confidence"], "high")

    def test_conflicting_http_charset_rejects_without_overwriting_previous_artifacts(self):
        raw = self.text.encode("gb18030")
        output = self.download(raw, "text/vtt; charset=gb18030")
        paths = [output, output.with_name(output.name + ".raw"), output.with_name(output.name + ".decode.json")]
        before = {path: path.read_bytes() for path in paths}
        with self.assertRaises(DownloadError) as caught:
            self.download((self.text + "更多原文").encode("gb18030"), "text/vtt; charset=utf-8")
        self.assertEqual(caught.exception.code, "download_forbidden")
        self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_shared_sidecar_writer_keeps_nonzero_replacement_diagnostics_for_literal_code(self):
        # Both the direct HTTP and yt-dlp subtitle paths use this writer.
        raw = "示例 `�` 是代码字面量。".encode("utf-8")
        decoded = decode_text_bytes(raw)
        path = self.downloader.download_dir / "quoted.vtt"
        _preserve_raw_text_artifact(path, raw, decoded)
        metadata = json.loads(path.with_name(path.name + ".decode.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["replacement_character_count"], 1)
        self.assertEqual(metadata["normalization_version"], decoded.normalization_version)
        self.assertEqual(metadata["mojibake_score"], 0)
        self.assertFalse(metadata["repaired"])
        self.assertEqual(path.with_name(path.name + ".raw").read_bytes(), raw)
