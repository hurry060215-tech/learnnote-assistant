"""Pure media-kind classification used by acquisition and preflight layers.

This module deliberately has no downloader, network, cookie, or filesystem
dependencies.  Keeping the classification contract here lets callers reason
about candidates without importing the transport implementation.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import ResourceCandidate


MEDIA_EXT_RE = re.compile(r"\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)", re.I)
AUDIO_EXT_RE = re.compile(r"\.(m4a|mp3|aac|opus|ogg|oga|wav)(\?|#|$)", re.I)
MANIFEST_EXT_RE = re.compile(r"\.(m3u8|mpd)(\?|#|$)", re.I)
FRAGMENT_EXT_RE = re.compile(r"\.(m4s|ts)(\?|#|$)", re.I)
SUBTITLE_EXT_RE = re.compile(r"\.(vtt|srt|ass|ssa)(\?|#|$)", re.I)
MEDIA_ENDPOINT_HINT_RE = re.compile(
    r"(^|[/?&=._\s-])(api|ananas|play|player|stream|video|audio|media|source|sources|sourcelist|backup|backups|cdn|baseurl|base_url|base-url|host|domain|vod|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|hls|dash|manifest|playlist|master|m3u8|mpd|objectid|dtoken|fileid|httpmd)([/?&=._\s-]|$)",
    re.I,
)
REQUEST_BODY_REPLAY_METHODS = {"POST", "PUT", "PATCH"}
DIRECT_MEDIA_ASSET_RE = re.compile(r"\.(?:css|js|mjs|map|wasm|woff2?|ttf|otf|eot)$", re.I)
IMAGE_ASSET_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|avif|svg|ico)$", re.I)
NON_PRIMARY_FRAME_RE = re.compile(
    r"(^|[./?&=_-])(ad|ads|advert|advertisement|banner|campaign|promo|promotion|activity|event|blackboard|era)([./?&=_-]|$)",
    re.I,
)


def _is_http_url(url: str) -> bool:
    try:
        return urlparse(url or "").scheme.lower() in {"http", "https"}
    except (TypeError, ValueError):
        return False


def _media_endpoint_hint(url: str) -> bool:
    return bool(MEDIA_ENDPOINT_HINT_RE.search(url or ""))


def _is_clearly_non_media_asset_url(url: str) -> bool:
    try:
        path = urlparse(url or "").path.lower()
    except (TypeError, ValueError):
        path = str(url or "").lower()
    if DIRECT_MEDIA_ASSET_RE.search(path) or IMAGE_ASSET_RE.search(path):
        return True
    image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    transformed_extensions = (".avi", ".avif", ".webp")
    for marker in ("@", "%40"):
        source, found, transform = path.partition(marker)
        if found and source.endswith(image_extensions) and transform.endswith(transformed_extensions) and "/" not in transform:
            return True
    return False


def _is_scannable_play_endpoint(candidate: ResourceCandidate) -> bool:
    if not _is_http_url(candidate.url) or classify_resource(candidate.url, candidate.mime) != "unknown":
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


def classify_resource(url: str, mime: str = "") -> str:
    lowered = (url or "").lower()
    mime_lower = (mime or "").lower()
    if lowered.startswith("blob:"):
        return "blob"
    if mime_lower.startswith("image/") or _is_clearly_non_media_asset_url(url):
        return "unknown"
    if "mpegurl" in mime_lower:
        return "hls"
    if "dash+xml" in mime_lower:
        return "dash"
    if not FRAGMENT_EXT_RE.search(lowered) and "m3u8" in lowered:
        return "hls"
    if not FRAGMENT_EXT_RE.search(lowered) and ".mpd" in lowered:
        return "dash"
    try:
        subtitle_context = urlparse(url).path
    except (TypeError, ValueError):
        subtitle_context = lowered
    if re.search(r"(?:^|[/?&=._-])(?:subtitle|subtitles|caption|captions)(?:[/?&=._-]|$)", subtitle_context, re.I):
        return "subtitle"
    if "audio/" in mime_lower or "application/ogg" in mime_lower:
        return "audio"
    if "video/" in mime_lower or "application/mp4" in mime_lower:
        return "video"
    if "text/vtt" in mime_lower or "subrip" in mime_lower:
        return "subtitle"
    if FRAGMENT_EXT_RE.search(lowered):
        return "fragment"
    if AUDIO_EXT_RE.search(lowered):
        return "audio"
    if MEDIA_EXT_RE.search(lowered):
        return "video"
    if SUBTITLE_EXT_RE.search(lowered):
        return "subtitle"
    return "unknown"


def effective_resource_kind(candidate: ResourceCandidate) -> str:
    resolved_url = candidate.resolved_url or candidate.url
    if _is_clearly_non_media_asset_url(resolved_url) or str(candidate.mime or "").lower().startswith("image/"):
        return "unknown"
    if candidate.resolved_url and candidate.resolved_url != candidate.url:
        resolved = classify_resource(candidate.resolved_url, candidate.mime)
        if resolved in {"hls", "dash", "video", "audio", "subtitle"}:
            return resolved
    inferred = classify_resource(candidate.url, candidate.mime)
    if inferred != "unknown":
        return inferred
    declared = (candidate.kind or "").lower()
    if declared in {"video", "audio", "hls", "dash", "subtitle", "fragment", "blob"}:
        return declared
    if _is_scannable_play_endpoint(candidate):
        return "video"
    return "unknown"


__all__ = ["classify_resource", "effective_resource_kind"]
