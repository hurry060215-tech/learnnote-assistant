"""Interpret supplied browser media evidence without transport or persistence.

Fallbacks retain the original candidate identity; inferred candidates are deep
copies. Ranking keeps the existing candidate normalization and score updates.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from .models import ResourceCandidate
from .media_kinds import classify_resource, effective_resource_kind
from .media_candidate_ranking import (
    rank_enriched_candidates,
    score_candidate,
    should_guess_sibling_manifest_with_blob_boundary,
)
from .media_url_parsing import _is_http_url, _media_endpoint_hint


FRAGMENT_EXT_RE = re.compile(r"\.(m4s|ts)(\?|#|$)", re.I)


BROWSER_REQUEST_HEADER_ALLOWLIST = {
    "accept": "Accept",
    "accept-language": "Accept-Language",
    "authorization": "Authorization",
    "content-type": "Content-Type",
    "origin": "Origin",
    "referer": "Referer",
    "sec-ch-ua": "Sec-CH-UA",
    "sec-ch-ua-mobile": "Sec-CH-UA-Mobile",
    "sec-ch-ua-platform": "Sec-CH-UA-Platform",
    "sec-fetch-dest": "Sec-Fetch-Dest",
    "sec-fetch-mode": "Sec-Fetch-Mode",
    "sec-fetch-site": "Sec-Fetch-Site",
    "user-agent": "User-Agent",
    "x-requested-with": "X-Requested-With",
}


YTDLP_HTTP_HEADER_ORDER = (
    "User-Agent",
    "Accept-Language",
    "Origin",
    "Referer",
    "Accept",
    "Sec-CH-UA",
    "Sec-CH-UA-Mobile",
    "Sec-CH-UA-Platform",
    "Sec-Fetch-Dest",
    "Sec-Fetch-Mode",
    "Sec-Fetch-Site",
    "X-Requested-With",
    "Authorization",
)


REQUEST_BODY_REPLAY_METHODS = {"POST", "PUT", "PATCH"}


PAGE_SCAN_SOURCE_PREFIXES = ("page-scan", "page-frame-scan")


NON_PRIMARY_FRAME_RE = re.compile(
    r"(^|[./?&=_-])(ad|ads|advert|advertisement|banner|campaign|promo|promotion|activity|event|blackboard|era)([./?&=_-]|$)",
    re.I,
)


def infer_manifest_url_from_fragment(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    path = parsed.path or ""
    lowered = path.lower()
    for ext in (".m3u8", ".mpd"):
        index = lowered.find(ext)
        if index < 0:
            continue
        manifest_path = path[: index + len(ext)]
        if manifest_path == path:
            return ""
        return urlunparse(parsed._replace(path=manifest_path, params="", fragment=""))
    return ""


def infer_sibling_manifest_urls_from_fragment(url: str) -> list[str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return []
    path = parsed.path or ""
    lowered = path.lower()
    if not FRAGMENT_EXT_RE.search(path) or ".m3u8" in lowered or ".mpd" in lowered:
        return []
    slash = path.rfind("/")
    directory = path[: slash + 1] if slash >= 0 else "/"
    names = (
        ("index.m3u8", "playlist.m3u8", "master.m3u8")
        if lowered.endswith(".ts")
        else ("manifest.mpd", "index.mpd", "master.m3u8", "index.m3u8")
    )

    directories = [directory]
    parent = directory.rstrip("/")
    parent_name = parent.rsplit("/", 1)[-1].lower()
    parent_directory = parent.rsplit("/", 1)[0] + "/" if "/" in parent else "/"
    if (
        parent_directory not in directories
        and parent_directory != "/"
        and re.search(r"^(segments?|chunks?|fragments?|video|audio|v\d+|\d{3,4}p|[a-z]{2,4}_?\d{3,4}p|avc|h26[45]|dash|hls)$", parent_name)
    ):
        directories.append(parent_directory)

    results: list[str] = []
    for candidate_directory in directories:
        for name in names:
            guessed = urlunparse(parsed._replace(path=f"{candidate_directory}{name}", params="", fragment=""))
            if guessed not in results:
                results.append(guessed)
    return results


def _safe_header_value(value: object) -> str:
    return re.sub(r"[\r\n]+", " ", str(value or "")).strip()


def browser_request_headers_for_candidate(candidate: ResourceCandidate | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in (candidate.request_headers if candidate else {}).items():
        lower = str(name).lower()
        canonical = BROWSER_REQUEST_HEADER_ALLOWLIST.get(lower)
        if not canonical:
            continue
        cleaned = _safe_header_value(value)
        if cleaned:
            headers[canonical] = cleaned
    return headers


def ytdlp_headers_from_browser_context(page_url: str, resources: list[ResourceCandidate]) -> dict[str, str]:
    headers: dict[str, str] = {}
    ordered = sorted(
        resources,
        key=lambda item: (
            1 if item.is_main_video else 0,
            1 if item.playback_match else 0,
            item.score or 0,
        ),
        reverse=True,
    )
    for candidate in ordered:
        candidate_headers = browser_request_headers_for_candidate(candidate)
        for name in YTDLP_HTTP_HEADER_ORDER:
            value = candidate_headers.get(name)
            if value and name not in headers:
                headers[name] = value

    if page_url:
        headers.setdefault("Referer", _safe_header_value(page_url))
    return headers


def _is_scannable_play_endpoint(candidate: ResourceCandidate) -> bool:
    if not _is_http_url(candidate.url):
        return False
    if classify_resource(candidate.url, candidate.mime) != "unknown":
        return False
    request_type = (candidate.request_type or "").lower()
    method = (candidate.method or "").upper()
    label = (candidate.label or "").lower()
    source = (candidate.source or "").lower()
    if request_type in {"xmlhttprequest", "fetch"} and _media_endpoint_hint(candidate.url):
        return True
    if source.startswith("pagehook") and _media_endpoint_hint(candidate.url):
        return True
    if method in REQUEST_BODY_REPLAY_METHODS and candidate.request_body and _media_endpoint_hint(candidate.url):
        return True
    return "play" in label and _media_endpoint_hint(candidate.url)


def fallback_page_contexts(page_url: str, resources: list[ResourceCandidate]) -> list[tuple[str, ResourceCandidate | None]]:
    contexts: list[tuple[str, ResourceCandidate | None]] = []
    seen: set[str] = set()

    def add(url: str, candidate: ResourceCandidate | None = None) -> None:
        value = _safe_header_value(url)
        if not _is_http_url(value):
            return
        if value in seen:
            return
        seen.add(value)
        contexts.append((value, candidate))

    add(page_url, None)
    ordered = sorted(
        resources,
        key=lambda item: (
            1 if item.is_main_video else 0,
            1 if item.playback_match else 0,
            item.score or 0,
        ),
        reverse=True,
    )
    for item in ordered:
        add(item.frame_url, item)
        add(item.page_url, item)
        if classify_resource(item.url, item.mime) == "unknown" and (
            item.source == "dom" or "iframe" in (item.label or "").lower() or _is_scannable_play_endpoint(item)
        ):
            add(item.url, item)
        add(item.request_headers.get("Referer", ""), item)
        add(item.initiator, item)
    return contexts


def fallback_page_urls(page_url: str, resources: list[ResourceCandidate]) -> list[str]:
    return [url for url, _ in fallback_page_contexts(page_url, resources)]


def enrich_with_inferred_manifest_resources(resources: list[ResourceCandidate]) -> list[ResourceCandidate]:
    enriched = list(resources)
    known_urls = {item.url for item in resources if item.url}
    has_blob_boundary = any(effective_resource_kind(item) == "blob" for item in resources)
    for item in resources:
        inferred_url = infer_manifest_url_from_fragment(item.url)
        if inferred_url and inferred_url not in known_urls:
            inferred = item.model_copy(deep=True)
            inferred.url = inferred_url
            inferred.kind = classify_resource(inferred_url, item.mime)
            inferred.mime = "application/vnd.apple.mpegurl" if inferred.kind == "hls" else "application/dash+xml"
            inferred.source = "inferred-manifest"
            inferred.label = item.label or "inferred manifest"
            inferred.score = min(100, max(item.score, score_candidate(inferred)) + 12)
            if not inferred.playback_match:
                inferred.playback_match = "inferred-from-fragment"
            enriched.append(inferred)
            known_urls.add(inferred_url)
            continue
        if inferred_url:
            continue
        if has_blob_boundary and not should_guess_sibling_manifest_with_blob_boundary(item):
            continue
        if effective_resource_kind(item) != "fragment":
            continue
        for guessed_url in infer_sibling_manifest_urls_from_fragment(item.url):
            if guessed_url in known_urls:
                continue
            guessed = item.model_copy(deep=True)
            guessed.url = guessed_url
            guessed.kind = classify_resource(guessed_url, "")
            guessed.mime = "application/vnd.apple.mpegurl" if guessed.kind == "hls" else "application/dash+xml"
            guessed.source = "manifest-guess"
            guessed.label = "guessed HLS manifest from segment directory" if guessed.kind == "hls" else "guessed DASH manifest from segment directory"
            guessed.score = min(72, max(42, (item.score or 0) + 18))
            if not guessed.playback_match:
                guessed.playback_match = "inferred-from-fragment"
            enriched.append(guessed)
            known_urls.add(guessed_url)
    return enriched


def rank_media_candidates(resources: list[ResourceCandidate]) -> list[ResourceCandidate]:
    enriched = enrich_with_inferred_manifest_resources(resources)
    return rank_enriched_candidates(enriched, is_untrusted_page_scan_candidate=_is_untrusted_page_scan_candidate)


def _same_site_host(left: str, right: str) -> bool:
    left_host = (urlparse(left or "").hostname or "").lower().strip(".")
    right_host = (urlparse(right or "").hostname or "").lower().strip(".")
    if not left_host or not right_host:
        return True
    return left_host == right_host or left_host.endswith(f".{right_host}") or right_host.endswith(f".{left_host}")


def _is_untrusted_page_scan_candidate(candidate: ResourceCandidate) -> bool:
    source = (candidate.source or "").lower()
    if not source.startswith(PAGE_SCAN_SOURCE_PREFIXES):
        return False
    if candidate.user_selected or candidate.is_main_video or candidate.playback_match:
        return False

    top_page = candidate.page_url or ""
    frame_url = candidate.frame_url or ""
    referer = (candidate.request_headers or {}).get("Referer", "")
    frame_context = frame_url or (referer if referer and referer != top_page else "")
    suspicious_context = any(
        NON_PRIMARY_FRAME_RE.search(value or "")
        for value in (candidate.url, frame_url, referer, candidate.label)
    )
    third_party_frame = bool(frame_context and top_page and not _same_site_host(frame_context, top_page))
    return suspicious_context or third_party_frame
