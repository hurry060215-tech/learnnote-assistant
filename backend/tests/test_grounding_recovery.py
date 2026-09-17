import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.grounding_recovery import omit_unsupported_name_passages
from app.models import TranscriptResult
from app.summarizer import _validated_generated_note, note_grounding_issues


class GroundingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.supported = "他们乘飞机抵达东京，游览博物馆，晚上观看花火大会，最后返回酒店。" * 35
        self.note = "# 东京行程\n\n## 游览\n\n" + self.supported + "\n\n## 行程安排\n\n昨天问 GPT 今天可以去哪里，被告知有花火大会。\n\n## 回程\n\n最后返回酒店。"

    def test_small_name_mismatch_keeps_verified_note_and_retains_audit(self):
        transcript = TranscriptResult(full_text=self.supported + "昨天呢我问GBT说我们今天有什么能去看的。")
        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].message.content = self.note
        events = []
        with tempfile.TemporaryDirectory() as directory:
            result = _validated_generated_note(client, "test", {}, self.note, transcript, [], "", events, artifact_dir=Path(directory))
            audit = json.loads((Path(directory) / "omitted-summary-passages.json").read_text(encoding="utf-8"))
        self.assertIn(self.supported, result)
        self.assertIn("来源核对提示", result)
        self.assertNotIn("GPT", result)
        self.assertNotIn("## 行程安排", result)
        self.assertFalse(audit["published"])
        self.assertIn("GPT", audit["passages"][0])
        self.assertEqual(note_grounding_issues(result, transcript, []), [])
        self.assertEqual(events[-1]["code"], "partial_recovery")

    def test_actual_unsupported_names_still_fail_initial_validation(self):
        issues = note_grounding_issues(self.note, TranscriptResult(full_text=self.supported + "GBT"), [])
        self.assertIn("unsupported_terms:gpt", issues)

    def test_no_omission_for_quantities_code_headings_short_or_large_passages(self):
        cases = [
            (self.note, ["unsupported_quantity:500元"]),
            (self.note + "\n\n```python\nGPT()\n```", ["unsupported_terms:gpt"]),
            (self.note.replace("# 东京行程", "# GPT 行程"), ["unsupported_terms:gpt"]),
            ("# 笔记\n\nGPT 建议。", ["unsupported_terms:gpt"]),
            (self.note + "\n\nGPT " + "无依据的内容。" * 60, ["unsupported_terms:gpt"]),
        ]
        for note, issues in cases:
            with self.subTest(issues=issues, length=len(note)):
                self.assertEqual(omit_unsupported_name_passages(note, issues), ("", []))
