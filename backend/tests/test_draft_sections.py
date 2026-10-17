import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.draft_sections import draft_sections_document
from app.models import TranscriptResult, TranscriptSegment
from app.pipeline_progress import write_progressive_draft
from app.partial_outline_projection import partial_outline
from app.storage import read_json


class TemporalDraftTests(unittest.TestCase):
    def transcript(self, minutes):
        cues = [TranscriptSegment(start=i * 30, end=(i + 1) * 30, text=f"Original source statement {i}.")
                for i in range(minutes * 2)]
        return TranscriptResult(source="browser-subtitle", segments=cues, full_text="\n".join(c.text for c in cues))

    def test_long_outline_covers_tail_with_stable_source_backed_sections(self):
        short = draft_sections_document(self.transcript(30))
        long = draft_sections_document(self.transcript(180))
        self.assertEqual(len(long["sections"]), 36)
        self.assertEqual(long["sections"][:6], short["sections"])
        self.assertEqual(long["sections"][-1]["end"], 10800)
        for section in long["sections"]:
            self.assertEqual(section["status"], "draft")
            self.assertFalse(section["verified"])
            self.assertFalse(section["summary_generated"])
            for excerpt in section["excerpts"]:
                self.assertEqual(excerpt["text"], f"Original source statement {excerpt['source_cue_index']}.")

    def test_sections_are_written_before_draft_ready_and_remain_unverified(self):
        with tempfile.TemporaryDirectory() as tmp, patch("app.storage.TASK_DIR", Path(tmp)), patch("app.observability.TASK_DIR", Path(tmp)):
            transcript = self.transcript(5)
            transcript.segments[0].text = "https://example.test/?token=private-value"
            path = write_progressive_draft("reference", "Reference", transcript)
            text = path.read_text(encoding="utf-8")
            sections = read_json("reference", "draft_sections.json", {})
            self.assertIn("按时间段的阅读提纲", text)
            self.assertIn("不是 AI 主题总结", text)
            self.assertNotIn("private-value", text)
            self.assertNotIn("private-value", str(sections))
            self.assertEqual(sections["schema_version"], 1)
            self.assertFalse(sections["summary_generated"])

    def test_untimed_transcript_does_not_invent_chapter_times(self):
        value = draft_sections_document(TranscriptResult(full_text="No timed cues"))
        self.assertEqual(value["sections"], [])

    def test_pre_preview_serialized_long_cue_outline_still_validates_without_rewriting(self):
        # Frozen output generated with draft_sections.py at 42b1913, before
        # preview wording changed. Do not rebuild this fixture from current code.
        saved = Path(__file__).with_name("fixtures") / "draft_sections_pre_preview_long_cue.json"
        original = saved.read_bytes()
        text = "Synthetic saved long cue. " * 20
        transcript = TranscriptResult(source="browser-subtitle", full_text=text,
            segments=[TranscriptSegment(start=0, end=10, text=text)])
        document = json.loads(original)
        attempt = "abcdef123456"
        with tempfile.TemporaryDirectory() as tmp:
            events = Path(tmp) / "events.jsonl"
            events.write_text("\n".join(json.dumps(event) for event in [
                {"schema_version": 1, "event": "pipeline_attempt_started", "details": {"attempt_id": attempt}},
                {"schema_version": 1, "event": "draft_ready", "details": {"attempt_id": attempt,
                 "artifact": "draft.md", "sections_artifact": "draft_sections.json", "summary_generated": False}},
            ]), encoding="utf-8")
            result = partial_outline(document, transcript, events, attempt)
            self.assertEqual(result["reason"], "ready")
            self.assertEqual(result["revision"], "950ed03b2ca4ce934f20678ec0658f1f3e2c375ddc9976e9e28ecd1f44517a15")
            self.assertEqual(result["sections"][0]["excerpts"][0]["text"], text[:280])
            changed = transcript.model_copy(deep=True)
            changed.segments[0].text = "Different source"
            self.assertEqual(partial_outline(document, changed, events, attempt)["reason"], "invalid_artifact")
        self.assertEqual(document, json.loads(original))
        self.assertEqual(saved.read_bytes(), original)

    def test_preview_discloses_non_contiguous_sampling_and_clipping_without_changing_source(self):
        transcript = self.transcript(240)
        transcript.segments[0].text = "长" * 300
        original = transcript.model_dump_json()
        with tempfile.TemporaryDirectory() as tmp, patch("app.storage.TASK_DIR", Path(tmp)), patch("app.observability.TASK_DIR", Path(tmp)):
            text = write_progressive_draft("sample", "Synthetic", transcript).read_text(encoding="utf-8")
        preview = text.split("## 按时间段", 1)[0]
        self.assertIn("原文抽样（最多 12 条，不保证连续）", preview)
        self.assertIn("按字幕条目位置均匀抽取，不按内容重要性筛选", preview)
        self.assertEqual(preview.count("- `"), 12)
        self.assertIn("长" * 280 + " […]", preview)
        self.assertIn("Original source statement 479.", preview)
        self.assertIn("每 5 分钟抽取至多 3 条原文（首、中、末条）", text)
        self.assertEqual(transcript.model_dump_json(), original)
        # Existing persisted outlines are compared byte-for-byte with this
        # projection; UI clipping labels must not change its saved schema/text.
        section = draft_sections_document(transcript)["sections"][0]
        self.assertEqual(section["excerpts"][0]["text"], "长" * 280)
        self.assertEqual(section["heading_excerpt"], "长" * 80)

    def test_untimed_preview_names_first_lines_and_does_not_offer_timestamp_context(self):
        transcript = TranscriptResult(full_text="\n".join("行" * 300 + str(i) for i in range(15)))
        with tempfile.TemporaryDirectory() as tmp, patch("app.storage.TASK_DIR", Path(tmp)), patch("app.observability.TASK_DIR", Path(tmp)):
            text = write_progressive_draft("untimed", "Synthetic", transcript).read_text(encoding="utf-8")
        self.assertIn("原文开头预览（最多 12 行）", text)
        self.assertIn("无法按时间定位", text)
        self.assertNotIn("点击时间点", text)
        self.assertNotIn("按字幕条目位置均匀抽取", text)
        self.assertIn("当前来源面板不展示未分段文字", text)
        self.assertNotIn("阅读完整字幕", text)
        self.assertEqual(text.count(" […]"), 12)
