"""Bounded, no-download playlist previews; never crawl unrelated sites."""
from itertools import islice
from urllib.parse import urlsplit

from .source_input import normalize_source_input

ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "bilibili.com", "www.bilibili.com", "m.bilibili.com"}


def preview_playlist(value: str) -> dict:
    normalized = normalize_source_input(value)
    parsed = urlsplit(normalized.url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ValueError("playlist_platform_unsupported")
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True, "lazy_playlist": True, "playlistend": 24, "socket_timeout": 10, "retries": 0, "extractor_retries": 0, "cachedir": False}) as downloader:
            info = downloader.extract_info(normalized.url, download=False)
            entries = []
            for item in islice((info or {}).get("entries") or [], 24):
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
