"""Real SQLite/owned artifacts: progress must not republish unchanged evidence."""
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import knowledge, library, storage
from app.models import SourceEvidence, TaskRecord


class IncrementalTaskIndexTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.tasks = self.root / "tasks"
        self.task_root = self.tasks / "synthetic-index"
        self.task_root.mkdir(parents=True)
        for module in (library, knowledge, storage):
            self.stack.enter_context(patch.object(module, "DATA_DIR", self.root))
            self.stack.enter_context(patch.object(module, "ensure_dirs", return_value=None))
        for module in (library, storage):
            self.stack.enter_context(patch.object(module, "TASK_DIR", self.tasks))
        self.stack.enter_context(patch.object(storage, "record_task_event"))
        self.stack.enter_context(patch.object(storage, "record_status"))
        self.note = self.task_root / "note.md"
        self.transcript = self.task_root / "transcript.json"
        self.note.write_text("# Original\n\nSynthetic source.", encoding="utf-8")
        self.transcript.write_text(json.dumps({"segments": [
            {"start": i, "end": i + 1, "text": f"Synthetic cue {i}"} for i in range(1000)
        ]}), encoding="utf-8")
        self.task = TaskRecord(id=self.task_root.name, source_type="local", title="Synthetic source",
                               created_at="2026-10-23", updated_at="2026-10-23",
                               note_path=str(self.note), transcript_path=str(self.transcript))
        storage.save_task(self.task)

    def sql(self, query):
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as connection:
            return connection.execute(query).fetchall()

    def snapshot(self):
        return {table: self.sql(f"SELECT * FROM {table} ORDER BY 1") for table in
                ("library_tasks", "library_tasks_fts", "source_evidence", "source_evidence_fts", "task_projection_revisions")}

    def test_progress_has_zero_content_reads_or_evidence_rewrites_across_connections(self):
        before = self.sql("SELECT * FROM source_evidence ORDER BY evidence_id")
        with patch.object(library, "read_canonical_text", wraps=library.read_canonical_text) as read, \
             patch.object(library, "replace_task_evidence_in_transaction", wraps=library.replace_task_evidence_in_transaction) as publish:
            for tick in range(3):
                storage.update_task(self.task.id, progress=tick, message=f"Tick {tick}")
            storage.update_task(self.task.id, status="running", phase="transcribing")
        read.assert_not_called()
        publish.assert_not_called()
        self.assertEqual(self.sql("SELECT * FROM source_evidence ORDER BY evidence_id"), before)
        self.assertEqual(len(before), 1001)
        self.assertEqual(self.sql("SELECT status FROM library_tasks"), [("running",)])

    def test_atomic_replacement_at_same_path_and_mtime_is_detected(self):
        old_stat = self.note.stat()
        replacement = self.note.with_suffix(".new")
        replacement.write_text("# Modified\n\nSynthetic source.", encoding="utf-8")
        os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        replacement.replace(self.note)
        storage.update_task(self.task.id, progress=10)
        self.assertIn("Modified", self.sql("SELECT text FROM source_evidence WHERE locator='note'")[0][0])

    def test_title_review_and_checkpoint_republish_compatible_evidence(self):
        storage.update_task(self.task.id, title="Changed title", checkpoint="transcribed",
                            summary_diagnostics={"review_required": True})
        rows = self.sql("SELECT title, metadata_json FROM source_evidence")
        self.assertTrue(all(row[0] == "Changed title" for row in rows))
        self.assertTrue(all(json.loads(row[1])["review_required"] for row in rows))
        note = self.sql("SELECT metadata_json FROM source_evidence WHERE locator='note'")[0][0]
        self.assertEqual(json.loads(note)["checkpoint"], "transcribed")

    def test_partial_draft_is_never_searchable_and_missing_artifacts_clear_projection(self):
        partial = self.task_root / "draft.partial.md"
        partial.write_text("Unpublished secret draft", encoding="utf-8")
        storage.update_task(self.task.id, note_path=str(partial))
        self.assertEqual(self.sql("SELECT text FROM source_evidence WHERE locator='note'"), [])
        self.assertFalse(library.search_library("Unpublished"))
        self.transcript.unlink()
        storage.update_task(self.task.id, progress=20)
        self.assertEqual(self.sql("SELECT text FROM source_evidence"), [])

    def test_failure_rolls_back_catalog_fts_evidence_and_receipt_then_retries(self):
        before = self.snapshot()
        storage.atomic_write_text(self.note, "# Replacement\n\nNew source content.")
        original = library.replace_task_evidence_in_transaction

        def fail_after_evidence(connection, task_id, evidence):
            original(connection, task_id, evidence)
            raise sqlite3.OperationalError("synthetic interrupted publication")

        with patch.object(library, "replace_task_evidence_in_transaction", side_effect=fail_after_evidence):
            self.assertFalse(library.index_task(self.task))
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(library.index_task(self.task))
        self.assertIn("Replacement", self.sql("SELECT text FROM source_evidence WHERE locator='note'")[0][0])

    def test_unavailable_catalog_does_not_lose_manifest_and_next_save_retries(self):
        storage.atomic_write_text(self.note, "# Recovered\n\nSynthetic new content.")
        with patch.object(library, "_connect", side_effect=sqlite3.OperationalError("temporarily unavailable")):
            storage.update_task(self.task.id, progress=25)
        self.assertEqual(storage.get_task(self.task.id).progress, 25)
        storage.update_task(self.task.id, progress=26)
        self.assertIn("Recovered", self.sql("SELECT text FROM source_evidence WHERE locator='note'")[0][0])

    def test_malformed_transcript_leaves_previous_projection_and_durable_progress(self):
        before = self.snapshot()
        storage.atomic_write_text(self.transcript, json.dumps({"segments": [{"text": "Source", "start": "invalid"}]}))
        storage.update_task(self.task.id, progress=25)
        self.assertEqual(storage.get_task(self.task.id).progress, 25)
        self.assertEqual(self.snapshot(), before)

    def test_artifact_changed_during_read_does_not_commit_mixed_projection(self):
        before = self.snapshot()
        storage.atomic_write_text(self.note, "# Changed source")
        read = library.read_canonical_text

        def replace_during_read(path):
            value = read(path)
            if path == self.note:
                storage.atomic_write_text(self.note, "# A different version")
            return value

        with patch.object(library, "read_canonical_text", side_effect=replace_during_read):
            self.assertFalse(library.index_task(self.task))
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(library.index_task(self.task))

    def test_evidence_deletion_invalidates_receipt_and_rebuild_restores_it(self):
        knowledge.remove_evidence(f"task-{self.task.id}-note")
        self.assertEqual(self.sql("SELECT * FROM task_projection_revisions"), [])
        storage.update_task(self.task.id, progress=30)
        self.assertEqual(len(self.sql("SELECT * FROM source_evidence")), 1001)
        rebuilt = library.rebuild_index()
        self.assertEqual(rebuilt["indexed"], 1)
        self.assertEqual(len(self.sql("SELECT * FROM source_evidence")), 1001)

    def test_legacy_catalog_without_receipt_is_rebuilt_once(self):
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as connection:
            connection.execute("DROP TABLE task_projection_revisions")
            connection.commit()
        with patch.object(library, "replace_task_evidence_in_transaction", wraps=library.replace_task_evidence_in_transaction) as publish:
            self.assertTrue(library.index_task(self.task))
            self.assertTrue(library.index_task(self.task))
        self.assertEqual(publish.call_count, 1)

    def test_reassigned_evidence_invalidates_both_owners_without_stealing_it_back(self):
        knowledge.add_evidence(SourceEvidence(evidence_id=f"task-{self.task.id}-note",
                                              task_id="other-owner", text="Explicit external replacement"))
        self.assertEqual(self.sql("SELECT * FROM task_projection_revisions"), [])
        self.assertFalse(library.index_task(self.task))
        self.assertEqual(self.sql("SELECT task_id FROM source_evidence WHERE locator=''"), [("other-owner",)])

    def test_explicit_rebuild_does_not_trust_a_filesystem_revision_receipt(self):
        before = library.task_index_revision(self.task, self.task_root, "")
        self.note.write_text("# Rebuilt external content", encoding="utf-8")
        with patch.object(library, "task_index_revision", return_value=before):
            self.assertEqual(library.rebuild_index()["indexed"], 1)
        self.assertIn("Rebuilt external", self.sql("SELECT text FROM source_evidence WHERE locator='note'")[0][0])

    def test_missing_fts_is_atomically_backfilled_from_content_without_artifact_reads(self):
        before = self.snapshot()
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as connection:
            connection.execute("DROP TABLE library_tasks_fts")
            connection.execute("DROP TABLE source_evidence_fts")
            connection.commit()
        with patch.object(library, "read_canonical_text", side_effect=AssertionError("unneeded artifact read")):
            storage.update_task(self.task.id, progress=40)
        after = self.snapshot()
        for table in ("library_tasks_fts", "source_evidence_fts", "source_evidence", "task_projection_revisions"):
            self.assertEqual(before[table], after[table])


if __name__ == "__main__":
    unittest.main()
