from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability import read_task_events_after, record_task_event
from app.models import TaskRecord, now_iso
from app.routers.events import events_router, sse_frame


class EventStreamTests(unittest.TestCase):
    def test_sse_frame_preserves_chinese_and_has_reconnect_id(self) -> None:
        frame = sse_frame(7, "draft_ready", {"message": "字幕大纲已可阅读", "progress": 42})
        self.assertTrue(frame.startswith("id: 7\nevent: draft_ready\n"))
        data = next(line[6:] for line in frame.splitlines() if line.startswith("data: "))
        self.assertEqual(json.loads(data)["message"], "字幕大纲已可阅读")
        self.assertTrue(frame.endswith("\n\n"))

    def test_event_name_is_restricted_to_safe_characters(self) -> None:
        frame = sse_frame(1, "task\nevil", {"ok": True})
        self.assertIn("event: taskevil\n", frame)
        self.assertNotIn("event: task\nevil", frame)

    def test_reconnect_cursor_uses_absolute_event_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("app.observability.TASK_DIR", Path(tmp)):
            for index in range(3):
                record_task_event("cursor-task", "step", details={"index": index})
            page = read_task_events_after("cursor-task", after=1)
        self.assertEqual([event_id for event_id, _event in page], [2, 3])
        self.assertEqual([event["details"]["index"] for _event_id, event in page], [1, 2])

    def test_stream_endpoint_replays_after_last_event_id_and_emits_terminal_state(self) -> None:
        timestamp = now_iso()
        task = TaskRecord(
            id="stream-task",
            title="阶段事件",
            source_type="local",
            created_at=timestamp,
            updated_at=timestamp,
            status="success",
            phase="completed",
        )
        app = FastAPI()
        app.include_router(events_router)
        with tempfile.TemporaryDirectory() as tmp, \
             patch("app.observability.TASK_DIR", Path(tmp)), \
             patch("app.routers.events.get_task", return_value=task):
            record_task_event("stream-task", "pipeline_attempt_started", details={"sequence": 1})
            record_task_event("stream-task", "stage_timing", phase="transcript", details={"duration_ms": 12})
            record_task_event("stream-task", "draft_ready", phase="transcript", status="ready", message="字幕草稿已就绪")
            response = TestClient(app).get(
                "/api/tasks/stream-task/events/stream?after=1",
                headers={"Last-Event-ID": "2"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertIn("id: 3\nevent: draft_ready\n", response.text)
        self.assertIn("字幕草稿已就绪", response.text)
        self.assertIn('"event_id":3', response.text)
        self.assertIn("event: task_terminal", response.text)
        self.assertNotIn("pipeline_attempt_started", response.text)
        self.assertNotIn("stage_timing", response.text)


if __name__ == "__main__":
    unittest.main()
