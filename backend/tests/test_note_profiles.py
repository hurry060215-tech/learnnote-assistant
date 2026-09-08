from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from app.models import FrameGrid, TaskOptions, TranscriptResult, TranscriptSegment
from app.summarizer import local_markdown_note, note_generation_contract, note_grounding_issues, note_style_instruction, note_template_instruction
from app.summarizer import _validated_generated_note


class NoteProfileTests(unittest.TestCase):
    def test_rejected_name_translation_is_retained_for_local_diagnosis(self):
        transcript = TranscriptResult(full_text="入住阿曼基沃酒店。")
        client = MagicMock()
        candidate = "# 酒店体验\n\n入住阿曼基沃（Amanjiwo）酒店。"
        client.chat.completions.create.return_value.choices[0].message.content = candidate
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = _validated_generated_note(client, "test-model", {}, candidate, transcript, [], "", events, artifact_dir=Path(tmp))
            self.assertEqual(result, "")
            self.assertEqual((Path(tmp) / "rejected-summary.md").read_text(encoding="utf-8"), candidate)
            self.assertFalse((Path(tmp) / "note.md").exists())
        self.assertEqual(events[-1]["code"], "rejected")
        repair_prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("unsupported_terms:amanjiwo", repair_prompt)
        self.assertIn("保留材料支持的对应中文解释", repair_prompt)

    def test_travel_duration_is_not_claimed_video_duration(self):
        transcript = TranscriptResult(source="faster-whisper", full_text="坐7小时专属列车，前往酒店入住。",
            segments=[TranscriptSegment(start=0, end=1857, text="坐7小时专属列车，前往酒店入住。")])
        for text in ("视频记录了乘坐7小时列车前往酒店的过程。", "该视频探访了要花7小时才能到达的酒店。", "本材料描述坐7小时火车的旅行体验。"):
            with self.subTest(text=text):
                self.assertEqual(note_grounding_issues("# 酒店探访\n\n" + text, transcript, []), [])
        for text in ("本视频时长为7小时。", "视频总时长约7小时。", "这节微课共7小时。"):
            with self.subTest(text=text):
                self.assertTrue(any(i.startswith("duration_mismatch:") for i in note_grounding_issues(text, transcript, [])))

    def test_editorial_english_labels_do_not_count_as_unsupported_facts(self):
        transcript = TranscriptResult(full_text="梯度决定方向，学习率决定步长。")
        note = "# TL;DR\n\n梯度决定方向。\n\n## Key takeaways\n\n学习率决定步长。\n\n## Overview\n\n梯度与学习率配合。"
        self.assertEqual(note_grounding_issues(note, transcript, []), [])

    def test_grounding_rejects_wrong_duration_and_unsupported_terms(self):
        transcript = TranscriptResult(
            language="zh",
            segments=[TranscriptSegment(start=0, end=96, text="梯度决定方向，学习率决定步长。")],
            full_text="梯度决定方向，学习率决定步长。",
            source="faster-whisper",
        )
        grids = [FrameGrid(path="grid.jpg", start=0, end=96, frame_count=2, frame_timestamps=[0, 90], url="/grid.jpg")]
        issues = note_grounding_issues(
            "这节微课共 6 分钟。\n## 例题\n使用 Adam、Kaggle 和 NumPy 完成练习。",
            transcript,
            grids,
        )
        self.assertTrue(any(item.startswith("duration_mismatch:") for item in issues))
        self.assertTrue(any(item.startswith("unsupported_terms:") for item in issues))
        self.assertIn("unsupported_example_section", issues)

    def test_grounding_accepts_source_supported_note(self):
        transcript = TranscriptResult(
            language="zh",
            segments=[TranscriptSegment(start=0, end=96, text="梯度决定方向，学习率决定步长。")],
            full_text="梯度决定方向，学习率决定步长。",
            source="faster-whisper",
        )
        grids = [FrameGrid(path="grid.jpg", start=0, end=96, frame_count=2, frame_timestamps=[0, 90], url="/grid.jpg")]
        note = "# 梯度下降\n\n- 梯度决定方向。\n- 学习率决定步长。\n\n## 自测题\n\n学习率控制什么？"
        self.assertEqual(note_grounding_issues(note, transcript, grids), [])

    def test_custom_profile_enters_generation_contract(self):
        options = TaskOptions(
            note_style="custom",
            note_profile_name="Research review",
            note_profile_prompt="Organize claims by evidence strength.",
            note_profile_sections=["Question", "Evidence", "Limitations"],
        )
        contract = note_generation_contract(options)
        self.assertIn("Research review", contract)
        self.assertIn("Organize claims by evidence strength.", contract)
        self.assertIn("Question、Evidence、Limitations", contract)
        self.assertIn("真实性", contract)
        self.assertIn("Research review", note_style_instruction(options))

    def test_profile_limits_are_enforced(self):
        with self.assertRaises(ValueError):
            TaskOptions(note_profile_prompt="x" * 4001)
        with self.assertRaises(ValueError):
            TaskOptions(note_profile_sections=[str(index) for index in range(17)])

    def test_operation_tutorial_contract_requires_evidenced_actions(self):
        options = TaskOptions(note_style="operation-tutorial", note_template="operation-tutorial")

        contract = note_generation_contract(options)
        combined = " ".join([contract, note_style_instruction(options), note_template_instruction(options)]).lower()

        for required in ("steps", "interface changes", "commands", "common errors", "evidence"):
            self.assertIn(required, combined)
        self.assertIn("omit unsupported", combined)

    def test_new_note_use_cases_are_mapped_to_prompts(self):
        for use_case in ("classroom-review", "exam-review", "quick-summary"):
            options = TaskOptions(note_style=use_case, note_template=use_case)
            self.assertNotEqual(note_style_instruction(options), note_style_instruction(TaskOptions()))
            self.assertNotEqual(note_template_instruction(options), note_template_instruction(TaskOptions()))

    def test_operation_tutorial_local_fallback_uses_actionable_sections(self):
        transcript = TranscriptResult(
            source="faster-whisper",
            full_text=(
                "Open settings. Select the model provider. Run docker pull example/image. "
                "If the connection fails, check the API key."
            ),
            segments=[
                TranscriptSegment(start=0, end=2, text="Open settings"),
                TranscriptSegment(start=2, end=4, text="Select the model provider"),
                TranscriptSegment(start=4, end=7, text="Run docker pull example/image"),
                TranscriptSegment(start=7, end=10, text="If the connection fails, check the API key"),
            ],
        )
        grids = [FrameGrid(path="grid.jpg", url="/grid.jpg", start=0, end=10, frame_count=2, frame_timestamps=[0, 7])]
        note = local_markdown_note(
            "Docker setup",
            transcript,
            grids,
            options=TaskOptions(note_style="operation-tutorial", note_template="visual-handout", summary_depth="deep"),
        )

        for heading in ("## 操作步骤", "## 界面变化", "## 命令与参数", "## 常见错误与处理"):
            self.assertIn(heading, note)
        self.assertIn("`docker pull example/image`", note)
        self.assertIn("00:00:07", note)
        self.assertNotIn("## 概念精讲", note)
        self.assertNotIn("学习目标与笔记格式", note)
        self.assertNotIn("旧风格兼容", note)

    def test_operation_tutorial_does_not_turn_narration_into_a_command(self):
        transcript = TranscriptResult(
            source="faster-whisper",
            full_text="Docker installation starts by opening settings. Save the configuration.",
            segments=[
                TranscriptSegment(start=0, end=3, text="Docker installation starts by opening settings"),
                TranscriptSegment(start=3, end=5, text="Save the configuration"),
            ],
        )

        note = local_markdown_note(
            "Docker setup",
            transcript,
            [],
            options=TaskOptions(note_style="operation-tutorial", note_template="visual-handout", summary_depth="deep"),
        )

        self.assertIn("材料中未出现可逐字核对的完整命令", note)
        self.assertNotIn("`Docker installation starts by opening settings`", note)


if __name__ == "__main__":
    unittest.main()
