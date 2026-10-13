"""Original-text context survives casefold expansions; no semantic assertions."""
from copy import deepcopy
import unittest

from app.course_comparison import build_comparison
from app.library import _library_search_result
from app.text_indices import original_casefold_offset


class UnicodeExcerptTests(unittest.TestCase):
    def test_folded_positions_map_to_original_characters_and_boundaries(self):
        for text in ("ASCII 中文", "aßbİcﬃd", "", "ßİﬃ"):
            with self.subTest(text=text):
                expected = [index for index, char in enumerate(text) for _ in char.casefold()]
                self.assertEqual([original_casefold_offset(text, offset) for offset in range(len(text.casefold()))], expected)
                self.assertEqual(original_casefold_offset(text, -1), -1)
                self.assertEqual(original_casefold_offset(text, len(text.casefold())), len(text))

    def test_comparison_and_edge_citations_preserve_original_context(self):
        cases = [("Straße " * 100 + "scale is an ordered set.", "scale", 700),
                 ("İ " * 100 + "中文关键字", "关键", 202),
                 ("ﬃ " * 100 + "First later", "later first", 200),
                 ("x" * 100 + "ß original" + "y" * 600, "ss", 100),
                 ("x" * 100 + "ﬃ original" + "y" * 600, "fi", 100),
                 ("x" * 100 + "İ original" + "y" * 600, "\u0307", 100),
                 ("plain ASCII 中文", "ASCII", 6)]
        for text, query, offset in cases:
            rows = [{"evidence_id": f"source-{i}", "text": text, "locator": "12.345-18.765s", "task_id": f"task-{i}",
                     "course_source": {"kind": "task", "id": f"task-{i}", "title": "Synthetic"}} for i in range(2)]
            before = deepcopy(rows)
            with self.subTest(query=query, prefix=text[:10]):
                result = build_comparison(rows, {"events": []}, query)
                expected = text[max(0, offset - 80):offset + 440]
                self.assertEqual([row["excerpt"] for row in result["matches"]], [expected, expected])
                self.assertEqual([row["excerpt"] for row in result["edges"][0]["citations"]], [expected, expected])
                self.assertLessEqual(len(expected), 520)
                self.assertFalse(result["inference"])
                self.assertEqual(result["edges"][0]["kind"], "keyword_cooccurrence")
                self.assertEqual(rows, before)
                self.assertEqual(build_comparison(rows, {"events": []}, "absent-token")["matches"], [])
                with self.assertRaisesRegex(ValueError, "invalid_comparison_query"):
                    build_comparison(rows, {"events": []}, " ")

    def test_library_snippets_map_positions_after_existing_whitespace_normalization(self):
        cases = [("Straße \n" * 100 + "scale is an ordered set.", "scale", 700),
                 ("İ " * 100 + "中文关键字", "关键", 202),
                 ("ﬃ " * 100 + "Original" + "z" * 500, " ORIGINAL ", 200),
                 ("x" * 100 + "ß original" + "y" * 600, "ss", 100),
                 ("ASCII 中文", "ascii", 0), ("x" * 500, "missing", 0), ("x" * 500, "", 0)]
        for text, query, offset in cases:
            row = dict.fromkeys(("task_id", "title", "source", "source_type", "mode", "status", "checkpoint", "created_at", "updated_at"), "synthetic")
            row["content"] = text
            before = deepcopy(row)
            normalized = " ".join(text.split())
            start = max(0, offset - 90)
            expected = ("…" if start else "") + normalized[start:start + 320] + ("…" if start + 320 < len(normalized) else "")
            with self.subTest(query=query, prefix=text[:10]):
                result = _library_search_result(row, query)
                self.assertEqual(result["snippet"], expected)
                self.assertLessEqual(len(result["snippet"]), 322)
                self.assertNotIn("content", result)
                self.assertEqual(row, before)
