from __future__ import annotations

import functools
import json
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse
from unittest.mock import patch

from app.config import DATA_DIR
from app.downloader import DownloadError, MediaDownloader, preflight_media_resource
from app.models import BrowserCookie, ResourceCandidate
from app.runtime import ffmpeg_bin

TEST_RUN_DIR = DATA_DIR / "test-runs"
TEST_RUN_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_RUN_DIR)


def json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class HeaderGateHandler(QuietHandler):
    required_origin = "https://course.example.com"
    required_referer = "https://course.example.com/lesson/1"
    required_user_agent = "Chrome Test UA"
    required_authorization = "Bearer playback-token"
    required_cookie = "AUTH=ok"

    def do_GET(self) -> None:
        if (
            self.headers.get("Origin") != self.required_origin
            or self.headers.get("Referer") != self.required_referer
            or self.headers.get("User-Agent") != self.required_user_agent
            or self.headers.get("Authorization") != self.required_authorization
            or self.headers.get("Cookie") != self.required_cookie
        ):
            self.send_error(403, "missing browser context")
            return
        super().do_GET()


class PageScanHeaderGateHandler(QuietHandler):
    required_user_agent = "Chrome Test UA"
    required_x_requested_with = "XMLHttpRequest"
    media_name = "secure.mp4"

    def _has_browser_headers(self) -> bool:
        return (
            self.headers.get("User-Agent") == self.required_user_agent
            and self.headers.get("X-Requested-With") == self.required_x_requested_with
        )

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/player.json":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            body = b'{"videoUrl":"/secure.mp4"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == f"/{self.media_name}":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
        super().do_GET()


class RangeGateHandler(QuietHandler):
    required_range = "bytes=0-"

    def do_GET(self) -> None:
        if self.headers.get("Range") != self.required_range:
            self.send_error(403, "range required")
            return
        super().do_GET()


class RangeRecordingHandler(QuietHandler):
    seen_ranges: list[str] = []

    def do_GET(self) -> None:
        self.__class__.seen_ranges.append(self.headers.get("Range") or "")
        super().do_GET()


class LoginPageAsMediaHandler(QuietHandler):
    def do_GET(self) -> None:
        body = ("<html><title>login</title><body>Please sign in before watching this lesson.</body></html>" * 80).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class OctetStreamLoginPageAsMediaHandler(LoginPageAsMediaHandler):
    def do_GET(self) -> None:
        body = ("<html><title>login</title><body>Please sign in before watching this lesson.</body></html>" * 80).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ImageRedirectAsMediaHandler(QuietHandler):
    def do_GET(self) -> None:
        if urlparse(self.path).path == "/candidate":
            self.send_response(302)
            self.send_header("Location", "/logo.png")
            self.end_headers()
            return
        body = b"\x89PNG\r\n\x1a\n" + (b"not-a-video" * 700)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DisguisedImageAsVideoHandler(QuietHandler):
    def do_GET(self) -> None:
        body = b"\x89PNG\r\n\x1a\n" + (b"not-a-video" * 700)
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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
            content_type = "application/octet-stream" if "raw=1" in self.path else "application/vnd.apple.mpegurl"
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


class ContentDispositionMediaHandler(QuietHandler):
    media_name = "source.mp4"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/download":
            media = Path(self.directory) / self.media_name
            body = media.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''lesson%20download.mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


class SplitAVPreflightHandler(QuietHandler):
    required_referer = "https://course.example.com/player"
    required_cookie = "AUTH=ok"
    audio_forbidden = False
    seen_audio_range = ""
    video_body = b"\x00\x00\x00\x18ftypmp42" + (b"video-only" * 512)
    audio_body = b"\x00\x00\x00\x18ftypM4A " + (b"audio-only" * 512)

    def _authorized(self) -> bool:
        return (
            self.headers.get("Referer") == self.required_referer
            and self.headers.get("Cookie") == self.required_cookie
        )

    def _send_media(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/video-only.mp4":
            if not self._authorized():
                self.send_error(403, "missing browser context")
                return
            self._send_media(self.video_body, "video/mp4")
            return
        if path == "/audio-only.m4a":
            self.__class__.seen_audio_range = self.headers.get("Range") or ""
            if self.audio_forbidden or not self._authorized():
                self.send_error(403, "missing audio context")
                return
            self._send_media(self.audio_body, "audio/mp4")
            return
        super().do_GET()


class DirectJsonMediaHandler(QuietHandler):
    required_user_agent = "Chrome Test UA"
    required_x_requested_with = "XMLHttpRequest"
    required_referer_suffix = "/lesson.html"
    media_name = "real.mp4"

    def _has_browser_headers(self) -> bool:
        return (
            self.headers.get("User-Agent") == self.required_user_agent
            and self.headers.get("X-Requested-With") == self.required_x_requested_with
            and (self.headers.get("Referer") or "").endswith(self.required_referer_suffix)
        )

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/play":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            body = b'{"data":{"videoUrl":"/real.mp4","mimeType":"video/mp4"}}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == f"/{self.media_name}" and not self._has_browser_headers():
            self.send_error(403, "missing browser headers")
            return
        super().do_GET()


class SourceEndpointJsonMediaHandler(DirectJsonMediaHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/source":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            body = b'{"data":{"sourceUrl":"/real.mp4","mimeType":"video/mp4"}}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


class MultiSourceJsonMediaHandler(DirectJsonMediaHandler):
    forbidden_name = "forbidden.mp4"
    media_name = "real.mp4"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/play":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            body = json_bytes({
                "data": {
                    "videoUrl": f"/{self.forbidden_name}",
                    "backupUrl": f"/{self.media_name}",
                    "mimeType": "video/mp4",
                }
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == f"/{self.forbidden_name}":
            self.send_error(403, "expired source")
            return
        if path == f"/{self.media_name}" and not self._has_browser_headers():
            self.send_error(403, "missing browser headers")
            return
        super().do_GET()


class EmptyJsonPlayHandler(DirectJsonMediaHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/play":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            body = b'{"data":{"status":"ok","message":"no media url yet"}}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


class ChaoxingJsonArrayMediaHandler(DirectJsonMediaHandler):
    media_body = b"\x00\x00\x00\x18ftypmp42" + (b"chaoxing-extensionless" * 512)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/play":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            body = b'{"sources":[{"url":"/ananas/status/objectid-123?flag=normal"}],"streams":["/vod/lesson?id=noext"]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/ananas/status/objectid-123":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.media_body)))
            self.end_headers()
            self.wfile.write(self.media_body)
            return
        super().do_GET()


