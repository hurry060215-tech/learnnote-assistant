import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import knowledge
from app.models import SourceEvidence


class EvidenceBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scope = patch.object(knowledge, "DATA_DIR", self.root)
        self.scope.start(); self.addCleanup(self.scope.stop)

    def item(self, number, task="one", text=None):
        return SourceEvidence(evidence_id=f"task-{task}-{number}", task_id=task, source_type="video",
            title="Source", source_uri="https://example.test/reference", locator=f"{number}s",
            text=text or f"Source phrase {number}", metadata={"start": number, "source_revision": "reference"})

    def test_batch_preserves_single_item_contract_and_uses_one_connection(self):
        items = [self.item(i, text=f"```py\n  value = {i}\n```\n\nParagraph") for i in range(360)]
        original = knowledge._connect
        with patch.object(knowledge, "_connect", wraps=original) as connect:
            knowledge.replace_task_evidence("one", items)
        self.assertEqual(connect.call_count, 1)
        batch = knowledge.evidence_for_task("one", limit=500)
        self.assertEqual(len(batch), 360)
        knowledge.add_evidence(items[0])
        after = knowledge.evidence_by_ids([items[0].evidence_id])[0]
        self.assertEqual(batch[0], {key: value for key, value in after.items() if key != "created_at"})
        self.assertEqual(after["text"], items[0].text)

    def test_failed_mid_batch_replacement_rolls_back_all_original_evidence(self):
        knowledge.replace_task_evidence("one", [self.item(1), self.item(2)])
        before = knowledge.evidence_for_task("one")
        original = knowledge._write_evidence
        def failure(connection, item, fts, **kwargs):
            if item.evidence_id.endswith("4"):
                raise sqlite3.OperationalError("fixture disk failure")
            return original(connection, item, fts, **kwargs)
        with patch.object(knowledge, "_write_evidence", side_effect=failure), self.assertRaises(sqlite3.OperationalError):
            knowledge.replace_task_evidence("one", [self.item(3), self.item(4)])
        self.assertEqual(knowledge.evidence_for_task("one"), before)
        self.assertEqual({row["evidence_id"] for row in knowledge.search_evidence("phrase", limit=20)}, {item["evidence_id"] for item in before})

    def test_other_tasks_cannot_be_deleted_or_overwritten(self):
        knowledge.replace_task_evidence("one", [self.item(1)])
        other = self.item(2, "two"); knowledge.add_evidence(other)
        with self.assertRaises(ValueError):
            knowledge.replace_task_evidence("one", [other])
        with self.assertRaises(ValueError):
            knowledge.replace_task_evidence("one", [other.model_copy(update={"task_id": "one"})])
        self.assertEqual(len(knowledge.evidence_for_task("one")), 1)
        self.assertEqual(len(knowledge.evidence_for_task("two")), 1)
        knowledge.replace_task_evidence("one", [])
        self.assertEqual(knowledge.evidence_for_task("one"), [])
        self.assertEqual(len(knowledge.evidence_for_task("two")), 1)
