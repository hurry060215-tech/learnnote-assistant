from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.claims import build_claim_evidence_map
from app.knowledge import add_evidence, extract_import_text_with_metadata, preserve_raw_import, redecode_evidence
from app.learning_spaces import (
    get_learning_space,
    preview_space_sources,
    refresh_space_sources,
    save_learning_space,
    save_space_practice,
    update_space_practice,
)
from app.models import SourceEvidence, TranscriptResult, TranscriptSegment
from app.processor import browser_subtitle_text_is_player_ui


class CloseoutEvidenceTests(unittest.TestCase):
    def test_import_records_encoding_and_can_redecode_preserved_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = "中文编码资料".encode("gb18030")
            with patch("app.knowledge.DATA_DIR", root):
                text, source_type, decoding = extract_import_text_with_metadata("lesson.txt", raw, "text/plain")
                raw_info = preserve_raw_import(raw, "lesson.txt")
                stored = add_evidence(SourceEvidence(
                    evidence_id="encoding-case",
                    source_type=source_type,
                    title="lesson",
                    text=text,
                    metadata={**decoding, "filename": "lesson.txt", "content_type": "text/plain", "raw_sha256": raw_info["sha256"], "raw_byte_count": raw_info["byte_count"]},
                ))
                refreshed = redecode_evidence(stored.evidence_id, "gb18030")
            self.assertEqual(refreshed["text"], "中文编码资料")
            self.assertEqual(refreshed["metadata"]["encoding"], "gb18030")
            self.assertEqual(refreshed["metadata"]["raw_sha256"], raw_info["sha256"])

    def test_claims_expose_direct_located_and_review_boundaries(self):
        transcript = TranscriptResult(segments=[TranscriptSegment(start=0, end=10, text="梯度下降通过学习率控制更新步长。")], full_text="梯度下降通过学习率控制更新步长。")
        result = build_claim_evidence_map("ej", "证据", "# 证据\n\n[00:00-00:10] 梯度下降通过学习率控制更新步长。\n\n这一现象可能意味着模型一定收敛。", transcript)
        self.assertEqual(result["schema_version"], 5)
        self.assertEqual(result["claims"][0]["verification"], "direct")
        self.assertEqual(result["claims"][1]["verification"], "inference")
        self.assertEqual(result["source_revision_kind"], "normalized_note_utf8_sha256")

    def test_bilibili_control_values_are_rejected_as_subtitles(self):
        self.assertTrue(browser_subtitle_text_is_player_ui("背景不透明度 87%"))
        self.assertTrue(browser_subtitle_text_is_player_ui("B站自研的AI原声翻译功能"))
        self.assertFalse(browser_subtitle_text_is_player_ui("今天我们比较两家超市的价格"))


class CloseoutLearningSpaceTests(unittest.TestCase):
    def test_source_revision_requires_explicit_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("app.learning_spaces.DATA_DIR", root), patch("app.learning_spaces._live_source", return_value=("资料", "rev-1", "local://one")):
                space = save_learning_space("空间", [{"kind": "task", "id": "task-1", "title": "资料"}])
                with patch("app.learning_spaces._live_source", return_value=("资料", "rev-2", "local://one")):
                    preview = preview_space_sources(space["id"], [{"kind": "task", "id": "task-1"}])
                    self.assertEqual(preview["stale_count"], 1)
                    unchanged = save_learning_space("改了目标", [{"kind": "task", "id": "task-1"}], goal="新目标", space_id=space["id"], revision=space["revision"])
                    self.assertEqual(unchanged["sources"][0]["source_revision"], "rev-1")
                    refreshed = refresh_space_sources(space["id"], ["task:task-1"])
                self.assertEqual(refreshed["space"]["sources"][0]["source_revision"], "rev-2")

    def test_practice_update_keeps_source_reference_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = [{"evidence_id": "e1", "title": "资料", "text": "来源内容足够长", "locator": "0-2s", "metadata": {}}]
            with patch("app.learning_spaces.DATA_DIR", root), patch("app.learning_spaces.space_evidence", return_value=evidence):
                space = save_learning_space("空间", [])
                item = save_space_practice(space["id"], [{"question": "旧问题", "answer": "旧答案", "source_evidence_ids": ["e1"]}])[0]
                updated = update_space_practice(space["id"], item["id"], "新问题", "新答案", ["e1"])
                saved_space = get_learning_space(space["id"])
            self.assertEqual(updated["question"], "新问题")
            self.assertEqual(updated["source_evidence_ids"], ["e1"])
            self.assertEqual(saved_space["title"], "空间")


if __name__ == "__main__":
    unittest.main()