class DirectPostJsonMediaHandler(DirectJsonMediaHandler):
    required_body = "lesson=42&token=ok"
    seen_bodies: list[str] = []

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/play":
            self.send_error(405, "POST required")
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/play":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        self.__class__.seen_bodies.append(body)
        if not self._has_browser_headers() or body != self.required_body:
            self.send_error(403, "missing browser context")
            return
        payload = b'{"data":{"videoUrl":"/real.mp4","mimeType":"video/mp4"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class SplitHostPathJsonMediaHandler(DirectJsonMediaHandler):
    media_body = b"\x00\x00\x00\x18ftypmp42" + (b"split-host-path" * 512)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/play":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_port}"
            payload = json_bytes({
                "data": {
                    "cdnBase": f"http://{host}/cdn/",
                    "filePath": "real.mp4",
                    "mimeType": "video/mp4",
                }
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/cdn/real.mp4":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.media_body)))
            self.end_headers()
            self.wfile.write(self.media_body)
            return
        super().do_GET()


class ParentBaseNestedJsonMediaHandler(DirectJsonMediaHandler):
    media_body = b"\x00\x00\x00\x18ftypmp42" + (b"parent-base-nested-path" * 512)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/play":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_port}"
            payload = json_bytes({
                "cdnBase": f"http://{host}/cdn/",
                "data": {
                    "streams": [
                        {
                            "filePath": "nested/real.mp4",
                            "mimeType": "video/mp4",
                        }
                    ]
                },
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/cdn/nested/real.mp4":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.media_body)))
            self.end_headers()
            self.wfile.write(self.media_body)
            return
        super().do_GET()


class HostPrefixFilenameJsonMediaHandler(DirectJsonMediaHandler):
    media_body = b"\x00\x00\x00\x18ftypmp42" + (b"host-prefix-filename" * 512)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/play":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_port}"
            payload = json_bytes({
                "data": {
                    "cdnHost": f"http://{host}",
                    "pathPrefix": "/cdn/course42/",
                    "video": {
                        "fileName": "real.mp4",
                        "mimeType": "video/mp4",
                    },
                }
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/cdn/course42/real.mp4":
            if not self._has_browser_headers():
                self.send_error(403, "missing browser headers")
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.media_body)))
            self.end_headers()
            self.wfile.write(self.media_body)
            return
        super().do_GET()


class Html5VideoElementHandler(QuietHandler):
    media_body = b"\x00\x00\x00\x18ftypmp42" + (b"html5-video-element" * 512)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/lesson.html":
            body = b"""
            <!doctype html>
            <html><body>
              <video controls src="/api/play?id=42&token=abc"></video>
            </body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/play":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.media_body)))
            self.end_headers()
            self.wfile.write(self.media_body)
            return
        super().do_GET()


class IframePlayerShellHandler(QuietHandler):
    media_body = b"\x00\x00\x00\x18ftypmp42" + (b"iframe-player-shell" * 512)
    seen_shell_referer = ""
    seen_media_referer = ""

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/course/shell.html":
            body = b"""
            <!doctype html>
            <html><body>
              <iframe id="course-player" title="lesson video player" src="/frame.html?jobid=42"></iframe>
            </body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/frame.html":
            type(self).seen_shell_referer = self.headers.get("Referer", "")
            body = b"""
            <!doctype html>
            <html><body>
              <script>window.__playInfo = {"videoUrl":"/media/lesson.mp4","mimeType":"video/mp4"};</script>
            </body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/media/lesson.mp4":
            type(self).seen_media_referer = self.headers.get("Referer", "")
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.media_body)))
            self.end_headers()
            self.wfile.write(self.media_body)
            return
        super().do_GET()


class BlackboardActivityIframeHandler(QuietHandler):
    media_body = b"\x00\x00\x00\x18ftypmp42" + (b"six-second-promo" * 512)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/video/BV-course":
            body = b"""
            <!doctype html><html><body>
              <iframe src="/blackboard/era/activity-player.html" title="activity player"></iframe>
            </body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/blackboard/era/activity-player.html":
            body = b"""
            <!doctype html><html><body>
              <video autoplay src="/activity.hdslb.com/promo.mp4"></video>
            </body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in {"/activity.hdslb.com/promo.mp4", "/course.mp4"}:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.media_body)))
            self.end_headers()
            self.wfile.write(self.media_body)
            return
        super().do_GET()


class RedirectMediaHandler(QuietHandler):
    media_name = "final.mp4"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/gate":
            self.send_response(302)
            self.send_header("Location", f"/{self.media_name}")
            self.end_headers()
            return
        super().do_GET()


class ResolvedMediaOnlyHandler(QuietHandler):
    media_name = "final.mp4"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/expired-gate":
            self.send_error(403, "expired gate")
            return
        super().do_GET()


class RedirectManifestHandler(QuietHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/manifest-gate":
            self.send_response(302)
            self.send_header("Location", "/real/master.m3u8")
            self.end_headers()
            return
        if path == "/real/master.m3u8":
            body = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n#EXT-X-ENDLIST\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


class PostManifestHandler(QuietHandler):
    seen_body = b""
    seen_referer = ""
    seen_x_requested_with = ""

    def do_GET(self) -> None:
        self.send_error(405, "manifest requires POST")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/play":
            self.send_error(404, "not found")
            return
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen_body = self.rfile.read(length)
        type(self).seen_referer = self.headers.get("Referer", "")
        type(self).seen_x_requested_with = self.headers.get("X-Requested-With", "")
        body = b"\n".join([
            b"#EXTM3U",
            b"#EXT-X-VERSION:3",
            b"#EXT-X-TARGETDURATION:6",
            b'#EXT-X-KEY:METHOD=AES-128,URI="key.bin"',
            b"#EXTINF:6,",
            b"seg/000.ts",
            b"#EXT-X-ENDLIST",
            b"",
        ])
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ResolvedManifestOnlyHandler(QuietHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/expired-gate":
            self.send_error(403, "expired gate")
            return
        if path == "/real/master.m3u8":
            body = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n#EXT-X-ENDLIST\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


@unittest.skipUnless(ffmpeg_bin(), "ffmpeg is required for downloader priority tests")
class DownloaderPriorityTests(unittest.TestCase):
    def test_page_scan_downloads_extensionless_html5_video_src(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Html5VideoElementHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                media_url = f"http://127.0.0.1:{server.server_port}/api/play?id=42&token=abc"
                downloader = MediaDownloader(root / "task")
                media_path, selected = downloader.download(
                    page_url=page_url,
                    resources=[],
                    cookies=[],
                    title="HTML5 element",
                )

                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.kind, "video")
                self.assertEqual(selected.label, "html video src")
                self.assertEqual(downloader.attempts[0].strategy, "page-scan")
                self.assertEqual(downloader.attempts[1].strategy, "direct-file")
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_page_scan_recurses_into_player_iframe_and_downloads_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            IframePlayerShellHandler.seen_shell_referer = ""
            IframePlayerShellHandler.seen_media_referer = ""
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(IframePlayerShellHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                shell_url = f"http://127.0.0.1:{server.server_port}/course/shell.html"
                frame_url = f"http://127.0.0.1:{server.server_port}/frame.html?jobid=42"
                media_url = f"http://127.0.0.1:{server.server_port}/media/lesson.mp4"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=shell_url,
                        resources=[],
                        cookies=[],
                        title="Iframe player",
                    )

                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "page-scan")
                self.assertEqual(selected.request_headers["Referer"], frame_url)
                self.assertEqual(IframePlayerShellHandler.seen_shell_referer, shell_url)
                self.assertEqual(IframePlayerShellHandler.seen_media_referer, frame_url)
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:3]], ["page-scan", "page-scan", "direct-file"])
                self.assertEqual(downloader.attempts[-1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_blackboard_activity_iframe_video_is_not_a_primary_page_scan_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), BlackboardActivityIframeHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/video/BV-course"
                downloader = MediaDownloader(root / "task")
                discovered = downloader._discover_page_resources(page_url, [], None)
                promo = next(item for item in discovered if item.url.endswith("/activity.hdslb.com/promo.mp4"))

                self.assertIn("/blackboard/era/", promo.frame_url)
                self.assertEqual(promo.page_url, page_url)
                self.assertEqual(downloader._candidate_resources(discovered), [])

                trusted = ResourceCandidate(
                    url=f"http://127.0.0.1:{server.server_port}/course.mp4",
                    source="webRequestResolved",
                    kind="video",
                    mime="video/mp4",
                    playback_match="resolved-final-url",
                    is_main_video=True,
                )
                ranked = downloader._candidate_resources([promo, trusted])
                self.assertEqual([item.url for item in ranked], [trusted.url])
            finally:
                server.shutdown()
                server.server_close()

    def test_bilibili_page_resolver_precedes_unknown_blackboard_iframe_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "resolved.mp4"
            output.write_bytes(b"\x00\x00\x00\x18ftypmp42" + (b"course-video" * 512))
            page_url = "https://www.bilibili.com/video/BV1course?p=1"
            frame_hint = ResourceCandidate(
                url="https://www.bilibili.com/blackboard/era/activity.html",
                source="iframeHint",
                kind="unknown",
                label="activity iframe",
                page_url=page_url,
                frame_url="https://www.bilibili.com/blackboard/era/activity.html",
            )
            downloader = MediaDownloader(root / "task")

            with patch.object(downloader, "_download_with_ytdlp", return_value=output) as ytdlp, patch.object(
                downloader, "_discover_page_resources"
            ) as page_scan:
                media_path, selected = downloader.download(
                    page_url=page_url,
                    resources=[frame_hint],
                    cookies=[],
                    title="Bilibili course",
                )

            self.assertEqual(media_path, output)
            self.assertIsNone(selected)
            self.assertEqual(ytdlp.call_args.args[0], page_url)
            page_scan.assert_not_called()

    def test_direct_page_url_precedes_untrusted_page_scan_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), BlackboardActivityIframeHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/course.mp4"
                promo_url = f"http://127.0.0.1:{server.server_port}/activity.hdslb.com/promo.mp4"
                downloader = MediaDownloader(root / "task")
                media_path, selected = downloader.download(
                    page_url=page_url,
                    resources=[
                        ResourceCandidate(
                            url=promo_url,
                            source="page-scan",
                            kind="video",
                            mime="video/mp4",
                            score=100,
                            page_url="https://www.bilibili.com/video/BV-course",
                            frame_url="https://www.bilibili.com/blackboard/era/activity.html",
                        )
                    ],
                    cookies=[],
                    title="Direct course",
                )

                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, page_url)
                self.assertEqual(selected.source, "page-url")
            finally:
                server.shutdown()
                server.server_close()

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
                                "Authorization": HeaderGateHandler.required_authorization,
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
                self.assertEqual(downloader.attempts[0].request_header_names, ["Origin", "Referer", "User-Agent"])
                self.assertIn("候选证据", downloader.attempts[0].message)
                self.assertIn("请求头 Origin, Referer, User-Agent", downloader.attempts[0].message)
                self.assertNotIn("AUTH=ok", downloader.attempts[0].message)
                self.assertNotIn(HeaderGateHandler.required_user_agent, downloader.attempts[0].message)
                self.assertNotIn(HeaderGateHandler.required_authorization, downloader.attempts[0].message)
                self.assertNotIn("Authorization", downloader.attempts[0].message)
                self.assertNotIn("Cookie", downloader.attempts[0].request_header_names)
                self.assertNotIn("Authorization", downloader.attempts[0].request_header_names)
            finally:
                server.shutdown()
                server.server_close()

    def test_extensionless_content_disposition_video_download(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / ContentDispositionMediaHandler.media_name
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
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ContentDispositionMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/download?id=lesson"
                candidate = ResourceCandidate(
                    url=media_url,
                    source="webRequest",
                    kind="video",
                    mime="application/octet-stream",
                    score=100,
                )
                result = preflight_media_resource(candidate, [], f"http://127.0.0.1:{server.server_port}/lesson.html")
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.resolved_url, media_url)
                self.assertIn("lesson%20download.mp4", result.content_disposition)

                downloader = MediaDownloader(root / "task")
                media_path, selected = downloader.download(
                    page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                    resources=[candidate],
                    cookies=[],
                    title="Header named",
                )
                self.assertTrue(media_path.exists())
                self.assertEqual(media_path.suffix, ".mp4")
                self.assertEqual(media_path.stat().st_size, video.stat().st_size)
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.status_code, 200)
                self.assertEqual(selected.content_length, video.stat().st_size)
                self.assertEqual(selected.mime, "application/octet-stream")
                self.assertIn("lesson%20download.mp4", selected.headers.get("content-disposition", ""))
                self.assertEqual(downloader.attempts[0].status_code, 200)
                self.assertEqual(downloader.attempts[0].content_length, video.stat().st_size)
                self.assertEqual(downloader.attempts[0].mime, "application/octet-stream")
            finally:
                server.shutdown()
                server.server_close()

    def test_direct_json_play_endpoint_downloads_embedded_media_url(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / DirectJsonMediaHandler.media_name
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

            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(DirectJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                play_url = f"http://127.0.0.1:{server.server_port}/api/play?id=42"
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                        resources=[
                            ResourceCandidate(
                                url=play_url,
                                source="webRequest",
                                kind="video",
                                mime="video/mp4",
                                score=100,
                                label="extensionless play API",
                                request_headers={
                                    "User-Agent": DirectJsonMediaHandler.required_user_agent,
                                    "X-Requested-With": DirectJsonMediaHandler.required_x_requested_with,
                                },
                            )
                        ],
                        cookies=[],
                        title="Direct JSON API",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "direct-response")
                self.assertEqual(selected.request_headers["X-Requested-With"], DirectJsonMediaHandler.required_x_requested_with)
                self.assertTrue(selected.request_headers["Referer"].endswith(DirectJsonMediaHandler.required_referer_suffix))
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["direct-response-scan", "direct-file"])
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_source_named_json_endpoint_preflights_as_playback_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / SourceEndpointJsonMediaHandler.media_name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"source" * 512)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SourceEndpointJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                source_url = f"http://127.0.0.1:{server.server_port}/source?id=42"
                media_url = f"http://127.0.0.1:{server.server_port}/{SourceEndpointJsonMediaHandler.media_name}"
                candidate = ResourceCandidate(
                    url=source_url,
                    source="webRequest",
                    kind="unknown",
                    mime="application/json",
                    score=92,
                    label="source playback API",
                    request_type="fetch",
                    request_headers={
                        "User-Agent": SourceEndpointJsonMediaHandler.required_user_agent,
                        "X-Requested-With": SourceEndpointJsonMediaHandler.required_x_requested_with,
                    },
                )

                preflight = preflight_media_resource(candidate, [], page_url)

                self.assertTrue(preflight.downloadable)
                self.assertEqual(preflight.strategy, "direct-response-probe")
                self.assertEqual(preflight.resolved_url, media_url)
                self.assertEqual(preflight.content_type, "video/mp4")
            finally:
                server.shutdown()
                server.server_close()

    def test_chaoxing_json_array_endpoint_preflights_and_downloads_extensionless_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ChaoxingJsonArrayMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                play_url = f"http://127.0.0.1:{server.server_port}/api/play?id=42"
                media_url = f"http://127.0.0.1:{server.server_port}/ananas/status/objectid-123?flag=normal"
                candidate = ResourceCandidate(
                    url=play_url,
                    source="webRequest",
                    kind="video",
                    mime="application/json",
                    score=100,
                    label="chaoxing play API",
                    request_headers={
                        "User-Agent": ChaoxingJsonArrayMediaHandler.required_user_agent,
                        "X-Requested-With": ChaoxingJsonArrayMediaHandler.required_x_requested_with,
                    },
                )

                preflight = preflight_media_resource(candidate, [], page_url)
                self.assertTrue(preflight.downloadable)
                self.assertEqual(preflight.strategy, "direct-response-probe")
                self.assertEqual(preflight.kind, "video")
                self.assertEqual(preflight.resolved_url, media_url)
                self.assertEqual(preflight.status_code, 200)
                self.assertEqual(preflight.content_type, "video/mp4")

                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=page_url,
                        resources=[candidate],
                        cookies=[],
                        title="Chaoxing JSON Array",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "direct-response")
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["direct-response-scan", "direct-file"])
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_post_json_play_endpoint_replays_browser_request_body(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / DirectPostJsonMediaHandler.media_name
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

            DirectPostJsonMediaHandler.seen_bodies = []
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(DirectPostJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                play_url = f"http://127.0.0.1:{server.server_port}/api/play"
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                candidate = ResourceCandidate(
                    url=play_url,
                    source="webRequest",
                    kind="unknown",
                    mime="application/json",
                    score=100,
                    label="POST play API",
                    method="POST",
                    request_type="xmlhttprequest",
                    request_headers={
                        "User-Agent": DirectPostJsonMediaHandler.required_user_agent,
                        "X-Requested-With": DirectPostJsonMediaHandler.required_x_requested_with,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    request_body={"type": "form", "content": DirectPostJsonMediaHandler.required_body},
                )

                preflight = preflight_media_resource(candidate, [], page_url)
                self.assertTrue(preflight.downloadable)
                self.assertEqual(preflight.strategy, "direct-response-probe")
                self.assertEqual(preflight.resolved_url, media_url)

                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=page_url,
                        resources=[candidate],
                        cookies=[],
                        title="POST JSON API",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "direct-response")
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["direct-response-scan", "direct-file"])
                self.assertGreaterEqual(DirectPostJsonMediaHandler.seen_bodies.count(DirectPostJsonMediaHandler.required_body), 2)
            finally:
                server.shutdown()
                server.server_close()

    def test_obeebee_page_scan_candidate_resolving_to_png_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), ImageRedirectAsMediaHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = "https://www.obeebee.com/"
                candidate = ResourceCandidate(
                    url=f"http://127.0.0.1:{server.server_port}/candidate",
                    source="page-scan",
                    kind="video",
                    score=100,
                    user_selected=True,
                )

                preflight = preflight_media_resource(candidate, [], page_url)
                self.assertTrue(preflight.ok)
                self.assertFalse(preflight.downloadable)
                self.assertEqual(preflight.code, "media_mismatch")
                self.assertEqual(preflight.content_type, "image/png")

                downloader = MediaDownloader(root / "task")
                with self.assertRaises(DownloadError) as raised:
                    downloader._download_file(candidate, [], page_url, "Wrong candidate")
                self.assertEqual(raised.exception.code, "media_mismatch")
                self.assertFalse(list((root / "task" / "download").glob("*_direct*")))
            finally:
                server.shutdown()
                server.server_close()

    def test_png_magic_disguised_as_video_mime_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), DisguisedImageAsVideoHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                candidate = ResourceCandidate(
                    url=f"http://127.0.0.1:{server.server_port}/fake.mp4",
                    source="webRequestResolved",
                    kind="video",
                    mime="video/mp4",
                    is_main_video=True,
                )
                preflight = preflight_media_resource(candidate, [], "https://www.obeebee.com/")
                self.assertFalse(preflight.downloadable)
                self.assertEqual(preflight.code, "media_mismatch")
                self.assertIn("PNG image", preflight.message)

                downloader = MediaDownloader(root / "task")
                with self.assertRaises(DownloadError) as raised:
                    downloader._download_file(candidate, [], "https://www.obeebee.com/", "Disguised image")
                self.assertEqual(raised.exception.code, "media_mismatch")
                self.assertFalse(list((root / "task" / "download").glob("*_direct*")))
            finally:
                server.shutdown()
                server.server_close()

    def test_direct_json_play_endpoint_without_media_returns_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(EmptyJsonPlayHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                play_url = f"http://127.0.0.1:{server.server_port}/api/play"
                candidate = ResourceCandidate(
                    url=play_url,
                    source="webRequest",
                    kind="video",
                    mime="application/json",
                    score=90,
                    label="empty play API",
                    request_headers={
                        "User-Agent": EmptyJsonPlayHandler.required_user_agent,
                        "X-Requested-With": EmptyJsonPlayHandler.required_x_requested_with,
                    },
                )

                preflight = preflight_media_resource(candidate, [], page_url)
                self.assertTrue(preflight.ok)
                self.assertFalse(preflight.downloadable)
                self.assertEqual(preflight.strategy, "direct-file-probe")
                self.assertEqual(preflight.code, "download_forbidden")
                self.assertIn("no downloadable video", preflight.message)

                downloader = MediaDownloader(root / "task")
                with self.assertRaises(DownloadError) as raised:
                    downloader._download_file(candidate, [], page_url, "Empty JSON API")
                self.assertEqual(raised.exception.code, "download_forbidden")
                self.assertIn("no downloadable video", raised.exception.message)
            finally:
                server.shutdown()
                server.server_close()

    def test_split_host_path_json_endpoint_preflights_and_downloads_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SplitHostPathJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                play_url = f"http://127.0.0.1:{server.server_port}/api/play"
                media_url = f"http://127.0.0.1:{server.server_port}/cdn/real.mp4"
                candidate = ResourceCandidate(
                    url=play_url,
                    source="webRequest",
                    kind="unknown",
                    mime="application/json",
                    score=92,
                    label="split host/path play API",
                    request_type="fetch",
                    request_headers={
                        "User-Agent": SplitHostPathJsonMediaHandler.required_user_agent,
                        "X-Requested-With": SplitHostPathJsonMediaHandler.required_x_requested_with,
                    },
                )

                preflight = preflight_media_resource(candidate, [], page_url)
                self.assertTrue(preflight.downloadable)
                self.assertEqual(preflight.strategy, "direct-response-probe")
                self.assertEqual(preflight.resolved_url, media_url)
                self.assertEqual(preflight.content_type, "video/mp4")

                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=page_url,
                        resources=[candidate],
                        cookies=[],
                        title="Split host path JSON API",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "direct-response")
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["direct-response-scan", "direct-file"])
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_parent_json_base_combines_with_nested_media_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ParentBaseNestedJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                play_url = f"http://127.0.0.1:{server.server_port}/api/play"
                media_url = f"http://127.0.0.1:{server.server_port}/cdn/nested/real.mp4"
                candidate = ResourceCandidate(
                    url=play_url,
                    source="webRequest",
                    kind="unknown",
                    mime="application/json",
                    score=92,
                    label="parent base nested path API",
                    request_type="fetch",
                    request_headers={
                        "User-Agent": ParentBaseNestedJsonMediaHandler.required_user_agent,
                        "X-Requested-With": ParentBaseNestedJsonMediaHandler.required_x_requested_with,
                    },
                )

                preflight = preflight_media_resource(candidate, [], page_url)
                self.assertTrue(preflight.downloadable)
                self.assertEqual(preflight.strategy, "direct-response-probe")
                self.assertEqual(preflight.resolved_url, media_url)
                self.assertEqual(preflight.content_type, "video/mp4")

                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=page_url,
                        resources=[candidate],
                        cookies=[],
                        title="Parent base nested JSON API",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "direct-response")
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["direct-response-scan", "direct-file"])
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_json_host_prefix_and_nested_filename_combine_to_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(HostPrefixFilenameJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                play_url = f"http://127.0.0.1:{server.server_port}/api/play"
                media_url = f"http://127.0.0.1:{server.server_port}/cdn/course42/real.mp4"
                candidate = ResourceCandidate(
                    url=play_url,
                    source="webRequest",
                    kind="unknown",
                    mime="application/json",
                    score=92,
                    label="host prefix filename API",
                    request_type="fetch",
                    request_headers={
                        "User-Agent": HostPrefixFilenameJsonMediaHandler.required_user_agent,
                        "X-Requested-With": HostPrefixFilenameJsonMediaHandler.required_x_requested_with,
                    },
                )

                preflight = preflight_media_resource(candidate, [], page_url)
                self.assertTrue(preflight.downloadable)
                self.assertEqual(preflight.strategy, "direct-response-probe")
                self.assertEqual(preflight.resolved_url, media_url)
                self.assertEqual(preflight.content_type, "video/mp4")

                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=page_url,
                        resources=[candidate],
                        cookies=[],
                        title="Host prefix filename JSON API",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "direct-response")
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["direct-response-scan", "direct-file"])
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_unknown_post_play_endpoint_is_scanned_with_browser_request_body(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / DirectPostJsonMediaHandler.media_name
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

            DirectPostJsonMediaHandler.seen_bodies = []
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(DirectPostJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                play_url = f"http://127.0.0.1:{server.server_port}/api/play"
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=page_url,
                        resources=[
                            ResourceCandidate(
                                url=play_url,
                                source="webRequest",
                                kind="unknown",
                                mime="application/json",
                                score=70,
                                label="POST play API JSON",
                                request_type="fetch",
                                method="POST",
                                page_url=page_url,
                                request_headers={
                                    "User-Agent": DirectPostJsonMediaHandler.required_user_agent,
                                    "X-Requested-With": DirectPostJsonMediaHandler.required_x_requested_with,
                                    "Content-Type": "application/x-www-form-urlencoded",
                                },
                                request_body={"type": "form", "content": DirectPostJsonMediaHandler.required_body},
                            )
                        ],
                        cookies=[],
                        title="Unknown POST API fallback",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "direct-response")
                self.assertEqual(DirectPostJsonMediaHandler.seen_bodies, [DirectPostJsonMediaHandler.required_body])
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["direct-response-scan", "direct-file"])
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_resolved_post_play_endpoint_downloads_media_with_get(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / DirectPostJsonMediaHandler.media_name
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

            DirectPostJsonMediaHandler.seen_bodies = []
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(DirectPostJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                play_url = f"http://127.0.0.1:{server.server_port}/api/play"
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                media_path, selected = downloader.download(
                    page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                    resources=[
                        ResourceCandidate(
                            url=play_url,
                            resolved_url=media_url,
                            source="webRequest",
                            kind="video",
                            mime="video/mp4",
                            score=100,
                            label="resolved POST play API",
                            method="POST",
                            request_headers={
                                "User-Agent": DirectPostJsonMediaHandler.required_user_agent,
                                "X-Requested-With": DirectPostJsonMediaHandler.required_x_requested_with,
                                "Content-Type": "application/x-www-form-urlencoded",
                            },
                            request_body={"type": "form", "content": DirectPostJsonMediaHandler.required_body},
                        )
                    ],
                    cookies=[],
                    title="Resolved POST JSON API",
                )

                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, play_url)
                self.assertEqual(selected.resolved_url, media_url)
                self.assertEqual(downloader.attempts[0].strategy, "direct-file")
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertEqual(DirectPostJsonMediaHandler.seen_bodies, [])
            finally:
                server.shutdown()
                server.server_close()

    def test_direct_candidate_does_not_reuse_observed_partial_range(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "full-video.mp4"
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
            RangeRecordingHandler.seen_ranges = []
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RangeRecordingHandler, directory=str(root)))
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
                            request_headers={"Range": "bytes=100000-"},
                        )
                    ],
                    cookies=[],
                    title="Full direct",
                )
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(RangeRecordingHandler.seen_ranges[0], "")
                self.assertEqual(media_path.stat().st_size, video.stat().st_size)
            finally:
                server.shutdown()
                server.server_close()

    def test_direct_candidate_records_final_redirect_url(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / RedirectMediaHandler.media_name
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
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RedirectMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                gate_url = f"http://127.0.0.1:{server.server_port}/gate"
                final_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                media_path, selected = downloader.download(
                    page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                    resources=[
                        ResourceCandidate(
                            url=gate_url,
                            source="webRequest",
                            kind="video",
                            mime="video/mp4",
                            score=100,
                        )
                    ],
                    cookies=[],
                    title="Redirect direct",
                )
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, gate_url)
                self.assertEqual(selected.resolved_url, final_url)
                self.assertEqual(downloader.attempts[0].url, gate_url)
                self.assertEqual(downloader.attempts[0].resolved_url, final_url)
                self.assertIn("最终 URL", downloader.attempts[0].message)
            finally:
                server.shutdown()
                server.server_close()

    def test_direct_candidate_prefers_existing_resolved_url(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / ResolvedMediaOnlyHandler.media_name
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
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ResolvedMediaOnlyHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                gate_url = f"http://127.0.0.1:{server.server_port}/expired-gate"
                final_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                media_path, selected = downloader.download(
                    page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                    resources=[
                        ResourceCandidate(
                            url=gate_url,
                            resolved_url=final_url,
                            source="webRequest",
                            kind="video",
                            mime="video/mp4",
                            score=100,
                        )
                    ],
                    cookies=[],
                    title="Resolved direct",
                )
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, gate_url)
                self.assertEqual(selected.resolved_url, final_url)
                self.assertEqual(selected.status_code, 200)
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertEqual(downloader.attempts[0].url, gate_url)
                self.assertEqual(downloader.attempts[0].resolved_url, final_url)
            finally:
                server.shutdown()
                server.server_close()

    def test_unknown_candidate_uses_resolved_video_url(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / ResolvedMediaOnlyHandler.media_name
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
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ResolvedMediaOnlyHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                gate_url = f"http://127.0.0.1:{server.server_port}/expired-gate"
                final_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                media_path, selected = downloader.download(
                    page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                    resources=[
                        ResourceCandidate(
                            url=gate_url,
                            resolved_url=final_url,
                            source="webRequestResolved",
                            kind="unknown",
                            mime="",
                            score=20,
                        )
                    ],
                    cookies=[],
                    title="Resolved unknown direct",
                )
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.kind, "video")
                self.assertEqual(selected.resolved_url, final_url)
                self.assertEqual(downloader.attempts[0].strategy, "direct-file")
                self.assertEqual(downloader.attempts[0].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_manifest_download_uses_final_redirect_url_for_ffmpeg(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text, **kwargs):
            captured["cmd"] = cmd
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"0" * 5000)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RedirectManifestHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                gate_url = f"http://127.0.0.1:{server.server_port}/manifest-gate"
                final_url = f"http://127.0.0.1:{server.server_port}/real/master.m3u8"
                candidate = ResourceCandidate(url=gate_url, source="webRequest", kind="hls", mime="application/vnd.apple.mpegurl")
                downloader = MediaDownloader(root / "task")
                with patch("app.downloader.ffmpeg_bin", return_value="ffmpeg"), patch("app.downloader.subprocess.run", side_effect=fake_run):
                    media = downloader._download_manifest(candidate, [], "https://course.example.com/lesson", "Redirect HLS")

                self.assertTrue(media.exists())
                self.assertEqual(candidate.resolved_url, final_url)
                self.assertIn("-i", captured["cmd"])
                self.assertEqual(captured["cmd"][captured["cmd"].index("-i") + 1], final_url)
            finally:
                server.shutdown()
                server.server_close()

    def test_manifest_download_allows_extensionless_segments_and_keys(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text, **kwargs):
            captured["cmd"] = cmd
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"0" * 5000)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RedirectManifestHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                manifest_url = f"http://127.0.0.1:{server.server_port}/real/master.m3u8"
                candidate = ResourceCandidate(
                    url=manifest_url,
                    source="webRequest",
                    kind="hls",
                    mime="application/vnd.apple.mpegurl",
                )
                downloader = MediaDownloader(root / "task")
                with patch("app.downloader.ffmpeg_bin", return_value="ffmpeg"), patch("app.downloader.subprocess.run", side_effect=fake_run):
                    media = downloader._download_manifest(candidate, [], "https://course.example.com/lesson", "Extensionless HLS")

                self.assertTrue(media.exists())
                self.assertIn("-protocol_whitelist", captured["cmd"])
                self.assertIn("file,http,https,tcp,tls,crypto,data", captured["cmd"])
                self.assertIn("-allowed_extensions", captured["cmd"])
                self.assertIn("ALL", captured["cmd"])
                self.assertLess(captured["cmd"].index("-allowed_extensions"), captured["cmd"].index("-i"))
            finally:
                server.shutdown()
                server.server_close()

    def test_unknown_candidate_uses_resolved_manifest_url(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text, **kwargs):
            captured["cmd"] = cmd
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"0" * 5000)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ResolvedManifestOnlyHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                gate_url = f"http://127.0.0.1:{server.server_port}/expired-gate"
                final_url = f"http://127.0.0.1:{server.server_port}/real/master.m3u8"
                downloader = MediaDownloader(root / "task")
                with patch("app.downloader.ffmpeg_bin", return_value="ffmpeg"), patch("app.downloader.subprocess.run", side_effect=fake_run):
                    media_path, selected = downloader.download(
                        page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                        resources=[
                            ResourceCandidate(
                                url=gate_url,
                                resolved_url=final_url,
                                source="webRequestResolved",
                                kind="unknown",
                                mime="",
                                score=20,
                            )
                        ],
                        cookies=[],
                        title="Resolved unknown HLS",
                    )

                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.kind, "hls")
                self.assertEqual(selected.resolved_url, final_url)
                self.assertEqual(downloader.attempts[0].strategy, "manifest-ffmpeg")
                self.assertIn("-i", captured["cmd"])
                self.assertEqual(captured["cmd"][captured["cmd"].index("-i") + 1], final_url)
            finally:
                server.shutdown()
                server.server_close()

    def test_manifest_download_replays_post_body_to_local_manifest(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text, **kwargs):
            captured["cmd"] = cmd
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"0" * 5000)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            PostManifestHandler.seen_body = b""
            PostManifestHandler.seen_referer = ""
            PostManifestHandler.seen_x_requested_with = ""
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(PostManifestHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                manifest_url = f"http://127.0.0.1:{server.server_port}/api/play"
                candidate = ResourceCandidate(
                    url=manifest_url,
                    source="webRequest",
                    kind="hls",
                    mime="application/vnd.apple.mpegurl",
                    method="POST",
                    request_headers={
                        "Referer": "https://course.example.com/lesson",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    request_body={"content": "objectid=42&dtoken=abc"},
                )
                downloader = MediaDownloader(root / "task")
                with patch("app.downloader.ffmpeg_bin", return_value="ffmpeg"), patch("app.downloader.subprocess.run", side_effect=fake_run):
                    media = downloader._download_manifest(candidate, [], "https://course.example.com/lesson", "Post HLS")

                self.assertTrue(media.exists())
                self.assertEqual(PostManifestHandler.seen_body, b"objectid=42&dtoken=abc")
                self.assertEqual(PostManifestHandler.seen_referer, "https://course.example.com/lesson")
                self.assertEqual(PostManifestHandler.seen_x_requested_with, "XMLHttpRequest")
                self.assertIn("-i", captured["cmd"])
                ffmpeg_input = Path(captured["cmd"][captured["cmd"].index("-i") + 1])
                self.assertEqual(ffmpeg_input.suffix, ".m3u8")
                self.assertTrue(ffmpeg_input.is_file())
                manifest = ffmpeg_input.read_text(encoding="utf-8")
                self.assertIn(f'URI="http://127.0.0.1:{server.server_port}/api/key.bin"', manifest)
                self.assertIn(f"http://127.0.0.1:{server.server_port}/api/seg/000.ts", manifest)
            finally:
                server.shutdown()
                server.server_close()

    def test_direct_video_candidate_with_audio_url_uses_two_ffmpeg_inputs(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text, **kwargs):
            captured["cmd"] = cmd
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"0" * 5000)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = ResourceCandidate(
                url="https://cdn.example.com/course/video-only.mp4?token=v",
                source="direct-response",
                kind="video",
                mime="video/mp4",
                audio_url="https://cdn.example.com/course/audio-only.m4a?token=a",
                audio_mime="audio/mp4",
                request_headers={
                    "Referer": "https://course.example.com/player",
                    "User-Agent": "Chrome Test UA",
                },
            )
            downloader = MediaDownloader(root / "task")
            with patch("app.downloader.ffmpeg_bin", return_value="ffmpeg"), patch("app.downloader.subprocess.run", side_effect=fake_run):
                media = downloader._download_file(candidate, [], "https://course.example.com/lesson", "Split AV")

            self.assertTrue(media.exists())
            self.assertEqual(media.name, "Split_AV_direct_av.mp4")
            self.assertEqual(captured["cmd"].count("-i"), 2)
            input_indexes = [index + 1 for index, value in enumerate(captured["cmd"]) if value == "-i"]
            self.assertEqual(captured["cmd"][input_indexes[0]], candidate.url)
            self.assertEqual(captured["cmd"][input_indexes[1]], candidate.audio_url)
            self.assertIn("-map", captured["cmd"])
            self.assertIn("0:v:0", captured["cmd"])
            self.assertIn("1:a:0", captured["cmd"])
            downloader._record_attempt("direct-av-merge", "success", "合并完成", candidate, output_path=media)
            self.assertEqual(downloader.attempts[0].companion_audio_url, candidate.audio_url)
            self.assertEqual(downloader.attempts[0].companion_audio_mime, "audio/mp4")

    def test_preflight_video_with_audio_url_requires_companion_audio_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            SplitAVPreflightHandler.audio_forbidden = False
            SplitAVPreflightHandler.seen_audio_range = ""
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SplitAVPreflightHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                video_url = f"http://127.0.0.1:{server.server_port}/video-only.mp4"
                audio_url = f"http://127.0.0.1:{server.server_port}/audio-only.m4a"
                result = preflight_media_resource(
                    ResourceCandidate(
                        url=video_url,
                        source="direct-response",
                        kind="video",
                        mime="video/mp4",
                        audio_url=audio_url,
                        audio_mime="audio/mp4",
                        request_headers={"Referer": SplitAVPreflightHandler.required_referer},
                    ),
                    [BrowserCookie(name="AUTH", value="ok", domain="127.0.0.1")],
                    "https://course.example.com/lesson",
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.strategy, "direct-file-probe")
                self.assertIn("伴随音频流预检通过", " ".join(result.warnings))
                self.assertEqual(SplitAVPreflightHandler.seen_audio_range, "bytes=0-4095")
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_video_with_audio_url_fails_when_companion_audio_is_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            SplitAVPreflightHandler.audio_forbidden = True
            SplitAVPreflightHandler.seen_audio_range = ""
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SplitAVPreflightHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                video_url = f"http://127.0.0.1:{server.server_port}/video-only.mp4"
                audio_url = f"http://127.0.0.1:{server.server_port}/audio-only.m4a"
                result = preflight_media_resource(
                    ResourceCandidate(
                        url=video_url,
                        source="direct-response",
                        kind="video",
                        mime="video/mp4",
                        audio_url=audio_url,
                        audio_mime="audio/mp4",
                        request_headers={"Referer": SplitAVPreflightHandler.required_referer},
                    ),
                    [BrowserCookie(name="AUTH", value="ok", domain="127.0.0.1")],
                    "https://course.example.com/lesson",
                )
                self.assertTrue(result.ok)
                self.assertFalse(result.downloadable)
                self.assertEqual(result.strategy, "companion-audio-probe")
                self.assertEqual(result.code, "auth_required")
                self.assertIn("伴随音频流预检返回 HTTP 403", result.message)
            finally:
                SplitAVPreflightHandler.audio_forbidden = False
                server.shutdown()
                server.server_close()

    def test_manifest_download_prefers_existing_resolved_url_for_probe(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text, **kwargs):
            captured["cmd"] = cmd
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"0" * 5000)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ResolvedManifestOnlyHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                gate_url = f"http://127.0.0.1:{server.server_port}/expired-gate"
                final_url = f"http://127.0.0.1:{server.server_port}/real/master.m3u8"
                candidate = ResourceCandidate(
                    url=gate_url,
                    resolved_url=final_url,
                    source="webRequest",
                    kind="hls",
                    mime="application/vnd.apple.mpegurl",
                )
                downloader = MediaDownloader(root / "task")
                with patch("app.downloader.ffmpeg_bin", return_value="ffmpeg"), patch("app.downloader.subprocess.run", side_effect=fake_run):
                    media = downloader._download_manifest(candidate, [], "https://course.example.com/lesson", "Resolved HLS")

                self.assertTrue(media.exists())
                self.assertEqual(candidate.resolved_url, final_url)
                self.assertEqual(candidate.status_code, 200)
                self.assertIn("-i", captured["cmd"])
                self.assertEqual(captured["cmd"][captured["cmd"].index("-i") + 1], final_url)
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

    def test_direct_candidate_rejects_login_page_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(LoginPageAsMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/video.mp4"
                downloader = MediaDownloader(root / "task")
                with self.assertRaises(DownloadError) as ctx:
                    downloader.download(
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
                        title="Login page",
                    )
                self.assertEqual(ctx.exception.code, "auth_required")
                self.assertEqual(downloader.attempts[0].strategy, "direct-file")
                self.assertEqual(downloader.attempts[0].status, "failed")
                self.assertEqual(downloader.attempts[0].code, "auth_required")
            finally:
                server.shutdown()
                server.server_close()

    def test_direct_candidate_rejects_octet_stream_login_page_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(OctetStreamLoginPageAsMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/video.mp4"
                candidate = ResourceCandidate(
                    url=media_url,
                    source="webRequest",
                    kind="video",
                    mime="application/octet-stream",
                    score=100,
                )
                preflight = preflight_media_resource(candidate, [], f"http://127.0.0.1:{server.server_port}/lesson.html")
                self.assertFalse(preflight.downloadable)
                self.assertEqual(preflight.code, "auth_required")

                downloader = MediaDownloader(root / "task")
                with self.assertRaises(DownloadError) as ctx:
                    downloader.download(
                        page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                        resources=[candidate],
                        cookies=[],
                        title="Octet login page",
                    )
                self.assertEqual(ctx.exception.code, "auth_required")
                self.assertEqual(downloader.attempts[0].strategy, "direct-file")
                self.assertEqual(downloader.attempts[0].code, "auth_required")
            finally:
                server.shutdown()
                server.server_close()

    def test_manifest_candidate_rejects_login_page_body_before_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(LoginPageAsMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                manifest_url = f"http://127.0.0.1:{server.server_port}/lesson.m3u8"
                downloader = MediaDownloader(root / "task")
                with patch("app.downloader.subprocess.run") as ffmpeg_run:
                    with patch.object(downloader, "_download_with_ytdlp", side_effect=DownloadError("no_media_found", "no fallback")):
                        with self.assertRaises(DownloadError) as ctx:
                            downloader.download(
                                page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                                resources=[
                                    ResourceCandidate(
                                        url=manifest_url,
                                        source="webRequest",
                                        kind="hls",
                                        mime="application/vnd.apple.mpegurl",
                                        score=100,
                                    )
                                ],
                                cookies=[],
                                title="Login manifest",
                            )
                self.assertEqual(ctx.exception.code, "auth_required")
                ffmpeg_run.assert_not_called()
                self.assertEqual(downloader.attempts[0].strategy, "manifest-ffmpeg")
                self.assertEqual(downloader.attempts[0].status, "failed")
                self.assertEqual(downloader.attempts[0].code, "auth_required")
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

    def test_page_scan_uses_media_url_embedded_in_page_url_when_page_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "query-hidden.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"video" * 2048)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                page_url = f"http://127.0.0.1:{server.server_port}/missing?objectid={quote(quote(media_url))}"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=page_url,
                        resources=[],
                        cookies=[],
                        title="Page URL query",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "page-scan-url")
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["page-scan", "direct-file"])
                self.assertEqual(downloader.attempts[0].status, "failed")
                self.assertEqual(downloader.attempts[1].status, "success")
            finally:
                server.shutdown()
                server.server_close()

    def test_page_scan_reuses_browser_headers_from_fallback_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / PageScanHeaderGateHandler.media_name
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"video" * 2048)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(PageScanHeaderGateHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                player_url = f"http://127.0.0.1:{server.server_port}/player.json"
                media_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=f"http://127.0.0.1:{server.server_port}/lesson",
                        resources=[
                            ResourceCandidate(
                                url=player_url,
                                source="dom",
                                kind="unknown",
                                label="iframe player api",
                                request_headers={
                                    "User-Agent": PageScanHeaderGateHandler.required_user_agent,
                                    "X-Requested-With": PageScanHeaderGateHandler.required_x_requested_with,
                                },
                            )
                        ],
                        cookies=[],
                        title="Header page scan",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, media_url)
                self.assertEqual(selected.source, "direct-response")
                self.assertEqual(selected.request_headers["User-Agent"], PageScanHeaderGateHandler.required_user_agent)
                self.assertEqual(selected.request_headers["X-Requested-With"], PageScanHeaderGateHandler.required_x_requested_with)
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["direct-response-scan", "direct-file"])
                self.assertEqual(downloader.attempts[0].status, "success")
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

    def test_direct_video_candidate_switches_to_manifest_when_response_is_hls(self) -> None:
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
                hls_url = f"http://127.0.0.1:{server.server_port}/stream?lesson=1"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=f"http://127.0.0.1:{server.server_port}/lesson.html",
                        resources=[
                            ResourceCandidate(
                                url=hls_url,
                                source="webRequest",
                                kind="video",
                                mime="video/mp4",
                                score=100,
                                label="extensionless playback endpoint",
                            )
                        ],
                        cookies=[],
                        title="Direct endpoint manifest",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, hls_url)
                self.assertEqual(selected.kind, "hls")
                self.assertEqual(selected.mime, "application/vnd.apple.mpegurl")
                self.assertEqual(selected.status_code, 200)
                self.assertEqual(selected.content_length, playlist.stat().st_size)
                self.assertEqual(selected.headers.get("content-type"), "application/vnd.apple.mpegurl")
                self.assertEqual(downloader.attempts[0].strategy, "manifest-ffmpeg")
                self.assertEqual(downloader.attempts[0].kind, "hls")
                self.assertEqual(downloader.attempts[0].status, "success")
                self.assertEqual(downloader.attempts[0].status_code, 200)
                self.assertEqual(downloader.attempts[0].content_length, playlist.stat().st_size)
                self.assertEqual(downloader.attempts[0].mime, "application/vnd.apple.mpegurl")
            finally:
                server.shutdown()
                server.server_close()

    def test_page_scan_downloads_extensionless_hls_from_manifest_body(self) -> None:
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
                hls_url = f"http://127.0.0.1:{server.server_port}/stream?lesson=1&raw=1"
                downloader = MediaDownloader(root / "task")
                with patch.object(downloader, "_download_with_ytdlp") as ytdlp:
                    media_path, selected = downloader.download(
                        page_url=hls_url,
                        resources=[],
                        cookies=[],
                        title="Manifest body",
                    )
                ytdlp.assert_not_called()
                self.assertTrue(media_path.exists())
                self.assertIsNotNone(selected)
                self.assertEqual(selected.url, hls_url)
                self.assertEqual(selected.kind, "hls")
                self.assertEqual(selected.mime, "application/vnd.apple.mpegurl")
                self.assertEqual(selected.label, "response manifest")
                self.assertEqual(selected.status_code, 200)
                self.assertEqual(selected.content_length, playlist.stat().st_size)
                self.assertEqual(selected.headers.get("content-type"), "application/octet-stream")
                self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["page-scan", "manifest-ffmpeg"])
                self.assertEqual(downloader.attempts[1].status, "success")
                self.assertEqual(downloader.attempts[1].status_code, 200)
                self.assertEqual(downloader.attempts[1].content_length, playlist.stat().st_size)
                self.assertEqual(downloader.attempts[1].mime, "application/vnd.apple.mpegurl")
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
                            "Authorization": HeaderGateHandler.required_authorization,
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

    def test_preflight_retries_with_open_ended_range(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "range-preflight.mp4"
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
                result = preflight_media_resource(
                    ResourceCandidate(
                        url=media_url,
                        source="webRequest",
                        kind="video",
                        mime="video/mp4",
                        score=100,
                    ),
                    [],
                    f"http://127.0.0.1:{server.server_port}/lesson.html",
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.strategy, "direct-file-probe")
                self.assertEqual(result.status_code, 200)
                self.assertIn("Range", result.request_header_names)
                self.assertIn("open-ended Range", " ".join(result.warnings))
                self.assertGreater(result.bytes_checked, 0)
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_reports_extensionless_video_response_manifest(self) -> None:
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
                hls_url = f"http://127.0.0.1:{server.server_port}/stream?lesson=1"
                result = preflight_media_resource(
                    ResourceCandidate(
                        url=hls_url,
                        source="webRequest",
                        kind="video",
                        mime="video/mp4",
                        score=100,
                    ),
                    [],
                    f"http://127.0.0.1:{server.server_port}/lesson.html",
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.kind, "hls")
                self.assertEqual(result.strategy, "manifest-probe")
                self.assertIn("正式任务会改用 ffmpeg 合并", " ".join(result.warnings))
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_reports_json_play_endpoint_embedded_media_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / DirectJsonMediaHandler.media_name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"preflight" * 512)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(DirectJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                play_url = f"http://127.0.0.1:{server.server_port}/api/play?id=42"
                media_url = f"http://127.0.0.1:{server.server_port}/{DirectJsonMediaHandler.media_name}"
                result = preflight_media_resource(
                    ResourceCandidate(
                        url=play_url,
                        source="webRequest",
                        kind="video",
                        mime="video/mp4",
                        score=100,
                        request_headers={
                            "User-Agent": DirectJsonMediaHandler.required_user_agent,
                            "X-Requested-With": DirectJsonMediaHandler.required_x_requested_with,
                        },
                    ),
                    [],
                    page_url,
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.strategy, "direct-response-probe")
                self.assertEqual(result.kind, "video")
                self.assertEqual(result.resolved_url, media_url)
                self.assertIn("Referer", result.request_header_names)
                self.assertIn("X-Requested-With", result.request_header_names)
                self.assertIn("embedded media URL", " ".join(result.warnings))
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_tries_next_embedded_media_url_when_first_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / MultiSourceJsonMediaHandler.media_name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"backup" * 512)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(MultiSourceJsonMediaHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                page_url = f"http://127.0.0.1:{server.server_port}/lesson.html"
                play_url = f"http://127.0.0.1:{server.server_port}/api/play?id=42"
                backup_url = f"http://127.0.0.1:{server.server_port}/{MultiSourceJsonMediaHandler.media_name}"
                result = preflight_media_resource(
                    ResourceCandidate(
                        url=play_url,
                        source="webRequest",
                        kind="video",
                        mime="video/mp4",
                        score=100,
                        request_headers={
                            "User-Agent": MultiSourceJsonMediaHandler.required_user_agent,
                            "X-Requested-With": MultiSourceJsonMediaHandler.required_x_requested_with,
                        },
                    ),
                    [],
                    page_url,
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.strategy, "direct-response-probe")
                self.assertEqual(result.kind, "video")
                self.assertEqual(result.resolved_url, backup_url)
                self.assertIn("embedded media URLs", " ".join(result.warnings))
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_prefers_existing_resolved_manifest_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ResolvedManifestOnlyHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                gate_url = f"http://127.0.0.1:{server.server_port}/expired-gate"
                final_url = f"http://127.0.0.1:{server.server_port}/real/master.m3u8"
                result = preflight_media_resource(
                    ResourceCandidate(
                        url=gate_url,
                        resolved_url=final_url,
                        source="webRequest",
                        kind="hls",
                        mime="application/vnd.apple.mpegurl",
                        score=100,
                    ),
                    [],
                    "https://course.example.com/lesson",
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.kind, "hls")
                self.assertEqual(result.strategy, "manifest-probe")
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.resolved_url, final_url)
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_plain_fragment_tries_sibling_manifest_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ResolvedManifestOnlyHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                fragment_url = f"http://127.0.0.1:{server.server_port}/real/seg-0001.ts"
                manifest_url = f"http://127.0.0.1:{server.server_port}/real/master.m3u8"
                result = preflight_media_resource(
                    ResourceCandidate(
                        url=fragment_url,
                        source="webRequest",
                        kind="fragment",
                        playback_match="fragment-near-playhead",
                        score=40,
                    ),
                    [],
                    "https://course.example.com/lesson",
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.kind, "hls")
                self.assertEqual(result.strategy, "manifest-probe")
                self.assertEqual(result.url, fragment_url)
                self.assertEqual(result.resolved_url, manifest_url)
                self.assertIn("sibling manifest guess", " ".join(result.warnings))
            finally:
                server.shutdown()
                server.server_close()

    def test_preflight_prefers_existing_resolved_video_url(self) -> None:
        ffmpeg = ffmpeg_bin()
        assert ffmpeg is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / ResolvedMediaOnlyHandler.media_name
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
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(ResolvedMediaOnlyHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                gate_url = f"http://127.0.0.1:{server.server_port}/expired-gate"
                final_url = f"http://127.0.0.1:{server.server_port}/{video.name}"
                result = preflight_media_resource(
                    ResourceCandidate(
                        url=gate_url,
                        resolved_url=final_url,
                        source="webRequest",
                        kind="video",
                        mime="video/mp4",
                        score=100,
                    ),
                    [],
                    "https://course.example.com/lesson",
                )
                self.assertTrue(result.ok)
                self.assertTrue(result.downloadable)
                self.assertEqual(result.kind, "video")
                self.assertEqual(result.strategy, "direct-file-probe")
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.resolved_url, final_url)
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
        self.assertEqual(result.code, "no_media_found")


if __name__ == "__main__":
    unittest.main()
