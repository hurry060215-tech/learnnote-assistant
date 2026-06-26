from __future__ import annotations

import http.cookiejar
import html
import json
import os
import re
import subprocess
from base64 import b64decode, urlsafe_b64decode
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests

from .models import BrowserCookie, DownloadAttempt, MediaPreflightResult, ResourceCandidate
from .runtime import ffmpeg_bin


MEDIA_EXT_RE = re.compile(r"\.(mp4|m4v|webm|mov|mkv)(\?|#|$)", re.I)
MANIFEST_EXT_RE = re.compile(r"\.(m3u8|mpd)(\?|#|$)", re.I)
FRAGMENT_EXT_RE = re.compile(r"\.(m4s|ts)(\?|#|$)", re.I)
SUBTITLE_EXT_RE = re.compile(r"\.(vtt|srt|ass|ssa)(\?|#|$)", re.I)
TEXT_MEDIA_HINT_RE = re.compile(r"\.(mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)([?#]|[\"'\s<>]|$)", re.I)
TEXT_MEDIA_URL_RE = re.compile(
    r"(?:https?:)?//[^\s\"'<>\\]+\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s\"'<>\\]*)?"
    r"|(?:/[^\s\"'<>\\]+)\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s\"'<>\\]*)?"
    r"|(?:[A-Za-z0-9._~!$&()*+,;=:@%-]+/)*[A-Za-z0-9._~!$&()*+,;=:@%-]+\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|vtt|srt|ass|ssa)(?:\?[^\s\"'<>\\]*)?",
    re.I,
)
TEXT_RESPONSE_RE = re.compile(r"json|text|html|javascript|mpegurl|dash\+xml|xml|x-mpegurl", re.I)
MEDIA_ENDPOINT_HINT_RE = re.compile(
    r"(^|[/?&=._\s-])(api|play|player|stream|video|media|hls|dash|manifest|playlist|master|m3u8|mpd)([/?&=._\s-]|$)",
    re.I,
)
JSON_MEDIA_KEY_RE = re.compile(r"(url|src|file|play|media|video|stream|source|hls|m3u8|dash|mpd|subtitle|caption)", re.I)
JSON_MIME_KEY_RE = re.compile(r"(mime|type|format|content.?type|media.?type)", re.I)
TEXT_MEDIA_FIELD_RE = re.compile(
    r"(?P<key>[\"']?[A-Za-z_$][A-Za-z0-9_$.-]{0,79}[\"']?)\s*[:=]\s*[\"'](?P<url>[^\"'<>\\\s]{4,})[\"']",
    re.I,
)
B64ISH_RE = re.compile(r"^[A-Za-z0-9+/_=-]{16,}$")
MAX_PAGE_SCAN_BYTES = 2 * 1024 * 1024
SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa"}
SUBTITLE_LANGUAGE_PREFERENCES = ("zh-CN", "zh-Hans", "zh-Hant", "zh", "en", "en-US")
BROWSER_REQUEST_HEADER_ALLOWLIST = {
    "accept": "Accept",
    "accept-language": "Accept-Language",
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
)


class DownloadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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


def _safe_header_value(value: object) -> str:
    return re.sub(r"[\r\n]+", " ", str(value or "")).strip()


def normalize_media_url(raw: str, base_url: str) -> str:
    value = html.unescape(str(raw or ""))
    value = value.replace("\\/", "/").replace("\\u0026", "&").strip()
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


