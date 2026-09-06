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


if __name__ == "__main__":
    unittest.main()
