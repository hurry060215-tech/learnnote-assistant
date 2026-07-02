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
from urllib.parse import quote
from unittest.mock import patch

from app.config import DATA_DIR, TEMP_DIR
from app.downloader import (
    DownloadError,
    MediaDownloader,
    _rewrite_dash_manifest_for_local_file,
    choose_ytdlp_subtitle_language,
    classify_resource,
    cookie_header_for_url,
    download_headers_for_candidate,
    effective_resource_kind,
    extract_media_resources_from_text,
    extract_player_page_resources_from_html,
    fallback_page_urls,
    ffmpeg_cookies_option,
    infer_manifest_url_from_fragment,
    infer_sibling_manifest_urls_from_fragment,
    score_resource,
    source_rank,
    ytdlp_headers_from_browser_context,
)
from app.main import render_diagnostics_markdown, task_audit_summary
from app.models import ActiveVideoInfo, BrowserCookie, CurrentPageTaskRequest, DownloadAttempt, DrmSignal, FrameGrid, ResourceCandidate, TaskOptions, TranscriptResult, TranscriptSegment, VisualWindow
from app.processor import build_summary_diagnostics, cookie_sync_summary, process_current_page_task, process_local_video_task, read_note, read_transcript, redacted_request_dump, redacted_resource
from app.summarizer import MAX_GRIDS_PER_VISION_CALL, MAX_VISION_GRIDS, build_visual_windows, ensure_visual_appendix, local_markdown_note, summarize_with_diagnostics
from app.storage import create_task, get_task, task_dir
from app.transcriber import transcribe_audio_openai_compatible, transcript_from_subtitle

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
        self.assertEqual(classify_resource("https://cdn.example.com/archive/lesson.avi?token=abc"), "video")
        self.assertEqual(classify_resource("https://cdn.example.com/index.m3u8"), "hls")
        self.assertEqual(classify_resource("https://cdn.example.com/manifest.mpd"), "dash")
        self.assertEqual(classify_resource("blob:https://example.com/abc"), "blob")

    def test_declared_media_hint_sources_rank_above_plain_dom(self) -> None:
        self.assertEqual(source_rank("scriptHint"), 3)
        self.assertEqual(source_rank("domHint"), 3)
        self.assertEqual(source_rank("locationHint"), 3)
        self.assertEqual(source_rank("iframeHint"), 3)
        self.assertGreater(source_rank("webRequest"), source_rank("domHint"))
        self.assertGreater(source_rank("domHint"), source_rank("dom"))
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

    def test_page_json_extracts_chaoxing_style_extensionless_playback_endpoints(self) -> None:
        payload = json.dumps(
            {
                "sources": [
                    {"url": "/ananas/status/objectid-123?flag=normal"},
                    {"file": "/api/play?objectid=456&dtoken=abc"},
                ],
                "streams": ["https://media.example.com/vod/lesson?id=noext"],
                "other": "/ordinary/page",
            }
        )

        resources = extract_media_resources_from_text(payload, "https://course.example.com/lesson", "page-scan")
        by_url = {item.url: item for item in resources}

        self.assertEqual(by_url["https://course.example.com/ananas/status/objectid-123?flag=normal"].kind, "video")
        self.assertEqual(by_url["https://course.example.com/api/play?objectid=456&dtoken=abc"].kind, "video")
        self.assertEqual(by_url["https://media.example.com/vod/lesson?id=noext"].kind, "video")
        self.assertNotIn("https://course.example.com/ordinary/page", by_url)

    def test_infers_manifest_url_from_nested_fragment(self) -> None:
        fragment = "https://cdn.example.com/live/master.m3u8/segment-001.ts?token=abc"
        self.assertEqual(classify_resource(fragment), "fragment")
        self.assertEqual(infer_manifest_url_from_fragment(fragment), "https://cdn.example.com/live/master.m3u8?token=abc")
        dash_fragment = "https://cdn.example.com/dash/manifest.mpd/chunk-1.m4s"
        self.assertEqual(infer_manifest_url_from_fragment(dash_fragment), "https://cdn.example.com/dash/manifest.mpd")

    def test_guesses_sibling_manifest_urls_from_plain_fragments(self) -> None:
        self.assertEqual(
            infer_sibling_manifest_urls_from_fragment("https://cdn.example.com/live/seg-001.ts?token=abc"),
            [
                "https://cdn.example.com/live/index.m3u8?token=abc",
                "https://cdn.example.com/live/playlist.m3u8?token=abc",
                "https://cdn.example.com/live/master.m3u8?token=abc",
            ],
        )
        self.assertEqual(
            infer_sibling_manifest_urls_from_fragment("https://cdn.example.com/dash/chunk-001.m4s?token=abc"),
            [
                "https://cdn.example.com/dash/manifest.mpd?token=abc",
                "https://cdn.example.com/dash/index.mpd?token=abc",
                "https://cdn.example.com/dash/master.m3u8?token=abc",
                "https://cdn.example.com/dash/index.m3u8?token=abc",
            ],
        )
        self.assertEqual(
            infer_sibling_manifest_urls_from_fragment("https://cdn.example.com/live/720p/seg-001.ts?token=abc"),
            [
                "https://cdn.example.com/live/720p/index.m3u8?token=abc",
                "https://cdn.example.com/live/720p/playlist.m3u8?token=abc",
                "https://cdn.example.com/live/720p/master.m3u8?token=abc",
                "https://cdn.example.com/live/index.m3u8?token=abc",
                "https://cdn.example.com/live/playlist.m3u8?token=abc",
                "https://cdn.example.com/live/master.m3u8?token=abc",
            ],
        )
        self.assertEqual(
            infer_sibling_manifest_urls_from_fragment("https://cdn.example.com/dash/video/chunk-001.m4s?token=abc"),
            [
                "https://cdn.example.com/dash/video/manifest.mpd?token=abc",
                "https://cdn.example.com/dash/video/index.mpd?token=abc",
                "https://cdn.example.com/dash/video/master.m3u8?token=abc",
                "https://cdn.example.com/dash/video/index.m3u8?token=abc",
                "https://cdn.example.com/dash/manifest.mpd?token=abc",
                "https://cdn.example.com/dash/index.mpd?token=abc",
                "https://cdn.example.com/dash/master.m3u8?token=abc",
                "https://cdn.example.com/dash/index.m3u8?token=abc",
            ],
        )
        self.assertEqual(infer_sibling_manifest_urls_from_fragment("https://cdn.example.com/live/master.m3u8/seg.ts"), [])

    def test_cookie_header_matches_parent_domains(self) -> None:
        cookies = [
            BrowserCookie(name="SESSDATA", value="abc", domain=".chaoxing.com"),
            BrowserCookie(name="other", value="nope", domain=".example.com"),
        ]
        header = cookie_header_for_url(cookies, "https://mooc1.chaoxing.com/video")
        self.assertEqual(header, "SESSDATA=abc")

    def test_cookie_header_respects_path_secure_and_expiry(self) -> None:
        cookies = [
            BrowserCookie(name="ROOT", value="ok", domain=".cdn.example.com", path="/"),
            BrowserCookie(name="HLS", value="token", domain=".cdn.example.com", path="/hls"),
            BrowserCookie(name="OTHER_PATH", value="nope", domain=".cdn.example.com", path="/api"),
            BrowserCookie(name="SECURE_ONLY", value="https-only", domain=".cdn.example.com", path="/hls", secure=True),
            BrowserCookie(name="EXPIRED", value="old", domain=".cdn.example.com", path="/hls", expirationDate=1),
            BrowserCookie(name="BAD", value="a\nb", domain=".cdn.example.com", path="/hls"),
        ]

        header = cookie_header_for_url(cookies, "https://media.cdn.example.com/hls/master.m3u8")
        self.assertEqual(header, "ROOT=ok; HLS=token; SECURE_ONLY=https-only")

        insecure_header = cookie_header_for_url(cookies, "http://media.cdn.example.com/hls/master.m3u8")
        self.assertEqual(insecure_header, "ROOT=ok; HLS=token")

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
        self.assertEqual(headers["Authorization"], "Bearer bad")

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
        self.assertEqual(headers["Authorization"], "Bearer bad")

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

    def test_dash_manifest_rewrite_absolutizes_baseurl_and_segment_paths(self) -> None:
        manifest = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
  <Period>
    <AdaptationSet>
      <Representation id="v1">
        <BaseURL>video/</BaseURL>
        <SegmentTemplate initialization="init-$RepresentationID$.m4s" media="chunk-$Number$.m4s" />
        <SegmentList>
          <Initialization sourceURL="init-list.m4s" />
          <SegmentURL media="seg-1.m4s" index="seg-1.idx" />
        </SegmentList>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""

        rewritten = _rewrite_dash_manifest_for_local_file(manifest, "https://cdn.example.com/course/play/manifest.mpd?token=abc")

        self.assertIn("<BaseURL>https://cdn.example.com/course/play/video/</BaseURL>", rewritten)
        self.assertIn('initialization="https://cdn.example.com/course/play/video/init-$RepresentationID$.m4s"', rewritten)
        self.assertIn('media="https://cdn.example.com/course/play/video/chunk-$Number$.m4s"', rewritten)
        self.assertIn('sourceURL="https://cdn.example.com/course/play/video/init-list.m4s"', rewritten)
        self.assertIn('media="https://cdn.example.com/course/play/video/seg-1.m4s"', rewritten)
        self.assertIn('index="https://cdn.example.com/course/play/video/seg-1.idx"', rewritten)

    def test_download_falls_back_to_ytdlp_for_failed_media_candidate_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "task" / "downloads" / "candidate-ytdlp.mp4"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"0" * 8192)
            candidate = ResourceCandidate(
                url="https://cdn.example.com/course/master.mpd",
                source="webRequest",
                kind="dash",
                mime="application/dash+xml",
                score=100,
                request_headers={"Referer": "https://course.example.com/player"},
            )
            downloader = MediaDownloader(root / "task")

            with patch.object(downloader, "_download_candidate", side_effect=DownloadError("unsupported_manifest", "ffmpeg failed")):
                with patch.object(downloader, "_discover_page_resources", return_value=[]):
                    with patch.object(downloader, "_download_with_ytdlp", return_value=output) as ytdlp:
                        media_path, selected = downloader.download(
                            page_url="https://course.example.com/lesson",
                            resources=[candidate],
                            cookies=[],
                            title="candidate fallback",
                        )

            self.assertEqual(media_path, output)
            self.assertIs(selected, candidate)
            self.assertEqual(ytdlp.call_args.args[0], "https://cdn.example.com/course/master.mpd")
            self.assertEqual([attempt.strategy for attempt in downloader.attempts[:2]], ["manifest-ffmpeg", "candidate-ytdlp"])
            self.assertEqual(downloader.attempts[1].status, "success")

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

    def test_page_scan_infers_extensionless_play_endpoint_without_mime(self) -> None:
        resources = extract_media_resources_from_text(
            json.dumps({
                "lesson": {
                    "title": "chapter 1",
                    "playUrl": "/api/playback/getVideo?id=42&token=abc",
                    "coverUrl": "https://cdn.example.com/covers/chapter-1?id=42",
                }
            }),
            "https://course.example.com/player/index.html",
            "page-scan",
        )

        by_label = {resource.label: resource for resource in resources}

        self.assertEqual(by_label["json lesson/playUrl"].kind, "video")
        self.assertEqual(by_label["json lesson/playUrl"].url, "https://course.example.com/api/playback/getVideo?id=42&token=abc")
        self.assertNotIn("json lesson/coverUrl", by_label)

    def test_page_scan_finds_generic_extensionless_json_value_with_mime(self) -> None:
        resources = extract_media_resources_from_text(
            json.dumps({
                "code": 0,
                "data": "/api/playback/get?id=42&token=abc",
                "mimeType": "video/mp4",
            }),
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_label = {resource.label: resource for resource in resources}

        self.assertEqual(by_label["json data"].kind, "video")
        self.assertEqual(by_label["json data"].mime, "video/mp4")
        self.assertEqual(by_label["json data"].url, "https://course.example.com/api/playback/get?id=42&token=abc")

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

    def test_page_scan_finds_extensionless_declared_media_hints(self) -> None:
        resources = extract_media_resources_from_text(
            """
            <html>
              <head>
                <link rel="preload" as="video" href="/opaque/video-stream?id=preload">
                <link rel="preload" type="application/dash+xml" href="/opaque/manifest?id=dash">
                <link rel="prefetch" as="fetch" href="/api/play?id=prefetch">
                <meta property="og:video" content="/opaque/og-stream?id=meta">
              </head>
            </html>
            """,
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_label = {resource.label: resource for resource in resources}

        self.assertEqual(by_label["html link preload as=video"].kind, "video")
        self.assertEqual(by_label["html link preload as=video"].url, "https://course.example.com/opaque/video-stream?id=preload")
        self.assertEqual(by_label["html link preload application/dash+xml"].kind, "dash")
        self.assertEqual(by_label["html link preload application/dash+xml"].mime, "application/dash+xml")
        self.assertEqual(by_label["html link prefetch as=fetch"].kind, "video")
        self.assertEqual(by_label["html meta og:video"].kind, "video")

    def test_page_scan_finds_html5_media_element_sources(self) -> None:
        resources = extract_media_resources_from_text(
            """
            <video src="/api/play?id=42&token=abc"></video>
            <video>
              <source type="application/vnd.apple.mpegurl" src="/opaque/hls?id=42">
              <source type="application/dash+xml" data-src="/opaque/dash?id=42">
              <track kind="subtitles" src="/caption?id=42">
            </video>
            """,
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_label = {resource.label: resource for resource in resources}
        by_url = {resource.url: resource for resource in resources}

        self.assertEqual(by_label["html video src"].kind, "video")
        self.assertEqual(by_label["html video src"].url, "https://course.example.com/api/play?id=42&token=abc")
        self.assertEqual(by_url["https://course.example.com/opaque/hls?id=42"].kind, "hls")
        self.assertEqual(by_url["https://course.example.com/opaque/hls?id=42"].label, "html source application/vnd.apple.mpegurl")
        self.assertEqual(by_url["https://course.example.com/opaque/dash?id=42"].kind, "dash")
        self.assertEqual(by_url["https://course.example.com/opaque/dash?id=42"].mime, "application/dash+xml")
        self.assertEqual(by_url["https://course.example.com/caption?id=42"].kind, "subtitle")
        self.assertEqual(by_url["https://course.example.com/caption?id=42"].label, "html track subtitles")

    def test_page_scan_decodes_js_escaped_media_fields_inside_script(self) -> None:
        resources = extract_media_resources_from_text(
            r"""
            <script>
              window.__playConfig = {
                hls: "https:\u002F\u002Fcdn.example.com\u002Fsecure\u002Flesson.m3u8\u003Ftoken\u003Dabc\u0026uid\u003D1",
                videoUrl: "https:\/\/cdn.example.com\/archive\/lesson.mp4\x3Fsig\x3Dok"
              };
            </script>
            """,
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_url = {resource.url: resource for resource in resources}

        self.assertEqual(by_url["https://cdn.example.com/secure/lesson.m3u8?token=abc&uid=1"].kind, "hls")
        self.assertEqual(by_url["https://cdn.example.com/secure/lesson.m3u8?token=abc&uid=1"].label, "field hls")
        self.assertEqual(by_url["https://cdn.example.com/archive/lesson.mp4?sig=ok"].kind, "video")
        self.assertEqual(by_url["https://cdn.example.com/archive/lesson.mp4?sig=ok"].label, "field videoUrl")

    def test_page_scan_decodes_js_escaped_media_urls_outside_media_fields(self) -> None:
        resources = extract_media_resources_from_text(
            r"""
            <script>
              window.__payload = 'https:\/\/cdn.example.com\/secure\/payload.m3u8\x3Ftoken\x3Dpayload';
              window.__generic = "https:\/\/cdn.example.com\/archive\/payload.mp4\x3Fsig\x3Dok";
            </script>
            """,
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_url = {resource.url: resource for resource in resources}

        self.assertEqual(by_url["https://cdn.example.com/secure/payload.m3u8?token=payload"].kind, "hls")
        self.assertEqual(by_url["https://cdn.example.com/secure/payload.m3u8?token=payload"].label, "page scan")
        self.assertEqual(by_url["https://cdn.example.com/archive/payload.mp4?sig=ok"].kind, "video")
        self.assertEqual(by_url["https://cdn.example.com/archive/payload.mp4?sig=ok"].request_headers["Referer"], "https://course.example.com/player/index.html")

    def test_page_scan_extracts_player_iframe_pages_for_recursive_scan(self) -> None:
        resources = extract_player_page_resources_from_html(
            """
            <iframe id="course-player" title="lesson video player" src="/frame.html?jobid=42"></iframe>
            <iframe src="/ads/banner.html"></iframe>
            """,
            "https://mooc1.chaoxing.com/lesson/shell.html",
            "page-frame-scan",
        )

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0].url, "https://mooc1.chaoxing.com/frame.html?jobid=42")
        self.assertEqual(resources[0].kind, "unknown")
        self.assertEqual(resources[0].source, "page-frame-scan")
        self.assertEqual(resources[0].request_headers["Referer"], "https://mooc1.chaoxing.com/lesson/shell.html")

    def test_page_scan_finds_chaoxing_style_media_fields(self) -> None:
        encoded_hls = "https%3A%2F%2Fcdn.example.com%2Fchaoxing%2Fmaster.m3u8%3Ftoken%3Dabc"
        resources = extract_media_resources_from_text(
            json.dumps({
                "job": {
                    "objectid": encoded_hls,
                    "dtoken": "/api/ananas/video?id=42&dtoken=abc",
                    "mediaType": "video/mp4",
                }
            }),
            "https://mooc1.chaoxing.com/player/index.html",
            "page-scan",
        )
        by_label = {resource.label: resource for resource in resources}

        self.assertEqual(by_label["json job/objectid"].kind, "hls")
        self.assertEqual(by_label["json job/objectid"].url, "https://cdn.example.com/chaoxing/master.m3u8?token=abc")
        self.assertEqual(by_label["json job/dtoken"].kind, "video")
        self.assertEqual(by_label["json job/dtoken"].url, "https://mooc1.chaoxing.com/api/ananas/video?id=42&dtoken=abc")
        self.assertEqual(by_label["json job/dtoken"].mime, "video/mp4")

    def test_page_scan_decodes_wrapped_media_field_values(self) -> None:
        encoded = "https%3A%2F%2Fcdn.example.com%2Fsecure%2Flesson.m3u8%3Ftoken%3Dabc"
        double_encoded = quote(quote("https://cdn.example.com/secure/backup.m3u8?token=double"))
        packed = b64encode(b"https://cdn.example.com/video/lesson.mp4?sign=ok").decode("ascii")
        resources = extract_media_resources_from_text(
            json.dumps({
                "playInfo": {
                    "hls": encoded,
                    "backupHlsUrl": double_encoded,
                    "videoUrl": packed,
                }
            }),
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_url = {resource.url: resource for resource in resources}

        self.assertEqual(by_url["https://cdn.example.com/secure/lesson.m3u8?token=abc"].kind, "hls")
        self.assertEqual(by_url["https://cdn.example.com/secure/backup.m3u8?token=double"].kind, "hls")
        self.assertEqual(by_url["https://cdn.example.com/video/lesson.mp4?sign=ok"].kind, "video")

    def test_page_scan_decodes_nested_base64_json_media_config(self) -> None:
        nested_config = json.dumps(
            {
                "playInfo": {
                    "videoUrl": "/api/media/file?id=42&token=abc",
                    "mimeType": "video/mp4",
                }
            },
            indent=2,
        )
        packed = b64encode(nested_config.encode("utf-8")).decode("ascii")
        resources = extract_media_resources_from_text(
            json.dumps({"code": 0, "data": packed}),
            "https://course.example.com/player/index.html",
            "page-scan",
        )
        by_label = {resource.label: resource for resource in resources}

        self.assertEqual(by_label["json data/playInfo/videoUrl"].kind, "video")
        self.assertEqual(by_label["json data/playInfo/videoUrl"].url, "https://course.example.com/api/media/file?id=42&token=abc")
        self.assertEqual(by_label["json data/playInfo/videoUrl"].mime, "video/mp4")

    def test_page_scan_decodes_encoded_media_urls_outside_media_fields(self) -> None:
        double_encoded = quote(quote("https://cdn.example.com/secure/double.mp4?token=twice"))
        resources = extract_media_resources_from_text(
            f"""
            <a href="/player?objectid=https%3A%2F%2Fcdn.example.com%2Fsecure%2Flesson.m3u8%3Ftoken%3Dabc%26uid%3D1">
              open player
            </a>
            <script>window.__encoded = "{double_encoded}";</script>
            """,
            "https://course.example.com/lesson/index.html",
            "page-scan",
        )
        by_url = {resource.url: resource for resource in resources}

        self.assertEqual(len(resources), 2)
        self.assertEqual(by_url["https://cdn.example.com/secure/lesson.m3u8?token=abc&uid=1"].kind, "hls")
        self.assertEqual(by_url["https://cdn.example.com/secure/lesson.m3u8?token=abc&uid=1"].label, "encoded page scan")
        self.assertEqual(by_url["https://cdn.example.com/secure/double.mp4?token=twice"].kind, "video")
        self.assertEqual(by_url["https://cdn.example.com/secure/double.mp4?token=twice"].request_headers["Referer"], "https://course.example.com/lesson/index.html")
        self.assertFalse([resource.url for resource in resources if "/https%3A%2F%2F" in resource.url])

    def test_page_scan_extracts_flv_direct_urls(self) -> None:
        resources = extract_media_resources_from_text(
            "window.playUrl='https://cdn.example.com/live/lesson.flv?token=abc';",
            "https://course.example.com/player/index.html",
            "page-scan",
        )

        self.assertEqual(resources[0].kind, "video")
        self.assertEqual(resources[0].url, "https://cdn.example.com/live/lesson.flv?token=abc")

    def test_page_scan_extracts_avi_direct_urls(self) -> None:
        resources = extract_media_resources_from_text(
            "window.playUrl='https://cdn.example.com/archive/lesson.avi?token=abc';",
            "https://course.example.com/player/index.html",
            "page-scan",
        )

        self.assertEqual(resources[0].kind, "video")
        self.assertEqual(resources[0].url, "https://cdn.example.com/archive/lesson.avi?token=abc")

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
            request_body={"type": "form", "content": "lesson=42&token=secret"},
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
        self.assertEqual(data["resources"][0]["request_body"]["content"], "<redacted>")
        self.assertEqual(data["resources"][0]["headers"], {"content-type": "video/mp4"})

        selected = redacted_resource(resource)
        self.assertEqual(selected.request_headers["Referer"], "<redacted>")
        self.assertEqual(selected.request_body["content"], "<redacted>")
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


class TranscriberBoundaryTests(unittest.TestCase):
    def test_openai_compatible_asr_parses_verbose_segments(self) -> None:
        calls = []

        class FakeTranscriptions:
            def create(self, **kwargs):
                calls.append(kwargs)
                return {
                    "language": "zh",
                    "text": "第一句 第二句",
                    "segments": [
                        {"start": 0.0, "end": 1.5, "text": "第一句"},
                        {"start": 1.5, "end": 3.0, "text": "第二句"},
                    ],
                }

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.audio = types.SimpleNamespace(transcriptions=FakeTranscriptions())

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.wav"
            audio.write_bytes(b"fake audio")
            with patch.dict(sys.modules, {"openai": fake_openai}):
                transcript = transcribe_audio_openai_compatible(
                    audio,
                    TaskOptions(
                        transcriber="openai-compatible",
                        whisper_model="small",
                        llm_api_key="test-key",
                        llm_base_url="https://asr.example/v1",
                    ),
                )

        self.assertEqual(transcript.source, "openai-compatible-asr")
        self.assertEqual(transcript.language, "zh")
        self.assertEqual([segment.text for segment in transcript.segments], ["第一句", "第二句"])
        self.assertEqual(calls[0]["model"], "whisper-1")
        self.assertEqual(calls[0]["response_format"], "verbose_json")

    def test_groq_asr_missing_key_warning_includes_provider_model_and_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.wav"
            audio.write_bytes(b"fake audio")
            transcript = transcribe_audio_openai_compatible(
                audio,
                TaskOptions(
                    transcriber="groq",
                    whisper_model="whisper-large-v3",
                    llm_base_url="https://api.groq.com/openai/v1",
                ),
            )

        self.assertEqual(transcript.source, "groq-asr-missing-key")
        self.assertIn("provider=groq", transcript.warning)
        self.assertIn("model=whisper-large-v3", transcript.warning)
        self.assertIn("base=api.groq.com", transcript.warning)
        self.assertIn("stage=configuration", transcript.warning)
        self.assertIn("code=missing_api_key", transcript.warning)
        self.assertNotIn("sk-", transcript.warning)

    def test_remote_asr_error_warning_redacts_secret_like_values(self) -> None:
        class FakeTranscriptions:
            def create(self, **kwargs):
                raise RuntimeError(
                    "quota failed for sk-secretvalue123456 "
                    "Bearer abcdefghijklmnop api_key=secretsecret123"
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.audio = types.SimpleNamespace(transcriptions=FakeTranscriptions())

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.wav"
            audio.write_bytes(b"fake audio")
            with patch.dict(sys.modules, {"openai": fake_openai}):
                transcript = transcribe_audio_openai_compatible(
                    audio,
                    TaskOptions(
                        transcriber="openai-compatible",
                        whisper_model="small",
                        llm_api_key="test-key",
                        llm_base_url="https://api.openai.com/v1",
                    ),
                )

        self.assertEqual(transcript.source, "openai-compatible-asr-error")
        self.assertIn("provider=openai", transcript.warning)
        self.assertIn("model=whisper-1", transcript.warning)
        self.assertIn("stage=transcription", transcript.warning)
        self.assertIn("code=api_error", transcript.warning)
        self.assertIn("sk-<redacted>", transcript.warning)
        self.assertIn("Bearer <redacted>", transcript.warning)
        self.assertIn("api_key=<redacted>", transcript.warning)
        self.assertIn("sk-<redacted>", transcript.full_text)
        self.assertNotIn("sk-secretvalue123456", transcript.warning)
        self.assertNotIn("abcdefghijklmnop", transcript.warning)
        self.assertNotIn("secretsecret123", transcript.full_text)


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

    def test_remote_asr_option_uses_openai_compatible_transcriber(self) -> None:
        options = TaskOptions(
            transcriber="openai-compatible",
            whisper_model="whisper-1",
            llm_api_key="test-key",
        )
        task = create_task("local", "Remote ASR", options=options)
        input_path = task_dir(task.id) / "upload.mp4"
        input_path.write_bytes(b"fake mp4")
        try:
            def fake_normalize(source: Path, target: Path) -> Path:
                target.write_bytes(b"normalized mp4")
                return target

            def fake_extract_audio(video: Path, target: Path) -> Path:
                target.write_bytes(b"audio")
                return target

            with patch("app.processor.normalize_video", side_effect=fake_normalize), \
                patch("app.processor.extract_audio", side_effect=fake_extract_audio), \
                patch("app.processor.transcribe_audio", side_effect=AssertionError("local faster-whisper should not run")), \
                patch(
                    "app.processor.transcribe_audio_openai_compatible",
                    return_value=TranscriptResult(
                        source="openai-compatible-asr",
                        full_text="remote transcript",
                        segments=[TranscriptSegment(start=0, end=1, text="remote transcript")],
                    ),
                ) as remote_asr, \
                patch("app.processor.extract_frames", return_value=[]), \
                patch("app.processor.build_frame_grids", return_value=[]), \
                patch("app.processor.summarize_with_diagnostics", return_value=("# Remote ASR", "local-template", "")):
                process_local_video_task(task.id, input_path, "Remote ASR", options)

            remote_asr.assert_called_once()
            self.assertEqual(remote_asr.call_args.args[1].transcriber, "openai-compatible")
            record = get_task(task.id)
            self.assertEqual(record.status, "success")
            self.assertEqual(record.options.transcriber, "openai-compatible")
            transcript = read_transcript(task.id)
            self.assertEqual(transcript["source"], "openai-compatible-asr")
            self.assertEqual(transcript["segments"][0]["text"], "remote transcript")
            report = render_diagnostics_markdown(record)
            self.assertIn("转写引擎：OpenAI-compatible ASR · whisper-1", report)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_local_video_prefers_embedded_subtitle_over_audio_pipeline(self) -> None:
        task = create_task("local", "Embedded subtitle lesson")
        input_path = task_dir(task.id) / "upload.mkv"
        input_path.write_bytes(b"fake mkv")
        embedded_subtitle = task_dir(task.id) / "embedded_subtitle.srt"
        try:
            def fake_normalize(source: Path, target: Path) -> Path:
                target.write_bytes(b"normalized mp4")
                return target

            def fake_extract_embedded_subtitle(source: Path, target: Path) -> Path:
                self.assertEqual(source, input_path)
                target.write_text("1\n00:00:00,000 --> 00:00:02,000\nembedded cue\n\n", encoding="utf-8")
                return target

            with patch("app.processor.normalize_video", side_effect=fake_normalize), \
                patch("app.processor.extract_embedded_subtitle", side_effect=fake_extract_embedded_subtitle), \
                patch("app.processor.extract_audio", side_effect=AssertionError("audio extraction should be skipped")), \
                patch("app.processor.transcribe_audio", side_effect=AssertionError("ASR should be skipped")), \
                patch("app.processor.extract_frames", return_value=[]), \
                patch("app.processor.build_frame_grids", return_value=[]), \
                patch("app.processor.summarize_with_diagnostics", return_value=("# Embedded subtitle lesson", "local-template", "")):
                process_local_video_task(task.id, input_path, "Embedded subtitle lesson", TaskOptions())

            record = get_task(task.id)
            self.assertEqual(record.status, "success")
            self.assertTrue(record.subtitle_path.endswith("embedded_subtitle.srt"))
            self.assertEqual(Path(record.subtitle_path), embedded_subtitle)
            transcript = read_transcript(task.id)
            self.assertEqual(transcript["source"], "embedded-subtitle")
            self.assertEqual(transcript["segments"][0]["text"], "embedded cue")
            report = render_diagnostics_markdown(record)
            self.assertIn("转写来源：视频内嵌字幕", report)
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
                headers={
                    "content-disposition": "attachment; filename*=UTF-8''lesson%20download.mp4",
                },
                request_headers={
                    "Referer": "https://course.example.com/lesson",
                    "Range": "bytes=100-200",
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
            self.assertIn("Content-Disposition", report)
            self.assertIn("lesson%20download.mp4", report)
            self.assertIn("direct-file", report)
            self.assertIn("download_forbidden", report)
            self.assertIn("Range 只作为浏览器播放证据", report)
            self.assertIn("## 下一步建议", report)
            self.assertIn("媒体服务器拒绝下载", report)
            self.assertIn("Range, Referer", report)
            self.assertNotIn("SESSION=secret", report)
            self.assertNotIn("Bearer secret", report)
            self.assertNotIn("Cookie", report.split("可复用请求头名：", 1)[1].splitlines()[0])
            self.assertNotIn("Authorization", report.split("可复用请求头名：", 1)[1].splitlines()[0])
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_diagnostics_report_lists_cookie_domains_without_values(self) -> None:
        task = create_task("current_page", "Cookie diagnostics", "https://course.example.com/lesson")
        try:
            record = get_task(task.id)
            record.cookie_summary = cookie_sync_summary([
                BrowserCookie(name="SESSION", value="secret-session", domain=".course.example.com", secure=True, httpOnly=True),
                BrowserCookie(name="CDN_TOKEN", value="secret-cdn", domain=".cdn.example.com", secure=True),
            ])

            report = render_diagnostics_markdown(record)

            self.assertIn(".course.example.com (1)", report)
            self.assertIn(".cdn.example.com (1)", report)
            self.assertIn("2", report)
            self.assertNotIn("secret-session", report)
            self.assertNotIn("secret-cdn", report)
            self.assertNotIn("SESSION", report)
            self.assertNotIn("CDN_TOKEN", report)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_task_audit_marks_download_only_media_ready_for_rerun(self) -> None:
        task = create_task("current_page", "Downloaded only", "https://course.example.com/lesson")
        try:
            record = get_task(task.id)
            record.status = "success"
            record.phase = "completed"
            record.progress = 100
            media = task_dir(task.id) / "media.mp4"
            media.write_bytes(b"media")
            record.media_path = str(media)
            record.selected_resource = ResourceCandidate(
                url="https://cdn.example.com/lesson.m3u8",
                source="webRequest",
                kind="hls",
                playback_match="same-frame",
            )

            audit = task_audit_summary(record)
            gates = {gate["key"]: gate for gate in audit["gates"]}

            self.assertEqual(gates["source"]["state"], "pass")
            self.assertEqual(gates["media"]["state"], "pass")
            self.assertEqual(gates["transcript"]["state"], "warn")
            self.assertEqual(audit["blocked_gate"], "transcript")
            self.assertFalse(audit["ok"])
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_task_audit_marks_failed_download_at_media_gate(self) -> None:
        task = create_task("current_page", "Forbidden media", "https://course.example.com/lesson")
        try:
            record = get_task(task.id)
            record.status = "failed"
            record.phase = "failed"
            record.error_code = "download_forbidden"
            record.download_attempts = [
                DownloadAttempt(
                    strategy="direct-file",
                    status="failed",
                    code="download_forbidden",
                    message="HTTP 403",
                    url="https://cdn.example.com/lesson.mp4",
                )
            ]

            audit = task_audit_summary(record)
            gates = {gate["key"]: gate for gate in audit["gates"]}
            report = render_diagnostics_markdown(record)

            self.assertEqual(gates["source"]["state"], "pass")
            self.assertEqual(gates["media"]["state"], "fail")
            self.assertEqual(audit["blocked_gate"], "media")
            self.assertIn("## Stage Audit Gates", report)
            self.assertIn("- media: fail", report)
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
                cookies=[
                    BrowserCookie(name="COURSE", value="secret-course", domain=".course.example.com", secure=True),
                    BrowserCookie(name="CDN", value="secret-cdn", domain=".cdn.example.com"),
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
            self.assertEqual(record.cookie_summary["total"], 2)
            self.assertEqual(record.cookie_summary["domains"][".course.example.com"], 1)
            self.assertEqual(record.cookie_summary["domains"][".cdn.example.com"], 1)
            self.assertTrue(record.subtitle_path.endswith("browser_subtitles.srt"))
            self.assertIn("first browser cue", Path(record.subtitle_path).read_text(encoding="utf-8"))
            transcript = read_transcript(task.id)
            self.assertEqual(transcript["source"], "browser-subtitle")
            self.assertEqual([segment["text"] for segment in transcript["segments"]], ["first browser cue", "second browser cue"])
            self.assertIn("first browser cue", read_note(task.id))
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_current_page_prefers_full_page_subtitle_over_partial_browser_subtitles(self) -> None:
        task = create_task("current_page", "Partial browser subtitle lesson", "https://course.example.com/lesson")
        source_path = task_dir(task.id) / "download.mp4"
        subtitle_path = task_dir(task.id) / "page_subtitle.srt"

        class FakeDownloader:
            def __init__(self, work_dir: Path):
                self.work_dir = work_dir
                self.attempts = []

            def download(self, page_url, resources, cookies, title):
                source_path.write_bytes(b"downloaded video")
                return source_path, ResourceCandidate(url="https://cdn.example.com/lesson.mp4", source="webRequest", kind="video")

            def download_subtitle(self, resources, cookies, referer, title):
                subtitle_path.write_text(
                    "1\n00:00:00,000 --> 00:00:02,000\nfull page cue one\n\n"
                    "2\n00:00:02,000 --> 00:00:04,000\nfull page cue two\n",
                    encoding="utf-8",
                )
                self.attempts.append(DownloadAttempt(strategy="subtitle-file", status="success", url="https://cdn.example.com/lesson.vtt"))
                return subtitle_path

        def fake_normalize(source: Path, target: Path) -> Path:
            self.assertEqual(source, source_path)
            target.write_bytes(b"normalized video")
            return target

        def fake_summary(title, transcript, grids, options, page_url):
            self.assertEqual(transcript.source, "page-subtitle")
            self.assertIn("full page cue one", transcript.full_text)
            self.assertNotIn("only current visible cue", transcript.full_text)
            return ("# Partial browser subtitle lesson\n\nfull page cue one", "local-template", "")

        try:
            request = CurrentPageTaskRequest(
                page_url="https://course.example.com/lesson",
                title="Partial browser subtitle lesson",
                resources=[
                    ResourceCandidate(url="https://cdn.example.com/lesson.mp4", source="webRequest", kind="video"),
                    ResourceCandidate(url="https://cdn.example.com/lesson.vtt", source="subtitleTrack", kind="subtitle", mime="text/vtt"),
                ],
                browser_subtitles=[
                    {"start": 38, "end": 42, "text": "only current visible cue"},
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
            self.assertEqual(record.subtitle_path, str(subtitle_path))
            self.assertTrue(any(attempt.strategy == "subtitle-file" and attempt.status == "success" for attempt in record.download_attempts))
            transcript = read_transcript(task.id)
            self.assertEqual(transcript["source"], "page-subtitle")
            self.assertEqual([segment["text"] for segment in transcript["segments"]], ["full page cue one", "full page cue two"])
            self.assertIn("full page cue one", read_note(task.id))
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
            self.assertTrue(record.subtitle_path.endswith("browser_subtitles.srt"))
            self.assertIn("老师讲到参数传递", Path(record.subtitle_path).read_text(encoding="utf-8"))
            self.assertEqual(record.summary_source, "local-template")
            self.assertTrue(record.summary_warning)
            self.assertTrue(record.summary_diagnostics_path)
            self.assertTrue(record.summary_diagnostics["used_page_text_fallback"])
            self.assertEqual(record.summary_diagnostics["browser_subtitle_count"], 2)
            self.assertGreater(record.summary_diagnostics["page_text_char_count"], 0)
            transcript = read_transcript(task.id)
            self.assertEqual(transcript["source"], "browser-subtitle")
            self.assertEqual([segment["text"] for segment in transcript["segments"]], ["老师讲到参数传递", "然后演示返回值"])
            note = read_note(task.id)
            self.assertIn("页面章节：函数封装", note)
            self.assertIn("老师讲到参数传递", note)
            self.assertIn("然后演示返回值", note)
            self.assertIn("## 页面要点", note)
            self.assertIn("## 浏览器字幕线索", note)
            self.assertIn("## 兜底学习笔记", note)
            self.assertIn("直取视频不可用时", note)
            self.assertIn("哪些步骤只靠文本还不够", note)
            report = render_diagnostics_markdown(record)
            self.assertIn("页面文本字符", report)
            self.assertIn("浏览器字幕条数：2", report)
            self.assertIn("合并文本字符", report)
            self.assertIn("页面文本兜底：是", report)
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
            self.assertEqual(record.status, "success")
            self.assertEqual(record.phase, "completed")
            self.assertEqual(record.error_code, "download_forbidden")
            self.assertEqual(record.error_detail, "signed URL expired")
            self.assertTrue(record.note_path)
            self.assertTrue(record.transcript_path)
            self.assertTrue(record.subtitle_path.endswith("browser_subtitles.srt"))
            self.assertIn("老师解释 if else 分支", Path(record.subtitle_path).read_text(encoding="utf-8"))
            self.assertEqual(record.summary_source, "local-template")
            self.assertTrue(record.summary_diagnostics_path)
            self.assertTrue(record.summary_diagnostics["used_page_text_fallback"])
            self.assertEqual(record.summary_diagnostics["browser_subtitle_count"], 1)
            self.assertIn("download_forbidden", record.summary_warning)
            self.assertIn("signed URL expired", record.summary_warning)
            self.assertEqual(record.download_attempts[0].message, "signed URL expired")
            note = read_note(task.id)
            self.assertIn("页面章节：条件判断", note)
            self.assertIn("老师解释 if else 分支", note)
            self.assertIn("## 兜底学习笔记", note)
            self.assertIn("回看目标：直取视频不可用时", note)
            report = render_diagnostics_markdown(record)
            self.assertIn("页面文本字符", report)
            self.assertIn("浏览器字幕条数：1", report)
            self.assertIn("页面文本兜底：是", report)
            transcript = read_transcript(task.id)
            self.assertEqual(transcript["source"], "browser-subtitle")
            self.assertEqual(transcript["segments"][0]["text"], "老师解释 if else 分支")
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_src_object_download_failure_reports_media_stream_boundary(self) -> None:
        task = create_task("current_page", "Stream lesson", "https://course.example.com/stream")

        class FailingDownloader:
            def __init__(self, work_dir: Path):
                self.work_dir = work_dir
                self.attempts = []

            def download(self, page_url, resources, cookies, title):
                raise DownloadError("no_media_found", "no media found")

        try:
            request = CurrentPageTaskRequest(
                page_url="https://course.example.com/stream",
                title="Stream lesson",
                page_text="MediaStream 课程说明",
                active_video=ActiveVideoInfo(
                    src="",
                    src_object=True,
                    src_object_type="MediaStream",
                    src_object_track_count=2,
                    src_object_video_tracks=1,
                    src_object_audio_tracks=1,
                    current_time=18,
                    duration=90,
                    paused=False,
                ),
                resources=[],
                options=TaskOptions(),
            )

            with patch("app.processor.MediaDownloader", FailingDownloader):
                process_current_page_task(task.id, request)

            record = get_task(task.id)
            self.assertEqual(record.status, "success")
            self.assertEqual(record.phase, "completed")
            self.assertEqual(record.error_code, "no_media_found")
            self.assertIsNotNone(record.active_video)
            assert record.active_video is not None
            self.assertTrue(record.active_video.src_object)
            self.assertEqual(record.active_video.src_object_video_tracks, 1)
            self.assertIn("MediaStream", record.error_detail)
            self.assertIn("不会录制标签页", record.error_detail)
            self.assertIn("no_media_found", record.summary_warning)
            self.assertTrue(record.note_path)
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
                        headers={
                            "content-disposition": "attachment; filename*=UTF-8''signed%20lesson.mp4",
                            "set-cookie": "SESSION=secret",
                        },
                        request_headers={
                            "Referer": "https://course.example.com/lesson",
                            "Cookie": "SESSION=secret",
                            "Authorization": "Bearer secret",
                        },
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
            self.assertEqual(
                record.selected_resource.headers.get("content-disposition"),
                "attachment; filename*=UTF-8''signed%20lesson.mp4",
            )
            self.assertNotIn("set-cookie", record.selected_resource.headers)
            self.assertEqual(record.selected_resource.request_headers["Referer"], "<redacted>")
            self.assertEqual(record.selected_resource.request_headers["Cookie"], "<redacted>")
            self.assertEqual(record.selected_resource.request_headers["Authorization"], "<redacted>")
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

    def test_blob_with_playback_matched_fragments_gets_manifest_guesses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(url="blob:https://course.example/active", source="activeVideo", kind="blob"),
                ResourceCandidate(
                    url="https://cdn.example.com/live/segment-001.ts?token=abc",
                    source="webRequest",
                    kind="fragment",
                    score=28,
                    playback_match="blob-same-frame",
                    request_headers={"Referer": "https://course.example.com/lesson"},
                ),
            ]
            candidates = downloader._candidate_resources(resources)
            urls = {candidate.url: candidate for candidate in candidates}
            guessed = urls["https://cdn.example.com/live/master.m3u8?token=abc"]
            self.assertEqual(guessed.kind, "hls")
            self.assertEqual(guessed.source, "manifest-guess")
            self.assertEqual(guessed.playback_match, "blob-same-frame")
            self.assertEqual(guessed.request_headers["Referer"], "https://course.example.com/lesson")
            self.assertLessEqual(guessed.score, 72)

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

    def test_user_selected_candidate_overrides_backend_rank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://cdn.example.com/live/master.m3u8",
                    source="webRequest",
                    kind="hls",
                    mime="application/vnd.apple.mpegurl",
                    score=100,
                    playback_match="manifest-near-playhead",
                    is_main_video=True,
                ),
                ResourceCandidate(
                    url="https://cdn.example.com/manual-choice.mp4",
                    source="webRequest",
                    kind="video",
                    mime="video/mp4",
                    score=72,
                    user_selected=True,
                    status_code=200,
                    request_headers={"Referer": "https://course.example.com/lesson"},
                ),
            ]

            candidates = downloader._candidate_resources(resources)

            self.assertEqual(candidates[0].url, "https://cdn.example.com/manual-choice.mp4")
            self.assertTrue(candidates[0].user_selected)
            self.assertEqual(candidates[0].request_headers["Referer"], "https://course.example.com/lesson")

    def test_manifest_near_playhead_wins_tied_backend_rank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://cdn.example.com/archive.mp4",
                    source="webRequest",
                    kind="video",
                    mime="video/mp4",
                    score=100,
                    time_stamp=2000,
                ),
                ResourceCandidate(
                    url="https://cdn.example.com/live/master.m3u8",
                    source="webRequest",
                    kind="hls",
                    mime="application/vnd.apple.mpegurl",
                    score=100,
                    playback_match="manifest-near-playhead",
                    is_main_video=True,
                    time_stamp=1000,
                ),
            ]

            candidates = downloader._candidate_resources(resources)

            self.assertEqual(candidates[0].url, "https://cdn.example.com/live/master.m3u8")
            self.assertEqual(candidates[0].playback_match, "manifest-near-playhead")
            downloader._record_attempt(
                strategy="manifest-ffmpeg",
                candidate=candidates[0],
                status="failed",
                code="download_forbidden",
                message="HTTP 403",
            )
            self.assertIn("播放进度附近 Manifest 请求", downloader.attempts[0].message)

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

    def test_playback_evidence_beats_higher_raw_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://cdn.example.com/archive-or-ad.mp4",
                    source="webRequest",
                    kind="video",
                    mime="video/mp4",
                    score=100,
                    time_stamp=3000,
                ),
                ResourceCandidate(
                    url="https://cdn.example.com/current-lesson.mp4",
                    source="pageHookBlobSource",
                    kind="video",
                    mime="video/mp4",
                    score=42,
                    playback_match="blob-source",
                    blob_url="blob:https://course.example/active-video",
                    time_stamp=1000,
                ),
            ]

            candidates = downloader._candidate_resources(resources)

            self.assertEqual(candidates[0].url, "https://cdn.example.com/current-lesson.mp4")
            self.assertEqual(candidates[0].playback_match, "blob-source")

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

    def test_low_confidence_manifest_candidates_are_guessed_from_plain_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://cdn.example.com/live/segment-001.ts?token=abc",
                    source="webRequest",
                    kind="fragment",
                    score=25,
                    request_headers={"Referer": "https://course.example.com/lesson"},
                )
            ]
            candidates = downloader._candidate_resources(resources)
            urls = {candidate.url: candidate for candidate in candidates}
            guessed = urls["https://cdn.example.com/live/master.m3u8?token=abc"]
            self.assertEqual(guessed.kind, "hls")
            self.assertEqual(guessed.source, "manifest-guess")
            self.assertEqual(guessed.playback_match, "inferred-from-fragment")
            self.assertEqual(guessed.request_headers["Referer"], "https://course.example.com/lesson")
            self.assertLessEqual(guessed.score, 72)

    def test_page_scan_extracts_plain_segment_urls_for_manifest_guessing(self) -> None:
        resources = extract_media_resources_from_text(
            "window.__segments=['https://cdn.example.com/live/segment-001.ts?token=abc'];",
            "https://course.example.com/lesson",
        )
        segment = next(item for item in resources if item.url == "https://cdn.example.com/live/segment-001.ts?token=abc")
        self.assertEqual(segment.kind, "fragment")
        self.assertEqual(segment.source, "page-scan")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            candidates = downloader._candidate_resources(resources)
        urls = {candidate.url: candidate for candidate in candidates}
        self.assertIn("https://cdn.example.com/live/master.m3u8?token=abc", urls)
        self.assertEqual(urls["https://cdn.example.com/live/master.m3u8?token=abc"].source, "manifest-guess")

    def test_manifest_guess_does_not_outrank_verified_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://cdn.example.com/live/segment-001.ts?token=abc",
                    source="webRequest",
                    kind="fragment",
                    score=25,
                    playback_match="blob-source",
                ),
                ResourceCandidate(
                    url="https://cdn.example.com/live/verified.m3u8?token=abc",
                    source="webRequest",
                    kind="hls",
                    score=94,
                    playback_match="blob-source",
                ),
            ]
            candidates = downloader._candidate_resources(resources)
            self.assertEqual(candidates[0].url, "https://cdn.example.com/live/verified.m3u8?token=abc")
            guessed_scores = [candidate.score for candidate in candidates if candidate.source == "manifest-guess"]
            self.assertTrue(guessed_scores)
            self.assertTrue(all(score <= 72 for score in guessed_scores))

    def test_resolved_final_url_candidate_outranks_play_api_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://course.example.com/api/play?id=42",
                    resolved_url="https://cdn.example.com/real/master.m3u8?token=abc",
                    source="webRequest",
                    kind="hls",
                    mime="application/vnd.apple.mpegurl",
                    score=100,
                    request_headers={"Referer": "https://course.example.com/lesson"},
                ),
                ResourceCandidate(
                    url="https://cdn.example.com/real/master.m3u8?token=abc",
                    source="webRequestResolved",
                    kind="hls",
                    mime="application/vnd.apple.mpegurl",
                    score=100,
                    playback_match="resolved-final-url",
                    request_headers={"Referer": "https://course.example.com/lesson"},
                ),
            ]
            candidates = downloader._candidate_resources(resources)

            self.assertEqual(candidates[0].url, "https://cdn.example.com/real/master.m3u8?token=abc")
            self.assertEqual(candidates[0].source, "webRequestResolved")
            self.assertEqual(candidates[0].playback_match, "resolved-final-url")
            self.assertEqual(candidates[0].request_headers["Referer"], "https://course.example.com/lesson")

    def test_download_failure_summarizes_all_attempted_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            resources = [
                ResourceCandidate(
                    url="https://cdn.example.com/expired.mp4",
                    source="webRequest",
                    kind="video",
                    mime="video/mp4",
                    score=100,
                ),
                ResourceCandidate(
                    url="https://cdn.example.com/current/master.m3u8",
                    source="webRequest",
                    kind="hls",
                    mime="application/vnd.apple.mpegurl",
                    score=90,
                ),
            ]

            with patch.object(downloader, "_download_candidate", side_effect=[
                DownloadError("download_forbidden", "HTTP 403"),
                DownloadError("unsupported_manifest", "second candidate failed"),
            ]):
                with patch.object(downloader, "_download_with_ytdlp", side_effect=DownloadError("unsupported_manifest", "yt-dlp fallback failed")):
                    with self.assertRaises(DownloadError) as ctx:
                        downloader.download("", resources, [], "attempt summary")

            self.assertEqual(ctx.exception.code, "unsupported_manifest")
            self.assertIn("已尝试 4 个下载候选", ctx.exception.message)
            self.assertIn("download_forbidden×1", ctx.exception.message)
            self.assertIn("unsupported_manifest×3", ctx.exception.message)
            self.assertIn("最后尝试：candidate-ytdlp", ctx.exception.message)
            self.assertEqual([attempt.status for attempt in downloader.attempts], ["failed", "failed", "failed", "failed"])
            self.assertEqual([attempt.strategy for attempt in downloader.attempts[2:]], ["candidate-ytdlp", "candidate-ytdlp"])

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

    def test_ffmpeg_cookie_option_keeps_domain_scoped_cookies(self) -> None:
        cookie_text = ffmpeg_cookies_option(
            [
                BrowserCookie(name="COURSE", value="ok", domain=".course.example.com", path="/"),
                BrowserCookie(name="CDN", value="token", domain=".cdn.example.com", path="/hls", secure=True),
                BrowserCookie(name="BAD", value="a\nb", domain=".cdn.example.com", path="/"),
                BrowserCookie(name="NO_DOMAIN", value="fallback", domain="", path="/"),
            ],
            "https://media.example.com/master.m3u8",
        )

        self.assertIn("COURSE=ok; domain=.course.example.com; path=/", cookie_text)
        self.assertIn("CDN=token; domain=.cdn.example.com; path=/hls; secure", cookie_text)
        self.assertIn("NO_DOMAIN=fallback; domain=media.example.com; path=/", cookie_text)
        self.assertNotIn("BAD=", cookie_text)

    def test_manifest_ffmpeg_receives_cookie_jar_and_browser_headers(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            output = Path(cmd[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"0" * 5000)
            return types.SimpleNamespace(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = MediaDownloader(Path(tmp))
            candidate = ResourceCandidate(
                url="https://cdn.example.com/course/master.m3u8",
                source="webRequest",
                kind="hls",
                request_headers={
                    "User-Agent": "Chrome Playback UA",
                    "Referer": "https://course.example.com/lesson/1",
                    "Origin": "https://course.example.com",
                },
            )
            with (
                patch("app.downloader.ffmpeg_bin", return_value="ffmpeg"),
                patch("app.downloader.subprocess.run", side_effect=fake_run),
                patch.object(downloader, "_probe_manifest_before_ffmpeg"),
            ):
                media = downloader._download_manifest(
                    candidate,
                    [
                        BrowserCookie(name="AUTH", value="ok", domain=".cdn.example.com", path="/"),
                        BrowserCookie(name="PLAYER", value="session", domain=".media.example.com", path="/hls"),
                    ],
                    "https://course.example.com/lesson/1",
                    "ffmpeg cookies",
                )
                self.assertTrue(media.exists())

        cmd = captured["cmd"]
        self.assertIn("-cookies", cmd)
        cookies_arg = cmd[cmd.index("-cookies") + 1]
        self.assertIn("AUTH=ok; domain=.cdn.example.com; path=/", cookies_arg)
        self.assertIn("PLAYER=session; domain=.media.example.com; path=/hls", cookies_arg)
        headers_arg = cmd[cmd.index("-headers") + 1]
        self.assertIn("Referer: https://course.example.com/lesson/1", headers_arg)
        self.assertIn("Origin: https://course.example.com", headers_arg)
        self.assertNotIn("Cookie:", headers_arg)
        self.assertEqual(cmd[cmd.index("-user_agent") + 1], "Chrome Playback UA")

    def test_ytdlp_fallback_accepts_flv_output(self) -> None:
        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def extract_info(self, page_url, download):
                output = Path(self.options["outtmpl"].replace("%(ext)s", "flv"))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"0" * 5000)
                return {"title": "fake flv"}

        fake_module = types.ModuleType("yt_dlp")
        fake_module.YoutubeDL = FakeYoutubeDL

        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"yt_dlp": fake_module}):
            downloader = MediaDownloader(Path(tmp))
            media = downloader._download_with_ytdlp(
                "https://course.example.com/lesson/1",
                None,
                "yt-dlp flv",
                [],
            )

            self.assertTrue(media.exists())
            self.assertEqual(media.suffix, ".flv")

    def test_ytdlp_fallback_accepts_avi_output(self) -> None:
        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def extract_info(self, page_url, download):
                output = Path(self.options["outtmpl"].replace("%(ext)s", "avi"))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"0" * 5000)
                return {"title": "fake avi"}

        fake_module = types.ModuleType("yt_dlp")
        fake_module.YoutubeDL = FakeYoutubeDL

        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"yt_dlp": fake_module}):
            downloader = MediaDownloader(Path(tmp))
            media = downloader._download_with_ytdlp(
                "https://course.example.com/lesson/1",
                None,
                "yt-dlp avi",
                [],
            )

            self.assertTrue(media.exists())
            self.assertEqual(media.suffix, ".avi")

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
            page_attempts = [url for url in attempted_urls if url in {"https://course.example.com/top", "https://player.example.com/embed/1"}]
            self.assertEqual(page_attempts[:2], ["https://course.example.com/top", "https://player.example.com/embed/1"])
            self.assertTrue(any(url.startswith("https://cdn.example.com/") for url in attempted_urls))
            self.assertTrue(any(attempt.strategy == "candidate-ytdlp" for attempt in downloader.attempts))
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
            FrameGrid(path="grid0.jpg", url="http://127.0.0.1/grid0.jpg", start=0, end=60, frame_count=9, frame_timestamps=[0, 20, 40]),
            FrameGrid(path="grid1.jpg", url="http://127.0.0.1/grid1.jpg", start=60, end=120, frame_count=6, frame_timestamps=[60, 80, 100]),
        ]

        windows = build_visual_windows(transcript, grids)

        self.assertEqual([window.id for window in windows], ["W001", "W002"])
        self.assertEqual(windows[0].grid_url, "http://127.0.0.1/grid0.jpg")
        self.assertEqual(windows[0].frame_timestamps, [0, 20, 40])
        self.assertEqual([segment.text for segment in windows[0].segments], ["intro", "demo steps"])
        self.assertEqual([segment.text for segment in windows[1].segments], ["recap"])
        self.assertIn("00:00:35 demo steps", windows[0].transcript_excerpt)

    def test_visual_windows_do_not_duplicate_boundary_transcript_segments(self) -> None:
        transcript = TranscriptResult(
            source="unit",
            full_text="first boundary second point",
            segments=[
                TranscriptSegment(start=10, end=20, text="first"),
                TranscriptSegment(start=20, end=40, text="boundary second"),
                TranscriptSegment(start=60, end=60, text="point marker"),
            ],
        )
        grids = [
            FrameGrid(path="grid0.jpg", url="http://127.0.0.1/grid0.jpg", start=0, end=20, frame_count=9, frame_timestamps=[0, 10]),
            FrameGrid(path="grid1.jpg", url="http://127.0.0.1/grid1.jpg", start=20, end=60, frame_count=9, frame_timestamps=[20, 40]),
            FrameGrid(path="grid2.jpg", url="http://127.0.0.1/grid2.jpg", start=60, end=90, frame_count=9, frame_timestamps=[60, 80]),
        ]

        windows = build_visual_windows(transcript, grids)

        self.assertEqual([segment.text for segment in windows[0].segments], ["first"])
        self.assertEqual([segment.text for segment in windows[1].segments], ["boundary second"])
        self.assertEqual([segment.text for segment in windows[2].segments], ["point marker"])
        self.assertNotIn("boundary second", windows[0].transcript_excerpt)
        self.assertNotIn("point marker", windows[1].transcript_excerpt)

    def test_local_note_contains_timeline_and_frame_index(self) -> None:
        transcript = TranscriptResult(
            source="unit",
            full_text="函数用于封装逻辑。",
            segments=[TranscriptSegment(start=5, end=8, text="函数用于封装逻辑。")],
        )
        grids = [FrameGrid(path="", url="http://127.0.0.1/grid.jpg", start=0, end=20, frame_count=2, frame_timestamps=[0, 10])]
        note = local_markdown_note("Python lesson", transcript, grids, "https://example.com")
        self.assertIn("# Python lesson", note)
        self.assertIn("00:00:05", note)
        self.assertIn("## 学习上下文", note)
        self.assertIn("课程标题：Python lesson", note)
        self.assertIn("来源页面：https://example.com（example.com）", note)
        self.assertIn("文本来源：unit", note)
        self.assertIn("画面切片：1 个窗口，覆盖 `00:00:00 - 00:00:20`；1/1 个窗口有同步字幕。", note)
        self.assertIn("主题线索：Python lesson；函数用于封装逻辑。", note)
        self.assertIn("用 W 编号回看画面网格", note)
        self.assertIn("## 学习路线", note)
        self.assertIn("优先回看：W001 `00:00:00 - 00:00:20`", note)
        self.assertIn("分段图文摘要", note)
        self.assertIn("视觉切片学习卡", note)
        self.assertIn("回看目标：对照画面确认本段的板书、PPT 切换、代码/界面操作和例题步骤是否被字幕完整覆盖。", note)
        self.assertIn("![W001 00:00:00 - 00:00:20](http://127.0.0.1/grid.jpg)", note.split("## 画面-字幕对齐索引")[0])
        self.assertIn("帧时间：00:00:00, 00:00:10", note.split("## 画面-字幕对齐索引")[0])
        self.assertIn("窗口检查点", note)
        self.assertIn("00:00:05` 函数用于封装逻辑。；对照画面确认对应的板书、PPT、代码或操作步骤。", note)
        self.assertIn("自测问题", note)
        self.assertIn("00:00:05` 这句“函数用于封装逻辑。”在画面中对应的标题、公式、代码或操作状态是什么？", note)
        self.assertIn("画面-字幕对齐索引", note)
        self.assertIn("http://127.0.0.1/grid.jpg", note)
        self.assertIn("W001 `00:00:00 - 00:00:20`", note)
        self.assertIn("![W001 00:00:00 - 00:00:20](http://127.0.0.1/grid.jpg)", note)
        self.assertIn("复习问题", note)

    def test_local_note_uses_note_template_option(self) -> None:
        transcript = TranscriptResult(
            source="unit",
            full_text="question based review",
            segments=[TranscriptSegment(start=1, end=3, text="question based review")],
        )

        note = local_markdown_note("Template lesson", transcript, [], "https://course.example", TaskOptions(note_template="qa"))

        self.assertIn("\u7b14\u8bb0\u683c\u5f0f", note)
        self.assertIn("\u95ee\u7b54\u590d\u4e60\u6a21\u677f", note)

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
        self.assertIn("## 学习路线", note)
        self.assertIn("## 学习上下文", note)
        self.assertIn("画面-字幕对齐索引", note)

    def test_llm_fallback_warning_includes_provider_model_and_error(self) -> None:
        class FakeCompletions:
            def create(self, **kwargs):
                raise RuntimeError("rate limit from provider")

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = types.SimpleNamespace(completions=FakeCompletions())

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI
        transcript = TranscriptResult(
            source="unit",
            full_text="short transcript",
            segments=[TranscriptSegment(start=0, end=4, text="short transcript")],
        )

        with patch.dict(sys.modules, {"openai": fake_openai}):
            note, source, warning = summarize_with_diagnostics(
                "Provider failure",
                transcript,
                [],
                TaskOptions(
                    llm_api_key="test-key",
                    llm_base_url="https://api.groq.com/openai/v1",
                    llm_model="groq-vision-model",
                ),
                "https://course.example",
            )

        self.assertEqual(source, "local-template")
        self.assertIn("provider=groq", warning)
        self.assertIn("model=groq-vision-model", warning)
        self.assertIn("base=api.groq.com", warning)
        self.assertIn("stage=text_summary", warning)
        self.assertIn("code=api_error", warning)
        self.assertIn("rate limit from provider", warning)
        self.assertIn("Provider failure", note)

    def test_visual_appendix_is_appended_to_llm_notes(self) -> None:
        transcript = TranscriptResult(
            source="unit",
            full_text="函数用于封装逻辑。",
            segments=[TranscriptSegment(start=5, end=8, text="函数用于封装逻辑。")],
        )
        grids = [FrameGrid(path="", url="http://127.0.0.1/grid.jpg", start=0, end=20, frame_count=2, frame_timestamps=[0, 10])]

        note = ensure_visual_appendix("# LLM note\n\n模型总结正文。", transcript, grids)

        self.assertIn("# LLM note", note)
        self.assertIn("## 画面切片附录", note)
        self.assertIn("W001 `00:00:00 - 00:00:20`", note)
        self.assertIn("![W001 00:00:00 - 00:00:20](http://127.0.0.1/grid.jpg)", note)
        self.assertIn("帧时间：00:00:00, 00:00:10", note)
        self.assertIn("00:00:05` 函数用于封装逻辑。；对照画面确认对应的板书、PPT、代码或操作步骤。", note)
        self.assertIn("自测问题", note)
        self.assertIn("00:00:05` 这句“函数用于封装逻辑。”在画面中对应的标题、公式、代码或操作状态是什么？", note)

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
        self.assertEqual(diagnostics["vision_batch_size"], MAX_GRIDS_PER_VISION_CALL)
        self.assertEqual(diagnostics["vision_expected_batch_count"], 20)
        self.assertEqual(diagnostics["vision_call_status"], "vision_llm_used")
        self.assertEqual(diagnostics["vision_grid_count"], MAX_VISION_GRIDS)
        self.assertEqual(diagnostics["llm_provider"], "openai")
        self.assertEqual(diagnostics["llm_base_host"], "api.openai.com")
        self.assertEqual(diagnostics["llm_model"], "vision-model")
        self.assertEqual(diagnostics["llm_failure_code"], "")
        self.assertEqual(diagnostics["vision_image_count"], MAX_VISION_GRIDS - 1)
        self.assertEqual(diagnostics["vision_call_plan"][0]["window_ids"], ["W001", "W002", "W003", "W004"])
        self.assertEqual(diagnostics["vision_call_plan"][0]["image_window_ids"], ["W002", "W003", "W004"])
        self.assertEqual(diagnostics["vision_call_plan"][-1]["window_ids"], ["W077", "W078", "W079", "W080"])
        self.assertEqual(diagnostics["vision_window_ids"][0], "W001")
        self.assertNotIn("W001", diagnostics["vision_image_window_ids"])
        self.assertIn("W001", diagnostics["missing_vision_image_window_ids"])
        self.assertEqual(diagnostics["omitted_vision_window_ids"], ["W081", "W082", "W083"])
        self.assertEqual(diagnostics["omitted_frame_grid_count"], 3)
        self.assertFalse(diagnostics["all_sent_grids_had_images"])
        self.assertFalse(diagnostics["all_grids_had_images"])

        task = create_task("local", "Long lesson", "https://course.example")
        try:
            record = get_task(task.id)
            record.summary_diagnostics = diagnostics
            report = render_diagnostics_markdown(record)
            self.assertIn("vision_llm_used", report)
            self.assertIn("LLM Provider", report)
            self.assertIn("api.openai.com", report)
            self.assertIn("20", report)
            self.assertIn("已送入视觉窗口", report)
            self.assertIn("缺少图片窗口：W001", report)
            self.assertIn("超限省略窗口：W081, W082, W083", report)
        finally:
            shutil.rmtree(task_dir(task.id), ignore_errors=True)

    def test_summary_diagnostics_classifies_openai_compatible_failure(self) -> None:
        warning = (
            "LLM 调用降级：provider=openrouter，model=openai/gpt-4.1-mini，base=openrouter.ai，"
            "stage=vision_merge，code=api_error，reason=HTTP 429；已使用本地画面索引模板。"
        )
        diagnostics = build_summary_diagnostics(
            "task-llm-fail",
            "Provider failure",
            "https://course.example",
            TaskOptions(
                visual_understanding=True,
                llm_api_key="test-key",
                llm_base_url="https://openrouter.ai/api/v1",
                llm_model="openai/gpt-4.1-mini",
            ),
            [],
            [],
            "local-template",
            warning,
        )

        self.assertEqual(diagnostics["llm_provider"], "openrouter")
        self.assertEqual(diagnostics["llm_base_host"], "openrouter.ai")
        self.assertEqual(diagnostics["llm_model"], "openai/gpt-4.1-mini")
        self.assertEqual(diagnostics["llm_failure_stage"], "vision_merge")
        self.assertEqual(diagnostics["llm_failure_code"], "api_error")
        self.assertEqual(diagnostics["llm_failure_reason"], "HTTP 429")
        self.assertEqual(diagnostics["vision_call_status"], "no_frame_grids")

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
                note, source = summarize_with_llm("Long lesson", transcript, grids, TaskOptions(llm_api_key="test-key", note_template="cornell"), "https://course.example")

        self.assertEqual(source, "vision-llm")
        self.assertTrue(note.startswith("merged note"))
        self.assertIn("## 画面切片附录", note)
        self.assertIn("W001 `00:00:00 - 00:03:00`", note)
        self.assertIn("![W001 00:00:00 - 00:03:00](http://127.0.0.1/grid_0.jpg)", note)
        self.assertIn("W009 `00:24:00 - 00:27:00`", note)
        self.assertIn("segment 8", note)
        self.assertEqual(len(completions.calls), 4)
        vision_image_counts = [
            len([item for item in call["messages"][0]["content"] if item.get("type") == "image_url"])
            for call in completions.calls[:3]
        ]
        self.assertEqual(vision_image_counts, [4, 4, 1])
        first_prompt = completions.calls[0]["messages"][0]["content"][0]["text"]
        self.assertIn("窗口 W001", first_prompt)
        self.assertIn("http://127.0.0.1/grid_0.jpg", first_prompt)
        self.assertIn("同编号标注的画面网格", first_prompt)
        first_content = completions.calls[0]["messages"][0]["content"]
        self.assertEqual(first_content[1]["type"], "text")
        self.assertIn("下面这张画面网格对应窗口 W001", first_content[1]["text"])
        self.assertEqual(first_content[2]["type"], "image_url")
        self.assertEqual(first_content[3]["type"], "text")
        self.assertIn("下面这张画面网格对应窗口 W002", first_content[3]["text"])
        self.assertEqual(first_content[4]["type"], "image_url")
        merge_content = completions.calls[3]["messages"][0]["content"]
        self.assertIn("画面索引清单", merge_content)
        self.assertIn("cornell", merge_content)
        self.assertIn("\u5eb7\u5948\u5c14\u6a21\u677f", merge_content)
        self.assertIn("W001 `00:00:00 - 00:03:00`", merge_content)
        self.assertIn("W009 `00:24:00 - 00:27:00`", merge_content)
        self.assertIn("http://127.0.0.1/grid_8.jpg", merge_content)
        self.assertIn("partial with 4 images", completions.calls[3]["messages"][0]["content"])
        self.assertIn("partial with 1 images", completions.calls[3]["messages"][0]["content"])

    def test_llm_summary_keeps_successful_vision_batches_when_one_batch_fails(self) -> None:
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
                self.vision_calls = 0

            def create(self, **kwargs):
                self.calls.append(kwargs)
                content = kwargs["messages"][0]["content"]
                if isinstance(content, list):
                    self.vision_calls += 1
                    images = [item for item in content if item.get("type") == "image_url"]
                    if self.vision_calls == 2:
                        raise RuntimeError("rate limit")
                    return Response(f"partial {self.vision_calls} with {len(images)} images")
                return Response("merged partial note")

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
                grids.append(
                    FrameGrid(
                        path=str(image),
                        url=f"http://127.0.0.1/grid_{index}.jpg",
                        start=index * 180,
                        end=(index + 1) * 180,
                        frame_count=9,
                    )
                )
            transcript = TranscriptResult(
                full_text="all transcript",
                segments=[TranscriptSegment(start=index * 180, end=index * 180 + 30, text=f"segment {index}") for index in range(9)],
            )
            with patch.dict(sys.modules, {"openai": fake_openai}):
                note, source = summarize_with_llm(
                    "Long lesson",
                    transcript,
                    grids,
                    TaskOptions(llm_api_key="test-key"),
                    "https://course.example",
                )

        self.assertEqual(source, "vision-llm")
        self.assertTrue(note.startswith("merged partial note"))
        self.assertEqual(len(completions.calls), 4)
        merge_content = completions.calls[3]["messages"][0]["content"]
        self.assertIn("Vision batch warning", merge_content)
        self.assertIn("1 vision batch(es) failed", merge_content)
        self.assertIn("partial 1 with 4 images", merge_content)
        self.assertIn("partial 3 with 1 images", merge_content)
        self.assertIn("W005 `00:12:00 - 00:15:00`", note)
        self.assertIn("W009 `00:24:00 - 00:27:00`", note)
        self.assertIn("http://127.0.0.1/grid_4.jpg", note)
        self.assertIn("segment 8", note)

    def test_llm_summary_reports_text_source_when_grid_images_are_missing(self) -> None:
        from app.summarizer import summarize_with_diagnostics

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
                return Response("# Text fallback note\n\nfrom transcript only")

        completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = types.SimpleNamespace(completions=completions)

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI

        transcript = TranscriptResult(
            full_text="all transcript",
            segments=[TranscriptSegment(start=0, end=30, text="segment 0")],
        )
        grids = [
            FrameGrid(
                path=str(TEST_RUN_DIR / "missing-grid.jpg"),
                url="http://127.0.0.1/missing-grid.jpg",
                start=0,
                end=180,
                frame_count=9,
            )
        ]

        with patch.dict(sys.modules, {"openai": fake_openai}):
            note, source, warning = summarize_with_diagnostics(
                "Missing image lesson",
                transcript,
                grids,
                TaskOptions(llm_api_key="test-key", visual_understanding=True),
                "https://course.example",
            )

        self.assertEqual(source, "text-llm")
        self.assertEqual(warning, "")
        self.assertIn("# Text fallback note", note)
        self.assertEqual(len(completions.calls), 1)
        content = completions.calls[0]["messages"][0]["content"]
        self.assertFalse(any(item.get("type") == "image_url" for item in content))


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
