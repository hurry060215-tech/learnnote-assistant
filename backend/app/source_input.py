from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse


HTTP_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
BVID_RE = re.compile(r"(?<![A-Za-z0-9])BV([A-Za-z0-9]{10})(?![A-Za-z0-9])", re.IGNORECASE)
AVID_RE = re.compile(r"(?<![A-Za-z0-9])av(\d{1,20})(?![A-Za-z0-9])", re.IGNORECASE)
CORRUPTED_TITLE_MARKERS = ("�", "锟", "鏍", "璇", "鐨", "浠", "鈥")


class SourceInputError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedSource:
    raw: str
    url: str
    platform: str
    source_id: str
    source_kind: str
    changed: bool

    @property
    def default_title(self) -> str:
        if self.platform == "bilibili" and self.source_id:
            return f"B站视频 · {self.source_id}"
        if self.platform == "youtube":
            return "YouTube 视频"
        return fallback_title_for_url(self.url)

    def as_dict(self) -> dict[str, object]:
        return {
            "input": self.raw,
            "normalized_url": self.url,
            "platform": self.platform,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "changed": self.changed,
            "default_title": self.default_title,
        }


def _strip_trailing_url_punctuation(value: str) -> str:
    return value.rstrip(".,;:!?，。；：！？)]}）】》")


def _url_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host == "b23.tv" or host.endswith(".bilibili.com"):
        return "bilibili"
    if host in {"youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"} or host.endswith(".youtube.com"):
        return "youtube"
    return "web"


def _bilibili_id_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    bvid = BVID_RE.search(path)
    if bvid:
        return f"BV{bvid.group(1)}"
    avid = AVID_RE.search(path)
    if avid:
        return f"av{avid.group(1)}"
    return ""


def _canonical_bilibili_part_url(url: str, source_id: str) -> str:
    if not source_id:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    part = str(query.get("p") or "").strip()
    query["p"] = part if part.isdigit() and int(part) > 0 else "1"
    return urlunparse(parsed._replace(query=urlencode(query)))


def normalize_source_input(value: str) -> NormalizedSource:
    raw = str(value or "").strip().strip("\"'")
    if not raw:
        raise SourceInputError("请输入 B站 BV号、视频页面链接或媒体直链。")

    url_match = HTTP_URL_RE.search(raw)
    if url_match:
        url = _strip_trailing_url_punctuation(url_match.group(0))
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise SourceInputError("链接必须是有效的 http 或 https 地址。")
        platform = _url_platform(url)
        source_id = _bilibili_id_from_url(url) if platform == "bilibili" else ""
        if platform == "bilibili" and source_id:
            url = _canonical_bilibili_part_url(url, source_id)
        return NormalizedSource(raw, url, platform, source_id, "url", url != raw)

    bvid = BVID_RE.search(raw)
    if bvid:
        source_id = f"BV{bvid.group(1)}"
        url = f"https://www.bilibili.com/video/{source_id}?p=1"
        return NormalizedSource(raw, url, "bilibili", source_id, "bvid", True)

    avid = AVID_RE.search(raw)
    if avid:
        source_id = f"av{avid.group(1)}"
        url = f"https://www.bilibili.com/video/{source_id}?p=1"
        return NormalizedSource(raw, url, "bilibili", source_id, "avid", True)

    raise SourceInputError("无法识别该输入。可粘贴 B站 BV/AV 号、B站/YouTube 页面链接，或 mp4/m3u8/mpd 直链。")


def title_looks_corrupted(value: str) -> bool:
    title = str(value or "").strip()
    if not title:
        return True
    question_ratio = title.count("?") / max(1, len(title))
    marker_count = sum(title.count(marker) for marker in CORRUPTED_TITLE_MARKERS)
    return question_ratio >= 0.18 or marker_count >= 2


def fallback_title_for_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    path = Path(unquote(parsed.path))
    stem = path.stem.strip(" ._-")
    if path.suffix.lower() in {".mp4", ".m4s", ".m4v", ".mov", ".mkv", ".webm", ".flv", ".avi"} and stem and len(stem) >= 3 and not title_looks_corrupted(stem):
        return stem[:160]
    host = (parsed.hostname or "").removeprefix("www.")
    if host:
        return f"学习视频 · {host}"
    return "学习视频"


def clean_task_title(title: str, page_url: str = "", default_title: str = "") -> str:
    value = re.sub(r"\s+", " ", str(title or "")).strip(" .")
    if value and not title_looks_corrupted(value):
        return value[:180]
    fallback = str(default_title or "").strip()
    if fallback and not title_looks_corrupted(fallback):
        return fallback[:180]
    return fallback_title_for_url(page_url)
