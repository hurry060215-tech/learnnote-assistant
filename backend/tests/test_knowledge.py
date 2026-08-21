from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.knowledge import add_evidence, answer_from_evidence, evidence_for_task, extract_import_text, remove_evidence, search_evidence
from app.models import SourceEvidence


class KnowledgeEvidenceTests(unittest.TestCase):
    def test_import_and_cited_local_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.knowledge.DATA_DIR", root):
                stored = add_evidence(SourceEvidence(
                    source_type="markdown",
                    title="梯度下降",
                    source_uri="local://lesson.md",
                    locator="paragraph 2",
                    text="学习率决定每一步参数更新的步长。",
                ))
                self.assertEqual(stored.schema_version, 1)
                hits = search_evidence("学习率")
                self.assertEqual(hits[0]["evidence_id"], stored.evidence_id)
                answer = answer_from_evidence("学习率")
                self.assertTrue(answer["grounded"])
                self.assertEqual(answer["citations"][0]["locator"], "paragraph 2")

                self.assertEqual(evidence_for_task(""), [])
                self.assertTrue(remove_evidence(stored.evidence_id))
                self.assertEqual(search_evidence("学习率"), [])

    def test_missing_evidence_is_explicitly_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.knowledge.DATA_DIR", Path(tmp)):
                answer = answer_from_evidence("不存在的主题")
                self.assertFalse(answer["grounded"])
                self.assertEqual(answer["citations"], [])

    def test_html_import_strips_script_and_markup(self) -> None:
        text, source_type = extract_import_text("page.html", "<script>secret()</script><h1>标题</h1><p>正文</p>".encode(), "text/html")
        self.assertEqual(source_type, "webpage")
        self.assertIn("标题", text)
        self.assertIn("正文", text)
        self.assertNotIn("secret", text)

    def test_like_fallback_is_used_when_fts_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.knowledge.DATA_DIR", Path(tmp)), patch("app.knowledge._fts_available", return_value=False):
                stored = add_evidence(SourceEvidence(title="Fallback", text="本地检索回退内容"))
                hits = search_evidence("回退")
                self.assertEqual(hits[0]["evidence_id"], stored.evidence_id)


if __name__ == "__main__":
    unittest.main()
