from __future__ import annotations

import functools
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app.downloader import MediaDownloader
from app.models import BrowserCookie, ResourceCandidate
from app.runtime import ffmpeg_bin


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class HeaderGateHandler(QuietHandler):
    required_origin = "https://course.example.com"
    required_referer = "https://course.example.com/lesson/1"
    required_user_agent = "Chrome Test UA"
    required_cookie = "AUTH=ok"

    def do_GET(self) -> None:
        if (
            self.headers.get("Origin") != self.required_origin
            or self.headers.get("Referer") != self.required_referer
            or self.headers.get("User-Agent") != self.required_user_agent
            or self.headers.get("Cookie") != self.required_cookie
        ):
            self.send_error(403, "missing browser context")
            return
        super().do_GET()


@unittest.skipUnless(ffmpeg_bin(), "ffmpeg is required for downloader priority tests")
class DownloaderPriorityTests(unittest.TestCase):
    def test_direct_browser_candidate_is_tried_before_page_resolver(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "direct.mp4"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=duration=2:size=320x180:rate=10",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=2",
                    "-shortest",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                        resources=[
                            ResourceCandidate(
                                url=media_url,
                                source="webRequest",
                                kind="video",
                                mime="video/mp4",
                                score=100,
                                label="playing video",
                            )
                        ],
                        cookies=[],
                        title="Direct first",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(downloader.attempts[0].strategy, "direct-file")
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertGreater(downloader.attempts[0].bytes_downloaded or 0, 4096)
            finally:
                server.shutdown()
                server.server_close()

    def test_direct_candidate_reuses_browser_request_headers_and_cookies(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "gated.mp4"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=duration=2:size=320x180:rate=10",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=2",
                    "-shortest",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(HeaderGateHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                media_path, selected = downloader.download(
                    page_url=HeaderGateHandler.required_referer,
                    resources=[
                        ResourceCandidate(
                            url=media_url,
                            source="webRequest",
                            kind="video",
                            mime="video/mp4",
                            score=100,
                            request_headers={
                                "Origin": HeaderGateHandler.required_origin,
                                "Referer": HeaderGateHandler.required_referer,
                                "User-Agent": HeaderGateHandler.required_user_agent,
                            },
                        )
                    ],
                    cookies=[BrowserCookie(name="AUTH", value="ok", domain="127.0.0.1")],
                    title="Header gated",
                )
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(downloader.attempts[0].status, "success")
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
