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


class CourseComparisonAcceptanceTests(unittest.TestCase):
    def test_time_filter_does_not_change_with_excerpt_character_position(self):
        source = {"kind": "task", "id": "video", "title": "Video"}
        for prefix in ("", "x" * 100):
            evidence = [
                {"evidence_id": "first", "locator": "15-18s", "text": prefix + "gradient first", "course_source": source},
                {"evidence_id": "early", "locator": "0-5s", "text": "gradient early", "course_source": source},
                {"evidence_id": "second", "locator": "20-25s", "text": "gradient second", "course_source": source},
            ]
            with self.subTest(prefix_length=len(prefix)), patch("app.courses.get_course", return_value={}), patch("app.courses.course_evidence", return_value=evidence):
                result = compare_course("fixture", "gradient", start=10, end=30)
            self.assertEqual([item["evidence_id"] for item in result["matches"]], ["first", "second"])
            self.assertEqual(result["filters"]["start"], 10)
            self.assertEqual(result["filters"]["end"], 30)

    def test_unfiltered_comparison_keeps_document_evidence_after_video(self):
        evidence = [
            {"evidence_id": "video", "locator": "15-20s", "text": "intro gradient", "course_source": {"kind": "task", "id": "video", "title": "Video"}},
            {"evidence_id": "document", "locator": "page:2", "text": "gradient notes", "course_source": {"kind": "material", "id": "document", "title": "Document"}},
        ]
        for ordered in (evidence, list(reversed(evidence))):
            with self.subTest(first=ordered[0]["evidence_id"]), patch("app.courses.get_course", return_value={}), patch("app.courses.course_evidence", return_value=ordered):
                result = compare_course("fixture", "gradient")
            self.assertEqual({item["evidence_id"] for item in result["matches"]}, {"video", "document"})
            self.assertEqual(len(result["edges"]), 1)
            self.assertIsNone(result["filters"]["start"])

    def test_same_evidence_registered_twice_is_not_a_cross_source_relation(self):
        evidence = {"evidence_id":"shared", "locator":"0-10s", "text":"gradient descent"}
        with patch("app.courses.get_course", return_value={"sources":[{"kind":"task","id":"one","title":"Video"},{"kind":"material","id":"registered-video","title":"Video"}]}), patch("app.courses.evidence_for_task", return_value=[evidence]), patch("app.courses.material_anchors", return_value=[evidence]):
            result = compare_course("fixture", "gradient")
        self.assertEqual(result["edges"], [])
        self.assertEqual(len(result["matches"]), 1)

    def test_comparison_filters_keep_correct_source_and_temporal_anchors(self):
        sources = [{"kind":"task","id":"one","title":"First"},{"kind":"task","id":"two","title":"Second"}]
        evidence = {"one":[{"evidence_id":"a","locator":"0-5s","text":"gradient early"},{"evidence_id":"b","locator":"15-20s","text":"gradient late"}], "two":[{"evidence_id":"c","locator":"15-20s","text":"gradient second"}]}
        with patch("app.courses.get_course", return_value={"sources":sources}), patch("app.courses.evidence_for_task", side_effect=lambda key, **kw:evidence[key]):
            result = compare_course("fixture", "gradient", start=10, end=30)
            self.assertEqual([item["evidence_id"] for item in result["matches"]], ["b", "c"])
            self.assertEqual(result["edges"][0]["evidence_ids"], ["b", "c"])
            self.assertEqual(len(compare_course("fixture", "gradient", source_id="two")["matches"]), 1)
            self.assertEqual(compare_course("fixture", "gradient", source_kind="material")["matches"], [])
            with self.assertRaisesRegex(ValueError, "invalid_comparison_filter"):
                compare_course("fixture", "gradient", start=20, end=10)


if __name__ == "__main__":
    unittest.main()
