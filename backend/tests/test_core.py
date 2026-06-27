from __future__ import annotations

import tempfile
import unittest
import shutil
import sys
import types
import json
import os
from base64 import b64encode
from pathlib import Path
from unittest.mock import patch

from app.config import DATA_DIR, TEMP_DIR
from app.downloader import (
    DownloadError,
    MediaDownloader,
    choose_ytdlp_subtitle_language,
    classify_resource,
    cookie_header_for_url,
    download_headers_for_candidate,
    effective_resource_kind,
    extract_media_resources_from_text,
    fallback_page_urls,
    infer_manifest_url_from_fragment,
    score_resource,
    ytdlp_headers_from_browser_context,
)
from app.main import render_diagnostics_markdown
from app.models import ActiveVideoInfo, BrowserCookie, CurrentPageTaskRequest, DownloadAttempt, DrmSignal, FrameGrid, ResourceCandidate, TaskOptions, TranscriptResult, TranscriptSegment, VisualWindow
from app.processor import build_summary_diagnostics, process_current_page_task, process_local_video_task, read_note, read_transcript, redacted_request_dump, redacted_resource
from app.summarizer import MAX_VISION_GRIDS, build_visual_windows, local_markdown_note, summarize_with_diagnostics
from app.storage import create_task, get_task, task_dir
from app.transcriber import transcript_from_subtitle

TEST_RUN_DIR = DATA_DIR / "test-runs"
TEST_RUN_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_RUN_DIR)


