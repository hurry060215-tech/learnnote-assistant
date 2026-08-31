from __future__ import annotations

import tempfile
import unittest
import sqlite3
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from app.knowledge import add_evidence
from app.library import backup_library, duplicate_groups, import_document_material, index_task, library_status, list_materials, material_anchors, rebuild_index, register_task_material, restore_library, search_library
from app.models import SourceEvidence
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

    def test_search_results_do_not_expose_paths_or_full_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks"
            task_dir = tasks / "private-task"
            task_dir.mkdir(parents=True)
            note = task_dir / "note.md"
            note.write_text("# 私有课程\n" + "敏感学习文本" * 200, encoding="utf-8")
            record = TaskRecord(
                id="private-task", source_type="local", mode="local", title="私有课程",
                note_path=str(note), media_path=str(task_dir / "media.mp4"),
                created_at="2026-08-21T00:00:00+00:00", updated_at="2026-08-21T00:00:00+00:00",
            )
            with patch("app.library.DATA_DIR", root), patch("app.library.TASK_DIR", tasks), patch("app.knowledge.DATA_DIR", root):
                self.assertTrue(index_task(record))
                result = search_library("敏感")[0]
            self.assertNotIn("note_path", result)
            self.assertNotIn("media_path", result)
            self.assertNotIn("content", result)
            self.assertLessEqual(len(str(result["snippet"])), 322)

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

    def test_restore_rejects_incomplete_schema_without_replacing_live_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks"
            tasks.mkdir()
            (root / "temp").mkdir()
            with patch("app.library.DATA_DIR", root), patch("app.library.TASK_DIR", tasks), patch("app.library.TEMP_DIR", root / "temp"), patch("app.knowledge.DATA_DIR", root):
                record = TaskRecord(
                    id="live-task", source_type="local", mode="local", title="Live lesson",
                    created_at="2026-08-21T00:00:00+00:00", updated_at="2026-08-21T00:00:00+00:00",
                )
                self.assertTrue(index_task(record))
                malformed = root / "malformed.sqlite3"
                connection = sqlite3.connect(malformed)
                connection.execute("CREATE TABLE library_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("INSERT INTO library_meta VALUES ('schema_version', '1')")
                connection.execute("CREATE TABLE library_tasks(task_id TEXT PRIMARY KEY)")
                connection.commit()
                connection.close()
                with self.assertRaisesRegex(ValueError, "library_backup_schema_mismatch"):
                    restore_library(malformed)
                self.assertEqual(search_library("Live")[0]["task_id"], "live-task")

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

    def test_document_materials_are_anchored_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.library.DATA_DIR", root), patch("app.library.TASK_DIR", root / "tasks"), patch("app.library.TEMP_DIR", root / "temp"), patch("app.knowledge.DATA_DIR", root):
                content = "# 第一章\n\n学习率决定优化步长。\n\n## 第二章\n\n动量用于平滑更新方向。".encode("utf-8")
                material = import_document_material("课程.md", content, "text/markdown")
                duplicate = import_document_material("副本.md", content, "text/markdown")
                self.assertEqual(material["source_type"], "markdown")
                self.assertGreaterEqual(material["anchor_count"], 2)
                self.assertTrue(duplicate["deduplicated"])
                self.assertEqual(duplicate["material_id"], material["material_id"])
                anchors = material_anchors(material["material_id"])
                self.assertTrue(any("学习率" in item["text"] for item in anchors))
                self.assertEqual(list_materials()[0]["material_id"], material["material_id"])
                self.assertEqual(library_status()["material_count"], 1)

    def test_local_video_task_registration_reuses_task_evidence_and_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "lesson.mp4"
            media.write_bytes(b"local-video-placeholder")
            with patch("app.library.DATA_DIR", root), patch("app.library.TASK_DIR", root / "tasks"), patch("app.library.TEMP_DIR", root / "temp"), patch("app.knowledge.DATA_DIR", root):
                add_evidence(SourceEvidence(
                    evidence_id="video-anchor",
                    source_type="video",
                    title="本地视频",
                    source_uri="local://lesson",
                    locator="31.0-45.0s",
                    text="学习率决定更新步长。",
                    task_id="video-task",
                ))
                task = TaskRecord(
                    id="video-task", source_type="local", mode="local", title="本地视频", status="success",
                    source_media_path=str(media), source_identity=SourceIdentity(media_sha256="a" * 64),
                    created_at="2026-08-31T00:00:00+00:00", updated_at="2026-08-31T00:00:00+00:00",
                )
                material = register_task_material(task)
                self.assertEqual(material["source_type"], "video")
                self.assertEqual(material["linked_task_id"], "video-task")
                self.assertFalse(material["owns_evidence"])
                self.assertFalse(material["metadata"]["original_media_duplicated"])
                self.assertEqual(material_anchors(material["material_id"])[0]["locator"], "31.0-45.0s")

    def test_text_pdf_import_uses_page_anchors(self) -> None:
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        document = canvas.Canvas(buffer)
        document.drawString(72, 760, "Evidence on page one")
        document.showPage()
        document.drawString(72, 760, "Evidence on page two")
        document.save()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.library.DATA_DIR", root), patch("app.library.TASK_DIR", root / "tasks"), patch("app.library.TEMP_DIR", root / "temp"), patch("app.knowledge.DATA_DIR", root):
                material = import_document_material("lesson.pdf", buffer.getvalue(), "application/pdf")
                anchors = material_anchors(material["material_id"])
                self.assertEqual(material["source_type"], "pdf")
                self.assertEqual([item["locator"] for item in anchors], ["page 1", "page 2"])
                self.assertIn("Evidence on page two", anchors[1]["text"])


if __name__ == "__main__":
    unittest.main()
