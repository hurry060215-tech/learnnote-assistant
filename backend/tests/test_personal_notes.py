from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.models import TaskRecord
from app.personal_notes import save_annotation, list_annotations, delete_annotation, annotation_markdown


class PersonalNotesTests(unittest.TestCase):
    def test_regeneration_preserves_personal_content_and_explicit_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            original = TaskRecord(id="original", title="原资料", source_type="local", created_at="2026-09-06", updated_at="2026-09-06")
            regenerated = original.model_copy(update={"id": "new-version", "source_task_id": "original"})
            tasks = {original.id: original, regenerated.id: regenerated}
            with patch("app.personal_notes.DATA_DIR", Path(directory)), patch("app.personal_notes.get_task", side_effect=tasks.__getitem__):
                note = save_annotation("task", original.id, "我的理解，不应进入模型重写。", "原文引句")
                self.assertEqual(list_annotations("task", regenerated.id)[0]["id"], note["id"])
                self.assertIn("我的理解", annotation_markdown("task", regenerated.id))
                updated = save_annotation("task", regenerated.id, "修订后的个人理解", "新引句", note["id"])
                self.assertEqual(list_annotations("task", original.id), [updated])
                self.assertTrue(delete_annotation("task", regenerated.id, note["id"]))
                self.assertEqual(list_annotations("task", original.id), [])

    def test_material_hash_keeps_annotations_across_reimport(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.personal_notes.DATA_DIR", Path(directory)), patch("app.personal_notes.get_material", return_value={"sha256": "a" * 64}):
                save_annotation("material", "first", "保留原文之外的个人补充。")
                self.assertEqual(len(list_annotations("material", "same-file-reimported")), 1)

    def test_annotation_anchor_is_bounded_and_survives_reloading(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.personal_notes.DATA_DIR", Path(directory)), patch("app.personal_notes.get_material", return_value={"sha256": "b" * 64}):
                saved = save_annotation(
                    "material",
                    "source",
                    "我的批注",
                    "原文片段",
                    anchor={"source_revision": "rev-1", "selected_text": "原文片段", "ignored": "drop"},
                )
                loaded = list_annotations("material", "source")
        self.assertEqual(saved["anchor"]["source_revision"], "rev-1")
        self.assertEqual(loaded[0]["anchor"]["selected_text"], "原文片段")
        self.assertNotIn("ignored", loaded[0]["anchor"])

    def test_changed_note_revision_marks_personal_anchor_stale_even_when_quote_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "note.md"
            note.write_text("# Lesson\n\nA sentence kept across generated revisions.", encoding="utf-8")
            task = TaskRecord(
                id="task-stale-anchor",
                title="Lesson",
                source_type="local",
                note_path=str(note),
                created_at="2026-09-24T00:00:00+00:00",
                updated_at="2026-09-24T00:00:00+00:00",
            )
            with patch("app.personal_notes.DATA_DIR", root), patch("app.personal_notes.get_task", return_value=task):
                save_annotation(
                    "task",
                    task.id,
                    "My own correction",
                    "A sentence kept across generated revisions.",
                    anchor={"source_revision": "previous-revision", "selected_text": "A sentence kept across generated revisions."},
                )
                annotation = list_annotations("task", task.id)[0]
        self.assertTrue(annotation["anchor_status"]["stale"])
        self.assertTrue(annotation["anchor_status"]["repairable"])

    def test_editing_text_without_a_new_selection_preserves_existing_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.personal_notes.DATA_DIR", Path(directory)), patch("app.personal_notes.get_material", return_value={"sha256": "c" * 64}):
                saved = save_annotation(
                    "material", "one", "First note", "Quoted passage",
                    anchor={"source_revision": "rev-1", "selected_text": "Quoted passage"},
                )
                save_annotation("material", "renamed", "Updated text", saved["quote"], saved["id"])
                current = list_annotations("material", "same-by-hash")[0]
        self.assertEqual(current["text"], "Updated text")
        self.assertEqual(current["anchor"]["source_revision"], "rev-1")
        self.assertEqual(current["anchor"]["selected_text"], "Quoted passage")


if __name__ == "__main__":
    unittest.main()
