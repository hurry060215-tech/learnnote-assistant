from __future__ import annotations

import functools
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

from app.downloader import MediaDownloader, preflight_media_resource
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


class RangeGateHandler(QuietHandler):
    required_range = "bytes=0-"

    def do_GET(self) -> None:
        if self.headers.get("Range") != self.required_range:
            self.send_error(403, "range required")
            return
        super().do_GET()


class ExtensionlessHlsHandler(QuietHandler):
    playlist_name = "lesson.m3u8"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/player.json":
            body = b'{"streams":{"hls":"/stream?lesson=1","mimeType":"application/vnd.apple.mpegurl"}}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/stream":
            playlist = Path(self.directory) / self.playlist_name
            body = playlist.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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

    def test_direct_candidate_retries_with_open_ended_range(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "range-gated.mp4"
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
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RangeGateHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                media_path, selected = downloader.download(
                    page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                    resources=[
                        ResourceCandidate(
                            url=media_url,
                            source="webRequest",
                            kind="video",
                            mime="video/mp4",
                            score=100,
                        )
                    ],
                    cookies=[],
                    title="Range gated",
                )
                self.assertTrue(media_path.exists())
                self.assertGreater(media_path.stat().st_size, 4096)
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(downloader.attempts[0].strategy, "direct-file")
                self.assertEqual(downloader.attempts[0].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_page_scan_candidate_is_tried_before_page_resolver(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "hidden.mp4"
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
            page = root / "lesson.html"
            page.write_text(
                '<!doctype html><script>window.__media={"url":"hidden.mp4"};</script>',
                encoding="utf-8",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/{page.name}"
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=page_url,
                        resources=[],
                        cookies=[],
                        title="Page scan",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "page-scan")
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["page-scan", "direct-file"])
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_page_scan_downloads_extensionless_hls_from_json(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
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
                    str(source),
                ],
                check=True,
            )
            playlist = root / "lesson.m3u8"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(source),
                    "-c",
                    "copy",
                    "-f",
                    "hls",
                    "-hls_time",
                    "1",
                    "-hls_list_size",
                    "0",
                    "-hls_segment_filename",
                    str(root / "lesson_%03d.ts"),
                    str(playlist),
                ],
                check=True,
            )

            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ExtensionlessHlsHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/player.json"
                hls_url = f"http://127.0.0.1:{server.server_port}/stream?lesson=1"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=page_url,
                        resources=[],
                        cookies=[],
                        title="Extensionless HLS",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, hls_url)
                self.assertEqual(selected.kind, "hls")
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["page-scan", "manifest-ffmpeg"])
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_reuses_browser_headers_and_cookies(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "preflight.mp4"
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
                result = preflight_media_resource(
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
                    ),
                    [BrowserCookie(name="AUTH", value="ok", domain="127.0.0.1")],
                    HeaderGateHandler.required_referer,
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.strategy, "direct-file-probe")
                self.assertEqual(result.status_code, 200)
                self.assertIn("Origin", result.request_header_names)
                self.assertIn("Referer", result.request_header_names)
                self.assertIn("User-Agent", result.request_header_names)
                self.assertIn("Range", result.request_header_names)
                self.assertNotIn("Cookie", result.request_header_names)
                self.assertGreater(result.bytes_checked, 0)
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_reports_missing_browser_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "forbidden.mp4"
            video.write_bytes(b"not-real-video-but-enough-for-header-gate")
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(HeaderGateHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                result = preflight_media_resource(
                    ResourceCandidate(url=media_url, source="webRequest", kind="video", mime="video/mp4"),
                    [],
                    HeaderGateHandler.required_referer,
                )
                self.assertTrue(result.ok)
                self.assertFalse(result.downloadable)
                self.assertEqual(result.code, "auth_required")
                self.assertEqual(result.status_code, 403)
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_keeps_blob_as_non_downloadable(self) -> None:
        result = preflight_media_resource(
            ResourceCandidate(url="blob:https://example.com/abc", source="activeVideo", kind="blob"),
            [],
            "https://example.com/lesson",
        )
        self.assertTrue(result.ok)
        self.assertFalse(result.downloadable)
        self.assertEqual(result.strategy, "blob-unrecoverable")
        self.assertEqual(result.code, "drm_or_encrypted")


if __name__ == "__main__":
    unittest.main()
