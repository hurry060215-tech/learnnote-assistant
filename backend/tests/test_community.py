from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.community import add_community_context, clear_community_context, community_settings, delete_community_item, list_community_context, sample_community_context, set_community_enabled
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

    def test_explicit_sample_is_reproducible_and_single_delete_is_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.community.DATA_DIR", Path(tmp)):
                set_community_enabled(True)
                add_community_context("task-sample", [{"kind": "comment", "text": "观点一"}, {"kind": "comment", "text": "观点二"}])
                first = sample_community_context("task-sample", 1, "fixed")
                second = sample_community_context("task-sample", 1, "fixed")
                self.assertEqual(first["items"], second["items"])
                item_id = first["items"][0]["item_id"]
                self.assertTrue(delete_community_item("task-sample", item_id))
                self.assertFalse(delete_community_item("other-task", item_id))


class CommunityPrivacyAcceptanceTests(unittest.TestCase):
    def test_contact_details_and_authors_are_not_stored_and_noise_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp, patch("app.community.DATA_DIR", Path(tmp)):
            set_community_enabled(True)
            result = add_community_context("task-safe", [
                {"text": "这个解释很好，联系 learner@example.com 或 +1 (415) 555-0123", "author_label": "Real Person"},
                {"text": "暂停"}, {"text": "加群领取优惠券"},
                {"text": "为什么选择这个参数？", "kind": "danmaku", "timestamp_seconds": 10},
                {"text": "为什么选择这个参数？", "kind": "danmaku", "timestamp_seconds": 15},
                {"text": "我不同意这个结论"},
            ])
            self.assertEqual(result["stored_count"], 3)
            self.assertEqual(result["filtered_count"], 2)
            self.assertEqual(result["deduplicated_count"], 1)
            self.assertTrue(all(item["author_label"] == "" for item in result["items"]))
            stored = list_community_context("task-safe")
            self.assertEqual(len(stored["groups"]["questions"]), 1)
            self.assertEqual(len(stored["groups"]["disagreements"]), 1)
            raw = (Path(tmp) / "community.sqlite3").read_bytes()
            self.assertNotIn(b"learner@example.com", raw)
            self.assertNotIn(b"415", raw)
            self.assertNotIn(b"Real Person", raw)
            self.assertFalse(stored["evidence_eligible"])

    def test_duplicate_retry_at_quota_does_not_fail_or_store_new_content(self):
        with tempfile.TemporaryDirectory() as tmp, patch("app.community.DATA_DIR", Path(tmp)), patch("app.community.COMMUNITY_CONTEXT_MAX_ITEMS_PER_TASK", 1):
            set_community_enabled(True)
            add_community_context("limited", [{"text": "Useful point"}])
            result = add_community_context("limited", [{"text": "USEFUL POINT"}])
            self.assertEqual(result["deduplicated_count"], 1)
            with self.assertRaisesRegex(ValueError, "community_storage_quota_exceeded"):
                add_community_context("limited", [{"text": "Different point"}])
            self.assertEqual(len(list_community_context("limited")["items"]), 1)

    def test_independent_export_is_not_limited_to_the_ui_page(self):
        import json
        from app.routers.knowledge_study import api_export_task_community_context
        with tempfile.TemporaryDirectory() as tmp, patch("app.community.DATA_DIR", Path(tmp)), patch("app.routers.knowledge_study.get_task"):
            set_community_enabled(True)
            for offset in range(0, 2001, 500):
                add_community_context("export", [{"text": f"Audience perspective item {index}"} for index in range(offset, min(offset + 500, 2001))])
            response = api_export_task_community_context("export")
            payload = json.loads(response.body)
            self.assertEqual(len(payload["items"]), 2001)
            self.assertFalse(payload["evidence_eligible"])
            self.assertIn("attachment", response.headers["content-disposition"])
            self.assertTrue(all(not item["author_label"] for item in payload["items"]))


if __name__ == "__main__":
    unittest.main()
