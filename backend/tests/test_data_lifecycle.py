from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.community import add_community_context, list_community_context, set_community_enabled
from app.knowledge import evidence_for_task, search_evidence
from app.library import delete_material, import_document_material, index_task, list_materials, register_task_material, remove_task
from app.models import StudyCard, TaskRecord
from app.study import list_cards, save_cards


class DataLifecycleTests(unittest.TestCase):
    def _patch_roots(self, root: Path):
        return (
            patch("app.library.DATA_DIR", root),
            patch("app.library.TASK_DIR", root / "tasks"),
            patch("app.library.TEMP_DIR", root / "temp"),
            patch("app.knowledge.DATA_DIR", root),
            patch("app.community.DATA_DIR", root),
            patch("app.study.DATA_DIR", root),
        )

    def test_task_removal_cascades_local_evidence_community_cards_and_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_root = root / "tasks" / "task-delete"
            task_root.mkdir(parents=True)
            (root / "temp").mkdir()
            note = task_root / "note.md"
            note.write_text("# 课程\n\n证据内容 00:12", encoding="utf-8")
            record = TaskRecord(
                id="task-delete", source_type="local", mode="local", title="课程",
                note_path=str(note), status="success",
                created_at="2026-08-31T00:00:00+00:00", updated_at="2026-08-31T00:00:00+00:00",
            )
            patches = self._patch_roots(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                self.assertTrue(index_task(record))
                evidence_ids = [item["evidence_id"] for item in evidence_for_task(record.id)]
                self.assertTrue(evidence_ids)
                set_community_enabled(True)
                add_community_context(record.id, [{"kind": "comment", "text": "社区观点"}])
                save_cards([StudyCard(front="问题", back="答案", source_evidence_ids=[evidence_ids[0]], status="active")])
                register_task_material(record)

                self.assertTrue(remove_task(record.id))
                self.assertEqual(evidence_for_task(record.id), [])
                self.assertEqual(list_community_context(record.id)["items"], [])
                self.assertEqual(list_cards(), [])
                self.assertFalse(any(item["linked_task_id"] == record.id for item in list_materials()))

    def test_material_delete_removes_only_owned_file_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tasks").mkdir()
            (root / "temp").mkdir()
            patches = self._patch_roots(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                material = import_document_material("lesson.md", "# 课程\n\n本地资料证据内容。".encode("utf-8"), "text/markdown")
                owned_file = root / "materials" / material["material_id"] / "lesson.md"
                self.assertTrue(owned_file.is_file())
                result = delete_material(material["material_id"])
                self.assertTrue(result["deleted"])
                self.assertFalse(owned_file.exists())
                self.assertEqual(search_evidence("本地资料证据"), [])
                self.assertEqual(list_materials(), [])


if __name__ == "__main__":
    unittest.main()
