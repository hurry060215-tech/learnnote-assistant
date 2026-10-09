"""Offline-only credential destination regressions using dummy reserved URLs."""
from __future__ import annotations

from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

import requests
import yt_dlp

from app import downloader as d, media_source_context as context, media_transport as transport
from app.media_candidate_ranking import _attach_companion_audio_resources
from app.media_url_parsing import _url_origin, same_http_origin
from app.models import BrowserCookie, MediaPreflightResult, ResourceCandidate

A = "https://media-a.invalid"
B = "https://page-b.invalid"
C = "https://frame-c.invalid"
AUTH = "Bearer SENTINEL_ORIGIN_A_ONLY"
VIDEO = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42" + bytes(8192)


def candidate(**overrides):
    values = dict(url=A + "/private.mp4", source="webRequest", kind="video", mime="video/mp4",
                  request_headers={"authorization": AUTH, "User-Agent": "Sentinel Browser", "Cookie": "IGNORE_SENTINEL"},
                  page_url=B + "/lesson", frame_url=B + "/lesson", is_main_video=True, score=100)
    values.update(overrides)
    return ResourceCandidate(**values)


class Response:
    def __init__(self, url, status=403, body=b"", kind="text/plain"):
        self.url = url
        self.status_code = status
        self.headers = {"content-type": kind, "content-length": str(len(body))}
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, **kwargs):
        if self.body:
            yield self.body


class AuthorizationScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="learnnote-header-scope-")
        self.addCleanup(self.temp.cleanup)
        self.engine = d.MediaDownloader(Path(self.temp.name))

    def test_strict_origin_equivalence_and_invalid_inputs(self):
        for left, right in ((A, A + ":443/clip"), (A.upper(), A), (A + "/one", A + "/two"),
                            ("https://b\u00fccher.invalid", "https://xn--bcher-kva.invalid")):
            with self.subTest(left=left, right=right):
                self.assertTrue(same_http_origin(left, right))
        self.assertFalse(same_http_origin("https://faß.invalid", "https://fass.invalid"))
        self.assertFalse(same_http_origin(A + ".", A))
        self.assertIsNone(_url_origin(A + "."))
        for url in (B, A + ".", A + ":444", A.replace("https:", "http:"), "", "/clip", "blob:" + A,
                    "https://", "https://[invalid", A + ":bad", A + ":65536", A + ":0",
                    "https://user@media-a.invalid", "https://media-a.invalid\\@page-b.invalid",
                    "https://bad_host.invalid", "https://media-a.invalid/\nclip", "https://%61.invalid"):
            with self.subTest(url=url):
                self.assertFalse(same_http_origin(A, url))
                headers = context.browser_request_headers_for_candidate(candidate(), url)
                self.assertNotIn("Authorization", headers)
                self.assertEqual(headers["User-Agent"], "Sentinel Browser")
        for url in ("", "https://", "https://[invalid", "https://bad_host.invalid"):
            self.assertIsNone(_url_origin(url))
            self.assertNotIn("Authorization", context.browser_request_headers_for_candidate(candidate(url=url)))

    def test_same_origin_direct_replay_and_cookie_scope(self):
        original = candidate()
        before = original.request_headers.copy()
        cookies = [BrowserCookie(name="session", value="SENTINEL_COOKIE_A", domain="media-a.invalid", path="/", secure=True)]
        captures = []

        def http(method, url, **kwargs):
            captures.append((url, kwargs["headers"]))
            return Response(url, 200, VIDEO, "video/mp4")

        with patch.object(d, "request_media", http):
            path, _ = self.engine.download(B + "/lesson", [original], cookies, "Sentinel")
        self.assertEqual(path.read_bytes(), VIDEO)
        self.assertEqual(captures[0][1]["Authorization"], AUTH)
        self.assertEqual(captures[0][1]["Cookie"], "session=SENTINEL_COOKIE_A")
        self.assertEqual(original.request_headers, before)
        diagnostics = json.dumps([attempt.model_dump(mode="json") for attempt in self.engine.attempts])
        self.assertNotIn(AUTH, diagnostics)
        self.assertNotIn("SENTINEL_COOKIE_A", diagnostics)
        other = d.download_headers_for_candidate(original, cookies, B, url=B + "/clip")
        self.assertNotIn("Authorization", other)
        self.assertNotIn("Cookie", other)
        self.assertEqual(other["User-Agent"], "Sentinel Browser")

    def test_full_download_api_and_cli_fallbacks_omit_global_authorization(self):
        for cli in (False, True):
            with self.subTest(cli=cli):
                captures = []
                engine = d.MediaDownloader(Path(self.temp.name) / str(cli))

                class YoutubeDL:
                    def __init__(self, opts):
                        self.opts = opts

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        pass

                    def extract_info(self, url, download):
                        captures.append((url, self.opts["http_headers"]))
                        if url != B + "/lesson":
                            raise RuntimeError("Unsupported URL")
                        (engine.download_dir / "sentinel.mp4").write_bytes(VIDEO)
                        return {"title": "Sentinel"}

                def run(cmd, **kwargs):
                    headers = dict(part.split(": ", 1) for index, part in enumerate(cmd) if index and cmd[index - 1] == "--add-header")
                    captures.append((cmd[-1], headers))
                    if cmd[-1] != B + "/lesson":
                        return SimpleNamespace(returncode=1, stderr="Unsupported URL", stdout="")
                    (engine.download_dir / "sentinel.mp4").write_bytes(VIDEO)
                    return SimpleNamespace(returncode=0, stderr="", stdout="")

                with ExitStack() as stack:
                    stack.enter_context(patch.object(d, "request_media", side_effect=lambda method, url, **kwargs: Response(url)))
                    stack.enter_context(patch.object(d, "ffmpeg_bin", return_value=None))
                    stack.enter_context(patch.object(d, "_should_run_ytdlp_cli", return_value=cli))
                    stack.enter_context(patch.object(yt_dlp, "YoutubeDL", YoutubeDL))
                    stack.enter_context(patch.object(d.subprocess, "run", run))
                    path, _ = engine.download(B + "/lesson", [candidate()], [], "Sentinel")
                self.assertTrue(path.is_file())
                self.assertEqual([url for url, _ in captures], [A + "/private.mp4", B + "/lesson"])
                for _, headers in captures:
                    self.assertNotIn("Authorization", headers)
                    self.assertEqual(headers["User-Agent"], "Sentinel Browser")

    def test_subtitle_probe_and_download_omit_global_authorization(self):
        captures = []
        engine = self.engine

        class YoutubeDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def extract_info(self, url, download):
                captures.append((url, download, self.opts["http_headers"]))
                if download:
                    (engine.download_dir / "sentinel.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nSynthetic caption.\n")
                return {"subtitles": {"en": [{"ext": "vtt"}]}}

        with patch.object(yt_dlp, "YoutubeDL", YoutubeDL), patch.object(d, "ffmpeg_bin", return_value=None):
            path = engine.download_subtitle([candidate()], [], B + "/lesson", "Sentinel")
        self.assertTrue(path.is_file())
        self.assertEqual([download for _, download, _ in captures], [False, True])
        for url, _, headers in captures:
            self.assertEqual(url, B + "/lesson")
            self.assertNotIn("Authorization", headers)

    def run_failed_download(self, resource, http):
        with patch.object(d, "request_media", http), patch.object(d.MediaDownloader, "_download_with_ytdlp", side_effect=d.DownloadError("no_media_found", "Synthetic unsupported")):
            with self.assertRaises(d.DownloadError):
                self.engine.download(B + "/lesson", [resource], [], "Sentinel")

    def test_full_download_frame_page_and_pre_resolved_targets(self):
        for resource, target in ((candidate(frame_url=C + "/embed"), C + "/embed"),
                                 (candidate(resolved_url=C + "/final.mp4"), C + "/final.mp4")):
            calls = []

            def http(method, url, **kwargs):
                calls.append((url, kwargs["headers"]))
                return Response(url)

            with self.subTest(target=target):
                before = resource.request_headers.copy()
                self.run_failed_download(resource, http)
                found = [headers for url, headers in calls if url == target]
                self.assertTrue(found)
                self.assertTrue(all("Authorization" not in headers for headers in found))
                self.assertEqual(resource.request_headers, before)

    def test_full_download_page_discovered_cross_origin_media(self):
        calls = []

        def http(method, url, **kwargs):
            calls.append((url, kwargs["headers"]))
            if url == A + "/player":
                return Response(url, 200, json.dumps({"videoUrl": C + "/clip.mp4"}).encode(), "application/json")
            return Response(url)

        self.run_failed_download(candidate(frame_url=A + "/player"), http)
        self.assertEqual(next(headers for url, headers in calls if url == A + "/player")["Authorization"], AUTH)
        found = [headers for url, headers in calls if url == C + "/clip.mp4"]
        self.assertTrue(found)
        self.assertTrue(all("Authorization" not in headers for headers in found))

    def test_embedded_response_and_manifest_candidates_keep_original_scope(self):
        parent = candidate()
        before = parent.model_dump()
        body = json.dumps({"sources": [A + "/same.mp4", C + "/other.m3u8"]}).encode()
        children = d._embedded_media_candidates_from_text_response(parent, body, A + "/player", B, "application/json")
        self.assertEqual(len(children), 2)
        for item in children:
            self.assertEqual("Authorization" in item.request_headers, item.url.startswith(A + "/"))
        self.assertEqual(parent.model_dump(), before)
        for origin in (A, C):
            response = Response(origin + "/manifest.m3u8", 200, b"#EXTM3U\n#EXTINF:1\npart.ts\n", "application/vnd.apple.mpegurl")
            with patch.object(d, "request_media", return_value=response):
                children = self.engine._discover_page_resources(origin + "/manifest.m3u8", [], parent)
            manifest = next(item for item in children if item.url == response.url)
            self.assertEqual("Authorization" in manifest.request_headers, origin == A)

    def test_audio_pairing_does_not_reattribute_another_origin(self):
        for audio_url in (A + "/audio.m4a", C + "/audio.m4a", A + ":444/audio.m4a", A.replace("https", "http") + "/audio.m4a"):
            video = candidate(request_headers={"User-Agent": "Sentinel Browser"}, frame_id=1, tab_id=2, playback_match="same-frame")
            audio = candidate(url=audio_url, kind="audio", mime="audio/mp4", frame_id=1, tab_id=2, playback_match="same-frame")
            before = [item.model_dump() for item in (video, audio)]
            merged = _attach_companion_audio_resources([video, audio])[0]
            self.assertEqual(merged.audio_url, audio_url)
            self.assertEqual("authorization" in merged.request_headers, same_http_origin(video.url, audio.url))
            self.assertEqual([item.model_dump() for item in (video, audio)], before)

    def test_companion_audio_preflight_uses_original_video_origin(self):
        for audio_url in (A + "/audio.m4a", C + "/audio.m4a"):
            resource = candidate(audio_url=audio_url)
            captures = []

            def response(method, url, **kwargs):
                captures.append(kwargs["headers"])
                return Response(url, 403)

            with patch.object(d, "_open_validated_media_response", response):
                d._preflight_companion_audio(resource, [], B, 1, MediaPreflightResult(ok=True, downloadable=True, kind="video", url=resource.url))
            self.assertEqual("Authorization" in captures[0], same_http_origin(resource.url, audio_url))

    def test_ffmpeg_manifest_and_paired_inputs_have_no_unscoped_credentials(self):
        cookies = [BrowserCookie(name="session", value="SENTINEL_COOKIE_A", domain="media-a.invalid", path="/lesson", secure=True)]
        manifests = {
            "hls": (b"#EXTM3U\n#EXTINF:1\nhttps://frame-c.invalid/part.ts\n", "application/vnd.apple.mpegurl", ".m3u8"),
            "dash": (b'<MPD><Period><AdaptationSet><Representation><BaseURL>https://frame-c.invalid/</BaseURL></Representation></AdaptationSet></Period></MPD>', "application/dash+xml", ".mpd"),
        }
        for kind, (body, mime, suffix) in manifests.items():
            for replay in (False, True):
                resource = candidate(url=A + "/lesson/manifest" + suffix, kind=kind, mime=mime,
                                     method="POST" if replay else "GET", request_body={"content": "sentinel=1"} if replay else {})
                commands, http_headers = [], []

                def http(method, url, **kwargs):
                    http_headers.append(kwargs["headers"])
                    return Response(url, 200, body, mime)

                def run(cmd, **kwargs):
                    commands.append(cmd)
                    Path(cmd[-1]).write_bytes(VIDEO)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

                with patch.object(d, "request_media", http), patch.object(d, "ffmpeg_bin", return_value="sentinel-ffmpeg"), patch.object(d.subprocess, "run", run):
                    self.engine._download_manifest(resource, cookies, B, "Sentinel")
                self.assertEqual(http_headers[0]["Authorization"], AUTH)
                self.assertNotIn(AUTH, " ".join(commands[0]))
                self.assertIn("-cookies", commands[0])
                self.assertIn("domain=media-a.invalid; path=/lesson; secure", " ".join(commands[0]))
                header_values = [commands[0][i + 1] for i, value in enumerate(commands[0]) if value == "-headers"]
                self.assertTrue(all("Cookie:" not in value and "Authorization:" not in value for value in header_values))
        commands = []
        with patch.object(d, "ffmpeg_bin", return_value="sentinel-ffmpeg"), patch.object(d.subprocess, "run", run):
            self.engine._download_file_with_audio(candidate(audio_url=C + "/audio.m4a"), cookies, B, "Sentinel")
        cmd = commands[0]
        self.assertNotIn(AUTH, " ".join(cmd))
        self.assertEqual(cmd.count("-cookies"), 2)
        self.assertTrue(all("Cookie:" not in cmd[i + 1] for i, value in enumerate(cmd) if value == "-headers"))

    def test_requests_redirects_strip_on_every_origin_change(self):
        initial = "http://media-a.invalid/clip"
        targets = [(initial + "?next=1", True), ("http://media-a.invalid:80/next", True),
                   (A + "/next", False), ("http://media-a.invalid:81/next", False), (C + "/next", False)]
        for target, retained in targets:
            captures = []
            session = transport._OriginScopedSession()
            session.trust_env = False

            def send(adapter, request, **kwargs):
                captures.append((request.url, dict(request.headers)))
                response = requests.Response()
                response.status_code = 302 if len(captures) == 1 else 200
                response.url = request.url
                response.request = request
                response.raw = io.BytesIO(b"")
                response._content = b""
                if len(captures) == 1:
                    response.headers["Location"] = target
                return response

            with patch.object(transport, "_OriginScopedSession", return_value=session), patch.object(requests.adapters.HTTPAdapter, "send", send):
                transport.request_media("GET", initial, headers={"Authorization": AUTH}, timeout=1)
            self.assertEqual(len(captures), 2)
            self.assertEqual("Authorization" in captures[1][1], retained, target)

    def test_pinned_preflight_redirect_control(self):
        for target in (A + "/next", C + "/next", A + ":444/next", A.replace("https", "http") + "/next"):
            captures = []

            class RawResponse:
                def __init__(self, status, headers):
                    self.status, self.headers = status, headers

                def getheaders(self):
                    return self.headers

                def close(self):
                    pass

            class Connection:
                def __init__(self, *args, **kwargs):
                    pass

                def request(self, method, path, **kwargs):
                    captures.append(kwargs["headers"])

                def getresponse(self):
                    return RawResponse(302, [("Location", target)]) if len(captures) == 1 else RawResponse(200, [])

                def close(self):
                    pass

            def validate(url, trusted):
                parsed = urlparse(url)
                return url, "192.0.2.1", parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)

            with patch.object(transport, "_validated_media_target", validate), patch.object(transport, "_PinnedHTTPSConnection", Connection), patch.object(transport.http.client, "HTTPConnection", Connection):
                with transport.open_validated_media_response("GET", A + "/start", trusted_page_url=A, headers={"Authorization": AUTH, "Cookie": "SENTINEL_COOKIE_A", "Origin": A}, body=None, timeout=1):
                    pass
            for name in ("Authorization", "Cookie", "Origin"):
                self.assertEqual(name in captures[1], same_http_origin(A, target))


if __name__ == "__main__":
    unittest.main()
