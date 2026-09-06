from __future__ import annotations

from contextlib import ExitStack, closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.knowledge import add_evidence, evidence_by_ids
from app.knowledge import extract_import_text
from app.library import backup_library, restore_library, import_document_material, list_materials, material_content
from app.models import SourceEvidence, StudyCard
from app.note_document import build_note_document, normalize_note_markdown
from app.study import save_cards, due_cards, review_card, study_summary, study_dashboard, update_study_plan, propose_cards


class TrustRegressions(unittest.TestCase):
    def test_course_card_filter_applies_before_limit_and_empty_scope_is_empty(self):
        cards=[StudyCard(front=f"其他课程{i}",back="答案",source_evidence_ids=["other"]) for i in range(35)]
        cards.append(StudyCard(front="目标课程",back="答案",source_evidence_ids=["target"]))
        save_cards(cards)
        selected=due_cards(1,{"target"})
        self.assertEqual([card.front for card in selected],["目标课程"])
        self.assertEqual(due_cards(1,set()),[])

    def test_html_import_preserves_preformatted_code_and_excludes_scripts(self):
        source = '<h1>代码课</h1><p>第一段。</p><pre># comment\n    print(1)</pre><script>private-script</script><p>最后一段。</p>'
        text, kind = extract_import_text("lesson.html", source.encode(), "text/html")
        self.assertEqual(kind, "webpage")
        self.assertIn("# 代码课", text)
        self.assertIn("```\n# comment\n    print(1)\n```", text)
        self.assertNotIn("private-script", text)

    def test_background_heartbeat_survives_a_delayed_two_minute_tick(self):
        from app.main import health_payload
        for elapsed, connected in ((74, True), (121, True), (299, True), (301, False)):
            with patch("app.main._extension_heartbeat_at", 1000), patch("app.main.time.monotonic", return_value=1000 + elapsed):
                self.assertEqual(health_payload()["extension_connected"], connected)

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name in ("library", "knowledge", "study"):
            self.stack.enter_context(patch(f"app.{name}.DATA_DIR", self.root))
        (self.root / "temp").mkdir()
        self.stack.enter_context(patch("app.library.TEMP_DIR", self.root / "temp"))

    def test_restore_index_keeps_materials_sources_and_card_anchors(self):
        original = "# 讲义\n\n```python\n# 参数更新\nweight -= rate * gradient\n```"
        material = import_document_material("lesson.md", original.encode(), "text/markdown")
        evidence = add_evidence(SourceEvidence(text="学习率决定每一步参数更新的步长。", title="来源"))
        save_cards([StudyCard(front="学习率？", back=evidence.text, source_evidence_ids=[evidence.evidence_id])])
        result = restore_library(backup_library())
        self.assertTrue(result["rollback_snapshot_created"])
        self.assertEqual(len(list_materials()), 1)
        self.assertEqual(material_content(material["material_id"]), original)
        self.assertEqual(evidence_by_ids([evidence.evidence_id])[0]["text"], evidence.text)
        self.assertEqual(due_cards()[0].source_evidence_ids, [evidence.evidence_id])

    def test_timestamp_alone_cannot_claim_verification(self):
        result = build_note_document("虚构", "# 虚构\n\n月球由奶酪构成。[00:10]", [])
        self.assertEqual(result["sections"][0]["verification"], "located")
        self.assertEqual(result["quality"]["coverage_ratio"], 0)
        self.assertEqual(result["quality"]["verified_section_count"], 0)

    def test_anchor_matching_is_not_a_substring_or_fact_verification(self):
        evidence = [{"evidence_id": "e1", "text": "原文", "locator": "11:23"}]
        result = build_note_document("课", "# 课\n\n声称。[1:23]", evidence)
        self.assertEqual(result["sections"][0]["source_evidence_ids"], [])
        result = build_note_document("课", "# 课\n\n声称。[11:23]", evidence)
        self.assertEqual(result["sections"][0]["verification"], "linked")
        self.assertEqual(result["quality"]["verified_section_count"], 0)

    def test_code_is_neither_heading_nor_citation(self):
        for fence in ("```", "~~~~", "````"):
            note = f"# 编程\n\n## 演示\n{fence}python\n# 编程\n# 注释\n---\n---\nclock = '12:34'\n{fence}\n"
            result = normalize_note_markdown("编程", note)
            self.assertFalse(result.report["blocking"])
            self.assertIn("# 注释\n---\n---", result.markdown)
            document = build_note_document("编程", result.markdown)
            self.assertEqual(len(document["sections"]), 1)
            self.assertEqual(document["quality"]["citation_count"], 0)

    def test_evidence_preserves_code_and_paragraphs(self):
        text = "定义。\n\n```python\n# comment\n    print(1)\n```"
        item = add_evidence(SourceEvidence(text=text))
        self.assertEqual(evidence_by_ids([item.evidence_id])[0]["text"], text)

    def test_pausing_stops_due_and_review_without_deleting_cards(self):
        card = save_cards([StudyCard(front="问题", back="答案")])[0]
        update_study_plan("暂停", 10, True, "Asia/Shanghai")
        self.assertEqual(due_cards(), [])
        self.assertEqual(study_dashboard()["quiz_queue"], [])
        with self.assertRaisesRegex(ValueError, "study_plan_paused"):
            review_card(card.card_id, 3)
        update_study_plan("恢复", 10, False)
        self.assertEqual(len(due_cards()), 1)

    def test_shanghai_day_and_new_york_dst_use_local_midnight(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 9, 6, 0, 30, tzinfo=timezone.utc)
        card = save_cards([StudyCard(front="问题", back="答案")])[0]
        update_study_plan("本地", 10, False, "Asia/Shanghai")
        review_card(card.card_id, 3)
        with closing(sqlite3.connect(self.root / "study.sqlite3")) as db:
            db.execute("UPDATE study_reviews SET reviewed_at='2026-09-05T17:00:00+00:00'")
            db.commit()
        with patch("app.study.datetime", Clock):
            self.assertEqual(study_summary()["reviewed_today"], 1)
            self.assertEqual(study_dashboard()["progress"]["activity"][-1]["review_count"], 1)
        update_study_plan("纽约", 10, False, "America/New_York")
        with patch("app.study.datetime", Clock):
            self.assertEqual(study_summary()["reviewed_today"], 1)
        with self.assertRaisesRegex(ValueError, "invalid_study_timezone"):
            update_study_plan("无效", 10, False, "../invalid")

    def test_cards_are_short_distinct_source_points(self):
        text = "# 标题\n课程标题：内部模板\n\n学习率决定每一步参数更新的步长，并影响收敛速度。\n梯度提供更新方向，沿负梯度移动可以降低当前损失。\n学习率决定每一步参数更新的步长，并影响收敛速度。"
        cards = propose_cards([SourceEvidence(evidence_id="e1", text=text, title="课")])
        self.assertEqual(len(cards), 2)
        self.assertNotEqual(cards[0].front, cards[1].front)
        self.assertTrue(all(len(card.back) <= 360 and card.source_evidence_ids == ["e1"] for card in cards))

    def test_dst_fall_back_counts_both_occurrences_of_one_thirty(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
        card = save_cards([StudyCard(front="问题", back="答案")])[0]
        update_study_plan("纽约", 10, False, "America/New_York")
        with closing(sqlite3.connect(self.root / "study.sqlite3")) as db:
            for stamp in ("2026-11-01T05:30:00+00:00", "2026-11-01T06:30:00+00:00"):
                db.execute("INSERT INTO study_reviews(card_id,rating,reviewed_at,due_at,stability,difficulty,idempotency_key) VALUES (?,3,?,'',1,1,?)", (card.card_id, stamp, stamp))
            db.commit()
        with patch("app.study.datetime", Clock):
            self.assertEqual(study_summary()["reviewed_today"], 2)
            self.assertEqual(study_dashboard()["progress"]["activity"][-1]["review_count"], 2)


if __name__ == "__main__":
    unittest.main()
