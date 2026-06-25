from __future__ import annotations

import tempfile
import unittest
import shutil
import sys
import types
from pathlib import Path
from unittest.mock import patch

from app.downloader import (
    DownloadError,
    MediaDownloader,
    classify_resource,
    cookie_header_for_url,
    download_headers_for_candidate,
    infer_manifest_url_from_fragment,
    score_resource,
    ytdlp_headers_from_browser_context,
)
from app.models import BrowserCookie, CurrentPageTaskRequest, FrameGrid, ResourceCandidate, TaskOptions, TranscriptResult, TranscriptSegment
from app.processor import read_note, read_transcript, redacted_request_dump, redacted_resource
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

    def test_infers_manifest_url_from_nested_fragment(self) -> None:
        fragment = "https://cdn.example.com/live/master.m3u8/segment-001.ts?token=abc"
        self.assertEqual(classify_resource(fragment), "fragment")
        self.assertEqual(infer_manifest_url_from_fragment(fragment), "https://cdn.example.com/live/master.m3u8?token=abc")
        dash_fragment = "https://cdn.example.com/dash/manifest.mpd/chunk-1.m4s"
        self.assertEqual(infer_manifest_url_from_fragment(dash_fragment), "https://cdn.example.com/dash/manifest.mpd")

    def test_cookie_header_matches_parent_domains(self) -> None:
        cookies = [
            BrowserCookie(name="SESSDATA", value="abc", domain=".chaoxing.com"),
            BrowserCookie(name="other", value="nope", domain=".example.com"),
        ]
        header = cookie_header_for_url(cookies, "https://mooc1.chaoxing.com/video")
        self.assertEqual(header, "SESSDATA=abc")

    def test_download_headers_reuse_browser_context_without_sensitive_values(self) -> None:
        candidate = ResourceCandidate(
            url="https://media.cdn.example.com/video.mp4",
            source="webRequest",
            kind="video",
            request_headers={
                "referer": "https://course.example.com/lesson/1",
                "origin": "https://course.example.com",
                "user-agent": "Chrome Test UA",
                "accept-language": "zh-CN,zh;q=0.9",
                "range": "bytes=0-",
                "cookie": "bad=1",
                "authorization": "Bearer bad",
            },
        )
        cookies = [BrowserCookie(name="SESSION", value="ok", domain=".cdn.example.com")]

        headers = download_headers_for_candidate(candidate, cookies, "https://fallback.example.com/page")

        self.assertEqual(headers["Referer"], "https://course.example.com/lesson/1")
        self.assertEqual(headers["Origin"], "https://course.example.com")
        self.assertEqual(headers["User-Agent"], "Chrome Test UA")
        self.assertEqual(headers["Accept-Language"], "zh-CN,zh;q=0.9")
        self.assertEqual(headers["Cookie"], "SESSION=ok")
        self.assertNotIn("Range", headers)
        self.assertNotIn("Authorization", headers)

    def test_ytdlp_headers_prefer_browser_playback_context(self) -> None:
        resources = [
            ResourceCandidate(
                url="https://cdn.example.com/background.mp4",
                source="webRequest",
                kind="video",
                score=90,
                request_headers={
                    "User-Agent": "Background UA",
                    "Referer": "https://course.example.com/background",
                    "Cookie": "bad=1",
                    "Authorization": "Bearer bad",
                },
            ),
            ResourceCandidate(
                url="https://cdn.example.com/lesson.m3u8",
                source="webRequest",
                kind="hls",
                score=88,
                playback_match="same-frame",
                is_main_video=True,
                request_headers={
                    "User-Agent": "Chrome Playback UA",
                    "Referer": "https://course.example.com/lesson/1",
                    "Origin": "https://course.example.com",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Accept": "*/*",
                    "Cookie": "bad=1",
                    "Authorization": "Bearer bad",
                },
            ),
        ]

        headers = ytdlp_headers_from_browser_context("https://course.example.com/lesson/1", resources)

        self.assertEqual(headers["User-Agent"], "Chrome Playback UA")
        self.assertEqual(headers["Referer"], "https://course.example.com/lesson/1")
        self.assertEqual(headers["Origin"], "https://course.example.com")
        self.assertEqual(headers["Accept-Language"], "zh-CN,zh;q=0.9")
        self.assertEqual(headers["Accept"], "*/*")
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("Authorization", headers)

    def test_persisted_request_metadata_redacts_cookie_and_header_values(self) -> None:
        resource = ResourceCandidate(
            url="https://media.example.com/video.mp4",
            source="webRequest",
            kind="video",
            headers={"content-type": "video/mp4", "set-cookie": "bad=1"},
            request_headers={"Referer": "https://course.example.com/lesson?token=secret", "User-Agent": "Chrome Test UA"},
        )
        request = CurrentPageTaskRequest(
            page_url="https://course.example.com/lesson",
            title="Header redaction",
            resources=[resource],
            cookies=[BrowserCookie(name="AUTH", value="secret", domain=".example.com")],
        )

        data = redacted_request_dump(request)
        self.assertEqual(data["cookies"][0]["value"], "<redacted>")
        self.assertEqual(data["resources"][0]["request_headers"]["Referer"], "<redacted>")
        self.assertEqual(data["resources"][0]["request_headers"]["User-Agent"], "<redacted>")
        self.assertEqual(data["resources"][0]["headers"], {"content-type": "video/mp4"})

        selected = redacted_resource(resource)
        self.assertEqual(selected.request_headers["Referer"], "<redacted>")
        self.assertEqual(selected.headers, {"content-type": "video/mp4"})


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

    def test_blob_source_mapping_candidate_is_prioritized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://cdn.example.com/background.mp4",
                    source="webRequest",
                    kind="video",
                    mime="video/mp4",
                    score=95,
                ),
                ResourceCandidate(
                    url="https://cdn.example.com/lesson.mp4",
                    source="pageHookBlobSource",
                    kind="video",
                    mime="video/mp4",
                    playback_match="blob-source",
                    blob_url="blob:https://course.example/active-video",
                ),
            ]
            candidates = downloader._candidate_resources(resources)
            self.assertEqual(candidates[0].url, "https://cdn.example.com/lesson.mp4")
            self.assertEqual(candidates[0].playback_match, "blob-source")
            self.assertEqual(candidates[0].blob_url, "blob:https://course.example/active-video")

    def test_manifest_candidate_is_inferred_from_fragment_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://cdn.example.com/course/master.m3u8/seg-001.ts?token=abc",
                    source="webRequest",
                    kind="fragment",
                    score=30,
                    playback_match="blob-same-frame",
                )
            ]
            candidates = downloader._candidate_resources(resources)
            self.assertEqual(candidates[0].url, "https://cdn.example.com/course/master.m3u8?token=abc")
            self.assertEqual(candidates[0].kind, "hls")
            self.assertEqual(candidates[0].source, "inferred-manifest")
            self.assertEqual(candidates[0].playback_match, "blob-same-frame")

    def test_ytdlp_fallback_receives_browser_http_headers(self) -> None:
        captured: dict = {}

        class FakeYoutubeDL:
            def __init__(self, options):
                captured["options"] = options

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def extract_info(self, page_url, download):
                captured["page_url"] = page_url
                captured["download"] = download
                output = Path(captured["options"]["outtmpl"].replace("%(ext)s", "mp4"))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"0" * 5000)
                return {"title": "fake"}

        fake_module = types.ModuleType("yt_dlp")
        fake_module.YoutubeDL = FakeYoutubeDL

        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"yt_dlp": fake_module}):
            downloader = MediaDownloader(Path(tmp))
            media = downloader._download_with_ytdlp(
                "https://course.example.com/lesson/1",
                None,
                "yt-dlp headers",
                [
                    ResourceCandidate(
                        url="https://cdn.example.com/lesson.m3u8",
                        source="webRequest",
                        kind="hls",
                        playback_match="same-frame",
                        is_main_video=True,
                        request_headers={
                            "User-Agent": "Chrome Playback UA",
                            "Referer": "https://course.example.com/lesson/1",
                            "Origin": "https://course.example.com",
                        },
                    )
                ],
            )

            self.assertTrue(media.exists())
            self.assertEqual(captured["page_url"], "https://course.example.com/lesson/1")
            self.assertTrue(captured["download"])
            self.assertEqual(captured["options"]["http_headers"]["User-Agent"], "Chrome Playback UA")
            self.assertEqual(captured["options"]["http_headers"]["Referer"], "https://course.example.com/lesson/1")
            self.assertEqual(captured["options"]["http_headers"]["Origin"], "https://course.example.com")


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

    def test_llm_summary_batches_all_frame_grids_before_merge(self) -> None:
        from app.summarizer import summarize_with_llm

        class Message:
            def __init__(self, content: str):
                self.content = content

        class Choice:
            def __init__(self, content: str):
                self.message = Message(content)

        class Response:
            def __init__(self, content: str):
                self.choices = [Choice(content)]

        class FakeCompletions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                content = kwargs["messages"][0]["content"]
                if isinstance(content, list):
                    images = [item for item in content if item.get("type") == "image_url"]
                    return Response(f"partial with {len(images)} images")
                return Response("merged note")

        completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = types.SimpleNamespace(completions=completions)

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grids = []
            for index in range(9):
                image = root / f"grid_{index}.jpg"
                image.write_bytes(b"fake-image")
                grids.append(FrameGrid(path=str(image), url=f"http://127.0.0.1/grid_{index}.jpg", start=index * 180, end=(index + 1) * 180, frame_count=9))
            transcript = TranscriptResult(
                full_text="all transcript",
                segments=[TranscriptSegment(start=index * 180, end=index * 180 + 30, text=f"segment {index}") for index in range(9)],
            )
            with patch.dict(sys.modules, {"openai": fake_openai}):
                note = summarize_with_llm("Long lesson", transcript, grids, TaskOptions(llm_api_key="test-key"), "https://course.example")

        self.assertEqual(note, "merged note")
        self.assertEqual(len(completions.calls), 4)
        vision_image_counts = [
            len([item for item in call["messages"][0]["content"] if item.get("type") == "image_url"])
            for call in completions.calls[:3]
        ]
        self.assertEqual(vision_image_counts, [4, 4, 1])
        self.assertIn("partial with 4 images", completions.calls[3]["messages"][0]["content"])
        self.assertIn("partial with 1 images", completions.calls[3]["messages"][0]["content"])


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
