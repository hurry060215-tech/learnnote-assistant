"""Pure ranking and pairing policy for discovered media candidates."""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urlparse

from .media_kinds import classify_resource, effective_resource_kind
from .models import ResourceCandidate


def _is_http_url(url: str) -> bool:
    try:
        return urlparse(url or "").scheme.lower() in {"http", "https"}
    except (TypeError, ValueError):
        return False


def score_kind(url: str, source: str, kind: str) -> int:
    score = {"hls": 95, "dash": 95, "video": 85, "audio": 35, "fragment": 15, "subtitle": 60, "blob": 5}.get(kind, 0)
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
    score_url = candidate.resolved_url or candidate.url
    return score_kind(score_url, candidate.source, effective_resource_kind(candidate))


def kind_rank(kind: str) -> int:
    return {"hls": 6, "dash": 6, "video": 5, "audio": 2, "fragment": 3, "subtitle": 2, "blob": 1}.get(kind, 0)


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
        "source-element": 8,
        "blob-source": 8,
        "range-near-playhead": 7,
        "fragment-near-playhead": 6,
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
        "fragment-near-playhead": "播放进度附近分片请求",
        "manifest-near-playhead": "播放进度附近 Manifest 请求",
        "resolved-final-url": "跳转后的真实媒体",
        "recent-media-request": "最近播放请求",
        "same-site-request": "同站请求",
        "inferred-from-fragment": "分片推断",
    }.get(match, match)


def should_guess_sibling_manifest_with_blob_boundary(candidate: ResourceCandidate) -> bool:
    match = candidate.playback_match or ""
    if match in {"blob-source", "blob-same-frame", "range-near-playhead", "fragment-near-playhead", "manifest-near-playhead"}:
        return True
    return bool(candidate.is_main_video and source_rank(candidate.source or "") >= source_rank("webRequest"))


def candidate_rank_key(candidate: ResourceCandidate, order: int = 0) -> tuple[int, int, int, int, int, int, int, int, float, int, int]:
    kind = effective_resource_kind(candidate)
    return (
        1 if candidate.user_selected else 0,
        1 if candidate.is_main_video else 0,
        0 if candidate.source == "manifest-guess" else 1,
        playback_match_rank(candidate.playback_match or ""),
        1 if kind in {"hls", "dash", "video"} else 0,
        kind_rank(kind),
        source_rank(candidate.source or ""),
        candidate.score or 0,
        candidate.time_stamp or 0,
        candidate.content_length or 0,
        -order,
    )


def _same_url_host(left: str, right: str) -> bool:
    return (urlparse(left or "").netloc or "").lower() == (urlparse(right or "").netloc or "").lower()


def _shared_path_prefix_score(left: str, right: str) -> int:
    left_parts = [part for part in urlparse(left or "").path.split("/") if part]
    right_parts = [part for part in urlparse(right or "").path.split("/") if part]
    if not left_parts or not right_parts:
        return 0
    shared = 0
    for left_part, right_part in zip(left_parts, right_parts):
        if left_part != right_part:
            break
        shared += 1
    if shared >= 2:
        return 3
    if shared == 1:
        return 1
    parent_words = " ".join(left_parts[:-1] + right_parts[:-1]).lower()
    return 1 if re.search(r"course|lesson|video|media|stream|dash|hls|vod", parent_words) else 0


def _companion_audio_match_score(video: ResourceCandidate, audio: ResourceCandidate) -> int:
    if effective_resource_kind(video) != "video" or effective_resource_kind(audio) != "audio":
        return -100
    score = 0
    if video.tab_id is not None and audio.tab_id is not None and video.tab_id == audio.tab_id:
        score += 2
    if video.frame_id is not None and audio.frame_id is not None and video.frame_id == audio.frame_id:
        score += 4
    if video.playback_match and video.playback_match == audio.playback_match:
        score += 4
    elif audio.playback_match:
        score += 1
    if video.is_main_video and audio.is_main_video:
        score += 2
    if video.blob_url and video.blob_url == audio.blob_url:
        score += 4
    if _same_url_host(video.url, audio.url):
        score += 2
    score += _shared_path_prefix_score(video.url, audio.url)
    if video.page_url and audio.page_url and video.page_url == audio.page_url:
        score += 1
    if video.time_stamp and audio.time_stamp and abs(video.time_stamp - audio.time_stamp) <= 5000:
        score += 1
    if video.current_time is not None and audio.current_time is not None and abs(video.current_time - audio.current_time) <= 3:
        score += 2
    if video.duration and audio.duration and abs(video.duration - audio.duration) <= 3:
        score += 2
    if video.source and audio.source and video.source == audio.source:
        score += 1
    return score


def _attach_companion_audio_resources(resources: list[ResourceCandidate]) -> list[ResourceCandidate]:
    audio_candidates = [item for item in resources if effective_resource_kind(item) == "audio" and _is_http_url(item.url)]
    if not audio_candidates:
        return resources
    paired: list[ResourceCandidate] = []
    for item in resources:
        if effective_resource_kind(item) != "video" or item.audio_url:
            paired.append(item)
            continue
        matches = sorted(
            ((_companion_audio_match_score(item, audio), audio.score or 0, index, audio) for index, audio in enumerate(audio_candidates)),
            key=lambda value: value[:3],
            reverse=True,
        )
        best_score, _, _, audio = matches[0] if matches else (-100, 0, 0, None)
        if audio is None or best_score < 6:
            paired.append(item)
            continue
        merged = item.model_copy(deep=True)
        merged.audio_url = audio.url
        merged.audio_mime = audio.mime or "audio/mp4"
        merged.score = min(100, max(merged.score or 0, score_candidate(merged)) + 7)
        if not merged.playback_match and audio.playback_match:
            merged.playback_match = audio.playback_match
        for name, value in (audio.request_headers or {}).items():
            merged.request_headers.setdefault(name, value)
        paired.append(merged)
    return paired


def rank_enriched_candidates(
    resources: list[ResourceCandidate],
    is_untrusted_page_scan_candidate: Callable[[ResourceCandidate], bool] | None = None,
) -> list[ResourceCandidate]:
    is_untrusted = is_untrusted_page_scan_candidate or (lambda _candidate: False)
    dedup: dict[str, tuple[int, ResourceCandidate]] = {}
    for order, item in enumerate(_attach_companion_audio_resources(resources)):
        if not item.url or item.url.startswith(("chrome-extension:", "data:")):
            continue
        if is_untrusted(item):
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


__all__ = [
    "candidate_rank_key",
    "kind_rank",
    "playback_match_label",
    "playback_match_rank",
    "rank_enriched_candidates",
    "score_candidate",
    "score_kind",
    "score_resource",
    "should_guess_sibling_manifest_with_blob_boundary",
    "source_rank",
]
