"""Pre-#143 synthetic snapshots, with #269 global credential removal applied."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from app import downloader, media_source_context as source_context
from app.models import ResourceCandidate

FIXTURE = Path(__file__).parent / "fixtures" / "downloader_source_context_v1.json"


def source_context_snapshot(module):
    """Capture existing decisions, candidate identity and mutation, without I/O."""
    fragments = [
        "https://cdn.example.test/course/master.m3u8/part.ts?fixture=one#part",
        "https://cdn.example.test/course/manifest.MPD/part.m4s;ignored?fixture=two#part",
        "https://cdn.example.test/course/720p/part.ts?fixture=three#part",
        "https://cdn.example.test/course/video/part.m4s?fixture=four",
        "https://cdn.example.test/segments/part.ts",
        "https://cdn.example.test/course/not-a-segment.mp4",
        "https://cdn.example.test/course/master.m3u8",
        "http://[invalid",
        "",
    ]
    resources = [
        ResourceCandidate(
            url="https://course.example.test/api/play", request_type="fetch", score=95,
            frame_url="https://player.example.test/embed", page_url="https://course.example.test/top",
            request_headers={"Referer": "https://course.example.test/referer", "User-Agent": "secondary", "Origin": "https://course.example.test"},
        ),
        ResourceCandidate(
            url="https://cdn.example.test/video.mp4", kind="video", score=40, is_main_video=True,
            frame_url="https://player.example.test/embed", page_url="https://course.example.test/top",
            request_headers={"Referer": "https://player.example.test/referer", "user-agent": " primary\r\nagent ", "accept": " video/* ", "Cookie": "synthetic=ignored", "Range": "bytes=1-", "Host": "ignored.example.test", "X-Unknown": "ignored", "Authorization": "Bearer synthetic", "accept-language": " "},
            initiator="https://player.example.test",
        ),
        ResourceCandidate(url="https://course.example.test/frame", source="dom", label="iframe", score=20,
                          frame_url="blob:ignored", request_headers={"referer": "https://ignored.example.test/case"}),
        ResourceCandidate(url="https://course.example.test/no-evidence", frame_url="data:text/plain,ignored"),
    ]
    before = [item.model_dump(mode="json") for item in resources]
    contexts = module.fallback_page_contexts(" https://course.example.test/top ", resources)
    context_rows = [[url, next((index for index, item in enumerate(resources) if item is candidate), None)] for url, candidate in contexts]
    header_rows = [module.browser_request_headers_for_candidate(item) for item in [None, *resources]]
    merged_headers = module.ytdlp_headers_from_browser_context("https://course.example.test/top", resources)

    fragment = ResourceCandidate(
        url="https://cdn.example.test/course/master.m3u8/part.ts?fixture=one", kind="fragment", score=12,
        source="webRequest", page_url="https://course.example.test/top", frame_id=3, tab_id=7,
        request_headers={"Referer": "https://course.example.test/top"},
    )
    blob = ResourceCandidate(url="blob:https://course.example.test/player", kind="blob")
    unrelated = ResourceCandidate(url="https://cdn.example.test/course/chunk.m4s", kind="fragment", source="webRequest")
    matched = unrelated.model_copy(update={"playback_match": "blob-source"})
    enriched = {}
    for name, items in (("nested", [fragment]), ("duplicate", [fragment, fragment.model_copy()]),
                        ("unrelated_blob", [blob, unrelated]), ("matched_blob", [blob, matched])):
        original = [item.model_dump(mode="json") for item in items]
        values = module.enrich_with_inferred_manifest_resources(items)
        enriched[name] = {
            "candidates": [item.model_dump(mode="json", exclude_defaults=True) for item in values],
            "input_unchanged": [item.model_dump(mode="json") for item in items] == original,
            "original_identity": [values[index] is item for index, item in enumerate(items)],
        }
    base = ResourceCandidate(url="https://cdn.example.test/lesson.mp4", source="page-frame-scan",
                             page_url="https://course.example.test/top", frame_url="https://unrelated.example.test/embed")
    trust_cases = [
        base, base.model_copy(update={"user_selected": True}), base.model_copy(update={"is_main_video": True}),
        base.model_copy(update={"playback_match": "same-frame"}), base.model_copy(update={"source": "webRequest"}),
        base.model_copy(update={"frame_url": "https://video.course.example.test/embed"}),
        base.model_copy(update={"frame_url": "", "request_headers": {"Referer": "https://unrelated.example.test/embed"}}),
        base.model_copy(update={"frame_url": "", "request_headers": {"referer": "https://unrelated.example.test/embed"}}),
        base.model_copy(update={"frame_url": "https://course.example.test/banner/embed"}),
        base.model_copy(update={"frame_url": "", "page_url": ""}),
    ]
    ranked = module.rank_media_candidates([
        base.model_copy(), base.model_copy(update={"url": "https://cdn.example.test/chosen.mp4", "user_selected": True}),
        ResourceCandidate(url="https://cdn.example.test/lesson.mp4", kind="video", source="webRequest", score=20),
        ResourceCandidate(url="https://cdn.example.test/lesson.mp4", kind="video", source="activeVideo", is_main_video=True),
        ResourceCandidate(url="data:video/mp4,ignored", kind="video"),
    ])
    return {
        "manifest_urls": [[value, module.infer_manifest_url_from_fragment(value), module.infer_sibling_manifest_urls_from_fragment(value)] for value in fragments],
        "fallback_contexts": context_rows,
        "fallback_urls": module.fallback_page_urls(" https://course.example.test/top ", resources),
        "scannable": [module._is_scannable_play_endpoint(item) for item in resources],
        "request_headers": header_rows,
        "ytdlp_headers": merged_headers,
        "context_input_unchanged": [item.model_dump(mode="json") for item in resources] == before,
        "enriched": enriched,
        "untrusted": [bool(module._is_untrusted_page_scan_candidate(item)) for item in trust_cases],
        "ranked": [item.model_dump(mode="json", exclude_defaults=True) for item in ranked],
    }


class SourceContextSnapshotTests(unittest.TestCase):
    def test_source_decisions_match_pre_split_golden(self):
        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(source_context_snapshot(source_context), expected)
        self.assertEqual(source_context_snapshot(downloader), expected)

    def test_downloader_keeps_original_function_and_constant_exports(self):
        names = (
            "FRAGMENT_EXT_RE", "BROWSER_REQUEST_HEADER_ALLOWLIST", "YTDLP_HTTP_HEADER_ORDER",
            "REQUEST_BODY_REPLAY_METHODS", "PAGE_SCAN_SOURCE_PREFIXES", "NON_PRIMARY_FRAME_RE",
            "infer_manifest_url_from_fragment", "infer_sibling_manifest_urls_from_fragment",
            "_safe_header_value", "browser_request_headers_for_candidate", "ytdlp_headers_from_browser_context",
            "_is_scannable_play_endpoint", "fallback_page_contexts", "fallback_page_urls",
            "enrich_with_inferred_manifest_resources", "rank_media_candidates", "_same_site_host",
            "_is_untrusted_page_scan_candidate",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertIs(getattr(downloader, name), getattr(source_context, name))

    def test_source_helpers_import_without_transport_api_or_storage(self):
        script = (
            "import sys; from app import media_source_context; "
            "assert not {'app.main', 'app.downloader', 'app.processor', 'app.storage', "
            "'app.media_transport', 'app.runtime', 'requests', 'yt_dlp'} & sys.modules.keys()"
        )
        subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)

    def test_enrichment_deep_copies_inherited_request_evidence(self):
        candidate = ResourceCandidate(url="https://cdn.example.test/stream/master.m3u8/part.ts", kind="fragment",
                                      request_headers={"Referer": "https://course.example.test/top"},
                                      request_body={"content": "synthetic=1"})
        original = candidate.model_dump(mode="json")
        inferred = source_context.enrich_with_inferred_manifest_resources([candidate])[1]
        inferred.request_headers["Referer"] = "https://other.example.test/"
        inferred.request_body["content"] = "changed"
        self.assertEqual(candidate.model_dump(mode="json"), original)
        self.assertNotEqual(inferred.url, candidate.url)

    def test_scannable_endpoint_requires_http_unknown_kind_and_play_evidence(self):
        cases = [
            ({"url": "https://course.example.test/api/play", "method": "POST", "request_body": {"content": "x=1"}}, True),
            ({"url": "https://course.example.test/api/play", "method": "GET"}, False),
            ({"url": "https://course.example.test/api/play", "source": "pageHookFetch"}, True),
            ({"url": "https://course.example.test/api/play", "label": "player endpoint"}, True),
            ({"url": "https://course.example.test/plain", "request_type": "fetch"}, False),
            ({"url": "https://course.example.test/video.mp4", "request_type": "fetch"}, False),
            ({"url": "blob:https://course.example.test/api/play", "request_type": "fetch"}, False),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                self.assertEqual(source_context._is_scannable_play_endpoint(ResourceCandidate(**fields)), expected)

    def test_missing_hosts_and_label_boundary_keep_existing_trust_policy(self):
        self.assertTrue(source_context._same_site_host("", "https://course.example.test"))
        self.assertTrue(source_context._same_site_host("https://course.example.test.", "https://video.course.example.test"))
        self.assertFalse(source_context._same_site_host("https://badcourse.example.test", "https://course.example.test"))
        base = ResourceCandidate(url="https://cdn.example.test/lesson.mp4", source="page-scan")
        self.assertFalse(source_context._is_untrusted_page_scan_candidate(base.model_copy(update={"label": "adaptive lesson"})))
        self.assertTrue(source_context._is_untrusted_page_scan_candidate(base.model_copy(update={"label": "ad/lesson"})))

    def test_empty_inputs_keep_explicit_fallbacks(self):
        self.assertEqual(source_context.fallback_page_contexts("blob:fixture", []), [])
        self.assertEqual(source_context.ytdlp_headers_from_browser_context("", []), {})
        self.assertEqual(source_context.ytdlp_headers_from_browser_context(" https://course.example.test/ ", []),
                         {"Referer": "https://course.example.test/"})
        self.assertEqual(source_context.enrich_with_inferred_manifest_resources([]), [])
        self.assertEqual(source_context.rank_media_candidates([]), [])


if __name__ == "__main__":
    unittest.main()
