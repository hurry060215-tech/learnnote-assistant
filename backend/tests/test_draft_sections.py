import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.draft_sections import draft_sections_document
from app.models import TranscriptResult, TranscriptSegment
from app.pipeline_progress import write_progressive_draft
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