class ResourceDetectionTests(unittest.TestCase):
    def test_python_tempdir_uses_project_test_run_dir(self) -> None:
        self.assertEqual(Path(tempfile.gettempdir()).resolve(), TEST_RUN_DIR.resolve())

    def test_backend_process_temp_env_uses_project_data_dir(self) -> None:
        self.assertEqual(Path(os.environ["TMP"]).resolve(), TEMP_DIR.resolve())
        self.assertEqual(Path(os.environ["TEMP"]).resolve(), TEMP_DIR.resolve())
        self.assertEqual(Path(os.environ["TMPDIR"]).resolve(), TEMP_DIR.resolve())
        self.assertTrue(TEMP_DIR.exists())

    def test_classifies_common_media_urls(self) -> None:
        self.assertEqual(classify_resource("https://cdn.example.com/video.mp4"), "video")
        self.assertEqual(classify_resource("https://cdn.example.com/live/lesson.flv?token=abc"), "video")
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

    def test_effective_kind_trusts_browser_media_candidate_when_url_is_extensionless(self) -> None:
        candidate = ResourceCandidate(
            url="https://cdn.example.com/playback?id=abc",
            source="webRequest",
            kind="video",
            mime="application/octet-stream",
        )
        self.assertEqual(classify_resource(candidate.url, candidate.mime), "unknown")
        self.assertEqual(effective_resource_kind(candidate), "video")

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
                "sec-fetch-dest": "video",
                "sec-fetch-mode": "no-cors",
                "sec-fetch-site": "same-site",
                "sec-ch-ua": '"Chromium";v="126"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "x-requested-with": "XMLHttpRequest",
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
        self.assertEqual(headers["Sec-Fetch-Dest"], "video")
        self.assertEqual(headers["Sec-Fetch-Mode"], "no-cors")
        self.assertEqual(headers["Sec-Fetch-Site"], "same-site")
        self.assertEqual(headers["Sec-CH-UA"], '"Chromium";v="126"')
        self.assertEqual(headers["Sec-CH-UA-Mobile"], "?0")
        self.assertEqual(headers["Sec-CH-UA-Platform"], '"Windows"')
        self.assertEqual(headers["X-Requested-With"], "XMLHttpRequest")
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
                    "Sec-Fetch-Dest": "video",
                    "Sec-Fetch-Mode": "no-cors",
                    "Sec-Fetch-Site": "same-site",
                    "Sec-CH-UA": '"Chromium";v="126"',
                    "Sec-CH-UA-Mobile": "?0",
                    "Sec-CH-UA-Platform": '"Windows"',
                    "X-Requested-With": "XMLHttpRequest",
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
        self.assertEqual(headers["Sec-Fetch-Dest"], "video")
        self.assertEqual(headers["Sec-Fetch-Mode"], "no-cors")
        self.assertEqual(headers["Sec-Fetch-Site"], "same-site")
        self.assertEqual(headers["Sec-CH-UA"], '"Chromium";v="126"')
        self.assertEqual(headers["Sec-CH-UA-Mobile"], "?0")
        self.assertEqual(headers["Sec-CH-UA-Platform"], '"Windows"')
        self.assertEqual(headers["X-Requested-With"], "XMLHttpRequest")
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("Authorization", headers)

    def test_fallback_page_urls_include_active_iframe_and_referer_context(self) -> None:
        urls = fallback_page_urls(
            "https://course.example.com/top",
            [
                ResourceCandidate(
                    url="https://media.example.com/video.mp4",
                    source="webRequest",
                    kind="video",
                    score=90,
                    frame_url="https://player.example.com/embed/1",
                    request_headers={"Referer": "https://player.example.com/embed/1?from=referer"},
                    initiator="https://player.example.com",
                    is_main_video=True,
                    playback_match="same-frame",
                ),
                ResourceCandidate(
                    url="https://course.example.com/iframe-player",
                    source="dom",
                    kind="unknown",
                    label="iframe",
                    score=50,
                ),
            ],
        )

        self.assertEqual(urls[0], "https://course.example.com/top")
        self.assertIn("https://player.example.com/embed/1", urls)
        self.assertIn("https://player.example.com/embed/1?from=referer", urls)
        self.assertIn("https://player.example.com", urls)
        self.assertIn("https://course.example.com/iframe-player", urls)

    def test_page_scan_finds_extensionless_json_media_urls(self) -> None:
        resources = extract_media_resources_from_text(
            """
            {
              "streams": {
                "hls": "/api/video/play?lesson=1&token=abc",
                "dashUrl": "/api/video/dash?lesson=1",
                "videoUrl": "/api/media/file?id=42",
                "mimeType": "video/mp4"
              }
            }
            """,
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_label = {resource.label: resource for resource in resources}

        self.assertEqual(by_label["json streams/hls"].kind, "hls")
        self.assertEqual(by_label["json streams/dashUrl"].kind, "dash")
        self.assertEqual(by_label["json streams/videoUrl"].kind, "video")
        self.assertEqual(by_label["json streams/hls"].url, "https://course.example.com/api/video/play?lesson=1&token=abc")
        self.assertEqual(by_label["json streams/hls"].mime, "application/vnd.apple.mpegurl")
        self.assertEqual(by_label["json streams/videoUrl"].mime, "video/mp4")

    def test_page_scan_finds_extensionless_media_fields_inside_script(self) -> None:
        resources = extract_media_resources_from_text(
            """
            <script>
              window.playInfo = {
                hls: "/stream?lesson=1&token=abc",
                dashUrl: "/dash/play?id=2",
                videoUrl: "/api/media/file?id=42"
              };
            </script>
            """,
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_label = {resource.label: resource for resource in resources}

        self.assertEqual(by_label["field hls"].kind, "hls")
        self.assertEqual(by_label["field dashUrl"].kind, "dash")
        self.assertEqual(by_label["field videoUrl"].kind, "video")
        self.assertEqual(by_label["field hls"].url, "https://course.example.com/stream?lesson=1&token=abc")
        self.assertEqual(by_label["field dashUrl"].mime, "application/dash+xml")

    def test_page_scan_decodes_wrapped_media_field_values(self) -> None:
        encoded = "https%3A%2F%2Fcdn.example.com%2Fsecure%2Flesson.m3u8%3Ftoken%3Dabc"
        packed = b64encode(b"https://cdn.example.com/video/lesson.mp4?sign=ok").decode("ascii")
        resources = extract_media_resources_from_text(
            json.dumps({
                "playInfo": {
                    "hls": encoded,
                    "videoUrl": packed,
                }
            }),
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_kind = {resource.kind: resource for resource in resources}

        self.assertEqual(by_kind["hls"].url, "https://cdn.example.com/secure/lesson.m3u8?token=abc")
        self.assertEqual(by_kind["video"].url, "https://cdn.example.com/video/lesson.mp4?sign=ok")

    def test_page_scan_extracts_flv_direct_urls(self) -> None:
        resources = extract_media_resources_from_text(
            "window.playUrl='https://cdn.example.com/live/lesson.flv?token=abc';",
            "https://course.example.com/player/index.html",
            "page-scan",
        )

        self.assertEqual(resources[0].kind, "video")
        self.assertEqual(resources[0].url, "https://cdn.example.com/live/lesson.flv?token=abc")

    def test_ytdlp_subtitle_language_prefers_human_chinese_then_auto(self) -> None:
        info = {
            "subtitles": {
                "en": [{"ext": "vtt"}],
                "zh-Hans": [{"ext": "vtt"}],
            },
            "automatic_captions": {
                "zh-CN": [{"ext": "vtt"}],
            },
        }
        self.assertEqual(choose_ytdlp_subtitle_language(info), ("zh-Hans", False))

        auto_only = {
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
                "zh-CN": [{"ext": "vtt"}],
            }
        }
        self.assertEqual(choose_ytdlp_subtitle_language(auto_only), ("zh-CN", True))

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

    def test_llm_api_key_is_not_persisted_in_task_or_request_snapshot(self) -> None:
        options = TaskOptions(
            llm_api_key="sk-secret",
            llm_base_url="https://models.example/v1",
            llm_model="vision-model",
        )
        task = create_task("page_text", "Secret options", "https://course.example.com", options)
        try:
            record = get_task(task.id)
            self.assertIsNone(record.options.llm_api_key)
            self.assertEqual(record.options.llm_base_url, "https://models.example/v1")
            self.assertEqual(record.options.llm_model, "vision-model")

            request = CurrentPageTaskRequest(
                page_url="https://course.example.com",
                title="Secret options",
                options=options,
            )
            dumped = redacted_request_dump(request)
            self.assertEqual(dumped["options"]["llm_api_key"], "<redacted>")
            self.assertEqual(dumped["options"]["llm_model"], "vision-model")
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)


class ProcessorBoundaryTests(unittest.TestCase):
    def test_local_mp4_is_normalized_instead_of_copied(self) -> None:
        task = create_task("local", "Local mp4 normalize")
        input_path = task_dir(task.id) / "upload.mp4"
        input_path.write_bytes(b"fake mp4")
        try:
            def fake_normalize(source: Path, target: Path) -> Path:
                self.assertEqual(source, input_path)
                self.assertEqual(target.name, "media.mp4")
                target.write_bytes(b"normalized mp4")
                return target

            def fake_extract_audio(video: Path, target: Path) -> Path:
                self.assertEqual(video.name, "media.mp4")
                target.write_bytes(b"audio")
                return target

            with patch("app.processor.normalize_video", side_effect=fake_normalize) as normalize:
                with patch("app.processor.extract_audio", side_effect=fake_extract_audio):
                    with patch(
                        "app.processor.transcribe_audio",
                        return_value=TranscriptResult(
                            source="unit",
                            full_text="normalized transcript",
                            segments=[TranscriptSegment(start=0, end=1, text="normalized transcript")],
                        ),
                    ):
                        with patch("app.processor.extract_frames", return_value=[]):
                            with patch("app.processor.build_frame_grids", return_value=[]):
                                with patch(
                                    "app.processor.summarize_with_diagnostics",
                                    return_value=("# Local mp4 normalize", "local-template", ""),
                                ):
                                    process_local_video_task(task.id, input_path, "Local mp4 normalize", TaskOptions())

            record = get_task(task.id)
            normalize.assert_called_once()
            self.assertEqual(record.status, "success")
            self.assertTrue(record.media_path.endswith("media.mp4"))
            self.assertEqual(Path(record.media_path).read_bytes(), b"normalized mp4")
            self.assertIn("Local mp4 normalize", read_note(task.id))
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_diagnostics_report_lists_header_names_without_sensitive_values(self) -> None:
        task = create_task("current_page", "Diagnostics redaction", "https://course.example.com/lesson")
        try:
            record = get_task(task.id)
            record.selected_resource = ResourceCandidate(
                url="https://cdn.example.com/lesson.mp4",
                source="webRequest",
                kind="video",
                request_headers={
                    "Referer": "https://course.example.com/lesson",
                    "Cookie": "SESSION=secret",
                    "Authorization": "Bearer secret",
                },
            )
            record.download_attempts = [
                DownloadAttempt(
                    strategy="direct-file",
                    status="failed",
                    code="download_forbidden",
                    message="HTTP 403",
                    url="https://cdn.example.com/lesson.mp4",
                )
            ]

            report = render_diagnostics_markdown(record)

            self.assertIn("Referer", report)
            self.assertIn("direct-file", report)
            self.assertIn("download_forbidden", report)
            self.assertIn("## 下一步建议", report)
            self.assertIn("媒体服务器拒绝下载", report)
            self.assertIn("已捕获可复用请求头名：Referer", report)
            self.assertNotIn("SESSION=secret", report)
            self.assertNotIn("Bearer secret", report)
            self.assertNotIn("Cookie", report.split("可复用请求头名：", 1)[1].splitlines()[0])
            self.assertNotIn("Authorization", report.split("可复用请求头名：", 1)[1].splitlines()[0])
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_current_page_prefers_browser_subtitles_over_audio_pipeline(self) -> None:
        task = create_task("current_page", "Browser subtitle lesson", "https://course.example.com/lesson")
        source_path = task_dir(task.id) / "download.mp4"

        class FakeDownloader:
            def __init__(self, work_dir: Path):
                self.work_dir = work_dir
                self.attempts = []

            def download(self, page_url, resources, cookies, title):
                source_path.write_bytes(b"downloaded video")
                return source_path, ResourceCandidate(url="https://cdn.example.com/lesson.mp4", source="webRequest", kind="video")

            def download_subtitle(self, resources, cookies, referer, title):
                raise AssertionError("download_subtitle should be skipped when browser subtitles are present")

        def fake_normalize(source: Path, target: Path) -> Path:
            self.assertEqual(source, source_path)
            target.write_bytes(b"normalized video")
            return target

        def fake_summary(title, transcript, grids, options, page_url):
            self.assertEqual(transcript.source, "browser-subtitle")
            self.assertIn("first browser cue", transcript.full_text)
            self.assertIn("second browser cue", transcript.full_text)
            return ("# Browser subtitle lesson\n\nfirst browser cue", "local-template", "")

        try:
            request = CurrentPageTaskRequest(
                page_url="https://course.example.com/lesson",
                title="Browser subtitle lesson",
                resources=[ResourceCandidate(url="https://cdn.example.com/lesson.mp4", source="webRequest", kind="video")],
                browser_subtitles=[
                    {"start": 0, "end": 2, "text": "first browser cue"},
                    {"start": 2, "end": 4, "text": "second browser cue"},
                ],
                options=TaskOptions(visual_understanding=False),
            )

            with patch("app.processor.MediaDownloader", FakeDownloader), \
                patch("app.processor.normalize_video", side_effect=fake_normalize), \
                patch("app.processor.extract_audio", side_effect=AssertionError("audio extraction should be skipped")), \
                patch("app.processor.transcribe_audio", side_effect=AssertionError("Whisper should be skipped")), \
                patch("app.processor.summarize_with_diagnostics", side_effect=fake_summary):
                process_current_page_task(task.id, request)

            record = get_task(task.id)
            self.assertEqual(record.status, "success")
            self.assertEqual(record.audio_path, "")
            transcript = read_transcript(task.id)
            self.assertEqual(transcript["source"], "browser-subtitle")
            self.assertEqual([segment["text"] for segment in transcript["segments"]], ["first browser cue", "second browser cue"])
            self.assertIn("first browser cue", read_note(task.id))
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_page_text_mode_includes_browser_subtitles(self) -> None:
        task = create_task("page_text", "Visible subtitle page", "https://course.example.com/lesson")
        try:
            request = CurrentPageTaskRequest(
                mode="page_text",
                page_url="https://course.example.com/lesson",
                title="Visible subtitle page",
                page_text="页面章节：函数封装",
                browser_subtitles=[
                    {"start": 12, "end": 16, "text": "老师讲到参数传递"},
                    {"start": 16, "end": 20, "text": "然后演示返回值"},
                ],
                options=TaskOptions(),
            )

            process_current_page_task(task.id, request)

            record = get_task(task.id)
            self.assertEqual(record.status, "success")
            self.assertTrue(record.transcript_path)
            transcript = read_transcript(task.id)
            self.assertEqual(transcript["source"], "browser-subtitle")
            self.assertEqual([segment["text"] for segment in transcript["segments"]], ["老师讲到参数传递", "然后演示返回值"])
            note = read_note(task.id)
            self.assertIn("页面章节：函数封装", note)
            self.assertIn("老师讲到参数传递", note)
            self.assertIn("然后演示返回值", note)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_download_failure_keeps_page_text_and_browser_subtitle_fallback_note(self) -> None:
        task = create_task("current_page", "Fallback lesson", "https://course.example.com/lesson")

        class FailingDownloader:
            def __init__(self, work_dir: Path):
                self.work_dir = work_dir
                self.attempts = [
                    DownloadAttempt(
                        strategy="direct-file",
                        url="https://cdn.example.com/expired.mp4",
                        status="failed",
                        code="download_forbidden",
                        message="signed URL expired",
                    )
                ]

            def download(self, page_url, resources, cookies, title):
                raise DownloadError("download_forbidden", "signed URL expired")

        try:
            request = CurrentPageTaskRequest(
                page_url="https://course.example.com/lesson",
                title="Fallback lesson",
                page_text="页面章节：条件判断",
                resources=[ResourceCandidate(url="https://cdn.example.com/expired.mp4", source="webRequest", kind="video")],
                browser_subtitles=[
                    {"start": 3, "end": 7, "text": "老师解释 if else 分支"},
                ],
                options=TaskOptions(),
            )

            with patch("app.processor.MediaDownloader", FailingDownloader):
                process_current_page_task(task.id, request)

            record = get_task(task.id)
            self.assertEqual(record.status, "failed")
            self.assertEqual(record.error_code, "download_forbidden")
            self.assertTrue(record.note_path)
            self.assertTrue(record.transcript_path)
            self.assertIn("兜底笔记", record.error_detail)
            self.assertEqual(record.download_attempts[0].message, "signed URL expired")
            note = read_note(task.id)
            self.assertIn("页面章节：条件判断", note)
            self.assertIn("老师解释 if else 分支", note)
            transcript = read_transcript(task.id)
            self.assertEqual(transcript["source"], "browser-subtitle")
            self.assertEqual(transcript["segments"][0]["text"], "老师解释 if else 分支")
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_drm_signal_without_downloadable_candidate_fails_before_downloader(self) -> None:
        task = create_task("current_page", "DRM lesson", "https://course.example.com/drm")
        try:
            request = CurrentPageTaskRequest(
                page_url="https://course.example.com/drm",
                title="DRM lesson",
                active_video=ActiveVideoInfo(
                    src="blob:https://course.example.com/locked",
                    current_time=125,
                    duration=1800,
                    paused=False,
                    width=1280,
                    height=720,
                    frame_id=7,
                    drm_detected=True,
                ),
                drm_detected=True,
                drm_signals=[
                    DrmSignal(
                        source="pageHookEme",
                        key_system="com.widevine.alpha",
                        init_data_type="cenc",
                        label="requestMediaKeySystemAccess",
                    )
                ],
                resources=[ResourceCandidate(url="blob:https://course.example.com/locked", source="activeVideo", kind="blob")],
            )

            with patch("app.processor.MediaDownloader") as downloader_class:
                process_current_page_task(task.id, request)

            downloader_class.assert_not_called()
            record = get_task(task.id)
            self.assertEqual(record.status, "failed")
            self.assertEqual(record.error_code, "drm_or_encrypted")
            self.assertTrue(record.drm_detected)
            self.assertIsNotNone(record.active_video)
            assert record.active_video is not None
            self.assertEqual(record.active_video.src, "blob:https://course.example.com/locked")
            self.assertEqual(record.active_video.current_time, 125)
            self.assertEqual(record.active_video.frame_id, 7)
            self.assertEqual(record.drm_signals[0].key_system, "com.widevine.alpha")
            self.assertEqual(record.download_attempts[0].strategy, "eme-detected")
            self.assertEqual(record.download_attempts[0].code, "drm_or_encrypted")
            self.assertIn("EME/DRM", record.error_detail)
            self.assertIn("com.widevine.alpha", record.error_detail)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_drm_signal_with_extensionless_browser_candidate_reaches_downloader(self) -> None:
        task = create_task("current_page", "Signed playback lesson", "https://course.example.com/lesson")
        source_path = task_dir(task.id) / "signed-download.bin"

        class FakeDownloader:
            def __init__(self, work_dir: Path):
                self.work_dir = work_dir
                self.attempts = [
                    DownloadAttempt(
                        strategy="direct-file",
                        url="https://cdn.example.com/api/play?id=abc",
                        source="webRequest",
                        kind="video",
                        status="success",
                    )
                ]

            def download(self, page_url, resources, cookies, title):
                source_path.write_bytes(b"downloaded signed video")
                return source_path, resources[0]

        def fake_normalize(source: Path, target: Path) -> Path:
            self.assertEqual(source, source_path)
            target.write_bytes(b"normalized video")
            return target

        try:
            request = CurrentPageTaskRequest(
                mode="download_only",
                page_url="https://course.example.com/lesson",
                title="Signed playback lesson",
                active_video=ActiveVideoInfo(
                    src="blob:https://course.example.com/player",
                    drm_detected=True,
                ),
                drm_detected=True,
                drm_signals=[DrmSignal(source="pageHookEme", key_system="com.widevine.alpha")],
                resources=[
                    ResourceCandidate(
                        url="https://cdn.example.com/api/play?id=abc",
                        source="webRequest",
                        kind="video",
                        mime="application/octet-stream",
                        score=96,
                    )
                ],
            )

            with patch("app.processor.MediaDownloader", FakeDownloader), \
                patch("app.processor.normalize_video", side_effect=fake_normalize):
                process_current_page_task(task.id, request)

            record = get_task(task.id)
            self.assertEqual(record.status, "success")
            self.assertEqual(record.error_code, "")
            self.assertTrue(record.media_path)
            self.assertEqual(record.selected_resource.url, "https://cdn.example.com/api/play?id=abc")
            self.assertEqual(record.selected_resource.kind, "video")
            self.assertEqual(record.download_attempts[0].strategy, "direct-file")
            self.assertTrue(record.drm_detected)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)


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

    def test_extensionless_browser_media_candidate_is_downloadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://cdn.example.com/playback?id=abc",
                    source="webRequest",
                    kind="video",
                    mime="application/octet-stream",
                    score=95,
                    request_type="media",
                )
            ]
            candidates = downloader._candidate_resources(resources)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].url, "https://cdn.example.com/playback?id=abc")
            self.assertEqual(candidates[0].kind, "video")
            self.assertGreaterEqual(candidates[0].score, 95)
            self.assertEqual(downloader._strategy_for_candidate(candidates[0]), "direct-file")

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

    def test_ytdlp_fallback_tries_iframe_page_after_top_page(self) -> None:
        attempted_urls = []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "iframe.mp4"
            media.write_bytes(b"0" * 5000)
            downloader = MediaDownloader(root / "task")

            def fake_ytdlp(page_url, cookie_file, title, resources):
                attempted_urls.append(page_url)
                if page_url == "https://player.example.com/embed/1":
                    return media
                raise DownloadError("no_media_found", "top page not supported")

            with patch.object(downloader, "_discover_page_resources", return_value=[]), patch.object(downloader, "_download_with_ytdlp", side_effect=fake_ytdlp):
                media_path, selected = downloader.download(
                    page_url="https://course.example.com/top",
                    resources=[
                        ResourceCandidate(
                            url="https://cdn.example.com/chunk-1.m4s",
                            source="webRequest",
                            kind="fragment",
                            score=20,
                            frame_url="https://player.example.com/embed/1",
                            playback_match="blob-same-frame",
                        )
                    ],
                    cookies=[],
                    title="iframe fallback",
                )

            self.assertEqual(media_path, media)
            self.assertIsNone(selected)
            self.assertEqual(attempted_urls[:2], ["https://course.example.com/top", "https://player.example.com/embed/1"])
            self.assertEqual(downloader.attempts[-1].strategy, "page-ytdlp")
            self.assertEqual(downloader.attempts[-1].url, "https://player.example.com/embed/1")

    def test_subtitle_fallback_downloads_platform_caption_with_ytdlp(self) -> None:
        calls = []

        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options
                calls.append(options)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def extract_info(self, page_url, download):
                if not download:
                    return {"subtitles": {"zh-CN": [{"ext": "vtt"}]}}
                output = Path(self.options["outtmpl"].replace("%(ext)s", "zh-CN.vtt"))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    "WEBVTT\r\n\r\n00:00:00.000 --> 00:00:01.000\r\n平台字幕内容\r\n",
                    encoding="utf-8",
                )
                return {"title": "fake"}

        fake_module = types.ModuleType("yt_dlp")
        fake_module.YoutubeDL = FakeYoutubeDL

        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"yt_dlp": fake_module}):
            downloader = MediaDownloader(Path(tmp))
            subtitle = downloader.download_subtitle(
                resources=[
                    ResourceCandidate(
                        url="https://cdn.example.com/lesson.m3u8",
                        source="webRequest",
                        kind="hls",
                        playback_match="same-frame",
                        is_main_video=True,
                        request_headers={
                            "User-Agent": "Chrome Playback UA",
                            "Referer": "https://course.example.com/lesson/1",
                        },
                    )
                ],
                cookies=[BrowserCookie(name="AUTH", value="ok", domain=".example.com")],
                referer="https://course.example.com/lesson/1",
                title="Platform subtitle",
            )

            self.assertIsNotNone(subtitle)
            assert subtitle is not None
            self.assertTrue(subtitle.exists())
            self.assertIn("平台字幕内容", subtitle.read_text(encoding="utf-8"))
            self.assertEqual(downloader.attempts[-1].strategy, "subtitle-ytdlp")
            self.assertEqual(downloader.attempts[-1].status, "success")
            self.assertEqual(calls[-1]["subtitleslangs"], ["zh-CN"])
            self.assertTrue(calls[-1]["skip_download"])
            self.assertEqual(calls[-1]["http_headers"]["User-Agent"], "Chrome Playback UA")


