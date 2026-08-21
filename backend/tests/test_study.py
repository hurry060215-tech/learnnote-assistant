from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import SourceEvidence
from app.study import due_cards, list_cards, propose_cards, review_card, save_cards, set_card_status


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


if __name__ == "__main__":
    unittest.main()
