"""Pure URL decoding and bounded page-media lexical hints.

Inputs are caller-supplied text/URLs; outputs are decoded values and hints.
This module never resolves DNS, fetches URLs, or persists browser data.
"""
from __future__ import annotations

import html
import ipaddress
import re
from base64 import b64decode, urlsafe_b64decode
from urllib.parse import unquote, urljoin, urlparse

TEXT_MEDIA_HINT_RE = re.compile(r"\.(mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)([?#]|[\"'\s<>]|$)", re.I)

TEXT_MEDIA_SUFFIXES = (
    ".mp4",
    ".m4v",
    ".webm",
    ".mov",
    ".mkv",
    ".flv",
    ".avi",
    ".m4a",
    ".mp3",
    ".aac",
    ".opus",
    ".ogg",
    ".oga",
    ".wav",
    ".m3u8",
    ".mpd",
    ".m4s",
    ".ts",
    ".vtt",
    ".srt",
    ".ass",
    ".ssa",
)

TEXT_MEDIA_TOKEN_DELIMITERS = frozenset(" \t\r\n\"'<>\\")

ENCODED_MEDIA_URL_RE = re.compile(
    r"https?%(?:25)*3A(?:(?:%(?:25)*2F)|/){2}[^\s\"'<>\\]+?(?:\.|%(?:25)*2E)(?:mp4|m4v|webm|mov|mkv|flv|avi|m4a|mp3|aac|opus|ogg|oga|wav|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:[^\s\"'<>\\]*)?",
    re.I,
)

MEDIA_ENDPOINT_HINT_RE = re.compile(
    r"(^|[/?&=._\s-])(api|ananas|play|player|stream|video|audio|media|source|sources|sourcelist|backup|backups|cdn|baseurl|base_url|base-url|host|domain|vod|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|hls|dash|manifest|playlist|master|m3u8|mpd|objectid|dtoken|fileid|httpmd)([/?&=._\s-]|$)",
    re.I,
)

JSON_MEDIA_KEY_RE = re.compile(
    r"(url|uri|path|src|address|file|fileid|objectid|dtoken|download|httpmd|play|playlist|media|video|audio|stream|source|sourcelist|video.?list|audio.?list|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|manifest|master|main|backup|hls|m3u8|dash|mpd|segment|fragment|chunk|subtitle|caption)",
    re.I,
)

JSON_MIME_KEY_RE = re.compile(r"(mime|type|format|content.?type|media.?type)", re.I)

JSON_VIDEO_CONTEXT_RE = re.compile(r"(url|uri|path|src|address|file|source|sourcelist|video.?list|audio.?list|video|audio|media|play|playlist|stream|vod|course|lesson|objectid|dtoken|fileid|download|httpmd|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|manifest|master|main|backup)", re.I)

JSON_BASE_URL_KEY_RE = re.compile(r"(base.?url|base.?path|path.?prefix|cdn|host|domain|origin|endpoint|server|root|prefix|dir|directory)", re.I)

TEXT_MEDIA_FIELD_RE = re.compile(
    r"(?P<key>[\"']?[A-Za-z_$][A-Za-z0-9_$.-]{0,79}[\"']?)\s*[:=]\s*[\"'](?P<url>(?:\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\.|[^\"'<>\\\s]){4,})[\"']",
    re.I,
)

PLAYER_PAGE_HINT_RE = re.compile(
    r"(player|play|video|media|vod|course|lesson|chapter|knowledge|clazz|job|mooc|ananas|xuexitong|chaoxing|study|viewer)",
    re.I,
)

B64ISH_RE = re.compile(r"^[A-Za-z0-9+/_=-]{16,}$")

MAX_PAGE_SCAN_BYTES = 2 * 1024 * 1024


def normalize_media_url(raw: str, base_url: str) -> str:
    value = html.unescape(str(raw or ""))
    value = (
        value.replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\u003A", ":")
        .replace("\\u003a", ":")
        .replace("\\u003F", "?")
        .replace("\\u003f", "?")
        .replace("\\u003D", "=")
        .replace("\\u003d", "=")
        .strip()
    )
    value = value.rstrip(".,;)")
    try:
        return urljoin(base_url, value)
    except Exception:
        return ""


def _mime_for_kind(kind: str) -> str:
    if kind == "hls":
        return "application/vnd.apple.mpegurl"
    if kind == "dash":
        return "application/dash+xml"
    if kind == "subtitle":
        return "text/vtt"
    if kind == "video":
        return "video/mp4"
    if kind == "audio":
        return "audio/mp4"
    return ""