class SummaryFallbackTests(unittest.TestCase):
    def test_visual_windows_align_frame_grids_with_transcript_segments(self) -> None:
        transcript = TranscriptResult(
            source="unit",
            full_text="intro demo recap",
            segments=[
                TranscriptSegment(start=0, end=5, text="intro"),
                TranscriptSegment(start=35, end=48, text="demo steps"),
                TranscriptSegment(start=80, end=92, text="recap"),
            ],
        )
        grids = [
            FrameGrid(path="grid0.jpg", url="http://127.0.0.1/grid0.jpg", start=0, end=60, frame_count=9),
            FrameGrid(path="grid1.jpg", url="http://127.0.0.1/grid1.jpg", start=60, end=120, frame_count=6),
        ]

        windows = build_visual_windows(transcript, grids)

        self.assertEqual([window.id for window in windows], ["W001", "W002"])
        self.assertEqual(windows[0].grid_url, "http://127.0.0.1/grid0.jpg")
        self.assertEqual([segment.text for segment in windows[0].segments], ["intro", "demo steps"])
        self.assertEqual([segment.text for segment in windows[1].segments], ["recap"])
        self.assertIn("00:00:35 demo steps", windows[0].transcript_excerpt)

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
        self.assertIn("画面-字幕对齐索引", note)
        self.assertIn("http://127.0.0.1/grid.jpg", note)
        self.assertIn("W001 `00:00:00 - 00:00:20`", note)
        self.assertIn("![W001 00:00:00 - 00:00:20](http://127.0.0.1/grid.jpg)", note)
        self.assertIn("复习问题", note)

    def test_summary_diagnostics_report_local_fallback_without_api_key(self) -> None:
        transcript = TranscriptResult(
            source="unit",
            full_text="函数用于封装逻辑。",
            segments=[TranscriptSegment(start=5, end=8, text="函数用于封装逻辑。")],
        )
        grids = [FrameGrid(path="", url="http://127.0.0.1/grid.jpg", start=0, end=20, frame_count=2)]

        with patch("app.summarizer.LLM_API_KEY", ""):
            note, source, warning = summarize_with_diagnostics("Python lesson", transcript, grids, TaskOptions(), "https://example.com")

        self.assertEqual(source, "local-template")
        self.assertIn("API Key", warning)
        self.assertIn("画面-字幕对齐索引", note)

    def test_summary_diagnostics_count_only_grids_eligible_for_vision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grids = []
            for index in range(MAX_VISION_GRIDS + 3):
                image = root / f"grid_{index}.jpg"
                image.write_bytes(b"fake-image")
                grids.append(
                    FrameGrid(
                        path=str(image),
                        url=f"http://127.0.0.1/grid_{index}.jpg",
                        start=index * 180,
                        end=(index + 1) * 180,
                        frame_count=9,
                    )
                )
            (root / "grid_0.jpg").unlink()

            diagnostics = build_summary_diagnostics(
                "task-1",
                "Long lesson",
                "https://course.example",
                TaskOptions(visual_understanding=True, llm_model="vision-model"),
                grids,
                [
                    VisualWindow(
                        id="W001",
                        index=1,
                        start=0,
                        end=180,
                        duration=180,
                        frame_count=9,
                        grid_url="http://127.0.0.1/grid_0.jpg",
                        grid_path=grids[0].path,
                    )
                ],
                "vision-llm",
                "",
            )

        self.assertEqual(diagnostics["frame_grid_count"], MAX_VISION_GRIDS + 3)
        self.assertEqual(diagnostics["available_grid_image_count"], MAX_VISION_GRIDS + 2)
        self.assertEqual(diagnostics["vision_grid_limit"], MAX_VISION_GRIDS)
        self.assertEqual(diagnostics["vision_grid_count"], MAX_VISION_GRIDS)
        self.assertEqual(diagnostics["vision_image_count"], MAX_VISION_GRIDS - 1)
        self.assertEqual(diagnostics["omitted_frame_grid_count"], 3)
        self.assertFalse(diagnostics["all_sent_grids_had_images"])
        self.assertFalse(diagnostics["all_grids_had_images"])

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
        first_prompt = completions.calls[0]["messages"][0]["content"][0]["text"]
        self.assertIn("窗口 W001", first_prompt)
        self.assertIn("http://127.0.0.1/grid_0.jpg", first_prompt)
        merge_content = completions.calls[3]["messages"][0]["content"]
        self.assertIn("画面索引清单", merge_content)
        self.assertIn("W001 `00:00:00 - 00:03:00`", merge_content)
        self.assertIn("W009 `00:24:00 - 00:27:00`", merge_content)
        self.assertIn("http://127.0.0.1/grid_8.jpg", merge_content)
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
