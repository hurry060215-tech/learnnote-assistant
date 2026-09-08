"""Bilibili timed captions, fetched before any video download.

The view -> selected page cid -> player -> subtitle JSON flow follows BiliNote's
MIT-licensed backend/app/downloaders/bilibili_subtitle.py (Jeffery Huang, 2024).
LearnNote keeps cookies scoped to each destination and does not store sessions.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


class BilibiliSubtitleError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


@dataclass
class BilibiliSubtitleResult:
    path: Path | None = None
    title: str = ""
    duration: float = 0


def _get_json(url: str, headers_for, *, params=None):
    with requests.get(url, params=params, headers=headers_for(url), timeout=(8, 15),
                      allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise BilibiliSubtitleError("subtitle_unavailable", f"B 站字幕请求未成功（HTTP {response.status_code}）。")
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > 8 * 1024 * 1024:
                raise BilibiliSubtitleError("subtitle_unavailable", "字幕响应超过安全大小限制。")
        try:
            value = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise BilibiliSubtitleError("subtitle_unavailable", "B 站字幕响应格式无法解析。") from exc
        if not isinstance(value, dict):
            raise BilibiliSubtitleError("subtitle_unavailable", "B 站字幕响应格式无效。")
        return value


def _timestamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def fetch_bilibili_subtitle(page_url: str, output: Path, headers_for) -> BilibiliSubtitleResult | None:
    parsed = urlparse(page_url)
    host = (parsed.hostname or "").lower()
    if host not in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}:
        return None
    match = re.search(r"/video/(BV[0-9A-Za-z]+|av[0-9]+)", parsed.path)
    if not match:
        return None
    identity = {"bvid": match[1]} if match[1].startswith("BV") else {"aid": match[1][2:]}
    try:
        part = int(parse_qs(parsed.query).get("p", ["1"])[0])
    except ValueError as exc:
        raise BilibiliSubtitleError("source_changed", "分集编号无效；请打开具体视频分集后重试。") from exc
    view = _get_json("https://api.bilibili.com/x/web-interface/view", headers_for, params=identity)
    if view.get("code") != 0:
        raise BilibiliSubtitleError("subtitle_unavailable", "暂时无法读取 B 站视频信息；将继续其他字幕获取方式。")
    data = view.get("data") or {}
    pages = data.get("pages") or []
    if pages:
        if part < 1 or part > len(pages):
            raise BilibiliSubtitleError("source_changed", "请求的分集不存在，未使用其他分集的字幕。")
        selected = pages[part - 1]
    else:
        if part != 1:
            raise BilibiliSubtitleError("source_changed", "无法核实请求的分集，未使用其他分集的字幕。")
        selected = data
    cid = selected.get("cid")
    if not cid:
        raise BilibiliSubtitleError("subtitle_unavailable", "视频分集信息缺少标识，未取得字幕。")
    result = BilibiliSubtitleResult(title=str(data.get("title") or ""), duration=float(selected.get("duration") or 0))
    player = _get_json("https://api.bilibili.com/x/player/wbi/v2", headers_for, params={**identity, "cid": cid})
    if player.get("code") != 0:
        raise BilibiliSubtitleError("subtitle_unavailable", "B 站字幕列表暂不可访问；将继续其他字幕获取方式。")
    pdata = player.get("data") or {}
    tracks = (pdata.get("subtitle") or {}).get("subtitles") or []
    if not tracks:
        if pdata.get("need_login_subtitle"):
            raise BilibiliSubtitleError("auth_required", "字幕需要 B 站登录态；本次未取得可访问字幕，不能判断视频没有字幕。")
        return result
    def rank(track):
        lang = str(track.get("lan") or "").lower()
        zh = lang.startswith("zh") or lang == "ai-zh"
        return (0 if zh and not track.get("ai_type") and not lang.startswith("ai-") else 1 if zh else 2)
    tracks = sorted((t for t in tracks if isinstance(t, dict) and t.get("subtitle_url")), key=rank)
    if not tracks:
        raise BilibiliSubtitleError("auth_required", "字幕轨未提供可访问地址；请从已登录的视频页交接。")
    track_url = str(tracks[0]["subtitle_url"])
    if track_url.startswith("//"):
        track_url = "https:" + track_url
    dest = urlparse(track_url)
    if dest.scheme != "https" or dest.username or dest.password or dest.port not in {None, 443} or not any(
        (dest.hostname or "").lower() == domain or (dest.hostname or "").lower().endswith("." + domain)
        for domain in ("hdslb.com", "bilibili.com")
    ):
        raise BilibiliSubtitleError("subtitle_unavailable", "字幕地址不属于可信的 B 站字幕服务，未发送登录态。")
    subtitle = _get_json(track_url, headers_for)
    segments = []
    for cue in subtitle.get("body") or []:
        try:
            start, end = float(cue["from"]), float(cue["to"])
            text = re.sub(r"\s+", " ", str(cue.get("content") or "")).strip()
            if text and math.isfinite(start) and math.isfinite(end) and 0 <= start < end:
                segments.append((start, end, text))
        except (TypeError, KeyError, ValueError):
            continue
    if not segments:
        return result
    segments.sort()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join(f"{i}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}" for i, (start, end, text) in enumerate(segments, 1)) + "\n", encoding="utf-8")
    result.path = output
    return result
