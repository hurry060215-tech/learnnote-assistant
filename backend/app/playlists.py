"""Bounded, no-download playlist previews; never crawl unrelated sites."""
from itertools import islice
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .source_input import HTTP_URL_RE, normalize_source_input

ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "bilibili.com", "www.bilibili.com", "m.bilibili.com"}


def preview_playlist(value: str) -> dict:
    normalized = normalize_source_input(value)
    parsed = urlsplit(normalized.url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ValueError("playlist_platform_unsupported")
    preview_url = normalized.url
    if normalized.platform == "bilibili" and normalized.source_id:
        # Single-video normalization supplies p=1. Anthology discovery must not
        # turn that default into an explicit part selection for yt-dlp.
        raw_url = HTTP_URL_RE.search(normalized.raw)
        explicit_part = raw_url and any(key == "p" for key, _ in parse_qsl(urlsplit(raw_url.group(0)).query, keep_blank_values=True))
        if not explicit_part:
            preview_url = urlunsplit(parsed._replace(query=urlencode([
                (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "p"])))
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True, "lazy_playlist": True, "playlistend": 24, "socket_timeout": 10, "retries": 0, "extractor_retries": 0, "cachedir": False}) as downloader:
            info = downloader.extract_info(preview_url, download=False)
            entries = []
            items = (info or {}).get("entries") or []
            # An explicitly selected Bilibili part is a video, not a playlist.
            # Preserve that selection rather than expanding its parent course.
            if (normalized.platform == "bilibili" and normalized.source_id and info
                    and info.get("_type") not in {"playlist", "multi_video"}
                    and "entries" not in info and info.get("id")):
                items = [{"url": normalized.url, "title": info.get("title")}]
            for item in islice(items, 24):
                if not isinstance(item, dict):
                    continue
                target = str(item.get("webpage_url") or item.get("url") or "")
                if not target.startswith(("http://", "https://")) and item.get("ie_key", "").lower().startswith("youtube"):
                    target = "https://www.youtube.com/watch?v=" + str(item.get("id") or target)
                candidate = normalize_source_input(target)
                if urlsplit(candidate.url).hostname not in ALLOWED_HOSTS:
                    continue
                entries.append({"kind": "url", "url": candidate.url, "title": str(item.get("title") or candidate.default_title)[:500]})
    except Exception as exc:
        raise ValueError("playlist_preview_unavailable") from exc
    if not entries:
        raise ValueError("playlist_has_no_accessible_entries")
    return {"title": str(info.get("title") or "课程")[:200], "sources": entries, "max_entries": 24, "requires_confirmation": True, "download_started": False}
