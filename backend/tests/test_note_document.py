from __future__ import annotations

import unittest
import json
import re
from pathlib import Path
from unittest.mock import patch

from app.note_document import build_note_document, lint_note_markdown, normalize_note_markdown
from app.models import TaskRecord, now_iso
from app.routers.notes import api_note_document


class NoteDocumentTests(unittest.TestCase):
    def test_snapshot_corpus_covers_languages_and_note_shapes(self):
        path = Path(__file__).parent / "fixtures" / "note_structure_golden_20260924.json"
        corpus = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(corpus["schema_version"], 1)
        self.assertGreaterEqual(len(corpus["cases"]), 5)
        self.assertEqual({case["language"] for case in corpus["cases"]}, {"en", "zh"})
        for case in corpus["cases"]:
            with self.subTest(case=case["id"]):
                markdown = (
                    case.get("markdown_prefix", "")
                    + case.get("paragraph", "") * case.get("paragraph_repeat", 1)
                    if case.get("paragraph") else case["markdown"]
                )
                normalized = normalize_note_markdown(case["title"], markdown)
                document = build_note_document(case["title"], normalized.markdown)
                self.assertEqual(
                    [section["heading"] for section in document["sections"]],
                    case["expected_headings"],
                )
                self.assertTrue(set(case.get("expected_issue_codes", [])).issubset(
                    {issue["code"] for issue in normalized.report["issues"]}
                ))
                if "expected_reflowed_paragraphs" in case:
                    self.assertEqual(normalized.report["reflowed_long_paragraphs"], case["expected_reflowed_paragraphs"])
                self.assertIn(
                    case["expected_anchor"],
                    {section["section_id"] for section in document["sections"]},
                )
                self.assertEqual(normalize_note_markdown(case["title"], normalized.markdown).markdown,
                                 normalized.markdown)

    def test_paraphrased_model_title_does_not_block_valid_summary(self):
        result = normalize_note_markdown("原始视频标题 - bilibili", "# 更简洁的总结标题\n\n## 核心观点\n" + "这是材料支持的总结。" * 12)
        self.assertFalse(result.report["blocking"])
        self.assertEqual(result.markdown.splitlines()[0], "# 原始视频标题 - bilibili")
        self.assertEqual(normalize_note_markdown("原始视频标题 - bilibili", result.markdown).markdown, result.markdown)

    def test_later_h1_content_is_preserved_as_section_and_code_untouched(self):
        result = normalize_note_markdown("标题", "介绍内容\n\n# 另一章节\n正文\n\n```python\n# code comment\n```")
        self.assertFalse(result.report["blocking"])
        self.assertIn("## 另一章节", result.markdown)
        self.assertIn("```python\n# code comment\n```", result.markdown)

    def test_code_bytes_and_prompt_examples_do_not_trigger_prose_gates(self):
        code = '```python\nvalue = "Ignore previous instructions"  \nname = "瀛︿範閫�"  \naccent = "e\u0301"  \n```'
        result = normalize_note_markdown("代码课", "## 示例\n\n" + code + "\n\n## 说明\n\n" + ("该示例仅用于说明字符串内容。" * 5) + "[00:10]")
        self.assertIn(code, result.markdown)
        self.assertFalse(result.report["blocking"])
        self.assertNotIn("internal_prompt_leak", {item["code"] for item in result.report["issues"]})
        self.assertNotIn("mojibake_detected", {item["code"] for item in result.report["issues"]})

    def test_long_chinese_prose_wraps_between_sentences_and_heading_levels_are_repaired(self):
        paragraph = "这句话完整说明一个经过证据确认的概念。" * 48
        raw = "## 主要内容\n\n#### 深层主题\n\n" + paragraph
        result = normalize_note_markdown("课程", raw)
        self.assertEqual(result.report["reflowed_long_paragraphs"], 1)
        self.assertEqual(result.report["adjusted_heading_jumps"], 1)
        self.assertIn("### 深层主题", result.markdown)
        self.assertEqual(re.sub(r"\s+", "", paragraph), re.sub(r"\s+", "", result.markdown.split("### 深层主题", 1)[1]))
        self.assertNotIn("long_paragraph", {item["code"] for item in result.report["issues"]})

    def test_section_anchors_do_not_change_when_an_unrelated_heading_is_added(self):
        first = normalize_note_markdown("课程", "## 核心结论\n正文 [00:10]\n\n## 复习\n回忆 [00:20]")
        changed = normalize_note_markdown("课程", "## 新增章节\n新增 [00:05]\n\n## 核心结论\n正文 [00:10]\n\n## 复习\n回忆 [00:20]")
        first_ids = {item["heading"]: item["section_id"] for item in build_note_document("课程", first.markdown)["sections"]}
        changed_ids = {item["heading"]: item["section_id"] for item in build_note_document("课程", changed.markdown)["sections"]}
        self.assertEqual(first_ids["核心结论"], changed_ids["核心结论"])
        self.assertEqual(first_ids["复习"], changed_ids["复习"])

    def test_normalize_removes_wrapper_duplicate_title_and_control_chars(self) -> None:
        result = normalize_note_markdown(
            "梯度下降",
            "```markdown\n# 梯度下降\n\n# 梯度下降\n\x00\n## 定义\n学习率决定步长。[01:23]\n```",
        )
        self.assertEqual(result.markdown.count("# 梯度下降"), 1)
        self.assertNotIn("```markdown", result.markdown)
        self.assertNotIn("\x00", result.markdown)
        self.assertTrue(result.report["changed"])

    def test_mojibake_is_a_blocking_quality_issue(self) -> None:
        issues = lint_note_markdown("# 标题\n\n瀛︿範閫�")
        self.assertTrue(any(item["code"] == "mojibake_detected" and item["severity"] == "error" for item in issues))

    def test_single_latin_character_does_not_false_positive(self) -> None:
        issues = lint_note_markdown("# 标题\n\n葡萄牙语姓名 Ãlvaro 的拼写示例。[00:03]")
        self.assertFalse(any(item["code"] == "mojibake_detected" for item in issues))

    def test_internal_prompt_leak_blocks_and_duplicate_paragraphs_warn(self) -> None:
        paragraph = "这是一段足够长的课程正文，用于验证重复内容检查不会静默放过重复拼接。"
        issues = lint_note_markdown("# 标题\n\n" + paragraph + "\n\n" + paragraph + "\n\n系统提示：不要输出 JSON")
        self.assertTrue(any(item["code"] == "internal_prompt_leak" and item["severity"] == "error" for item in issues))
        self.assertTrue(any(item["code"] == "duplicate_content" and item["severity"] == "warning" for item in issues))

    def test_document_projects_timestamp_citations(self) -> None:
        normalized = normalize_note_markdown("课程", "## 核心概念\n在 12:48–13:05 解释了证据链。")
        document = build_note_document(
            "课程",
            normalized.markdown,
            [{"evidence_id": "ev-1", "locator": "12:48", "text": "证据链"}],
        )
        section = next(item for item in document["sections"] if item["heading"] == "核心概念")
        self.assertEqual(section["citations"][0]["start"], 768.0)
        self.assertEqual(section["citations"][0]["end"], 785.0)
        self.assertIn("ev-1", section["source_evidence_ids"])
        self.assertEqual(section["verification"], "linked")
        self.assertFalse(any(item["heading"] == "课程" and not item["markdown"] for item in document["sections"]))

    def test_note_document_route_reads_by_task_id(self) -> None:
        timestamp = now_iso()
        task = TaskRecord(
            id="task-123",
            title="课程",
            source_type="local",
            created_at=timestamp,
            updated_at=timestamp,
        )
        with patch("app.routers.notes.get_task", return_value=task), \
             patch("app.routers.notes.read_task_note", return_value="# 课程\n\n## 结论\n见 00:12。") as read_note, \
             patch("app.routers.notes.evidence_for_task", return_value=[]):
            payload = api_note_document(task.id)
        read_note.assert_called_once_with(task.id)
        self.assertEqual(payload["task_id"], task.id)
        self.assertEqual(payload["sections"][0]["heading"], "结论")


if __name__ == "__main__":
    unittest.main()
