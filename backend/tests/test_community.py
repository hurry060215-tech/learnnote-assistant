from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.community import add_community_context, clear_community_context, community_settings, list_community_context, set_community_enabled
from app.knowledge import search_evidence


class CommunityContextTests(unittest.TestCase):
    def test_context_is_opt_in_local_deduplicated_and_never_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.community.DATA_DIR", root), patch("app.knowledge.DATA_DIR", root):
                self.assertFalse(community_settings()["enabled"])
                with self.assertRaisesRegex(ValueError, "community_context_disabled"):
                    add_community_context("task-1", [{"kind": "comment", "text": "这是评论"}])

                self.assertTrue(set_community_enabled(True)["enabled"])
                payload = [{
                    "kind": "danmaku",
                    "text": " 这个例子很容易理解 ",
                    "timestamp_seconds": 31.2,
                    "author_label": "观众 A",
                    "source_uri": "https://example.com/watch?id=1&token=secret#comment",
                }]
                first = add_community_context("task-1", payload)
                second = add_community_context("task-1", payload)
                self.assertEqual(first["stored_count"], 1)
                self.assertEqual(second["deduplicated_count"], 1)
                listed = list_community_context("task-1")
                self.assertFalse(listed["evidence_eligible"])
                self.assertEqual(listed["items"][0]["source_uri"], "https://example.com/watch")
                self.assertEqual(search_evidence("容易理解"), [])
                self.assertEqual(clear_community_context("task-1"), 1)

    def test_non_finite_timestamp_and_private_source_are_never_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.community.DATA_DIR", root):
                set_community_enabled(True)
                stored = add_community_context("task-private", [{
                    "kind": "comment",
                    "text": "独立观点",
                    "timestamp_seconds": "Infinity",
                    "source_uri": "http://127.0.0.1:8765/data/study.sqlite3?token=secret",
                }])
                self.assertIsNone(stored["items"][0]["timestamp_seconds"])
                self.assertEqual(stored["items"][0]["source_uri"], "")


if __name__ == "__main__":
    unittest.main()
