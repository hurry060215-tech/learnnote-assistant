"""One synthetic corpus must give the same publication decision at each layer."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.knowledge import extract_import_text_with_metadata
from app.models import TaskOptions, TranscriptResult, TranscriptSegment
from app.note_document import normalize_note_markdown
from app.processor import process_saved_transcript_task
from app.storage import create_task, get_task, task_dir, update_task, write_json
from app.text_cleanup import TextDecodingError, canonicalize_unicode_text, correct_transcript_terms, decode_text_bytes
from app.text_corruption import has_high_confidence_corruption
from app.transcript_quality import transcript_quality_report


CASES = json.loads((Path(__file__).parent / "fixtures/unicode_gate_20261009.json").read_text(encoding="utf-8"))["cases"]


class SharedUnicodeGateTests(unittest.TestCase):
    def test_import_transcript_and_formal_markdown_share_the_fixture_decisions(self):
        for case in CASES:
            text, blocked = case["text"], case["blocked"]
            with self.subTest(case=case["id"]):
                self.assertEqual(has_high_confidence_corruption(text), blocked)
                for codec, kwargs in (("utf-8", {}), ("utf-16", {}), ("gb18030", {"declared_encoding": "gb18030"})):
                    raw = text.encode(codec)
                    if blocked:
                        with self.assertRaisesRegex(TextDecodingError, "text_mojibake_detected"):
                            decode_text_bytes(raw, **kwargs)
                    else:
                        decoded = decode_text_bytes(raw, **kwargs)
                        self.assertEqual(decoded.text, text)
                        self.assertEqual(decoded.raw_sha256, hashlib.sha256(raw).hexdigest())
                        self.assertFalse(decoded.repaired)
                for suffix in ("txt", "md"):
                    if blocked:
                        with self.assertRaisesRegex(ValueError, "text_mojibake_detected"):
                            extract_import_text_with_metadata(f"fixture.{suffix}", text.encode("utf-8"))
                    else:
                        imported, _, _ = extract_import_text_with_metadata(f"fixture.{suffix}", text.encode("utf-8"))
                        self.assertEqual(imported, text)
                for source in ("page-subtitle", "faster-whisper"):
                    for segments in ([], [TranscriptSegment(start=3, end=9, text=text)]):
                        transcript = TranscriptResult(source=source, full_text=text, segments=segments)
                        quality = transcript_quality_report(transcript)
                        self.assertEqual(quality["formal_note_allowed"], not blocked)
                        self.assertEqual(quality["review_required"], blocked)
                        if blocked:
                            self.assertEqual(correct_transcript_terms(transcript), transcript, "Suspicious terms must remain available for explicit review")
                        elif "code" in case["id"] or "fence" in case["id"] or "delimiter" in case["id"]:
                            self.assertEqual(correct_transcript_terms(transcript), transcript, "Code literals must not receive ASR word substitutions")
                note = normalize_note_markdown("合成课程", "## 输入\n\n" + text)
                self.assertEqual(note.report["blocking"], blocked)
                self.assertIn(text, note.markdown, "The gate must report corruption without changing the user's words")

    def test_opt_out_preserves_new_artifacts_and_existing_reversible_repairs_remain(self):
        for text in ("锟斤拷", "鏂囧", "浣犲ソ", "瀛︿", "璇轰"):
            decoded = decode_text_bytes(text.encode("utf-8"), reject_mojibake=False)
            self.assertEqual(decoded.text, text)
            self.assertFalse(decoded.repaired)
            self.assertGreaterEqual(decoded.mojibake_score, 4)
        self.assertEqual(canonicalize_unicode_text("è¯¾ç¨‹æ€»ç»“"), "课程总结")
        self.assertEqual(canonicalize_unicode_text("中文".encode("utf-8").decode("gb18030")), "中文")

    def test_corrupt_saved_transcript_keeps_raw_bytes_and_a_review_draft_without_model_calls(self):
        for text in ("这段锟斤拷内容应被阻断。", "测试鏂囧字幕。"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp, \
                 patch("app.storage.TASK_DIR", Path(temp) / "tasks"), \
                 patch("app.observability.TASK_DIR", Path(temp) / "tasks"), \
                 patch("app.storage.ensure_dirs", lambda: None):
                task = create_task("local", "合成课程")
                transcript = TranscriptResult(source="page-subtitle", full_text=text, segments=[TranscriptSegment(start=3, end=9, text=text)])
                raw_path = write_json(task.id, "transcript_raw.json", transcript.model_dump(mode="json"))
                raw = raw_path.read_bytes()
                corrected = correct_transcript_terms(transcript)
                self.assertEqual(corrected, transcript)
                path = write_json(task.id, "transcript.json", corrected.model_dump(mode="json"))
                update_task(task.id, transcript_path=str(path))
                with patch("app.processor.summarize_with_diagnostics") as summarize:
                    process_saved_transcript_task(task.id, TaskOptions())
                summarize.assert_not_called()
                record = get_task(task.id)
                self.assertEqual(record.error_code, "transcript_review_required")
                self.assertEqual(record.summary_source, "transcript-draft")
                self.assertIn(text, Path(record.note_path).read_text(encoding="utf-8"))
                self.assertFalse((task_dir(task.id) / "note.md").exists())
                self.assertEqual(raw_path.read_bytes(), raw)
                self.assertFalse(record.summary_diagnostics["summary_generated"])
                self.assertEqual(record.summary_diagnostics["transcript_quality"]["issue_kind"], "unicode_corruption")
