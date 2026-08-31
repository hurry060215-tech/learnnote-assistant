from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.observability import read_task_events_after, record_task_event
from app.routers.events import sse_frame


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


if __name__ == "__main__":
    unittest.main()
