import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.upload_limits import UploadBudgetMiddleware, UploadBudgetExceeded, write_video_upload


class UploadLimitTests(unittest.TestCase):
    def test_chunked_body_is_bounded_before_parser(self):
        sent = []
        async def receive():
            return {"type": "http.request", "body": b"x" * 12, "more_body": True}
        async def app(scope, receive, send):
            while True:
                await receive()
        async def send(message):
            sent.append(message)
        with patch("app.upload_limits.MAX_VIDEO_BYTES", 20), patch("app.upload_limits.MULTIPART_OVERHEAD_BYTES", 0), patch("app.upload_limits.check_upload_space"):
            asyncio.run(UploadBudgetMiddleware(app)({"type": "http", "method": "POST", "path": "/api/tasks/from-local", "headers": []}, receive, send))
        self.assertEqual(sent[0]["status"], 413)

    def test_partial_file_and_upload_handle_are_cleaned_on_limit(self):
        class File:
            closed = False
            async def read(self, size):
                return b"x" * 12
            async def close(self):
                self.closed = True
        with tempfile.TemporaryDirectory() as directory:
            file = File()
            path = Path(directory) / "partial.mp4"
            with patch("app.upload_limits.MAX_VIDEO_BYTES", 20), patch("app.upload_limits.check_upload_space"):
                with self.assertRaises(UploadBudgetExceeded):
                    asyncio.run(write_video_upload(file, path))
            self.assertFalse(path.exists())
            self.assertTrue(file.closed)

    def test_low_disk_does_not_create_pending_file(self):
        class File:
            async def read(self, size):
                return b"content"
            async def close(self):
                pass
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.mp4"
            with patch("app.upload_limits.check_upload_space", side_effect=UploadBudgetExceeded("insufficient_storage", 507, "full")):
                with self.assertRaises(UploadBudgetExceeded):
                    asyncio.run(write_video_upload(File(), path))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