def _decoded_media_values(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    values = [raw]
    unquoted = unquote(raw)
    if unquoted and unquoted != raw:
        values.append(unquoted)

    compact = raw.strip()
    if B64ISH_RE.match(compact) and len(compact) % 4 in {0, 2, 3}:
        padded = compact + "=" * (-len(compact) % 4)
        for decoder in (urlsafe_b64decode, b64decode):
            try:
                decoded = decoder(padded).decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
            if decoded and decoded not in values and not re.search(r"[\x00-\x08\x0e-\x1f]", decoded):
                if _looks_like_json_url_candidate(decoded) or TEXT_MEDIA_HINT_RE.search(decoded):
                    values.append(decoded)
            break

    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


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


def extract_media_resources_from_text(text: str, base_url: str, source: str = "page-scan") -> list[ResourceCandidate]:
    if not text:
        return []
    resources: list[ResourceCandidate] = extract_media_resources_from_json_text(text, base_url, source)
    seen: set[str] = set()
    for resource in resources:
        seen.add(resource.url)
    resources.extend(extract_media_resources_from_field_text(text, base_url, source, seen))
    if not TEXT_MEDIA_HINT_RE.search(text):
        return resources
    for match in TEXT_MEDIA_URL_RE.finditer(text):
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


def fallback_page_urls(page_url: str, resources: list[ResourceCandidate]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        value = _safe_header_value(url)
        if not _is_http_url(value):
            return
        if value in seen:
            return
        seen.add(value)
        urls.append(value)

    add(page_url)
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
        add(item.frame_url)
        add(item.page_url)
        if classify_resource(item.url, item.mime) == "unknown" and (item.source == "dom" or "iframe" in (item.label or "").lower()):
            add(item.url)
        add(item.request_headers.get("Referer", ""))
        add(item.initiator)
    return urls


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
    if FRAGMENT_EXT_RE.search(lowered) and infer_manifest_url_from_fragment(url):
        return "fragment"
    if "mpegurl" in mime_lower or "m3u8" in lowered:
        return "hls"
    if "dash+xml" in mime_lower or ".mpd" in lowered:
        return "dash"
    if "video/" in mime_lower or MEDIA_EXT_RE.search(lowered):
        return "video"
    if "text/vtt" in mime_lower or "subrip" in mime_lower or SUBTITLE_EXT_RE.search(lowered):
        return "subtitle"
    if FRAGMENT_EXT_RE.search(lowered):
        return "fragment"
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


def _safe_request_header_names(headers: dict[str, str]) -> list[str]:
    return sorted(name for name in headers if name.lower() not in {"authorization", "cookie"})


def _response_content_length(response: requests.Response) -> int | None:
    try:
        value = int(response.headers.get("content-length") or 0)
    except ValueError:
        return None
    return value if value > 0 else None


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


def _textish_content_type(content_type: str) -> bool:
    return bool(re.search(r"html|json|text|xml|javascript", content_type or "", re.I))


def _looks_like_login_or_error(body: bytes) -> bool:
    if not body:
        return False
    text = body[:8192].decode("utf-8", errors="ignore").lower()
    return any(marker in text for marker in ["login", "signin", "sign in", "请登录", "登录", "unauthorized", "forbidden"])


def preflight_media_resource(
    candidate: ResourceCandidate,
    cookies: list[BrowserCookie],
    referer: str,
    timeout: int = 12,
) -> MediaPreflightResult:
    kind = effective_resource_kind(candidate)
    resolved_url = candidate.url
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
            message="浏览器只暴露 blob URL，后端无法直接下载；需要可见 mp4/m3u8/mpd 或本地视频。",
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
    headers = download_headers_for_candidate(candidate, cookies, referer, url=resolved_url)
    if kind == "video":
        headers.setdefault("Accept", "*/*")
        headers.setdefault("Range", "bytes=0-4095")
    elif kind == "hls":
        headers.setdefault("Accept", "application/vnd.apple.mpegurl,application/x-mpegURL,text/plain,*/*;q=0.8")
    else:
        headers.setdefault("Accept", "application/dash+xml,application/xml,text/xml,*/*;q=0.8")

    try:
        with requests.get(resolved_url, headers=headers, stream=True, timeout=timeout, allow_redirects=True) as response:
            body = _read_probe_bytes(response)
            content_type = response.headers.get("content-type", "")
            content_length = _response_content_length(response)
            base = {
                "strategy": strategy,
                "kind": kind,
                "url": candidate.url,
                "resolved_url": resolved_url,
                "status_code": response.status_code,
                "content_type": content_type,
                "content_length": content_length,
                "bytes_checked": len(body),
                "request_header_names": _safe_request_header_names(headers),
                "warnings": warnings,
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

            if kind == "hls":
                text = body.decode("utf-8", errors="ignore")
                if "#EXTM3U" not in text and "mpegurl" not in content_type.lower():
                    warnings.append("响应不像标准 HLS manifest，实际下载可能失败。")
                if re.search(r"#EXT-X-KEY:[^\n]*(SAMPLE-AES|skd://|widevine|fairplay)", text, re.I):
                    return MediaPreflightResult(
                        **{**base, "warnings": warnings},
                        ok=True,
                        downloadable=False,
                        code="drm_or_encrypted",
                        message="HLS manifest 疑似 DRM/加密流，第一版不尝试绕过。",
                    )
                if re.search(r"#EXT-X-KEY:[^\n]*METHOD=AES-128", text, re.I):
                    warnings.append("HLS 使用 AES-128 key，ffmpeg 仍可能因 key 权限失败。")

            if kind == "dash":
                text = body.decode("utf-8", errors="ignore")
                if "<MPD" not in text and "dash+xml" not in content_type.lower():
                    warnings.append("响应不像标准 DASH manifest，实际下载可能失败。")
                if re.search(r"ContentProtection|widevine|playready|urn:uuid", text, re.I):
                    return MediaPreflightResult(
                        **{**base, "warnings": warnings},
                        ok=True,
                        downloadable=False,
                        code="drm_or_encrypted",
                        message="DASH manifest 含 ContentProtection，疑似 DRM/加密流。",
                    )

            if kind == "video" and len(body) <= 0:
                return MediaPreflightResult(
                    **base,
                    ok=True,
                    downloadable=False,
                    code="download_forbidden",
                    message="媒体预检没有读到任何视频字节。",
                )

            return MediaPreflightResult(
                **{**base, "warnings": warnings},
                ok=True,
                downloadable=True,
                code="",
                message="后端可以访问该候选资源；正式任务仍会执行完整下载和合并。",
            )
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
            request_header_names=_safe_request_header_names(headers),
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
            strategy = self._strategy_for_candidate(candidate)
            try:
                media_path = self._download_candidate(candidate, cookies, page_url, title)
                self._record_attempt(
                    strategy=strategy,
                    candidate=candidate,
                    status="success",
                    message="浏览器候选资源直取成功。",
                    output_path=media_path,
                )
                return media_path, candidate
            except DownloadError as exc:
                self._record_attempt(strategy=strategy, candidate=candidate, status="failed", code=exc.code, message=exc.message)
                failed_urls.add(candidate.url)
                last_error = exc
                continue

        page_fallbacks = fallback_page_urls(page_url, resources)
        for fallback_url in page_fallbacks:
            page_scan_resources = self._discover_page_resources(fallback_url, cookies)
            for candidate in self._candidate_resources(page_scan_resources):
                if candidate.url in failed_urls:
                    continue
                strategy = self._strategy_for_candidate(candidate)
                try:
                    media_path = self._download_candidate(candidate, cookies, fallback_url, title)
                    self._record_attempt(
                        strategy=strategy,
                        candidate=candidate,
                        status="success",
                        message="页面文本扫描候选资源直取成功。",
                        output_path=media_path,
                    )
                    return media_path, candidate
                except DownloadError as exc:
                    self._record_attempt(strategy=strategy, candidate=candidate, status="failed", code=exc.code, message=exc.message)
                    failed_urls.add(candidate.url)
                    last_error = exc
                    continue

        for fallback_url in page_fallbacks:
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
        resources = self._with_inferred_manifest_resources(resources)
        dedup: dict[str, ResourceCandidate] = {}
        for item in resources:
            if not item.url or item.url.startswith(("chrome-extension:", "data:")):
                continue
            kind = effective_resource_kind(item)
            item.kind = kind
            boost = (8 if item.is_main_video else 0) + (10 if item.playback_match else 0)
            item.score = min(100, max(item.score, score_candidate(item)) + boost)
            if kind in {"hls", "dash", "video"}:
                dedup[item.url] = item
        return sorted(dedup.values(), key=lambda item: item.score, reverse=True)

    def _discover_page_resources(self, page_url: str, cookies: list[BrowserCookie]) -> list[ResourceCandidate]:
        if not re.match(r"^https?://", page_url, re.I):
            return []
        headers = download_headers_for_candidate(None, cookies, page_url, url=page_url)
        headers.setdefault("Accept", "text/html,application/xhtml+xml,application/json,text/plain,*/*;q=0.8")
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
                    return []
                if response.status_code >= 400:
                    self._record_attempt(
                        strategy="page-scan",
                        url=page_url,
                        status="failed",
                        code="download_forbidden",
                        message=f"页面扫描返回 HTTP {response.status_code}。",
                    )
                    return []
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
                    return []
                content_length = int(response.headers.get("content-length") or 0)
                if content_length > MAX_PAGE_SCAN_BYTES:
                    self._record_attempt(
                        strategy="page-scan",
                        url=page_url,
                        status="skipped",
                        code="unsupported_manifest",
                        message="页面响应过大，跳过文本媒体 URL 扫描。",
                    )
                    return []
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
                        return []
                    chunks.append(chunk)
                text = b"".join(chunks).decode(response.encoding or "utf-8-sig", errors="replace")
                base_url = final_url
                resources = extract_media_resources_from_text(text, base_url, "page-scan")
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
                            request_headers={"Referer": page_url},
                        ),
                    )
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
            return []

    def _with_inferred_manifest_resources(self, resources: list[ResourceCandidate]) -> list[ResourceCandidate]:
        enriched = list(resources)
        known_urls = {item.url for item in resources if item.url}
        for item in resources:
            inferred_url = infer_manifest_url_from_fragment(item.url)
            if not inferred_url or inferred_url in known_urls:
                continue
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
        return enriched

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
                message=message,
                output_path=str(output_path) if output_path else "",
                bytes_downloaded=downloaded,
                status_code=candidate.status_code if candidate else None,
                content_length=candidate.content_length if candidate else None,
                mime=candidate.mime if candidate else "",
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
        media = [path for path in after if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov", ".m4v"}]
        if not media:
            media = [path for path in self.download_dir.glob("*") if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov", ".m4v"}]
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

    def _download_file(self, candidate: ResourceCandidate, cookies: list[BrowserCookie], referer: str, title: str) -> Path:
        url = candidate.url
        suffix = Path(urlparse(url).path).suffix or ".mp4"
        output = self.download_dir / f"{_clean_filename(title)}_direct{suffix}"
        base_headers = download_headers_for_candidate(candidate, cookies, referer)

        def attempt(headers: dict[str, str]) -> Path:
            if output.exists():
                output.unlink()
            with requests.get(url, headers=headers, stream=True, timeout=30) as response:
                if response.status_code in {401, 403}:
                    raise DownloadError("auth_required", f"媒体资源返回 HTTP {response.status_code}。")
                if response.status_code == 416:
                    raise DownloadError("download_forbidden", "媒体资源拒绝当前 Range 请求。")
                if response.status_code >= 400:
                    raise DownloadError("download_forbidden", f"媒体资源返回 HTTP {response.status_code}。")
                content_type = response.headers.get("content-type", "")
                chunks = response.iter_content(chunk_size=1024 * 1024)
                first_chunk = b""
                for chunk in chunks:
                    if chunk:
                        first_chunk = chunk
                        break
                if _textish_content_type(content_type) and _looks_like_login_or_error(first_chunk):
                    raise DownloadError("auth_required", "媒体资源返回登录/错误页面，而不是视频文件。")
                with output.open("wb") as file:
                    if first_chunk:
                        file.write(first_chunk)
                    for chunk in chunks:
                        if chunk:
                            file.write(chunk)
            if not output.exists() or output.stat().st_size < 4096:
                raise DownloadError("download_forbidden", "下载文件过小，可能不是有效视频。")
            return output

        try:
            return attempt(base_headers)
        except DownloadError as first_error:
            if output.exists():
                output.unlink()
            range_headers = dict(base_headers)
            range_headers["Range"] = "bytes=0-"
            try:
                return attempt(range_headers)
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
            with requests.get(candidate.url, headers=probe_headers, stream=True, timeout=15, allow_redirects=True) as response:
                body = _read_probe_bytes(response)
                content_type = response.headers.get("content-type", "")
                if response.status_code in {401, 403}:
                    raise DownloadError("auth_required", f"manifest returned HTTP {response.status_code}; refresh login cookies and retry.")
                if response.status_code >= 400:
                    raise DownloadError("download_forbidden", f"manifest returned HTTP {response.status_code}.")
                if _textish_content_type(content_type) and _looks_like_login_or_error(body):
                    raise DownloadError("auth_required", "manifest URL returned a login/error page instead of an HLS/DASH manifest.")

                text = body.decode("utf-8", errors="ignore")
                if kind == "hls" and re.search(r"#EXT-X-KEY:[^\n]*(SAMPLE-AES|skd://|widevine|fairplay)", text, re.I):
                    raise DownloadError("drm_or_encrypted", "HLS manifest appears to use DRM/encrypted streaming.")
                if kind == "dash" and re.search(r"ContentProtection|widevine|playready|urn:uuid", text, re.I):
                    raise DownloadError("drm_or_encrypted", "DASH manifest contains ContentProtection and may be DRM protected.")
        except DownloadError:
            raise
        except requests.RequestException as exc:
            raise DownloadError("download_forbidden", f"manifest preflight failed: {exc}") from exc

    def _download_manifest(self, candidate: ResourceCandidate, cookies: list[BrowserCookie], referer: str, title: str) -> Path:
        url = candidate.url
        ffmpeg = ffmpeg_bin()
        if not ffmpeg:
            raise DownloadError("unsupported_manifest", "未找到 ffmpeg，无法合并 HLS/DASH。")
        output = self.download_dir / f"{_clean_filename(title)}_manifest.mp4"
        request_headers = download_headers_for_candidate(candidate, cookies, referer)
        self._probe_manifest_before_ffmpeg(candidate, request_headers)
        kind = effective_resource_kind(candidate)
        user_agent = request_headers.pop("User-Agent", "Mozilla/5.0 LearnNoteAssistant/0.1")
        headers = [f"{name}: {value}" for name, value in request_headers.items() if value]
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        if headers:
            cmd += ["-headers", "\r\n".join(headers) + "\r\n"]
        if kind in {"hls", "dash"}:
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
