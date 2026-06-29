from __future__ import annotations

import http.cookiejar
import html
import json
import os
import re
import subprocess
import time
from base64 import b64decode, urlsafe_b64decode
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests

from .models import BrowserCookie, DownloadAttempt, MediaPreflightResult, ResourceCandidate
from .runtime import ffmpeg_bin


MEDIA_EXT_RE = re.compile(r"\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)", re.I)
MANIFEST_EXT_RE = re.compile(r"\.(m3u8|mpd)(\?|#|$)", re.I)
FRAGMENT_EXT_RE = re.compile(r"\.(m4s|ts)(\?|#|$)", re.I)
SUBTITLE_EXT_RE = re.compile(r"\.(vtt|srt|ass|ssa)(\?|#|$)", re.I)
TEXT_MEDIA_HINT_RE = re.compile(r"\.(mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)([?#]|[\"'\s<>]|$)", re.I)
TEXT_MEDIA_URL_RE = re.compile(
    r"(?:https?:)?//[^\s\"'<>\\]+\.(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:\?[^\s\"'<>\\]*)?"
    r"|(?:/[^\s\"'<>\\]+)\.(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:\?[^\s\"'<>\\]*)?"
    r"|(?:[A-Za-z0-9._~!$&()*+,;=:@%-]+/)*[A-Za-z0-9._~!$&()*+,;=:@%-]+\.(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:\?[^\s\"'<>\\]*)?",
    re.I,
)
ENCODED_MEDIA_URL_RE = re.compile(
    r"https?%(?:25)*3A(?:(?:%(?:25)*2F)|/){2}[^\s\"'<>\\]+?(?:\.|%(?:25)*2E)(?:mp4|m4v|webm|mov|mkv|flv|avi|m3u8|mpd|m4s|ts|vtt|srt|ass|ssa)(?:[^\s\"'<>\\]*)?",
    re.I,
)
TEXT_RESPONSE_RE = re.compile(r"json|text|html|javascript|mpegurl|dash\+xml|xml|x-mpegurl", re.I)
MEDIA_ENDPOINT_HINT_RE = re.compile(
    r"(^|[/?&=._\s-])(api|play|player|stream|video|media|hls|dash|manifest|playlist|master|m3u8|mpd)([/?&=._\s-]|$)",
    re.I,
)
JSON_MEDIA_KEY_RE = re.compile(
    r"(url|src|file|fileid|objectid|dtoken|download|httpmd|play|media|video|stream|source|hls|m3u8|dash|mpd|segment|fragment|chunk|subtitle|caption)",
    re.I,
)
JSON_MIME_KEY_RE = re.compile(r"(mime|type|format|content.?type|media.?type)", re.I)
JSON_VIDEO_CONTEXT_RE = re.compile(r"(video|media|play|stream|vod|course|lesson|objectid|dtoken|fileid|download|httpmd)", re.I)
TEXT_MEDIA_FIELD_RE = re.compile(
    r"(?P<key>[\"']?[A-Za-z_$][A-Za-z0-9_$.-]{0,79}[\"']?)\s*[:=]\s*[\"'](?P<url>(?:\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\.|[^\"'<>\\\s]){4,})[\"']",
    re.I,
)
B64ISH_RE = re.compile(r"^[A-Za-z0-9+/_=-]{16,}$")
MAX_PAGE_SCAN_BYTES = 2 * 1024 * 1024
DIRECT_MEDIA_SUFFIXES = {".mp4", ".m4v", ".webm", ".mov", ".mkv", ".flv", ".avi"}
MEDIA_CONTENT_TYPE_SUFFIXES = {
    "video/mp4": ".mp4",
    "video/x-m4v": ".m4v",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/x-flv": ".flv",
    "video/flv": ".flv",
    "video/x-msvideo": ".avi",
}
SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa"}
SUBTITLE_LANGUAGE_PREFERENCES = ("zh-CN", "zh-Hans", "zh-Hant", "zh", "en", "en-US")
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
DOWNLOAD_RESPONSE_HEADER_ALLOWLIST = {
    "accept-ranges",
    "content-disposition",
    "content-length",
    "content-range",
    "content-type",
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
MAX_REPLAY_BODY_BYTES = 64 * 1024


class DownloadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ManifestEndpointDetected(RuntimeError):
    def __init__(self, kind: str, mime: str):
        super().__init__(kind)
        self.kind = kind
        self.mime = mime


class QuietYtdlpLogger:
    def debug(self, message: str) -> None:
        return

    def warning(self, message: str) -> None:
        return

    def error(self, message: str) -> None:
        return


def _clean_filename(value: str) -> str:
    value = re.sub(r"[^\w\-.]+", "_", value.strip(), flags=re.U)
    return value[:120] or "media"


def _filename_from_content_disposition(value: str) -> str:
    if not value:
        return ""
    filename = ""
    for part in value.split(";"):
        key, sep, raw = part.strip().partition("=")
        if not sep:
            continue
        key = key.lower()
        raw = raw.strip().strip('"')
        if key == "filename*":
            charset, marker, encoded = raw.partition("''")
            try:
                filename = unquote(encoded if marker else raw, encoding=charset or "utf-8", errors="replace")
            except LookupError:
                filename = unquote(encoded if marker else raw, errors="replace")
            break
        if key == "filename" and raw:
            filename = unquote(raw, errors="replace")
    if not filename:
        return ""
    return Path(filename.replace("\\", "/")).name


def _media_suffix_from_response(url: str, content_type: str = "", content_disposition: str = "") -> str:
    url_suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if url_suffix in DIRECT_MEDIA_SUFFIXES:
        return url_suffix

    disposition_name = _filename_from_content_disposition(content_disposition)
    disposition_suffix = Path(disposition_name).suffix.lower()
    if disposition_suffix in DIRECT_MEDIA_SUFFIXES:
        return disposition_suffix

    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in MEDIA_CONTENT_TYPE_SUFFIXES:
        return MEDIA_CONTENT_TYPE_SUFFIXES[mime]
    return ".mp4"


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
    results: list[str] = []
    for name in names:
        guessed = urlunparse(parsed._replace(path=f"{directory}{name}", params="", fragment=""))
        if guessed not in results:
            results.append(guessed)
    return results


def _domain_matches(cookie_domain: str, host: str) -> bool:
    cookie_domain = cookie_domain.lstrip(".").lower()
    host = host.lower()
    return host == cookie_domain or host.endswith(f".{cookie_domain}")


def cookie_header_for_url(cookies: list[BrowserCookie], url: str) -> str:
    host = urlparse(url).hostname or ""
    parts = []
    for cookie in cookies:
        if cookie.domain and _domain_matches(cookie.domain, host):
            parts.append(f"{cookie.name}={cookie.value}")
    return "; ".join(parts)


def _safe_cookie_field(value: str) -> str:
    text = str(value or "").strip()
    if not text or any(char in text for char in "\r\n;"):
        return ""
    return text


def ffmpeg_cookies_option(cookies: list[BrowserCookie], target_url: str = "") -> str:
    fallback_domain = urlparse(target_url).hostname or ""
    now = time.time()
    fields: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for cookie in cookies:
        if cookie.expirationDate and cookie.expirationDate < now:
            continue
        name = _safe_cookie_field(cookie.name)
        value = _safe_cookie_field(cookie.value)
        domain = _safe_cookie_field(cookie.domain or fallback_domain)
        path = _safe_cookie_field(cookie.path or "/") or "/"
        if not name or not value or not domain:
            continue
        key = (domain.lower(), path, name)
        if key in seen:
            continue
        seen.add(key)
        secure = "; secure" if cookie.secure else ""
        fields.append(f"{name}={value}; domain={domain}; path={path}{secure}")
    return "\n".join(fields)


def _safe_header_value(value: object) -> str:
    return re.sub(r"[\r\n]+", " ", str(value or "")).strip()


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
    return ""


def _media_endpoint_hint(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    target = " ".join([parsed.path or "", parsed.query or ""])
    return bool(MEDIA_ENDPOINT_HINT_RE.search(target))


def _manifest_kind_from_body(text: str, content_type: str = "") -> tuple[str, str]:
    head = (text or "")[:8192].lstrip("\ufeff\r\n\t ")
    lower_head = head[:256].lower()
    content_type = (content_type or "").lower()
    looks_html = lower_head.startswith(("<!doctype html", "<html"))
    if head.startswith("#EXTM3U") or (not looks_html and ("mpegurl" in content_type or "x-mpegurl" in content_type)):
        return "hls", "application/vnd.apple.mpegurl"
    if re.search(r"<MPD(?:\s|>)", head, re.I) or (not looks_html and "dash+xml" in content_type):
        return "dash", "application/dash+xml"
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
    if "/" in value and re.search(r"[?=&]|api|play|media|video|stream|m3u8|mpd|hls|dash", value, re.I):
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
    return bool(JSON_MEDIA_KEY_RE.search(text) and TEXT_MEDIA_HINT_RE.search(text))


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
                decoded = decoder(padded).decode("utf-8", errors="ignore").strip()
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

    context = " ".join(key_path + [_json_context_mime(parent)]).lower()
    if "mpegurl" in context or "x-mpegurl" in context or "m3u8" in context or "hls" in context:
        return "hls", "application/vnd.apple.mpegurl"
    if "dash+xml" in context or "mpd" in context or "dash" in context:
        return "dash", "application/dash+xml"
    if "text/vtt" in context or "subrip" in context or "subtitle" in context or "caption" in context:
        return "subtitle", "text/vtt"
    if "video/" in context or "mp4" in context or "video" in context:
        return "video", "video/mp4"
    if JSON_VIDEO_CONTEXT_RE.search(context) and _media_endpoint_hint(url):
        return "video", "video/mp4"
    return "unknown", ""


def _json_media_resources(node: object, base_url: str, source: str, key_path: list[str], seen: set[str]) -> list[ResourceCandidate]:
    resources: list[ResourceCandidate] = []
    if isinstance(node, dict):
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
                            resources.append(
                                ResourceCandidate(
                                    url=url,
                                    source=source,
                                    kind=kind,
                                    mime=mime,
                                    score=score_resource(url, mime, source),
                                    label=f"json {'/'.join(next_path[-3:])}",
                                    request_headers={"Referer": base_url},
                                )
                            )
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
                    resources.append(
                        ResourceCandidate(
                            url=url,
                            source=source,
                            kind=kind,
                            mime=mime,
                            score=score_resource(url, mime, source),
                            label=f"json {'/'.join(next_path[-3:])}",
                            request_headers={"Referer": base_url},
                        )
                    )
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
                        resources.extend(_json_media_resources(nested_data, base_url, source, next_path, seen))
                    else:
                        resources.extend(extract_media_resources_from_field_text(nested_text, base_url, source, seen))
                        resources.extend(extract_media_resources_from_encoded_url_text(nested_text, base_url, source, seen))
                    if len(resources) >= 60:
                        break
            if isinstance(value, (dict, list)):
                resources.extend(_json_media_resources(value, base_url, source, next_path, seen))
            if len(resources) >= 60:
                break
    elif isinstance(node, list):
        for index, value in enumerate(node[:120]):
            resources.extend(_json_media_resources(value, base_url, source, [*key_path, str(index)], seen))
            if len(resources) >= 60:
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


def _media_scan_text_variants(text: str) -> list[str]:
    body = str(text or "")
    variants = [body]
    decoded = html.unescape(_decode_js_string_escapes(body))
    if decoded and decoded != body:
        variants.append(decoded)
    return variants


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
        for match in TEXT_MEDIA_URL_RE.finditer(searchable):
            url = normalize_media_url(match.group(0), base_url)
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


def download_headers_for_candidate(
    candidate: ResourceCandidate | None,
    cookies: list[BrowserCookie],
    referer: str,
    url: str | None = None,
) -> dict[str, str]:
    target_url = url or (candidate.url if candidate else "")
    headers = browser_request_headers_for_candidate(candidate)
    headers.pop("Range", None)

    headers.setdefault("User-Agent", "Mozilla/5.0 LearnNoteAssistant/0.1")
    if referer:
        headers.setdefault("Referer", _safe_header_value(referer))

    cookie = cookie_header_for_url(cookies, target_url)
    if cookie:
        headers["Cookie"] = cookie
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

    headers.setdefault("User-Agent", "Mozilla/5.0 LearnNoteAssistant/0.1")
    if page_url:
        headers.setdefault("Referer", _safe_header_value(page_url))
    return headers


def _is_http_url(url: str) -> bool:
    return bool(re.match(r"^https?://", url or "", re.I))


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
        if classify_resource(item.url, item.mime) == "unknown" and (item.source == "dom" or "iframe" in (item.label or "").lower()):
            add(item.url, item)
        add(item.request_headers.get("Referer", ""), item)
        add(item.initiator, item)
    return contexts


def fallback_page_urls(page_url: str, resources: list[ResourceCandidate]) -> list[str]:
    return [url for url, _ in fallback_page_contexts(page_url, resources)]


def write_netscape_cookie_file(cookies: list[BrowserCookie], path: Path) -> Path:
    lines = ["# Netscape HTTP Cookie File\n"]
    for cookie in cookies:
        if not cookie.name:
            continue
        domain = cookie.domain or ""
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if cookie.secure else "FALSE"
        expires = int(cookie.expirationDate or 0)
        lines.append(
            "\t".join([
                domain,
                include_subdomains,
                cookie.path or "/",
                secure,
                str(expires),
                cookie.name,
                cookie.value,
            ]) + "\n"
        )
    path.write_text("".join(lines), encoding="utf-8")
    return path


def choose_ytdlp_subtitle_language(info: dict) -> tuple[str, bool]:
    subtitle_maps = [
        (info.get("subtitles") or {}, False),
        (info.get("automatic_captions") or {}, True),
    ]
    for subtitles, automatic in subtitle_maps:
        if not isinstance(subtitles, dict) or not subtitles:
            continue
        for preferred in SUBTITLE_LANGUAGE_PREFERENCES:
            preferred_lower = preferred.lower()
            for lang in subtitles:
                lowered = str(lang).lower()
                if lowered == preferred_lower or lowered.startswith(f"{preferred_lower}-"):
                    return str(lang), automatic
        for lang in subtitles:
            return str(lang), automatic
    return "", False


def classify_resource(url: str, mime: str = "") -> str:
    lowered = url.lower()
    mime_lower = mime.lower()
    if lowered.startswith("blob:"):
        return "blob"
    if FRAGMENT_EXT_RE.search(lowered):
        return "fragment"
    if "mpegurl" in mime_lower or "m3u8" in lowered:
        return "hls"
    if "dash+xml" in mime_lower or ".mpd" in lowered:
        return "dash"
    if "video/" in mime_lower or MEDIA_EXT_RE.search(lowered):
        return "video"
    if "text/vtt" in mime_lower or "subrip" in mime_lower or SUBTITLE_EXT_RE.search(lowered):
        return "subtitle"
    return "unknown"


def effective_resource_kind(candidate: ResourceCandidate) -> str:
    inferred = classify_resource(candidate.url, candidate.mime)
    if inferred != "unknown":
        return inferred
    declared = (candidate.kind or "").lower()
    if declared in {"video", "hls", "dash", "subtitle", "fragment", "blob"}:
        return declared
    return "unknown"


def score_kind(url: str, source: str, kind: str) -> int:
    score = 0
    if kind in {"hls", "dash"}:
        score += 95
    elif kind == "video":
        score += 85
    elif kind == "fragment":
        score += 15
    elif kind == "subtitle":
        score += 60
    elif kind == "blob":
        score += 5
    if source == "webRequestResolved":
        score += 12
    if source == "webRequest":
        score += 10
    if source.startswith("pageHook"):
        score += 10
    if source == "pageHookBlobSource":
        score += 8
    if "chaoxing" in url or "xuexitong" in url:
        score += 8
    return min(score, 100)


def score_resource(url: str, mime: str = "", source: str = "") -> int:
    return score_kind(url, source, classify_resource(url, mime))


def score_candidate(candidate: ResourceCandidate) -> int:
    return score_kind(candidate.url, candidate.source, effective_resource_kind(candidate))


def kind_rank(kind: str) -> int:
    return {
        "hls": 6,
        "dash": 6,
        "video": 5,
        "fragment": 3,
        "subtitle": 2,
        "blob": 1,
    }.get(kind, 0)


def source_rank(source: str) -> int:
    if source in {"pageHookMediaSource", "pageHookBlobSource"}:
        return 7
    if source.startswith("pageHookPlayer"):
        return 6
    if source == "webRequestResolved":
        return 6
    if source == "webRequest":
        return 5
    if source == "activeVideo":
        return 4
    if source.startswith("pageHook"):
        return 3
    if source in {"scriptHint", "domHint", "locationHint", "iframeHint"}:
        return 3
    if source == "dom":
        return 2
    return 0


def playback_match_rank(match: str) -> int:
    return {
        "exact-src": 9,
        "blob-source": 8,
        "range-near-playhead": 7,
        "manifest-near-playhead": 6,
        "resolved-final-url": 6,
        "blob-same-frame": 5,
        "same-frame": 4,
        "recent-media-request": 3,
        "same-site-request": 2,
        "inferred-from-fragment": 1,
    }.get(match, 0)


def playback_match_label(match: str) -> str:
    return {
        "exact-src": "当前 src",
        "source-element": "当前 source",
        "same-frame": "同播放器 frame",
        "blob-same-frame": "blob 播放同 frame",
        "blob-source": "Blob/MSE 来源映射",
        "range-near-playhead": "播放进度附近 Range 请求",
        "manifest-near-playhead": "播放进度附近 Manifest 请求",
        "resolved-final-url": "跳转后的真实媒体",
        "recent-media-request": "最近播放请求",
        "same-site-request": "同站请求",
        "inferred-from-fragment": "分片推断",
    }.get(match, match)


def candidate_rank_key(candidate: ResourceCandidate, order: int = 0) -> tuple[int, int, int, int, int, int, float, int, int]:
    kind = effective_resource_kind(candidate)
    return (
        candidate.score or 0,
        1 if candidate.is_main_video else 0,
        playback_match_rank(candidate.playback_match or ""),
        1 if kind in {"hls", "dash", "video"} else 0,
        kind_rank(kind),
        source_rank(candidate.source or ""),
        candidate.time_stamp or 0,
        candidate.content_length or 0,
        -order,
    )


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
        if has_blob_boundary:
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
    dedup: dict[str, tuple[int, ResourceCandidate]] = {}
    for order, item in enumerate(enrich_with_inferred_manifest_resources(resources)):
        if not item.url or item.url.startswith(("chrome-extension:", "data:")):
            continue
        kind = effective_resource_kind(item)
        item.kind = kind
        boost = (8 if item.is_main_video else 0) + (10 if item.playback_match else 0)
        if item.source == "manifest-guess":
            item.score = min(72, max(0, item.score or 0))
        else:
            item.score = min(100, max(item.score, score_candidate(item)) + boost)
        if kind in {"hls", "dash", "video"}:
            previous = dedup.get(item.url)
            if not previous or candidate_rank_key(item, order) > candidate_rank_key(previous[1], previous[0]):
                dedup[item.url] = (order, item)
    return [item for order, item in sorted(dedup.values(), key=lambda pair: candidate_rank_key(pair[1], pair[0]), reverse=True)]


def _safe_request_header_names(headers: dict[str, str]) -> list[str]:
    return sorted(name for name in headers if name.lower() not in {"authorization", "cookie"})


def _response_content_length(response: requests.Response) -> int | None:
    try:
        value = int(response.headers.get("content-length") or 0)
    except ValueError:
        return None
    return value if value > 0 else None


def _safe_download_response_headers(response: requests.Response) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in response.headers.items():
        lowered = name.lower()
        if lowered in DOWNLOAD_RESPONSE_HEADER_ALLOWLIST and value:
            headers[lowered] = _safe_header_value(value)
    return headers


def request_body_for_candidate(candidate: ResourceCandidate | None, target_url: str = "") -> tuple[str, bytes | None]:
    if not candidate:
        return "GET", None
    if target_url and target_url != candidate.url:
        return "GET", None
    method = str(candidate.method or "GET").upper()
    if method not in REQUEST_BODY_REPLAY_METHODS:
        return "GET", None
    body = candidate.request_body or {}
    content = str(body.get("content") or "")
    if not content:
        return "GET", None
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_REPLAY_BODY_BYTES:
        return "GET", None
    return method, encoded


def _update_candidate_from_download_response(candidate: ResourceCandidate, response: requests.Response) -> None:
    candidate.status_code = response.status_code
    candidate.content_length = _response_content_length(response)
    final_url = response.url or ""
    if final_url and final_url != candidate.url:
        candidate.resolved_url = final_url
    content_type = response.headers.get("content-type", "")
    if content_type:
        candidate.mime = content_type
    candidate.headers = {**candidate.headers, **_safe_download_response_headers(response)}


def _read_probe_bytes(response: requests.Response, limit: int = 64 * 1024) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    return b"".join(chunks)[:limit]


def _read_text_response_body(first_chunk: bytes, chunks, limit: int = MAX_PAGE_SCAN_BYTES) -> bytes:
    body = bytearray(first_chunk or b"")
    if len(body) >= limit:
        return bytes(body[:limit])
    for chunk in chunks:
        if not chunk:
            continue
        remaining = limit - len(body)
        body.extend(chunk[:remaining])
        if len(body) >= limit:
            break
    return bytes(body)


def _textish_content_type(content_type: str) -> bool:
    return bool(re.search(r"html|json|text|xml|javascript", content_type or "", re.I))


def _looks_like_login_or_error(body: bytes) -> bool:
    if not body:
        return False
    text = body[:8192].decode("utf-8", errors="ignore").lower()
    return any(marker in text for marker in ["login", "signin", "sign in", "请登录", "登录", "unauthorized", "forbidden"])


def _embedded_media_candidates_from_text_response(
    parent: ResourceCandidate,
    body: bytes,
    base_url: str,
    referer: str,
) -> list[ResourceCandidate]:
    text = body.decode("utf-8-sig", errors="replace")
    resources = extract_media_resources_from_text(text, base_url, "direct-response")
    if not resources:
        return []

    inherited_headers = browser_request_headers_for_candidate(parent)
    inherited_headers.setdefault("Referer", referer or base_url)
    inherited_headers.pop("Content-Type", None)
    skipped_urls = {parent.url, parent.resolved_url or ""}
    dedup: dict[str, ResourceCandidate] = {}
    for item in resources:
        if item.url in skipped_urls:
            continue
        kind = effective_resource_kind(item)
        if kind not in {"hls", "dash", "video"}:
            continue
        item.kind = kind
        item.score = min(100, max(item.score, score_candidate(item)))
        item.request_headers = {**(item.request_headers or {}), **inherited_headers}
        item.is_main_video = parent.is_main_video or item.is_main_video
        item.playback_match = parent.playback_match or item.playback_match
        item.page_url = parent.page_url or item.page_url
        item.tab_id = parent.tab_id if parent.tab_id is not None else item.tab_id
        item.frame_id = parent.frame_id if parent.frame_id is not None else item.frame_id
        dedup[item.url] = item
    return sorted(dedup.values(), key=lambda item: item.score, reverse=True)


def preflight_media_resource(
    candidate: ResourceCandidate,
    cookies: list[BrowserCookie],
    referer: str,
    timeout: int = 12,
) -> MediaPreflightResult:
    kind = effective_resource_kind(candidate)
    resolved_url = candidate.resolved_url or candidate.url
    warnings: list[str] = []
    if kind == "fragment":
        inferred = infer_manifest_url_from_fragment(candidate.url)
        if inferred:
            resolved_url = inferred
            kind = classify_resource(inferred, candidate.mime)
            warnings.append("已从分片 URL 推断 manifest 后预检。")

    if kind == "blob":
        return MediaPreflightResult(
            ok=True,
            downloadable=False,
            strategy="blob-unrecoverable",
            kind=kind,
            url=candidate.url,
            resolved_url=resolved_url,
            code="drm_or_encrypted",
            message="浏览器只暴露 blob URL，后端无法直接下载；需要可见 mp4/FLV/m3u8/mpd 或本地视频。",
        )
    if kind not in {"video", "hls", "dash"}:
        return MediaPreflightResult(
            ok=True,
            downloadable=False,
            strategy=f"unsupported-{kind}",
            kind=kind,
            url=candidate.url,
            resolved_url=resolved_url,
            code="unsupported_manifest",
            message="该候选不是可独立下载的视频文件或 manifest。",
        )

    strategy = "manifest-probe" if kind in {"hls", "dash"} else "direct-file-probe"
    base_headers = download_headers_for_candidate(candidate, cookies, referer, url=resolved_url)
    request_method, request_body = request_body_for_candidate(candidate, resolved_url)
    if kind == "video":
        base_headers.setdefault("Accept", "*/*")
    elif kind == "hls":
        base_headers.setdefault("Accept", "application/vnd.apple.mpegurl,application/x-mpegURL,text/plain,*/*;q=0.8")
    else:
        base_headers.setdefault("Accept", "application/dash+xml,application/xml,text/xml,*/*;q=0.8")

    def probe_once(headers: dict[str, str], attempt_warnings: list[str]) -> MediaPreflightResult:
        probe_kind = kind
        probe_strategy = strategy
        with requests.request(
            request_method,
            resolved_url,
            headers=headers,
            data=request_body,
            stream=True,
            timeout=timeout,
            allow_redirects=True,
        ) as response:
            body = _read_probe_bytes(response)
            content_type = response.headers.get("content-type", "")
            content_disposition = response.headers.get("content-disposition", "")
            content_length = _response_content_length(response)
            final_url = response.url or resolved_url
            base = {
                "strategy": probe_strategy,
                "kind": probe_kind,
                "url": candidate.url,
                "resolved_url": final_url,
                "status_code": response.status_code,
                "content_type": content_type,
                "content_disposition": content_disposition,
                "content_length": content_length,
                "bytes_checked": len(body),
                "request_header_names": _safe_request_header_names(headers),
                "warnings": attempt_warnings,
            }

            if response.status_code in {401, 403}:
                return MediaPreflightResult(
                    **base,
                    ok=True,
                    downloadable=False,
                    code="auth_required",
                    message=f"媒体预检返回 HTTP {response.status_code}，可能需要刷新登录态或重新打开页面。",
                )
            if response.status_code >= 400:
                return MediaPreflightResult(
                    **base,
                    ok=True,
                    downloadable=False,
                    code="download_forbidden",
                    message=f"媒体预检返回 HTTP {response.status_code}。",
                )
            if _textish_content_type(content_type) and _looks_like_login_or_error(body):
                return MediaPreflightResult(
                    **base,
                    ok=True,
                    downloadable=False,
                    code="auth_required",
                    message="媒体预检拿到登录/错误页面，而不是视频或 manifest。",
                )

            manifest_kind, manifest_mime = _manifest_kind_from_body(body.decode("utf-8", errors="ignore"), content_type)
            if probe_kind == "video" and manifest_kind in {"hls", "dash"}:
                probe_kind = manifest_kind
                base["kind"] = manifest_kind
                base["content_type"] = manifest_mime or content_type
                base["strategy"] = "manifest-probe"
                attempt_warnings.append("该视频直连响应实际是 HLS/DASH manifest，正式任务会改用 ffmpeg 合并。")

            if _textish_content_type(content_type) and manifest_kind == "unknown":
                embedded_candidates = _embedded_media_candidates_from_text_response(candidate, body, final_url, referer)
                if embedded_candidates:
                    selected = embedded_candidates[0]
                    attempt_warnings.append("Text/JSON response contains an embedded media URL; the full task will download that resolved resource.")
                    return MediaPreflightResult(
                        **{
                            **base,
                            "strategy": "direct-response-probe",
                            "kind": selected.kind,
                            "resolved_url": selected.url,
                            "warnings": attempt_warnings,
                        },
                        ok=True,
                        downloadable=True,
                        code="",
                        message="Media endpoint returned text/JSON with a downloadable video or manifest URL.",
                    )
                return MediaPreflightResult(
                    **{**base, "warnings": attempt_warnings},
                    ok=True,
                    downloadable=False,
                    code="download_forbidden",
                    message="Media endpoint returned text/JSON but no downloadable video or manifest URL was found.",
                )

            if probe_kind == "hls":
                text = body.decode("utf-8", errors="ignore")
                if "#EXTM3U" not in text and "mpegurl" not in content_type.lower():
                    attempt_warnings.append("响应不像标准 HLS manifest，实际下载可能失败。")
                if re.search(r"#EXT-X-KEY:[^\n]*(SAMPLE-AES|skd://|widevine|fairplay)", text, re.I):
                    return MediaPreflightResult(
                        **{**base, "warnings": attempt_warnings},
                        ok=True,
                        downloadable=False,
                        code="drm_or_encrypted",
                        message="HLS manifest 疑似 DRM/加密流，第一版不尝试绕过。",
                    )
                if re.search(r"#EXT-X-KEY:[^\n]*METHOD=AES-128", text, re.I):
                    attempt_warnings.append("HLS 使用 AES-128 key，ffmpeg 仍可能因 key 权限失败。")

            if probe_kind == "dash":
                text = body.decode("utf-8", errors="ignore")
                if "<MPD" not in text and "dash+xml" not in content_type.lower():
                    attempt_warnings.append("响应不像标准 DASH manifest，实际下载可能失败。")
                if re.search(r"ContentProtection|widevine|playready|urn:uuid", text, re.I):
                    return MediaPreflightResult(
                        **{**base, "warnings": attempt_warnings},
                        ok=True,
                        downloadable=False,
                        code="drm_or_encrypted",
                        message="DASH manifest 含 ContentProtection，疑似 DRM/加密流。",
                    )

            if probe_kind == "video" and len(body) <= 0:
                return MediaPreflightResult(
                    **base,
                    ok=True,
                    downloadable=False,
                    code="download_forbidden",
                    message="媒体预检没有读到任何视频字节。",
                )

            return MediaPreflightResult(
                **{**base, "warnings": attempt_warnings},
                ok=True,
                downloadable=True,
                code="",
                message="后端可以访问该候选资源；正式任务仍会执行完整下载和合并。",
            )

    probe_variants: list[tuple[dict[str, str], list[str]]] = []
    if kind == "video" and request_body is None:
        bounded = dict(base_headers)
        bounded["Range"] = "bytes=0-4095"
        open_ended = dict(base_headers)
        open_ended["Range"] = "bytes=0-"
        no_range = dict(base_headers)
        no_range.pop("Range", None)
        probe_variants = [
            (bounded, []),
            (open_ended, ["有界 Range 预检未通过，已改用 open-ended Range 重试。"]),
            (no_range, ["Range 预检未通过，已改用无 Range 请求重试。"]),
        ]
    else:
        probe_variants = [(base_headers, [])]

    first_result: MediaPreflightResult | None = None
    last_headers = base_headers
    try:
        for headers, variant_warnings in probe_variants:
            last_headers = headers
            result = probe_once(headers, [*warnings, *variant_warnings])
            if first_result is None:
                first_result = result
            if result.downloadable or result.code == "drm_or_encrypted":
                return result
        assert first_result is not None
        return first_result
    except requests.RequestException as exc:
        return MediaPreflightResult(
            ok=False,
            downloadable=False,
            strategy=strategy,
            kind=kind,
            url=candidate.url,
            resolved_url=resolved_url,
            code="download_forbidden",
            message=f"媒体预检连接失败：{exc}",
            request_header_names=_safe_request_header_names(last_headers),
            warnings=warnings,
        )


class MediaDownloader:
    def __init__(self, task_path: Path):
        self.task_path = task_path
        self.download_dir = task_path / "downloads"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.attempts: list[DownloadAttempt] = []

    def download(
        self,
        page_url: str,
        resources: list[ResourceCandidate],
        cookies: list[BrowserCookie],
        title: str,
    ) -> tuple[Path, ResourceCandidate | None]:
        resources = self._with_inferred_manifest_resources(resources)
        if any(item.url.startswith("blob:") for item in resources) and not any(
            effective_resource_kind(item) in {"hls", "dash", "video"} for item in resources
        ):
            for item in resources:
                kind = effective_resource_kind(item)
                if kind == "blob":
                    self._record_attempt(
                        strategy="blob-unrecoverable",
                        candidate=item,
                        status="skipped",
                        code="drm_or_encrypted",
                        message="页面只暴露 blob 媒体地址，未发现可下载的 manifest 或视频文件。",
                    )
                elif kind == "fragment":
                    self._record_attempt(
                        strategy="skip-fragment",
                        candidate=item,
                        status="skipped",
                        code="unsupported_manifest",
                        message="检测到媒体分片，但没有对应 manifest，不能作为独立视频下载。",
                    )
            raise DownloadError("drm_or_encrypted", "页面只暴露 blob 媒体地址，未发现可下载 manifest 或视频文件。")

        cookie_file = write_netscape_cookie_file(cookies, self.task_path / "cookies.txt") if cookies else None

        candidates = self._candidate_resources(resources)
        failed_urls: set[str] = set()
        if not candidates:
            for item in resources:
                kind = effective_resource_kind(item)
                if kind in {"fragment", "blob", "unknown"}:
                    self._record_attempt(
                        strategy=f"skip-{kind}",
                        candidate=item,
                        status="skipped",
                        code="unsupported_manifest",
                        message="该资源不是可独立下载的视频文件或 manifest，保留为诊断线索。",
                    )
        last_error: DownloadError | None = None
        for candidate in candidates:
            try:
                media_path = self._download_candidate(candidate, cookies, page_url, title)
                self._record_attempt(
                    strategy=self._strategy_for_candidate(candidate),
                    candidate=candidate,
                    status="success",
                    message="浏览器候选资源直取成功。",
                    output_path=media_path,
                )
                return media_path, candidate
            except DownloadError as exc:
                self._record_attempt(strategy=self._strategy_for_candidate(candidate), candidate=candidate, status="failed", code=exc.code, message=exc.message)
                failed_urls.add(candidate.url)
                last_error = exc
                continue

        page_fallbacks = fallback_page_contexts(page_url, resources)
        for fallback_url, context_candidate in page_fallbacks:
            page_scan_resources = self._discover_page_resources(fallback_url, cookies, context_candidate)
            for candidate in self._candidate_resources(page_scan_resources):
                if candidate.url in failed_urls:
                    continue
                try:
                    media_path = self._download_candidate(candidate, cookies, fallback_url, title)
                    self._record_attempt(
                        strategy=self._strategy_for_candidate(candidate),
                        candidate=candidate,
                        status="success",
                        message="页面文本扫描候选资源直取成功。",
                        output_path=media_path,
                    )
                    return media_path, candidate
                except DownloadError as exc:
                    self._record_attempt(strategy=self._strategy_for_candidate(candidate), candidate=candidate, status="failed", code=exc.code, message=exc.message)
                    failed_urls.add(candidate.url)
                    last_error = exc
                    continue

        for fallback_url, _context_candidate in page_fallbacks:
            try:
                media_path = self._download_with_ytdlp(fallback_url, cookie_file, title, resources)
                self._record_attempt(
                    strategy="page-ytdlp",
                    url=fallback_url,
                    status="success",
                    message="浏览器候选不可用，yt-dlp 页面解析成功。",
                    output_path=media_path,
                )
                return media_path, None
            except DownloadError as exc:
                self._record_attempt(strategy="page-ytdlp", url=fallback_url, status="failed", code=exc.code, message=exc.message)
                if not last_error:
                    last_error = exc
            except Exception as exc:
                self._record_attempt(strategy="page-ytdlp", url=fallback_url, status="failed", code="download_forbidden", message=str(exc))
                if not last_error:
                    last_error = DownloadError("download_forbidden", str(exc))

        if last_error:
            raise last_error
        raise DownloadError("no_media_found", "没有发现可直接下载的视频、HLS 或 DASH 资源。")

    def download_subtitle(
        self,
        resources: list[ResourceCandidate],
        cookies: list[BrowserCookie],
        referer: str,
        title: str,
    ) -> Path | None:
        candidates = self._subtitle_resources(resources)
        for candidate in candidates:
            try:
                path = self._download_text_file(candidate, cookies, referer, title)
                self._record_attempt(
                    strategy="subtitle-file",
                    candidate=candidate,
                    status="success",
                    message="检测到页面字幕轨，已优先使用字幕生成转写。",
                    output_path=path,
                )
                return path
            except DownloadError as exc:
                self._record_attempt(strategy="subtitle-file", candidate=candidate, status="failed", code=exc.code, message=exc.message)

        found_platform_subtitle = False
        for fallback_url in fallback_page_urls(referer, resources):
            try:
                path = self._download_subtitle_with_ytdlp(fallback_url, cookies, title, resources)
                if path:
                    self._record_attempt(
                        strategy="subtitle-ytdlp",
                        url=fallback_url,
                        status="success",
                        message="yt-dlp 发现平台字幕，已优先使用字幕生成转写。",
                        output_path=path,
                    )
                    return path
            except DownloadError as exc:
                found_platform_subtitle = True
                self._record_attempt(strategy="subtitle-ytdlp", url=fallback_url, status="failed", code=exc.code, message=exc.message)
        if not found_platform_subtitle:
            self._record_attempt(
                strategy="subtitle-ytdlp",
                url=referer,
                status="skipped",
                code="no_media_found",
                message="yt-dlp 没有发现可下载的平台字幕。",
            )
        return None

    def _candidate_resources(self, resources: list[ResourceCandidate]) -> list[ResourceCandidate]:
        return rank_media_candidates(resources)

    def _discover_page_resources(
        self,
        page_url: str,
        cookies: list[BrowserCookie],
        context_candidate: ResourceCandidate | None = None,
    ) -> list[ResourceCandidate]:
        if not re.match(r"^https?://", page_url, re.I):
            return []
        url_resources = extract_media_resources_from_text(page_url, page_url, "page-scan-url")
        headers = download_headers_for_candidate(context_candidate, cookies, page_url, url=page_url)
        headers.setdefault("Accept", "text/html,application/xhtml+xml,application/json,text/plain,*/*;q=0.8")

        def apply_context_headers(resources: list[ResourceCandidate], referer: str) -> list[ResourceCandidate]:
            if not resources:
                return resources
            inherited = browser_request_headers_for_candidate(context_candidate)
            inherited.setdefault("Referer", referer)
            for item in resources:
                item.request_headers = {**inherited, **(item.request_headers or {})}
            return resources

        try:
            with requests.get(page_url, headers=headers, stream=True, timeout=20) as response:
                if response.status_code in {401, 403}:
                    self._record_attempt(
                        strategy="page-scan",
                        url=page_url,
                        status="failed",
                        code="auth_required",
                        message=f"页面扫描返回 HTTP {response.status_code}。",
                    )
                    return apply_context_headers(url_resources, page_url)
                if response.status_code >= 400:
                    self._record_attempt(
                        strategy="page-scan",
                        url=page_url,
                        status="failed",
                        code="download_forbidden",
                        message=f"页面扫描返回 HTTP {response.status_code}。",
                    )
                    return apply_context_headers(url_resources, page_url)
                content_type = response.headers.get("content-type", "")
                final_url = response.url or page_url
                can_scan_body = (
                    not content_type
                    or bool(TEXT_RESPONSE_RE.search(content_type))
                    or bool(MANIFEST_EXT_RE.search(final_url.lower()))
                    or _media_endpoint_hint(final_url)
                )
                if not can_scan_body:
                    self._record_attempt(
                        strategy="page-scan",
                        url=page_url,
                        status="skipped",
                        code="unsupported_manifest",
                        message=f"页面响应不是可扫描文本：{content_type}",
                    )
                    return apply_context_headers(url_resources, final_url)
                content_length = int(response.headers.get("content-length") or 0)
                if content_length > MAX_PAGE_SCAN_BYTES:
                    self._record_attempt(
                        strategy="page-scan",
                        url=page_url,
                        status="skipped",
                        code="unsupported_manifest",
                        message="页面响应过大，跳过文本媒体 URL 扫描。",
                    )
                    return apply_context_headers(url_resources, final_url)
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_PAGE_SCAN_BYTES:
                        self._record_attempt(
                            strategy="page-scan",
                            url=page_url,
                            status="skipped",
                            code="unsupported_manifest",
                            message="页面响应超过扫描上限，跳过文本媒体 URL 扫描。",
                        )
                        return apply_context_headers(url_resources, final_url)
                    chunks.append(chunk)
                text = b"".join(chunks).decode(response.encoding or "utf-8-sig", errors="replace")
                base_url = final_url
                resources = [*url_resources]
                seen = {item.url for item in resources}
                for item in extract_media_resources_from_text(text, base_url, "page-scan"):
                    if item.url in seen:
                        continue
                    seen.add(item.url)
                    resources.append(item)
                manifest_kind, manifest_mime = _manifest_kind_from_body(text, content_type)
                if manifest_kind != "unknown" and not any(item.url == final_url for item in resources):
                    resources.insert(
                        0,
                        ResourceCandidate(
                            url=final_url,
                            source="page-scan",
                            kind=manifest_kind,
                            mime=manifest_mime,
                            score=score_kind(final_url, "page-scan", manifest_kind),
                            label="response manifest",
                            request_headers={**browser_request_headers_for_candidate(context_candidate), "Referer": page_url},
                        ),
                    )
                apply_context_headers(resources, base_url)
                self._record_attempt(
                    strategy="page-scan",
                    url=page_url,
                    status="success" if resources else "skipped",
                    code="" if resources else "no_media_found",
                    message=f"页面文本扫描发现 {len(resources)} 个媒体 URL。" if resources else "页面文本扫描没有发现媒体 URL。",
                )
                return resources
        except Exception as exc:
            self._record_attempt(
                strategy="page-scan",
                url=page_url,
                status="failed",
                code="download_forbidden",
                message=f"页面文本扫描失败：{exc}",
            )
            return apply_context_headers(url_resources, page_url)

    def _with_inferred_manifest_resources(self, resources: list[ResourceCandidate]) -> list[ResourceCandidate]:
        return enrich_with_inferred_manifest_resources(resources)

    def _subtitle_resources(self, resources: list[ResourceCandidate]) -> list[ResourceCandidate]:
        dedup: dict[str, ResourceCandidate] = {}
        for item in resources:
            if not item.url or item.url.startswith(("chrome-extension:", "data:", "blob:")):
                continue
            kind = effective_resource_kind(item)
            if kind != "subtitle":
                continue
            item.kind = kind
            item.score = min(100, max(item.score, score_candidate(item)))
            dedup[item.url] = item
        return sorted(dedup.values(), key=lambda item: item.score, reverse=True)

    def _strategy_for_candidate(self, candidate: ResourceCandidate) -> str:
        kind = effective_resource_kind(candidate)
        if kind in {"hls", "dash"}:
            return "manifest-ffmpeg"
        if kind == "video":
            return "direct-file"
        return f"unsupported-{kind}"

    def _candidate_evidence_summary(self, candidate: ResourceCandidate | None) -> str:
        if not candidate:
            return ""
        parts = [
            candidate.is_main_video and "主视频候选",
            candidate.playback_match and f"播放匹配 {playback_match_label(candidate.playback_match)}",
            candidate.frame_id is not None and f"frame {candidate.frame_id}",
            candidate.status_code and f"HTTP {candidate.status_code}",
            candidate.resolved_url and candidate.resolved_url != candidate.url and f"最终 URL {candidate.resolved_url}",
            candidate.mime and f"MIME {candidate.mime}",
            candidate.content_length and f"大小 {candidate.content_length}B",
        ]
        header_names = _safe_request_header_names(browser_request_headers_for_candidate(candidate))
        if header_names:
            parts.append(f"请求头 {', '.join(header_names)}")
        return "；".join(str(part) for part in parts if part)

    def _attempt_message(self, message: str, candidate: ResourceCandidate | None) -> str:
        evidence = self._candidate_evidence_summary(candidate)
        if not evidence:
            return message
        return f"{message}（候选证据：{evidence}）"

    def _record_attempt(
        self,
        strategy: str,
        status: str,
        message: str,
        candidate: ResourceCandidate | None = None,
        url: str = "",
        code: str = "",
        output_path: Path | None = None,
    ) -> None:
        downloaded = output_path.stat().st_size if output_path and output_path.exists() else None
        self.attempts.append(
            DownloadAttempt(
                strategy=strategy,
                url=candidate.url if candidate else url,
                source=candidate.source if candidate else "",
                kind=candidate.kind if candidate else "",
                score=candidate.score if candidate else 0,
                status=status,  # type: ignore[arg-type]
                code=code,
                message=self._attempt_message(message, candidate),
                output_path=str(output_path) if output_path else "",
                bytes_downloaded=downloaded,
                status_code=candidate.status_code if candidate else None,
                content_length=candidate.content_length if candidate else None,
                mime=candidate.mime if candidate else "",
                resolved_url=candidate.resolved_url if candidate else "",
            )
        )

    def _download_subtitle_with_ytdlp(
        self,
        page_url: str,
        cookies: list[BrowserCookie],
        title: str,
        resources: list[ResourceCandidate],
    ) -> Path | None:
        if not re.match(r"^https?://", page_url or "", re.I):
            return None
        try:
            import yt_dlp
        except Exception:
            return None

        cookie_file = write_netscape_cookie_file(cookies, self.task_path / "subtitle_cookies.txt") if cookies else None
        http_headers = ytdlp_headers_from_browser_context(page_url, resources)
        probe_opts = {
            "quiet": True,
            "no_warnings": True,
            "logger": QuietYtdlpLogger(),
            "noprogress": True,
            "skip_download": True,
            "http_headers": http_headers,
        }
        if cookie_file:
            probe_opts["cookiefile"] = str(cookie_file)

        try:
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                info = ydl.extract_info(page_url, download=False)
        except Exception as exc:
            message = str(exc)
            if "login" in message.lower() or "cookie" in message.lower():
                raise DownloadError("auth_required", "yt-dlp 字幕探测失败，可能需要登录态 cookie。") from exc
            if "404" in message or "not found" in message.lower() or "unsupported url" in message.lower():
                return None
            raise DownloadError("download_forbidden", f"yt-dlp 无法探测平台字幕：{message[:300]}") from exc

        lang, automatic = choose_ytdlp_subtitle_language(info or {})
        if not lang:
            return None

        outtmpl = str(self.download_dir / f"{_clean_filename(title)}_platform_sub.%(ext)s")
        opts = {
            "outtmpl": outtmpl,
            "skip_download": True,
            "writesubtitles": not automatic,
            "writeautomaticsub": automatic,
            "subtitleslangs": [lang],
            "subtitlesformat": "vtt/srt/ass/best",
            "quiet": True,
            "no_warnings": True,
            "logger": QuietYtdlpLogger(),
            "noprogress": True,
            "http_headers": http_headers,
        }
        if cookie_file:
            opts["cookiefile"] = str(cookie_file)

        before = set(self.download_dir.glob("*"))
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(page_url, download=True)
        except Exception as exc:
            message = str(exc)
            if "login" in message.lower() or "cookie" in message.lower():
                raise DownloadError("auth_required", "yt-dlp 字幕下载失败，可能需要登录态 cookie。") from exc
            raise DownloadError("download_forbidden", f"yt-dlp 无法下载平台字幕：{message[:300]}") from exc

        after = [path for path in self.download_dir.glob("*") if path not in before and path.is_file()]
        subtitles = [path for path in after if path.suffix.lower() in SUBTITLE_EXTENSIONS]
        if not subtitles:
            subtitles = [
                path for path in self.download_dir.glob(f"{_clean_filename(title)}_platform_sub*")
                if path.is_file() and path.suffix.lower() in SUBTITLE_EXTENSIONS
            ]
        if not subtitles:
            return None

        subtitle = max(subtitles, key=lambda path: path.stat().st_size)
        text = subtitle.read_text(encoding="utf-8-sig", errors="replace")
        text = re.sub(r"\r+\n", "\n", text)
        text = re.sub(r"\r+", "\n", text).strip()
        if not text:
            raise DownloadError("download_forbidden", "yt-dlp 下载的平台字幕为空。")
        with subtitle.open("w", encoding="utf-8", newline="\n") as file:
            file.write(text + "\n")
        return subtitle

    def _download_with_ytdlp(
        self,
        page_url: str,
        cookie_file: Path | None,
        title: str,
        resources: list[ResourceCandidate] | None = None,
    ) -> Path:
        try:
            import yt_dlp
        except Exception as exc:
            raise DownloadError("unsupported_manifest", "未安装 yt-dlp，跳过页面解析。") from exc

        http_headers = ytdlp_headers_from_browser_context(page_url, resources or [])
        outtmpl = str(self.download_dir / f"{_clean_filename(title)}.%(ext)s")
        opts = {
            "outtmpl": outtmpl,
            "format": "bestvideo*+bestaudio/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "logger": QuietYtdlpLogger(),
            "noprogress": True,
            "retries": 2,
            "fragment_retries": 2,
            "http_headers": http_headers,
        }
        if cookie_file:
            opts["cookiefile"] = str(cookie_file)

        before = set(self.download_dir.glob("*"))
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(page_url, download=True)
        except Exception as exc:
            message = str(exc)
            if "login" in message.lower() or "cookie" in message.lower():
                raise DownloadError("auth_required", "yt-dlp 页面下载失败，可能需要登录态 cookie。") from exc
            raise DownloadError("download_forbidden", f"yt-dlp 无法下载当前页面：{message[:300]}") from exc

        after = [path for path in self.download_dir.glob("*") if path not in before and path.is_file()]
        media = [path for path in after if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".flv", ".avi"}]
        if not media:
            media = [path for path in self.download_dir.glob("*") if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".flv", ".avi"}]
        if not media:
            raise DownloadError("download_forbidden", "yt-dlp 已运行但没有生成可用视频文件。")
        return max(media, key=lambda path: path.stat().st_size)

    def _download_candidate(
        self,
        candidate: ResourceCandidate,
        cookies: list[BrowserCookie],
        referer: str,
        title: str,
    ) -> Path:
        kind = effective_resource_kind(candidate)
        if kind in {"hls", "dash"}:
            return self._download_manifest(candidate, cookies, referer, title)
        if kind == "video":
            return self._download_file(candidate, cookies, referer, title)
        raise DownloadError("unsupported_manifest", f"不支持的候选资源类型：{kind}")

    def _download_embedded_media_response(
        self,
        parent: ResourceCandidate,
        body: bytes,
        base_url: str,
        cookies: list[BrowserCookie],
        referer: str,
        title: str,
    ) -> tuple[Path, ResourceCandidate] | None:
        candidates = _embedded_media_candidates_from_text_response(parent, body, base_url, referer)
        if not candidates:
            return None

        last_error: DownloadError | None = None
        for candidate in candidates:
            try:
                output = self._download_candidate(candidate, cookies, base_url or referer, title)
                self._record_attempt(
                    strategy="direct-response-scan",
                    candidate=candidate,
                    status="success",
                    message="播放接口返回文本/JSON，已解析并下载其中的真实媒体资源。",
                    output_path=output,
                )
                return output, candidate
            except DownloadError as exc:
                last_error = exc
                self._record_attempt(
                    strategy="direct-response-scan",
                    candidate=candidate,
                    status="failed",
                    code=exc.code,
                    message=exc.message,
                )
        if last_error:
            raise last_error
        return None

    def _download_file(self, candidate: ResourceCandidate, cookies: list[BrowserCookie], referer: str, title: str) -> Path:
        url = candidate.resolved_url or candidate.url
        base_headers = download_headers_for_candidate(candidate, cookies, referer, url=url)
        request_method, request_body = request_body_for_candidate(candidate, url)

        def attempt(headers: dict[str, str]) -> Path:
            with requests.request(request_method, url, headers=headers, data=request_body, stream=True, timeout=30) as response:
                _update_candidate_from_download_response(candidate, response)
                if response.status_code in {401, 403}:
                    raise DownloadError("auth_required", f"媒体资源返回 HTTP {response.status_code}。")
                if response.status_code == 416:
                    raise DownloadError("download_forbidden", "媒体资源拒绝当前 Range 请求。")
                if response.status_code >= 400:
                    raise DownloadError("download_forbidden", f"媒体资源返回 HTTP {response.status_code}。")
                content_type = response.headers.get("content-type", "")
                content_disposition = response.headers.get("content-disposition", "")
                chunks = response.iter_content(chunk_size=1024 * 1024)
                first_chunk = b""
                for chunk in chunks:
                    if chunk:
                        first_chunk = chunk
                        break
                if _textish_content_type(content_type):
                    body = _read_text_response_body(first_chunk, chunks)
                    if _looks_like_login_or_error(body):
                        raise DownloadError("auth_required", "Media endpoint returned a login/error page instead of a video file.")
                    manifest_kind, manifest_mime = _manifest_kind_from_body(body.decode("utf-8", errors="ignore"), content_type)
                    if manifest_kind in {"hls", "dash"}:
                        raise ManifestEndpointDetected(manifest_kind, manifest_mime)
                    resolved = self._download_embedded_media_response(candidate, body, response.url or url, cookies, referer, title)
                    if resolved:
                        output, resolved_candidate = resolved
                        for field in ResourceCandidate.model_fields:
                            setattr(candidate, field, getattr(resolved_candidate, field))
                        return output
                    raise DownloadError("download_forbidden", "Media endpoint returned text/JSON but no downloadable video or manifest URL was found.")
                manifest_kind, manifest_mime = _manifest_kind_from_body(first_chunk.decode("utf-8", errors="ignore"), content_type)
                if manifest_kind in {"hls", "dash"}:
                    raise ManifestEndpointDetected(manifest_kind, manifest_mime)
                suffix = _media_suffix_from_response(response.url or url, content_type, content_disposition)
                output = self.download_dir / f"{_clean_filename(title)}_direct{suffix}"
                if output.exists():
                    output.unlink()
                with output.open("wb") as file:
                    if first_chunk:
                        file.write(first_chunk)
                    for chunk in chunks:
                        if chunk:
                            file.write(chunk)
            if not output.exists() or output.stat().st_size < 4096:
                output.unlink(missing_ok=True)
                raise DownloadError("download_forbidden", "下载文件过小，可能不是有效视频。")
            return output

        try:
            return attempt(base_headers)
        except ManifestEndpointDetected as detected:
            candidate.kind = detected.kind
            candidate.mime = detected.mime
            return self._download_manifest(candidate, cookies, referer, title)
        except DownloadError as first_error:
            if request_body is not None:
                raise first_error
            range_headers = dict(base_headers)
            range_headers["Range"] = "bytes=0-"
            try:
                return attempt(range_headers)
            except ManifestEndpointDetected as detected:
                candidate.kind = detected.kind
                candidate.mime = detected.mime
                return self._download_manifest(candidate, cookies, referer, title)
            except DownloadError:
                raise first_error
        except Exception as exc:
            raise DownloadError("download_forbidden", f"直接下载失败：{exc}") from exc

    def _download_text_file(self, candidate: ResourceCandidate, cookies: list[BrowserCookie], referer: str, title: str) -> Path:
        url = candidate.url
        suffix = Path(urlparse(url).path).suffix or ".vtt"
        output = self.download_dir / f"{_clean_filename(title)}_subtitle{suffix}"
        headers = download_headers_for_candidate(candidate, cookies, referer)
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code in {401, 403}:
                raise DownloadError("auth_required", f"字幕资源返回 HTTP {response.status_code}。")
            if response.status_code >= 400:
                raise DownloadError("download_forbidden", f"字幕资源返回 HTTP {response.status_code}。")
            text = response.content.decode("utf-8-sig", errors="replace")
            text = re.sub(r"\r+\n", "\n", text)
            text = re.sub(r"\r+", "\n", text).strip()
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError("download_forbidden", f"字幕下载失败：{exc}") from exc
        if not text:
            raise DownloadError("download_forbidden", "字幕文件为空。")
        with output.open("w", encoding="utf-8", newline="\n") as file:
            file.write(text + "\n")
        return output

    def _probe_manifest_before_ffmpeg(
        self,
        candidate: ResourceCandidate,
        headers: dict[str, str],
    ) -> None:
        kind = effective_resource_kind(candidate)
        probe_headers = dict(headers)
        if kind == "hls":
            probe_headers.setdefault("Accept", "application/vnd.apple.mpegurl,application/x-mpegURL,text/plain,*/*;q=0.8")
        elif kind == "dash":
            probe_headers.setdefault("Accept", "application/dash+xml,application/xml,text/xml,*/*;q=0.8")
        else:
            probe_headers.setdefault("Accept", "*/*")

        try:
            probe_url = candidate.resolved_url or candidate.url
            with requests.get(probe_url, headers=probe_headers, stream=True, timeout=15, allow_redirects=True) as response:
                _update_candidate_from_download_response(candidate, response)
                body = _read_probe_bytes(response)
                content_type = response.headers.get("content-type", "")
                if response.status_code in {401, 403}:
                    raise DownloadError("auth_required", f"manifest returned HTTP {response.status_code}; refresh login cookies and retry.")
                if response.status_code >= 400:
                    raise DownloadError("download_forbidden", f"manifest returned HTTP {response.status_code}.")
                if _textish_content_type(content_type) and _looks_like_login_or_error(body):
                    raise DownloadError("auth_required", "manifest URL returned a login/error page instead of an HLS/DASH manifest.")

                text = body.decode("utf-8", errors="ignore")
                manifest_kind, manifest_mime = _manifest_kind_from_body(text, content_type)
                if manifest_kind == kind:
                    candidate.kind = manifest_kind
                    candidate.mime = manifest_mime or candidate.mime
                if kind == "hls" and re.search(r"#EXT-X-KEY:[^\n]*(SAMPLE-AES|skd://|widevine|fairplay)", text, re.I):
                    raise DownloadError("drm_or_encrypted", "HLS manifest appears to use DRM/encrypted streaming.")
                if kind == "dash" and re.search(r"ContentProtection|widevine|playready|urn:uuid", text, re.I):
                    raise DownloadError("drm_or_encrypted", "DASH manifest contains ContentProtection and may be DRM protected.")
        except DownloadError:
            raise
        except requests.RequestException as exc:
            raise DownloadError("download_forbidden", f"manifest preflight failed: {exc}") from exc

    def _download_manifest(self, candidate: ResourceCandidate, cookies: list[BrowserCookie], referer: str, title: str) -> Path:
        ffmpeg = ffmpeg_bin()
        if not ffmpeg:
            raise DownloadError("unsupported_manifest", "未找到 ffmpeg，无法合并 HLS/DASH。")
        output = self.download_dir / f"{_clean_filename(title)}_manifest.mp4"
        probe_url = candidate.resolved_url or candidate.url
        request_headers = download_headers_for_candidate(candidate, cookies, referer, url=probe_url)
        self._probe_manifest_before_ffmpeg(candidate, request_headers)
        url = candidate.resolved_url or candidate.url
        request_headers = download_headers_for_candidate(candidate, cookies, referer, url=url)
        kind = effective_resource_kind(candidate)
        user_agent = request_headers.pop("User-Agent", "Mozilla/5.0 LearnNoteAssistant/0.1")
        ffmpeg_cookies = ffmpeg_cookies_option(cookies, url)
        if ffmpeg_cookies:
            request_headers.pop("Cookie", None)
        headers = [f"{name}: {value}" for name, value in request_headers.items() if value]
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        if headers:
            cmd += ["-headers", "\r\n".join(headers) + "\r\n"]
        if ffmpeg_cookies:
            cmd += ["-cookies", ffmpeg_cookies]
        if kind in {"hls", "dash"}:
            cmd += ["-protocol_whitelist", "file,http,https,tcp,tls,crypto,data", "-allowed_extensions", "ALL"]
            cmd += ["-f", kind]
        cmd += ["-user_agent", user_agent, "-i", url, "-c", "copy", str(output)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = (result.stderr or "").lower()
            if "403" in stderr or "401" in stderr:
                raise DownloadError("auth_required", "ffmpeg 下载 manifest 失败，可能需要登录态 cookie。")
            if "encrypted" in stderr or "drm" in stderr or "unable to open key" in stderr:
                raise DownloadError("drm_or_encrypted", "媒体流疑似加密或 DRM 保护，无法直接下载。")
            raise DownloadError("unsupported_manifest", f"ffmpeg 无法处理该 manifest：{result.stderr[:300]}")
        if not output.exists() or output.stat().st_size < 4096:
            raise DownloadError("download_forbidden", "manifest 合并没有生成有效视频。")
        return output