def _media_endpoint_hint(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    target = " ".join([parsed.path or "", parsed.query or ""])
    return bool(MEDIA_ENDPOINT_HINT_RE.search(target))


def _endpoint_kind_hint(url: str) -> tuple[str, str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return "unknown", ""
    target = " ".join([parsed.path or "", parsed.query or ""]).lower()
    if re.search(r"(^|[/?&=._\s-])audio([/?&=._\s-]|$)", target):
        return "audio", "audio/mp4"
    if MEDIA_ENDPOINT_HINT_RE.search(target):
        return "video", "video/mp4"
    return "unknown", ""


def _looks_like_json_url_candidate(value: str) -> bool:
    value = value.strip()
    if len(value) < 4 or re.search(r"\s", value):
        return False
    if re.match(r"^(https?:)?//", value, re.I):
        return True
    if re.search(r"%2f|%3a|%3f|%3d|%26", value, re.I):
        return True
    if value.startswith("/"):
        return True
    if "/" in value and re.search(r"[?=&]|api|ananas|play|media|video|audio|stream|source|sourcelist|backup|cdn|vod|quality|qualities|definition|definitions|format|formats|profile|profiles|variant|variants|rendition|renditions|level|levels|track|tracks|m3u8|mpd|hls|dash|objectid|dtoken|fileid|httpmd", value, re.I):
        return True
    return False


def _looks_like_nested_media_text(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 8:
        return False
    if text[0] in "{[":
        has_media_field = JSON_MEDIA_KEY_RE.search(text)
        has_media_target = TEXT_MEDIA_HINT_RE.search(text) or MEDIA_ENDPOINT_HINT_RE.search(text)
        return bool(has_media_field and has_media_target)
    return bool(JSON_MEDIA_KEY_RE.search(text) and (TEXT_MEDIA_HINT_RE.search(text) or MEDIA_ENDPOINT_HINT_RE.search(text)))


def _repeated_unquote(value: str, limit: int = 3) -> list[str]:
    current = str(value or "")
    decoded: list[str] = []
    for _ in range(limit):
        next_value = unquote(current)
        if not next_value or next_value == current:
            break
        decoded.append(next_value)
        current = next_value
    return decoded


def _decoded_media_values(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    values = [raw]
    js_decoded = _decode_js_string_escapes(raw)
    if js_decoded and js_decoded not in values:
        values.insert(0, js_decoded)
    for unquoted in _repeated_unquote(raw):
        if unquoted and unquoted not in values:
            values.insert(0, unquoted)
        unquoted_js = _decode_js_string_escapes(unquoted)
        if unquoted_js and unquoted_js not in values:
            values.insert(0, unquoted_js)

    compact = raw.strip()
    if B64ISH_RE.match(compact) and len(compact) % 4 in {0, 2, 3}:
        padded = compact + "=" * (-len(compact) % 4)
        for decoder in (urlsafe_b64decode, b64decode):
            try:
                decoded = decoder(padded).decode("utf-8", errors="strict").strip()
            except Exception:
                continue
            if decoded and decoded not in values and not re.search(r"[\x00-\x08\x0e-\x1f]", decoded):
                if (
                    _looks_like_json_url_candidate(decoded)
                    or TEXT_MEDIA_HINT_RE.search(decoded)
                    or _looks_like_nested_media_text(decoded)
                ):
                    values.append(decoded)
            break

    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _decode_js_string_escapes(value: str) -> str:
    text = str(value or "")
    if "\\" not in text:
        return text

    def replace_unicode(match: re.Match[str]) -> str:
        try:
            char = chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)
        if re.search(r"[\x00-\x08\x0e-\x1f]", char):
            return match.group(0)
        return char

    def replace_hex(match: re.Match[str]) -> str:
        try:
            char = chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)
        if re.search(r"[\x00-\x08\x0e-\x1f]", char):
            return match.group(0)
        return char

    unicode_decoded = re.sub(r"\\u([0-9a-fA-F]{4})", replace_unicode, text)
    hex_decoded = re.sub(r"\\x([0-9a-fA-F]{2})", replace_hex, unicode_decoded)
    return (
        hex_decoded
        .replace("\\/", "/")
        .replace("\\&", "&")
        .replace("\\?", "?")
        .replace("\\=", "=")
    )


def _is_http_url(url: str) -> bool:
    return bool(re.match(r"^https?://", url or "", re.I))


def _url_origin(url: str) -> tuple[str, str, int] | None:
    """Return a strict HTTP origin for credential scope, without resolving DNS."""
    try:
        if not url or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
            return None
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        # Preserve browser host spelling; trailing-dot aliases fail validation.
        host = parsed.hostname.lower()
        try:
            host = ipaddress.ip_address(host).compressed
        except ValueError:
            ascii_host = host.encode("idna").decode("ascii")
            if not host.isascii() and ascii_host.encode("ascii").decode("idna") != host:
                return None
            host = ascii_host
            if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
                return None
        port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
        if not 1 <= port <= 65535 or "%" in host:
            return None
        return scheme, host, port
    except (TypeError, UnicodeError, ValueError):
        return None


def same_http_origin(left: str, right: str) -> bool:
    origin = _url_origin(left)
    return origin is not None and origin == _url_origin(right)
