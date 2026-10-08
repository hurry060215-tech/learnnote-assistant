"""Discover media candidates from supplied HTML/text without network access.

Returns the existing ResourceCandidate schema, preserving source labels,
ranking, deduplication and bounded scan behavior. Fetch/SSRF policy stays in
media_transport and downloader; finding a URL never authorizes fetching it.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from .models import ResourceCandidate
from .media_kinds import classify_resource
from .media_candidate_ranking import score_resource
from .media_json_discovery import (
    extract_media_resources_from_json_text,
    extract_media_resources_from_field_text,
    extract_media_resources_from_encoded_url_text,
)
from .media_url_parsing import (
    ENCODED_MEDIA_URL_RE,
    JSON_MEDIA_KEY_RE,
    MAX_PAGE_SCAN_BYTES,
    PLAYER_PAGE_HINT_RE,
    TEXT_MEDIA_FIELD_RE,
    TEXT_MEDIA_HINT_RE,
    TEXT_MEDIA_SUFFIXES,
    TEXT_MEDIA_TOKEN_DELIMITERS,
    _decode_js_string_escapes,
    _decoded_media_values,
    _is_http_url,
    _looks_like_json_url_candidate,
    _media_endpoint_hint,
    _mime_for_kind,
    normalize_media_url,
)

def _declared_media_kind(hint: str, url: str) -> tuple[str, str]:
    kind = classify_resource(url)
    if kind != "unknown":
        return kind, _mime_for_kind(kind)
    context = hint.lower()
    if "mpegurl" in context or "x-mpegurl" in context or "m3u8" in context or "hls" in context:
        return "hls", "application/vnd.apple.mpegurl"
    if "dash+xml" in context or "mpd" in context or "dash" in context:
        return "dash", "application/dash+xml"
    if "text/vtt" in context or "subrip" in context or "subtitle" in context or "caption" in context:
        return "subtitle", "text/vtt"
    if "video/" in context or "audio/" in context or re.search(r"\b(video|audio|media|player|play|stream)\b", context):
        return "video", "video/mp4"
    return "unknown", ""


class _DeclaredMediaHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hints: list[tuple[str, str, str]] = []
        self.page_hints: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.hints) >= 80:
            return
        tag = tag.lower()
        values = {str(name).lower(): str(value or "") for name, value in attrs if name}
        if tag == "link":
            href = values.get("href", "")
            rel = values.get("rel", "").lower()
            as_attr = values.get("as", "").lower()
            type_attr = values.get("type", "")
            if not href or not re.search(r"(^|\s)(preload|prefetch|modulepreload|prerender)(\s|$)", rel):
                return
            if as_attr in {"video", "audio"}:
                self.hints.append((href, f"{rel} {as_attr} {type_attr} media", f"html link {rel} as={as_attr}"))
            elif re.search(r"mpegurl|dash\+xml|video/|audio/", type_attr, re.I):
                self.hints.append((href, f"{rel} {type_attr}", f"html link {rel} {type_attr}"))
            elif as_attr == "fetch" and _media_endpoint_hint(href):
                self.hints.append((href, f"{rel} fetch play media", f"html link {rel} as=fetch"))
        elif tag == "meta":
            content = values.get("content", "")
            key = " ".join([values.get("property", ""), values.get("name", ""), values.get("itemprop", "")])
            if content and re.search(r"og:video|og:audio|twitter:player:stream|twitter:player|video|media|stream|hls|dash|m3u8|mpd", key, re.I):
                self.hints.append((content, f"{key} media", f"html meta {key.strip()}"))
        elif tag == "object":
            value = values.get("data", "")
            type_attr = values.get("type", "")
            if value and re.search(r"video/|audio/|mpegurl|dash\+xml|media|player|stream", f"{type_attr} {value}", re.I):
                self.hints.append((value, f"{type_attr} object media", "html object data"))
        elif tag == "embed":
            value = values.get("src", "")
            type_attr = values.get("type", "")
            if value and re.search(r"video/|audio/|mpegurl|dash\+xml|media|player|stream", f"{type_attr} {value}", re.I):
                self.hints.append((value, f"{type_attr} embed media", "html embed src"))
        elif tag in {"iframe", "frame"}:
            value = values.get("src", "") or values.get("data-src", "") or values.get("data-url", "")
            if not value:
                return
            hint = " ".join([
                tag,
                values.get("id", ""),
                values.get("name", ""),
                values.get("title", ""),
                values.get("class", ""),
                value,
            ])
            if PLAYER_PAGE_HINT_RE.search(hint):
                self.page_hints.append((value, hint, f"html {tag} player page"))
        elif tag in {"video", "audio", "source", "track"}:
            value = values.get("src", "") or values.get("data-src", "") or values.get("data-url", "")
            type_attr = values.get("type", "")
            kind_attr = values.get("kind", "")
            if not value:
                return
            if tag == "track":
                label_hint = kind_attr or type_attr or "src"
                self.hints.append((value, f"{tag} {kind_attr} {type_attr} subtitle caption", f"html {tag} {label_hint}"))
            else:
                label_hint = type_attr or "src"
                self.hints.append((value, f"{tag} {type_attr} media video audio", f"html {tag} {label_hint}"))


def extract_declared_media_resources_from_html(
    text: str,
    base_url: str,
    source: str = "page-scan",
    seen: set[str] | None = None,
) -> list[ResourceCandidate]:
    if not text or "<" not in text:
        return []
    parser = _DeclaredMediaHTMLParser()
    try:
        parser.feed((text or "")[:MAX_PAGE_SCAN_BYTES])
    except Exception:
        return []
    resources: list[ResourceCandidate] = []
    seen = seen if seen is not None else set()
    for value, hint, label in parser.hints:
        for raw_url in _decoded_media_values(value):
            if not _looks_like_json_url_candidate(raw_url):
                continue
            url = normalize_media_url(raw_url, base_url)
            if not url or url in seen:
                continue
            kind, mime = _declared_media_kind(hint, url)
            if kind == "unknown":
                continue
            resources.append(
                ResourceCandidate(
                    url=url,
                    source=source,
                    kind=kind,
                    mime=mime,
                    score=score_resource(url, mime, source),
                    label=label,
                    request_headers={"Referer": base_url},
                )
            )
            seen.add(url)
            break
        if len(resources) >= 60:
            break
    return resources


def extract_player_page_resources_from_html(
    text: str,
    base_url: str,
    source: str = "page-frame-scan",
    seen: set[str] | None = None,
) -> list[ResourceCandidate]:
    if not text or "<" not in text:
        return []
    parser = _DeclaredMediaHTMLParser()
    try:
        parser.feed((text or "")[:MAX_PAGE_SCAN_BYTES])
    except Exception:
        return []
    resources: list[ResourceCandidate] = []
    seen = seen if seen is not None else set()
    for value, hint, label in parser.page_hints[:12]:
        for raw_url in _decoded_media_values(value):
            if not raw_url or raw_url.startswith(("javascript:", "data:", "blob:")):
                continue
            url = normalize_media_url(raw_url, base_url)
            if not _is_http_url(url) or url in seen:
                continue
            if classify_resource(url) != "unknown":
                continue
            if not PLAYER_PAGE_HINT_RE.search(f"{hint} {url}"):
                continue
            resources.append(
                ResourceCandidate(
                    url=url,
                    source=source,
                    kind="unknown",
                    score=24,
                    label=label,
                    page_url=base_url,
                    frame_url=url,
                    request_headers={"Referer": base_url},
                )
            )
            seen.add(url)
            break
    return resources


def _media_scan_text_variants(text: str) -> list[str]:
    body = str(text or "")
    variants = [body]
    decoded = html.unescape(_decode_js_string_escapes(body))
    if decoded and decoded != body:
        variants.append(decoded)
    return variants


def _iter_media_url_tokens(text: str):
    """Yield URL-like media tokens with a bounded, single-pass scanner."""
    start = 0
    length = len(text)
    while start < length:
        while start < length and text[start] in TEXT_MEDIA_TOKEN_DELIMITERS:
            start += 1
        end = start
        while end < length and text[end] not in TEXT_MEDIA_TOKEN_DELIMITERS:
            end += 1
        if end <= start:
            break

        token = text[start:end].strip("()[]{};,")
        lowered = token.lower()
        suffix_end = -1
        for suffix in TEXT_MEDIA_SUFFIXES:
            position = lowered.find(suffix)
            while position >= 0:
                candidate_end = position + len(suffix)
                if candidate_end == len(token) or token[candidate_end] in "?#":
                    suffix_end = max(suffix_end, candidate_end)
                    break
                position = lowered.find(suffix, position + 1)

        if suffix_end > 0:
            scheme_positions = [
                position
                for marker in ("https://", "http://", "//")
                if (position := lowered.rfind(marker, 0, suffix_end)) >= 0
            ]
            if scheme_positions:
                token = token[max(scheme_positions):]
            else:
                prefix = token[:suffix_end]
                assignment = max(prefix.rfind("="), prefix.rfind(":"))
                if assignment >= 0:
                    token = token[assignment + 1:]
                token = token.lstrip("([{,;")
            token = token.rstrip(")]},;.")
            if token:
                yield token
        start = end + 1


def extract_media_resources_from_text(text: str, base_url: str, source: str = "page-scan") -> list[ResourceCandidate]:
    if not text:
        return []
    resources: list[ResourceCandidate] = extract_media_resources_from_json_text(text, base_url, source)
    seen: set[str] = set()
    for resource in resources:
        seen.add(resource.url)
    for searchable in _media_scan_text_variants(text):
        resources.extend(extract_declared_media_resources_from_html(searchable, base_url, source, seen))
        resources.extend(extract_media_resources_from_field_text(searchable, base_url, source, seen))
        resources.extend(extract_media_resources_from_encoded_url_text(searchable, base_url, source, seen))
        if not TEXT_MEDIA_HINT_RE.search(searchable):
            continue
        for raw_url in _iter_media_url_tokens(searchable):
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
                    label="page scan",
                    request_headers={"Referer": base_url},
                )
            )
            seen.add(url)
            if len(resources) >= 60:
                break
        if len(resources) >= 60:
            break
    return resources
