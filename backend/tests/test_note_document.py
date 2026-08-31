from __future__ import annotations

import unittest
from unittest.mock import patch

from app.note_document import build_note_document, lint_note_markdown, normalize_note_markdown
from app.models import TaskRecord, now_iso
from app.routers.notes import api_note_document


class NoteDocumentTests(unittest.TestCase):
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
        self.assertEqual(section["verification"], "verified")
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
