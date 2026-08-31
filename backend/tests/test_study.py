from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import SourceEvidence
from app.study import due_cards, export_study_data, get_study_plan, list_cards, propose_cards, review_card, review_history, save_cards, set_card_position, set_card_status, study_dashboard, study_summary, update_study_plan


class StudyLoopTests(unittest.TestCase):
    def test_propose_confirm_and_review_card_locally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.study.DATA_DIR", Path(tmp)):
                proposals = propose_cards([SourceEvidence(
                    evidence_id="e1", title="学习率", source_type="markdown", locator="p2",
                    text="学习率决定每一步参数更新的步长，并影响收敛速度。",
                )])
                self.assertEqual(len(proposals), 1)
                stored = save_cards(proposals)
                self.assertEqual(len(due_cards()), 1)
                reviewed = review_card(stored[0].card_id, 3)
                self.assertEqual(reviewed.reps, 1)
                self.assertGreater(reviewed.stability, 1.0)
                self.assertEqual(due_cards(), [])
                suspended = set_card_status(stored[0].card_id, "suspended")
                self.assertEqual(suspended.status, "suspended")
                self.assertEqual(list_cards("suspended")[0].card_id, stored[0].card_id)
                self.assertEqual(len(review_history(stored[0].card_id)), 1)
                self.assertEqual(study_summary()["reviewed_today"], 1)
                exported = export_study_data()
                self.assertEqual(exported["algorithm"], "fsrs-6.3.2")
                self.assertEqual(len(exported["reviews"]), 1)
                plan = get_study_plan()
                self.assertEqual(plan.daily_target, 10)
                updated_plan = update_study_plan("复习", 20, True)
                self.assertEqual(updated_plan.daily_target, 20)
                self.assertTrue(updated_plan.paused)
                reordered = set_card_position(stored[0].card_id, 42)
                self.assertEqual(reordered.position, 42)

    def test_dashboard_combines_due_quiz_mistakes_and_progress_locally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.study.DATA_DIR", Path(tmp)):
                proposals = propose_cards([
                    SourceEvidence(evidence_id="e1", title="课程", text="第一段内容足够长，可以创建第一张有依据的复习卡片。"),
                    SourceEvidence(evidence_id="e2", title="课程", text="第二段内容也足够长，可以创建第二张有依据的复习卡片。"),
                ])
                stored = save_cards(proposals)
                review_card(stored[0].card_id, 1)
                dashboard = study_dashboard(limit=10, activity_days=7)
                self.assertEqual(dashboard["privacy"]["storage"], "local-only")
                self.assertFalse(dashboard["privacy"]["accounts_required"])
                self.assertTrue(any(item["card_id"] == stored[0].card_id for item in dashboard["mistakes"]))
                self.assertTrue(any(item["quiz_id"] == f"card-{stored[1].card_id}" for item in dashboard["quiz_queue"]))
                self.assertEqual(len(dashboard["progress"]["activity"]), 7)
                self.assertTrue(all("back" not in item and item["answer_included"] is False for item in dashboard["due_cards"]))

    def test_review_idempotency_and_deleted_cards_stay_out_of_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.study.DATA_DIR", Path(tmp)):
                card = save_cards(propose_cards([SourceEvidence(
                    evidence_id="e1", title="课程", text="这是一段足够长且有明确证据来源的复习卡片内容，可以用于测试。",
                )]))[0]
                first = review_card(card.card_id, 3, "review-once")
                duplicate = review_card(card.card_id, 3, "review-once")
                self.assertEqual(first.reps, 1)
                self.assertEqual(duplicate.reps, 1)
                self.assertEqual(len(review_history(card.card_id)), 1)
                set_card_status(card.card_id, "deleted")
                exported = export_study_data()
                self.assertEqual(exported["cards"], [])
                self.assertEqual(exported["reviews"], [])


if __name__ == "__main__":
    unittest.main()
