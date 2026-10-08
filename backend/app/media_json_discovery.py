"""Discover ResourceCandidate values in caller-supplied JSON; no I/O."""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin, urlparse, urlunparse

from .models import ResourceCandidate
from .media_kinds import classify_resource
from .media_candidate_ranking import score_resource
from .media_url_parsing import (
    JSON_MEDIA_KEY_RE,
    TEXT_MEDIA_FIELD_RE,
    ENCODED_MEDIA_URL_RE,
    JSON_MIME_KEY_RE,
    JSON_VIDEO_CONTEXT_RE,
    JSON_BASE_URL_KEY_RE,
    TEXT_MEDIA_HINT_RE,
    _decoded_media_values,
    _looks_like_json_url_candidate,
    _looks_like_nested_media_text,
    _mime_for_kind,
    _endpoint_kind_hint,
    _media_endpoint_hint,
    normalize_media_url,
)

def _json_context_mime(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    parts = []
    for key, item in value.items():
        if JSON_MIME_KEY_RE.search(str(key)) and isinstance(item, str):
            parts.append(item)
    return " ".join(parts)


def _json_context_kind(key_path: list[str], url: str, parent: object) -> tuple[str, str]:
    kind = classify_resource(url)
    if kind != "unknown":
        return kind, _mime_for_kind(kind)

    parsed_url = urlparse(url)
    if parsed_url.path.endswith("/") and not parsed_url.query:
        return "unknown", ""

    key_context = " ".join(key_path).lower()
    mime_context = _json_context_mime(parent).lower()
    if "mpegurl" in key_context or "x-mpegurl" in key_context or "m3u8" in key_context or "hls" in key_context:
        return "hls", "application/vnd.apple.mpegurl"
    if "dash+xml" in key_context or "mpd" in key_context or "dash" in key_context:
        return "dash", "application/dash+xml"
    if "text/vtt" in key_context or "subrip" in key_context or "subtitle" in key_context or "caption" in key_context:
        return "subtitle", "text/vtt"
    if "audio/" in key_context or "m4a" in key_context or "mp3" in key_context or "aac" in key_context or "opus" in key_context or "audio" in key_context:
        return "audio", "audio/mp4"
    if "video/" in key_context or "mp4" in key_context or "video" in key_context:
        return "video", "video/mp4"
    if "mpegurl" in mime_context or "x-mpegurl" in mime_context or "m3u8" in mime_context or "hls" in mime_context:
        return "hls", "application/vnd.apple.mpegurl"
    if "dash+xml" in mime_context or "mpd" in mime_context or "dash" in mime_context:
        return "dash", "application/dash+xml"
    if "text/vtt" in mime_context or "subrip" in mime_context or "subtitle" in mime_context or "caption" in mime_context:
        return "subtitle", "text/vtt"
    if "audio/" in mime_context or "m4a" in mime_context or "mp3" in mime_context or "aac" in mime_context or "opus" in mime_context or "audio" in mime_context:
        return "audio", "audio/mp4"
    if "video/" in mime_context or "mp4" in mime_context or "video" in mime_context:
        return "video", "video/mp4"
    context = f"{key_context} {mime_context}"
    if JSON_VIDEO_CONTEXT_RE.search(context) and _media_endpoint_hint(url):
        return _endpoint_kind_hint(url)
    return "unknown", ""


def _normalize_json_base_url(value: str, base_url: str, key: str = "") -> str:
    raw = str(value or "").strip().strip("'\"")
    if not raw or re.search(r"\s", raw):
        return ""
    parsed_base = urlparse(base_url or "")
    key_context = str(key or "").lower()
    if raw.startswith("//"):
        return f"{parsed_base.scheme or 'https'}:{raw}".rstrip("/") + "/"
    if re.match(r"^https?://", raw, re.I):
        return raw.rstrip("/") + "/"
    if re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?(?:/.*)?$", raw):
        return f"{parsed_base.scheme or 'https'}://{raw}".rstrip("/") + "/"
    if raw.startswith("/") and re.search(r"(base.?path|path.?prefix|root|prefix|dir|directory)", key_context, re.I):
        return urljoin(base_url, raw).rstrip("/") + "/"
    if raw.endswith("/") and re.search(r"(base.?path|path.?prefix|root|prefix|dir|directory)", key_context, re.I):
        return urljoin(base_url, raw).rstrip("/") + "/"
    return ""


def _json_base_urls(node: dict, base_url: str) -> list[str]:
    urls: list[str] = []
    host_bases: list[str] = []
    path_bases: list[str] = []
    parsed_base = urlparse(base_url or "")

    def add(url: str, bucket: list[str] | None = None) -> None:
        if not url or url in urls:
            return
        urls.append(url)
        if bucket is not None and url not in bucket:
            bucket.append(url)

    for key, value in node.items():
        if not isinstance(value, str) or not JSON_BASE_URL_KEY_RE.search(str(key)):
            continue
        for candidate_value in _decoded_media_values(value):
            url = _normalize_json_base_url(candidate_value, base_url, str(key))
            raw = str(candidate_value or "").strip().strip("'\"")
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc and parsed.path.rstrip("/") in {"", "/"}:
                add(url, host_bases)
            elif raw.startswith("/") and parsed.netloc == parsed_base.netloc:
                add(url, path_bases)
            else:
                add(url)

    for host_base in host_bases:
        parsed_host = urlparse(host_base)
        for path_base in path_bases:
            parsed_path = urlparse(path_base)
            combined = urlunparse((parsed_host.scheme, parsed_host.netloc, parsed_path.path, "", "", "")).rstrip("/") + "/"
            add(combined)

    return sorted(urls, key=lambda item: len(urlparse(item).path or ""), reverse=True)[:8]


def _looks_like_split_media_path(value: str, key_path: list[str], parent: object) -> bool:
    text = str(value or "").strip().strip("'\"")
    if not text or re.search(r"\s", text):
        return False
    if re.match(r"^(?:https?:)?//", text, re.I):
        return False
    if text.startswith(("data:", "blob:", "javascript:")):
        return False
    if TEXT_MEDIA_HINT_RE.search(text):
        return True
    context = " ".join(key_path).lower()
    mime_context = _json_context_mime(parent).lower()
    return bool(JSON_VIDEO_CONTEXT_RE.search(context) and re.search(r"video/|mpegurl|dash\+xml|audio/", mime_context))


def _json_split_base_media_resources(
    node: dict,
    base_url: str,
    source: str,
    key_path: list[str],
    seen: set[str],
    inherited_bases: list[str] | None = None,
) -> list[ResourceCandidate]:
    bases = _json_base_urls(node, base_url)
    for inherited in inherited_bases or []:
        if inherited and inherited not in bases:
            bases.append(inherited)
    if not bases:
        return []
    resources: list[ResourceCandidate] = []
    for key, value in node.items():
        if not isinstance(value, str):
            continue
        next_path = [*key_path, str(key)]
        if not JSON_MEDIA_KEY_RE.search(str(key)):
            continue
        for candidate_value in _decoded_media_values(value):
            if not _looks_like_split_media_path(candidate_value, next_path, node):
                continue
            for media_base in bases:
                url = urljoin(media_base, candidate_value.lstrip("/") if not candidate_value.startswith("/") else candidate_value)
                if not url or url in seen:
                    continue
                kind, mime = _json_context_kind(next_path, url, node)
                if kind == "unknown":
                    continue
                score = min(100, score_resource(url, mime, source) + 18)
                resources.append(
                    ResourceCandidate(
                        url=url,
                        source=source,
                        kind=kind,
                        mime=mime,
                        score=score,
                        label=f"json combined {'/'.join(next_path[-3:])}",
                        request_headers={"Referer": base_url},
                    )
                )
                seen.add(url)
                break
            if len(resources) >= 20:
                break
        if len(resources) >= 20:
            break
    return resources


def _json_media_resources(
    node: object,
    base_url: str,
    source: str,
    key_path: list[str],
    seen: set[str],
    inherited_bases: list[str] | None = None,
) -> list[ResourceCandidate]:
    resources: list[ResourceCandidate] = []
    if isinstance(node, dict):
        local_bases = _json_base_urls(node, base_url)
        inherited_for_children = [*(inherited_bases or [])]
        for local_base in local_bases:
            if local_base not in inherited_for_children:
                inherited_for_children.append(local_base)
        local_video_resources: list[ResourceCandidate] = []
        local_audio_resources: list[ResourceCandidate] = []
        for key, value in node.items():
            next_path = [*key_path, str(key)]
            if isinstance(value, str) and JSON_MEDIA_KEY_RE.search(str(key)):
                for candidate_value in _decoded_media_values(value):
                    if not _looks_like_json_url_candidate(candidate_value):
                        continue
                    url = normalize_media_url(candidate_value, base_url)
                    if url and url not in seen:
                        kind, mime = _json_context_kind(next_path, url, node)
                        if kind != "unknown":
                            candidate = ResourceCandidate(
                                url=url,
                                source=source,
                                kind=kind,
                                mime=mime,
                                score=score_resource(url, mime, source),
                                label=f"json {'/'.join(next_path[-3:])}",
                                request_headers={"Referer": base_url},
                            )
                            resources.append(candidate)
                            if kind == "video":
                                local_video_resources.append(candidate)
                            elif kind == "audio":
                                local_audio_resources.append(candidate)
                            seen.add(url)
                            break
            if isinstance(value, str) and not JSON_MEDIA_KEY_RE.search(str(key)):
                for candidate_value in _decoded_media_values(value):
                    if not _looks_like_json_url_candidate(candidate_value):
                        continue
                    url = normalize_media_url(candidate_value, base_url)
                    if not url or url in seen:
                        continue
                    kind, mime = _json_context_kind(next_path, url, node)
                    if kind == "unknown":
                        continue
                    candidate = ResourceCandidate(
                        url=url,
                        source=source,
                        kind=kind,
                        mime=mime,
                        score=score_resource(url, mime, source),
                        label=f"json {'/'.join(next_path[-3:])}",
                        request_headers={"Referer": base_url},
                    )
                    resources.append(candidate)
                    if kind == "video":
                        local_video_resources.append(candidate)
                    elif kind == "audio":
                        local_audio_resources.append(candidate)
                    seen.add(url)
                    break
            if isinstance(value, str) and len(key_path) < 12:
                for candidate_text in _decoded_media_values(value):
                    nested_text = html.unescape(candidate_text).strip()
                    if not _looks_like_nested_media_text(nested_text):
                        continue
                    if nested_text[0] in "{[":
                        try:
                            nested_data = json.loads(nested_text)
                        except Exception:
                            continue
                        resources.extend(_json_media_resources(nested_data, base_url, source, next_path, seen, inherited_for_children))
                    else:
                        resources.extend(extract_media_resources_from_field_text(nested_text, base_url, source, seen))
                        resources.extend(extract_media_resources_from_encoded_url_text(nested_text, base_url, source, seen))
                    if len(resources) >= 60:
                        break
            if isinstance(value, (dict, list)):
                resources.extend(_json_media_resources(value, base_url, source, next_path, seen, inherited_for_children))
            if len(resources) >= 60:
                break
        for candidate in _json_split_base_media_resources(node, base_url, source, key_path, seen, inherited_bases):
            resources.append(candidate)
            if candidate.kind == "video":
                local_video_resources.append(candidate)
            elif candidate.kind == "audio":
                local_audio_resources.append(candidate)
        if local_video_resources and local_audio_resources:
            audio = max(local_audio_resources, key=lambda item: item.score or 0)
            for video in local_video_resources:
                if not video.audio_url:
                    video.audio_url = audio.url
                    video.audio_mime = audio.mime
    elif isinstance(node, list):
        for index, value in enumerate(node[:120]):
            resources.extend(_json_media_resources(value, base_url, source, [*key_path, str(index)], seen, inherited_bases))
            if len(resources) >= 60:
                break
    elif isinstance(node, str):
        for candidate_value in _decoded_media_values(node):
            if not _looks_like_json_url_candidate(candidate_value):
                continue
            url = normalize_media_url(candidate_value, base_url)
            if not url or url in seen:
                continue
            kind, mime = _json_context_kind(key_path, url, {})
            if kind == "unknown":
                continue
            resources.append(
                ResourceCandidate(
                    url=url,
                    source=source,
                    kind=kind,
                    mime=mime,
                    score=score_resource(url, mime, source),
                    label=f"json {'/'.join(key_path[-3:])}",
                    request_headers={"Referer": base_url},
                )
            )
            seen.add(url)
            break
    return resources


def extract_media_resources_from_json_text(text: str, base_url: str, source: str = "page-scan") -> list[ResourceCandidate]:
    stripped = (text or "").strip()
    if not stripped or stripped[0] not in "{[":
        return []
    try:
        data = json.loads(stripped)
    except Exception:
        return []
    return _json_media_resources(data, base_url, source, [], set())[:60]



def extract_media_resources_from_field_text(
    text: str,
    base_url: str,
    source: str = "page-scan",
    seen: set[str] | None = None,
) -> list[ResourceCandidate]:
    resources: list[ResourceCandidate] = []
    seen = seen if seen is not None else set()
    for match in TEXT_MEDIA_FIELD_RE.finditer(text or ""):
        key = (match.group("key") or "").strip("\"'")
        if not JSON_MEDIA_KEY_RE.search(key):
            continue
        for raw_url in _decoded_media_values(match.group("url") or ""):
            if not _looks_like_json_url_candidate(raw_url):
                continue
            url = normalize_media_url(raw_url, base_url)
            if not url or url in seen:
                continue
            kind, mime = _json_context_kind([key], url, {})
            if kind == "unknown":
                continue
            resources.append(
                ResourceCandidate(
                    url=url,
                    source=source,
                    kind=kind,
                    mime=mime,
                    score=score_resource(url, mime, source),
                    label=f"field {key}",
                    request_headers={"Referer": base_url},
                )
            )
            seen.add(url)
            break
        if len(resources) >= 60:
            break
    return resources


def extract_media_resources_from_encoded_url_text(
    text: str,
    base_url: str,
    source: str = "page-scan",
    seen: set[str] | None = None,
) -> list[ResourceCandidate]:
    resources: list[ResourceCandidate] = []
    seen = seen if seen is not None else set()
    for match in ENCODED_MEDIA_URL_RE.finditer(text or ""):
        for raw_url in _decoded_media_values(match.group(0)):
            url = normalize_media_url(raw_url, base_url)
            if not url or url in seen:
                continue
            kind = classify_resource(url)
            if kind == "unknown":
                continue
            mime = _mime_for_kind(kind)
            resources.append(
                ResourceCandidate(
                    url=url,
                    source=source,
                    kind=kind,
                    mime=mime,
                    score=score_resource(url, mime, source),
                    label="encoded page scan",
                    request_headers={"Referer": base_url},
                )
            )
            seen.add(url)
            break
        if len(resources) >= 60:
            break
    return resources
