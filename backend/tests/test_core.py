from __future__ import annotations

import tempfile
import unittest
import shutil
from pathlib import Path

from app.downloader import DownloadError, MediaDownloader, classify_resource, cookie_header_for_url, score_resource
from app.models import BrowserCookie, FrameGrid, ResourceCandidate, TranscriptResult, TranscriptSegment
from app.processor import read_note, read_transcript
from app.summarizer import local_markdown_note
from app.storage import create_task, task_dir
from app.transcriber import transcript_from_subtitle


class ResourceDetectionTests(unittest.TestCase):
    def test_classifies_common_media_urls(self) -> None:
        self.assertEqual(classify_resource("https://cdn.example.com/video.mp4"), "video")
        self.assertEqual(classify_resource("https://cdn.example.com/index.m3u8"), "hls")
        self.assertEqual(classify_resource("https://cdn.example.com/manifest.mpd"), "dash")
        self.assertEqual(classify_resource("blob:https://example.com/abc"), "blob")
        self.assertEqual(classify_resource("https://cdn.example.com/chunk.m4s"), "fragment")
        self.assertEqual(classify_resource("https://cdn.example.com/captions.vtt"), "subtitle")

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
            self.assertEqual(downloader.attempts[0].strategy, "blob-unrecoverable")
            self.assertEqual(downloader.attempts[0].status, "skipped")

    def test_blob_with_fragments_keeps_fragment_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            with self.assertRaises(DownloadError) as ctx:
                downloader.download(
                    page_url="https://course.example/video",
                    resources=[
                        ResourceCandidate(url="blob:https://course.example/abc", source="activeVideo", kind="blob"),
                        ResourceCandidate(url="https://cdn.example.com/chunk-001.m4s", source="webRequest", kind="fragment"),
                    ],
                    cookies=[],
                    title="Blob with fragments",
                )
            self.assertEqual(ctx.exception.code, "drm_or_encrypted")
            self.assertEqual([attempt.strategy for attempt in downloader.attempts], ["blob-unrecoverable", "skip-fragment"])

    def test_playback_matched_candidate_is_prioritized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(url="https://cdn.example.com/background.mp4", source="webRequest", kind="video", mime="video/mp4", score=85),
                ResourceCandidate(
                    url="https://cdn.example.com/lesson.m3u8",
                    source="webRequest",
                    kind="hls",
                    mime="application/vnd.apple.mpegurl",
                    score=90,
                    playback_match="same-frame",
                ),
            ]
            candidates = downloader._candidate_resources(resources)
            self.assertEqual(candidates[0].url, "https://cdn.example.com/lesson.m3u8")
            self.assertEqual(candidates[0].playback_match, "same-frame")


class SummaryFallbackTests(unittest.TestCase):
    def test_local_note_contains_timeline_and_frame_index(self) -> None:
        transcript = TranscriptResult(
            source="unit",
            full_text="函数用于封装逻辑。",
            segments=[TranscriptSegment(start=5, end=8, text="函数用于封装逻辑。")],
        )
        grids = [FrameGrid(path="", url="http://127.0.0.1/grid.jpg", start=0, end=20, frame_count=2)]
        note = local_markdown_note("Python lesson", transcript, grids, "https://example.com")
        self.assertIn("# Python lesson", note)
        self.assertIn("00:00:05", note)
        self.assertIn("分段图文摘要", note)
        self.assertIn("http://127.0.0.1/grid.jpg", note)
        self.assertIn("复习问题", note)


class SubtitleParsingTests(unittest.TestCase):
    def test_vtt_subtitle_is_converted_to_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lesson.vtt"
            path.write_text(
                "\n".join([
                    "WEBVTT",
                    "",
                    "00:00:01.000 --> 00:00:03.000",
                    "第一段字幕",
                    "",
                    "2",
                    "00:00:04,000 --> 00:00:06,000",
                    "<b>第二段字幕</b>",
                    "",
                ]),
                encoding="utf-8",
            )
            transcript = transcript_from_subtitle(path)
            self.assertEqual(transcript.source, "page-subtitle")
            self.assertEqual(len(transcript.segments), 2)
            self.assertEqual(transcript.segments[0].start, 1.0)
            self.assertEqual(transcript.segments[1].text, "第二段字幕")


class EmptyArtifactTests(unittest.TestCase):
    def test_empty_artifact_paths_return_empty_results(self) -> None:
        task = create_task(source_type="page_text", title="empty")
        try:
            self.assertEqual(read_note(task.id), "")
            self.assertEqual(read_transcript(task.id)["segments"], [])
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
