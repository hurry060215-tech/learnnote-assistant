from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.source_input import clean_task_title, normalize_source_input, title_looks_corrupted
from app.storage import create_task, list_tasks
from app.text_cleanup import correct_common_zh_asr_text, correct_transcript_terms
from app.models import TranscriptResult, TranscriptSegment


class SourceInputTests(unittest.TestCase):
    def test_bvid_and_avid_are_normalized_to_bilibili_pages(self) -> None:
        bv = normalize_source_input("BV1xx411c7mD")
        av = normalize_source_input("av170001")

        self.assertEqual(bv.url, "https://www.bilibili.com/video/BV1xx411c7mD?p=1")
        self.assertEqual(bv.source_id, "BV1xx411c7mD")
        self.assertEqual(av.url, "https://www.bilibili.com/video/av170001?p=1")
        self.assertEqual(av.platform, "bilibili")

    def test_copied_text_extracts_supported_url(self) -> None:
        source = normalize_source_input("课程链接：https://www.bilibili.com/video/BV1xx411c7mD?p=2。")

        self.assertEqual(source.url, "https://www.bilibili.com/video/BV1xx411c7mD?p=2")
        self.assertEqual(source.default_title, "B站视频 · BV1xx411c7mD")

    def test_bilibili_page_without_part_defaults_to_first_part(self) -> None:
        source = normalize_source_input("https://www.bilibili.com/video/BV181wezqEgK")
        selected = normalize_source_input("https://www.bilibili.com/video/BV181wezqEgK?p=7")

        self.assertEqual(source.url, "https://www.bilibili.com/video/BV181wezqEgK?p=1")
        self.assertEqual(selected.url, "https://www.bilibili.com/video/BV181wezqEgK?p=7")

    def test_normalize_api_reports_invalid_plain_text(self) -> None:
        client = TestClient(app)

        valid = client.post("/api/source/normalize", json={"value": "BV1xx411c7mD"})
        invalid = client.post("/api/source/normalize", json={"value": "这不是视频地址"})

        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["source"]["platform"], "bilibili")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["detail"]["code"], "invalid_source_input")

    def test_corrupted_title_uses_page_host_fallback(self) -> None:
        self.assertTrue(title_looks_corrupted("??-1.??????????????.mp4"))
        self.assertEqual(
            clean_task_title("??-1.??????????????.mp4", "https://mooc1.chaoxing.com/mycourse"),
            "学习视频 · mooc1.chaoxing.com",
        )

    def test_common_chinese_asr_terms_are_corrected_conservatively(self) -> None:
        source = TranscriptResult(
            language="zh",
            segments=[TranscriptSegment(start=0, end=4, text="半分建社会与武士运动，后来召开骨田会议")],
            full_text="半分建社会与武士运动，后来召开骨田会议",
        )

        corrected = correct_transcript_terms(source)

        self.assertEqual(corrected.segments[0].text, "半封建社会与五四运动，后来召开古田会议")
        self.assertEqual(correct_common_zh_asr_text("正常术语不修改"), "正常术语不修改")


class StaleTaskTests(unittest.TestCase):
    def test_list_tasks_closes_stale_running_task_without_deleting_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("app.storage.TASK_DIR", Path(tmp)):
            task = create_task("current_page", "stale course", "https://example.com/video")
            task.status = "running"
            task.phase = "downloading"
            task.title = "????????????"
            task.updated_at = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
            task_path = Path(tmp) / task.id / "task.json"
            task_path.write_text(task.model_dump_json(indent=2), encoding="utf-8")

            [record] = list_tasks()

            self.assertEqual(record.status, "failed")
            self.assertEqual(record.error_code, "task_interrupted")
            self.assertEqual(record.title, "学习视频 · example.com")
            self.assertTrue(task_path.is_file())

    def test_recent_running_task_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("app.storage.TASK_DIR", Path(tmp)):
            task = create_task("current_page", "active course", "https://example.com/video")
            task.status = "running"
            task.phase = "transcribing"
            task_path = Path(tmp) / task.id / "task.json"
            task_path.write_text(task.model_dump_json(indent=2), encoding="utf-8")

            [record] = list_tasks()

            self.assertEqual(record.status, "running")
            self.assertEqual(record.error_code, "")

    def test_list_tasks_finalizes_stale_cancelling_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("app.storage.TASK_DIR", Path(tmp)):
            task = create_task("local", "cancelled course")
            task.status = "cancelling"
            task.phase = "cancelling"
            task.cancel_requested = True
            task.cancel_requested_at = (datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat()
            task.updated_at = task.cancel_requested_at
            task_path = Path(tmp) / task.id / "task.json"
            task_path.write_text(task.model_dump_json(indent=2), encoding="utf-8")

            [record] = list_tasks()

            self.assertEqual(record.status, "cancelled")
            self.assertEqual(record.phase, "cancelled")
            self.assertTrue(record.cancelled_at)
            self.assertTrue(record.cancel_requested)

    def test_list_tasks_keeps_recent_cancelling_task_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("app.storage.TASK_DIR", Path(tmp)):
            task = create_task("local", "recent cancellation")
            task.status = "cancelling"
            task.phase = "cancelling"
            task.cancel_requested = True
            task.cancel_requested_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
            task.updated_at = task.cancel_requested_at
            task_path = Path(tmp) / task.id / "task.json"
            task_path.write_text(task.model_dump_json(indent=2), encoding="utf-8")

            [record] = list_tasks()

            self.assertEqual(record.status, "cancelling")
            self.assertFalse(record.cancelled_at)


if __name__ == "__main__":
    unittest.main()
