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
from app.models import ResourceCandidate
from app.runtime import ffmpeg_bin


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


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
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
