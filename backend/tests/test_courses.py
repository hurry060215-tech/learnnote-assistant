from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.courses import save_course, get_course, list_courses, delete_course, compare_course


class CourseTests(unittest.TestCase):
    def test_reorder_pause_and_conflict_protection_preserve_source_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.txt"
            source.write_text("preserve")
            with patch("app.courses.DATA_DIR", Path(directory)), patch("app.courses.get_task", side_effect=lambda key: SimpleNamespace(title=key)):
                course = save_course("课程", [{"kind":"task","id":"one"},{"kind":"task","id":"two"},{"kind":"task","id":"one"}])
                self.assertEqual(len(course["sources"]), 2)
                changed = save_course("课程", list(reversed(course["sources"])), True, course["id"], course["revision"])
                self.assertEqual(get_course(course["id"])["sources"][0]["id"], "two")
                self.assertTrue(changed["paused"])
                with self.assertRaisesRegex(ValueError, "course_changed"):
                    save_course("过时写入", [], False, course["id"], course["revision"])
                delete_course(course["id"])
                self.assertEqual(list_courses(), [])
                self.assertTrue(source.exists())

    def test_cooccurrence_edges_reference_the_actual_shared_term(self):
        evidence = {
            "one": [{"evidence_id":"a","locator":"0-10s","text":"学习率决定步长。"},{"evidence_id":"b","locator":"10-20s","text":"梯度表示更新方向。"}],
            "two": [{"evidence_id":"c","locator":"5-15s","text":"梯度可以用于优化。"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.courses.DATA_DIR", Path(directory)), patch("app.courses.get_task", side_effect=lambda key: SimpleNamespace(title=key)), patch("app.courses.evidence_for_task", side_effect=lambda key, **kw: evidence[key]):
                course = save_course("课程", [{"kind":"task","id":"one"},{"kind":"task","id":"two"}])
                result = compare_course(course["id"], "学习率 梯度")
                self.assertFalse(result["inference"])
                self.assertEqual(result["edges"][0]["evidence_ids"], ["b","c"])
                self.assertEqual(result["edges"][0]["terms"], ["梯度"])
                self.assertEqual(len(result["matches"]), 3)

    def test_unknown_source_is_not_accepted_as_canonical(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.courses.DATA_DIR", Path(directory)), patch("app.courses.get_task", side_effect=FileNotFoundError):
                with self.assertRaisesRegex(ValueError, "course_source_missing"):
                    save_course("课程", [{"kind":"task","id":"fake","title":"伪造来源"}])


if __name__ == "__main__":
    unittest.main()
