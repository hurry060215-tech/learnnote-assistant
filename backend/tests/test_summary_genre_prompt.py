"""Prompt contracts only; synthetic responses do not prove provider quality."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from app import summarizer
from app.models import TaskOptions, TranscriptResult, TranscriptSegment


class SummaryGenrePromptTests(unittest.TestCase):
    def test_shared_contract_attributes_opinions_without_inventing_speakers(self):
        contract = summarizer.note_generation_contract(TaskOptions())
        for required in ("访谈或播客保留话题", "各方观点、例子和分歧", "说话人姓名仅在来源明确时使用",
                         "观点应归属于说话人", "不写成已验证事实", "授课材料继续保留概念、推导和例题"):
            self.assertIn(required, contract)
        self.assertNotIn("老师", contract)
        classroom = TaskOptions(note_style="lecture")
        self.assertIn("按授课顺序", summarizer.note_style_instruction(classroom))
        exam = TaskOptions(note_style="exam-review")
        self.assertIn("testable points", summarizer.note_generation_contract(exam))
        self.assertIn("默认不生成自测题", contract)

    def test_actual_text_request_is_neutral_and_keeps_existing_dispatch_shape(self):
        text = "主持人认为先见面更方便，嘉宾对此持保留意见。"
        transcript = TranscriptResult(full_text=text, segments=[TranscriptSegment(start=0, end=10, text=text)])
        options = TaskOptions(llm_api_key="fixture", llm_base_url="http://127.0.0.1:9/v1", llm_model="synthetic")
        completion = NS(choices=[NS(message=NS(content="# 对话记录\n\n" + text), finish_reason="stop")])
        with patch("openai.OpenAI", return_value=object()), patch.object(summarizer, "_compatible_completion", return_value=completion) as create:
            result = summarizer.summarize_with_llm("对话记录", transcript, [], options)
        self.assertEqual(result[1], "text-llm")
        self.assertEqual(create.call_count, 1)
        args = create.call_args.kwargs
        self.assertEqual(args["stage"], "text_summary")
        self.assertEqual(args["temperature"], 0.2)
        prompt = args["messages"][0]["content"][0]["text"]
        self.assertIn("你是严谨的材料阅读笔记助手", prompt)
        self.assertNotIn("课程学习笔记助手", prompt)
        self.assertIn(text, prompt)
        self.assertIn("观点应归属于说话人", prompt)

    def test_repair_retains_source_constraints_without_assuming_a_teacher(self):
        with patch.object(summarizer, "_compatible_completion", return_value=NS(choices=[NS(message=NS(content="材料内容"))])) as create:
            summarizer._repair_grounded_note(object(), "synthetic", {}, "候选内容", TranscriptResult(full_text="材料内容"), [], "", ["empty_note"], [])
        prompt = create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("字幕和画面摘要能支持的材料内容", prompt)
        self.assertIn("来源没有给出的例子", prompt)
        self.assertNotIn("老师", prompt)
        self.assertIn("禁止自行补写英文译名", prompt)
