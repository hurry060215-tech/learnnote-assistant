import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.learning_spaces import (
    EXISTING_REVIEW_ID,
    get_learning_space,
    list_learning_spaces,
    migrate_courses_to_learning_spaces,
    save_learning_space,
    save_space_practice,
)
from app.models import StudyCard
from app.study import assign_cards_to_space, save_cards, unassigned_cards


class LearningSpaceTests(unittest.TestCase):
    def test_legacy_course_migration_is_idempotent_and_preserves_source_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            courses = root / "courses"
            courses.mkdir()
            (courses / ("a" * 32 + ".json")).write_text(
                '{"title":"旧课程","sources":[{"kind":"task","id":"task-1","title":"旧标题"}],"paused":false,"revision":3}',
                encoding="utf-8",
            )
            with patch("app.learning_spaces.DATA_DIR", root), patch("app.learning_spaces._live_source", return_value=("当前标题", "rev-1", "https://example.test/video")):
                first = migrate_courses_to_learning_spaces()
                second = migrate_courses_to_learning_spaces()
                self.assertEqual(first["migrated"], 1)
                self.assertEqual(second["migrated"], 0)
                spaces = list_learning_spaces()
                migrated = next(item for item in spaces if item["id"] == "a" * 32)
                self.assertEqual(migrated["title"], "旧课程")
                self.assertEqual(get_learning_space(migrated["id"])["sources"][0]["id"], "task-1")
                self.assertTrue(any(item["id"] == EXISTING_REVIEW_ID for item in spaces))

    def test_save_space_practice_deduplicates_and_keeps_evidence_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = {"e1": {"evidence_id": "e1", "title": "资料", "text": "原文", "locator": "0-2s", "metadata": {}}}
            with patch("app.learning_spaces.DATA_DIR", root), patch("app.learning_spaces._live_source", return_value=("资料", "rev", "")), patch("app.learning_spaces.space_evidence", return_value=list(evidence.values())):
                space = save_learning_space("空间", [])
                items = [{"question": "问题", "answer": "答案", "source_evidence_ids": ["e1"]}]
                self.assertEqual(len(save_space_practice(space["id"], items)), 1)
                self.assertEqual(len(save_space_practice(space["id"], items)), 1)
                self.assertEqual(len(get_learning_space(space["id"])["sources"]), 0)

    def test_existing_review_excludes_cards_assigned_to_a_learning_space(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("app.learning_spaces.DATA_DIR", root), patch("app.study.DATA_DIR", root):
                space = save_learning_space("空间", [])
                card = save_cards([StudyCard(front="同一张卡", back="同一答案", source_evidence_ids=["e1"])])[0]
                self.assertEqual(len(unassigned_cards()), 1)
                assign_cards_to_space(space["id"], card_ids=[card.card_id])
                self.assertEqual(unassigned_cards(), [])


if __name__ == "__main__":
    unittest.main()
