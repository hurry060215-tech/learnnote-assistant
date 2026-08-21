from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.library import backup_library, duplicate_groups, index_task, library_status, rebuild_index, restore_library, search_library
from app.models import SourceIdentity, TaskRecord


class LocalLibraryIndexTests(unittest.TestCase):
    def test_index_search_and_rebuild_from_task_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks"
            task_dir = tasks / "lesson-1"
            task_dir.mkdir(parents=True)
            note = task_dir / "note.md"
            transcript = task_dir / "transcript.json"
            note.write_text("# 梯度下降\n学习率决定步长。", encoding="utf-8")
            transcript.write_text('{"full_text":"梯度决定方向"}', encoding="utf-8")
            record = TaskRecord(
                id="lesson-1",
                source_type="local",
                mode="local",
                title="梯度下降课程",
                page_url="https://example.com/course?token=secret&v=1",
                status="success",
                phase="completed",
                note_path=str(note),
                transcript_path=str(transcript),
                created_at="2026-08-21T00:00:00+00:00",
                updated_at="2026-08-21T00:00:00+00:00",
            )
            (task_dir / "task.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
            with patch("app.library.DATA_DIR", root), patch("app.library.TASK_DIR", tasks), patch("app.knowledge.DATA_DIR", root):
                self.assertTrue(index_task(record))
                result = search_library("学习率")
                self.assertEqual(result[0]["task_id"], "lesson-1")
                self.assertNotIn("token=secret", result[0]["source"])
                from app.knowledge import search_evidence
                evidence = search_evidence("梯度")
                self.assertTrue(any(item["locator"] == "0.0-0.0s" or item["locator"] == "transcript" for item in evidence))
                status = library_status()
                self.assertEqual(status["indexed_task_count"], 1)
                (root / "library.sqlite3").unlink()
                rebuilt = rebuild_index()
                self.assertEqual(rebuilt["indexed"], 1)
                self.assertEqual(search_library("梯度")[0]["task_id"], "lesson-1")
                (task_dir / "task.json").unlink()
                rebuilt_empty = rebuild_index()
                self.assertEqual(rebuilt_empty["indexed"], 0)
                self.assertEqual(library_status()["indexed_task_count"], 0)

    def test_backup_and_restore_validate_schema_and_preserve_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks"
            tasks.mkdir()
            with patch("app.library.DATA_DIR", root), patch("app.library.TASK_DIR", tasks), patch("app.library.TEMP_DIR", root / "temp"), patch("app.knowledge.DATA_DIR", root):
                (root / "temp").mkdir()
                record = TaskRecord(
                    id="backup-task",
                    source_type="local",
                    mode="local",
                    title="Backup lesson",
                    created_at="2026-08-21T00:00:00+00:00",
                    updated_at="2026-08-21T00:00:00+00:00",
                )
                self.assertTrue(index_task(record))
                backup = backup_library()
                self.assertTrue(backup.is_file())
                (root / "library.sqlite3").unlink()
                restored = restore_library(backup)
                self.assertEqual(restored["indexed_task_count"], 1)
                self.assertEqual(search_library("Backup")[0]["task_id"], "backup-task")

    def test_duplicate_groups_use_media_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks"
            tasks.mkdir()
            with patch("app.library.DATA_DIR", root), patch("app.library.TASK_DIR", tasks), patch("app.library.TEMP_DIR", root / "temp"), patch("app.knowledge.DATA_DIR", root):
                for task_id in ("duplicate-a", "duplicate-b"):
                    record = TaskRecord(
                        id=task_id, source_type="local", mode="local", title=task_id,
                        source_identity=SourceIdentity(media_sha256="same-sha"),
                        created_at="2026-08-21T00:00:00+00:00", updated_at="2026-08-21T00:00:00+00:00",
                    )
                    index_task(record)
                groups = duplicate_groups()
                self.assertEqual(groups[0]["count"], 2)


if __name__ == "__main__":
    unittest.main()
