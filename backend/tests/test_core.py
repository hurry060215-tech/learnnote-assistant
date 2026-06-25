from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.downloader import DownloadError, MediaDownloader, classify_resource, cookie_header_for_url, score_resource
from app.models import BrowserCookie, ResourceCandidate, TranscriptResult, TranscriptSegment
from app.processor import read_note, read_transcript
from app.summarizer import local_markdown_note
from app.storage import create_task


class ResourceDetectionTests(unittest.TestCase):
    def test_classifies_common_media_urls(self) -> None:
        self.assertEqual(classify_resource("https://cdn.example.com/video.mp4"), "video")
        self.assertEqual(classify_resource("https://cdn.example.com/index.m3u8"), "hls")
        self.assertEqual(classify_resource("https://cdn.example.com/manifest.mpd"), "dash")
        self.assertEqual(classify_resource("blob:https://example.com/abc"), "blob")
        self.assertEqual(classify_resource("https://cdn.example.com/chunk.m4s"), "fragment")

    def test_scores_manifest_above_plain_video(self) -> None:
        self.assertGreater(
            score_resource("https://cdn.example.com/index.m3u8", "application/vnd.apple.mpegurl", "webRequest"),
            score_resource("https://cdn.example.com/video.mp4", "video/mp4", "dom"),
        )

    def test_cookie_header_matches_parent_domains(self) -> None:
        cookies = [
            BrowserCookie(name="SESSDATA", value="abc", domain=".chaoxing.com"),
            BrowserCookie(name="other", value="nope", domain=".example.com"),
        ]
        header = cookie_header_for_url(cookies, "https://mooc1.chaoxing.com/video")
        self.assertEqual(header, "SESSDATA=abc")


class DownloaderBoundaryTests(unittest.TestCase):
    def test_blob_only_resources_fail_as_encrypted_or_unrecoverable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            with self.assertRaises(DownloadError) as ctx:
                downloader.download(
                    page_url="https://course.example/video",
                    resources=[ResourceCandidate(url="blob:https://course.example/abc", source="dom", kind="blob")],
                    cookies=[],
                    title="Blob only",
                )
            self.assertEqual(ctx.exception.code, "drm_or_encrypted")


class SummaryFallbackTests(unittest.TestCase):
    def test_local_note_contains_timeline_and_frame_index(self) -> None:
        transcript = TranscriptResult(
            source="unit",
            full_text="函数用于封装逻辑。",
            segments=[TranscriptSegment(start=5, end=8, text="函数用于封装逻辑。")],
        )
        note = local_markdown_note("Python lesson", transcript, [], "https://example.com")
        self.assertIn("# Python lesson", note)
        self.assertIn("00:00:05", note)
        self.assertIn("复习问题", note)


class EmptyArtifactTests(unittest.TestCase):
    def test_empty_artifact_paths_return_empty_results(self) -> None:
        task = create_task(source_type="page_text", title="empty")
        self.assertEqual(read_note(task.id), "")
        self.assertEqual(read_transcript(task.id)["segments"], [])


if __name__ == "__main__":
    unittest.main()
