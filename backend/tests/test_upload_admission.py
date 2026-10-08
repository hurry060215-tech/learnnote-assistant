"""Real multipart lifecycle and configurable upload admission contracts."""
import asyncio
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from starlette.datastructures import Headers
from starlette.formparsers import MultiPartParser
from starlette.requests import Request

from app.upload_limits import (
    UploadBudgetExceeded, UploadBudgetMiddleware, _positive_byte_setting,
    check_upload_space, upload_policy_snapshot, write_video_upload,
)
from app.upload_reservations import reserved_bytes


class UploadAdmissionTests(unittest.TestCase):
    def test_content_length_rejection_does_not_consume_body(self):
        sent = []
        async def receive():
            self.fail("Oversized request body must not be consumed")
        async def app(scope, receive, send):
            self.fail("Oversized request must not reach multipart parsing")
        async def send(message):
            sent.append(message)
        with tempfile.TemporaryDirectory() as directory, patch("app.upload_limits.TEMP_DIR", Path(directory)), patch("app.upload_limits.MAX_VIDEO_BYTES", 20), patch("app.upload_limits.MULTIPART_OVERHEAD_BYTES", 0):
            asyncio.run(UploadBudgetMiddleware(app)({"type": "http", "method": "POST", "path": "/api/tasks/from-local", "headers": [(b"content-length", b"21")]}, receive, send))
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(json.loads(sent[1]["body"])["detail"]["written_bytes"], 0)

    def test_explicit_positive_limits_and_invalid_values(self):
        with patch.dict("os.environ", {"TEST_UPLOAD_LIMIT": str(6 * 1024**3)}):
            self.assertEqual(_positive_byte_setting("TEST_UPLOAD_LIMIT", 7), 6 * 1024**3)
        for value in ("0", "-1", "invalid"):
            with self.subTest(value=value), patch.dict("os.environ", {"TEST_UPLOAD_LIMIT": value}):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    _positive_byte_setting("TEST_UPLOAD_LIMIT", 7)

    def test_real_multipart_parser_closes_spool_on_limit_and_disconnect(self):
        # Force disk spooling before the second read fails. This guards the real
        # parser contract, rather than merely checking our final-file writer.
        for failure in ("limit", "disconnect"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                first = b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="test.mp4"\r\nContent-Type: video/mp4\r\n\r\n' + b"x" * 2048
                messages = iter([
                    {"type": "http.request", "body": first, "more_body": True},
                    {"type": "http.disconnect"} if failure == "disconnect" else {"type": "http.request", "body": b"x" * 4096, "more_body": True},
                ])
                handles, sent = [], []
                original = tempfile.SpooledTemporaryFile
                def spool(*args, **kwargs):
                    kwargs["dir"] = directory
                    handle = original(*args, **kwargs)
                    handles.append(handle)
                    return handle
                async def receive():
                    return next(messages)
                async def send(message):
                    sent.append(message)
                async def app(scope, receive, send):
                    request = Request(scope, receive)
                    parser = MultiPartParser(Headers(scope=scope), request.stream())
                    await parser.parse()
                scope = {"type": "http", "method": "POST", "path": "/api/tasks/from-local", "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")]}
                with patch("starlette.formparsers.SpooledTemporaryFile", side_effect=spool), patch.object(MultiPartParser, "spool_max_size", 1), patch("app.upload_limits.TEMP_DIR", root), patch("app.upload_limits.UPLOAD_DIR", root), patch("app.upload_limits.MAX_VIDEO_BYTES", 4096), patch("app.upload_limits.MULTIPART_OVERHEAD_BYTES", 0):
                    if failure == "disconnect":
                        from starlette.requests import ClientDisconnect
                        with self.assertRaises(ClientDisconnect):
                            asyncio.run(UploadBudgetMiddleware(app)(scope, receive, send))
                    else:
                        asyncio.run(UploadBudgetMiddleware(app)(scope, receive, send))
                        self.assertEqual(sent[0]["status"], 413)
                        detail = json.loads(sent[1]["body"])["detail"]
                        self.assertGreater(detail["received_bytes"], 4096)
                    self.assertEqual(reserved_bytes(root), 0)
                self.assertTrue(handles)
                self.assertTrue(all(handle.closed for handle in handles))
                self.assertEqual([p.name for p in root.iterdir()], ["upload-budget.sqlite3"])

    def test_actual_write_disk_full_reports_bytes_and_removes_partial(self):
        class File:
            closed = False
            chunks = iter([b"first", b"second"])
            async def read(self, size):
                return next(self.chunks, b"")
            async def close(self):
                self.closed = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "partial.mp4"
            file = File()
            original_open = Path.open
            class DiskFull(io.BytesIO):
                calls = 0
                def write(self, value):
                    self.calls += 1
                    if self.calls == 2:
                        raise OSError(errno.ENOSPC, "sensitive local path must not leak")
                    return super().write(value)
            def open_file(target, *args, **kwargs):
                if target == path:
                    path.touch()
                    return DiskFull()
                return original_open(target, *args, **kwargs)
            with patch("app.upload_limits.TEMP_DIR", root), patch.object(Path, "open", open_file):
                with self.assertRaises(UploadBudgetExceeded) as caught:
                    asyncio.run(write_video_upload(file, path))
            self.assertEqual(caught.exception.code, "insufficient_storage")
            self.assertEqual(caught.exception.status, 507)
            self.assertEqual(caught.exception.written_bytes, 5)
            self.assertEqual(caught.exception.received_bytes, 11)
            self.assertNotIn("sensitive", str(caught.exception))
            self.assertFalse(path.exists())
            self.assertTrue(file.closed)
            self.assertEqual(reserved_bytes(root), 0)

    def test_unavailable_storage_fails_closed_without_local_path(self):
        with patch("app.upload_limits.shutil.disk_usage", side_effect=OSError("private path")):
            with self.assertRaises(UploadBudgetExceeded) as caught:
                check_upload_space(Path("unused"))
        self.assertEqual(caught.exception.code, "storage_unavailable")
        self.assertNotIn("private", str(caught.exception))

    def test_policy_and_journal_follow_selected_data_directory(self):
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch("app.upload_limits.TEMP_DIR", root):
                    result = upload_policy_snapshot()
                self.assertEqual(result["active_upload_bytes"], 0)
                self.assertTrue((root / "upload-budget.sqlite3").exists())
                self.assertGreater(result["free_disk_bytes"], 0)

    def test_restart_after_data_directory_change_uses_new_policy_root(self):
        source = """
import json, os
from app.config import ensure_dirs, TEMP_DIR
from app.upload_limits import upload_policy_snapshot
ensure_dirs()
policy = upload_policy_snapshot()
assert policy['max_video_bytes'] == 6 * 1024**3
assert policy['required_free_disk_bytes'] == 1024**3
assert TEMP_DIR.parent == __import__('pathlib').Path(os.environ['LEARNNOTE_DATA_DIR']).resolve()
assert (TEMP_DIR / 'upload-budget.sqlite3').exists()
print('pass')
"""
        with tempfile.TemporaryDirectory() as directory:
            for name in ("before-migration", "after-migration"):
                env = {**os.environ, "LEARNNOTE_DATA_DIR": str(Path(directory) / name), "LEARNNOTE_MAX_VIDEO_BYTES": str(6 * 1024**3), "LEARNNOTE_UPLOAD_RESERVE_BYTES": str(1024**3)}
                result = subprocess.run([sys.executable, "-c", source], env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "pass")


if __name__ == "__main__":
    unittest.main()
