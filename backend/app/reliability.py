from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urldefrag

from .models import (
    CurrentPageTaskRequest,
    EvidenceCoverage,
    EvidenceGate,
    FrameSample,
    MediaIntegrity,
    SourceIdentity,
    TranscriptResult,
)
from .source_input import SourceInputError, normalize_source_input


MIN_TRANSCRIPT_CHARS = 20
MIN_TRANSCRIPT_COVERAGE = 0.25
MIN_TIMELINE_CHECKPOINT_COVERAGE = 0.60
MIN_VISUAL_CHECKPOINT_COVERAGE = 0.60


def _canonical_url(value: str) -> str:
    return urldefrag(str(value or "").strip())[0]


def _stable_fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def current_page_source_identity(request: CurrentPageTaskRequest) -> SourceIdentity:
    try:
        normalized = normalize_source_input(request.page_url)
        page_url = normalized.url
        platform = normalized.platform
        platform_id = normalized.source_id
    except SourceInputError:
        page_url = _canonical_url(request.page_url)
        platform = "web"
        platform_id = ""
    resources = sorted(
        (
            _canonical_url(item.url),
            _canonical_url(item.audio_url),
            str(item.kind or ""),
            str(item.source or ""),
            int(item.frame_id) if item.frame_id is not None else None,
        )
        for item in request.resources
        if item.url or item.audio_url
    )
    active = request.active_video
    fingerprint_payload = {
        "page_url": page_url,
        "title": " ".join((request.title or "").split()),
        "platform": platform,
        "platform_id": platform_id,
        "resources": resources,
        "active_video": {
            "src": _canonical_url(active.src) if active else "",
            "frame_url": _canonical_url(active.frame_url) if active else "",
            "duration": round(float(active.duration or 0), 3) if active else 0,
            "frame_id": active.frame_id if active else None,
        },
    }
    return SourceIdentity(
        page_url=page_url,
        platform=platform,
        platform_id=platform_id,
        title=request.title,
        resource_fingerprint=_stable_fingerprint(fingerprint_payload),
    )


def local_source_identity(title: str, integrity: MediaIntegrity) -> SourceIdentity:
    return SourceIdentity(
        platform="local",
        platform_id=integrity.sha256[:16],
        title=title,
        resource_fingerprint=integrity.sha256,
        media_sha256=integrity.sha256,
    )


def validate_source_identity(expected: SourceIdentity, actual: SourceIdentity) -> list[str]:
    reasons = []
    if expected.resource_fingerprint and expected.resource_fingerprint != actual.resource_fingerprint:
        reasons.append("resource_fingerprint_changed")
    if expected.page_url and _canonical_url(expected.page_url) != _canonical_url(actual.page_url):
        reasons.append("page_url_changed")
    if expected.platform_id and expected.platform_id != actual.platform_id:
        reasons.append("platform_id_changed")
    if expected.title and actual.title and " ".join(expected.title.split()) != " ".join(actual.title.split()):
        reasons.append("title_changed")
    return reasons


def _merged_covered_seconds(transcript: TranscriptResult, duration: float) -> float:
    intervals = []
    upper = max(0.0, duration)
    for segment in transcript.segments:
        start = max(0.0, min(upper, float(segment.start or 0))) if upper else max(0.0, float(segment.start or 0))
        end = max(start, min(upper, float(segment.end or start))) if upper else max(start, float(segment.end or start))
        if end > start and str(segment.text or "").strip():
            intervals.append((start, end))
    total = 0.0
    current_start = current_end = None
    for start, end in sorted(intervals):
        if current_start is None:
            current_start, current_end = start, end
        elif start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    if current_start is not None:
        total += current_end - current_start
    return total


def _checkpoint_times(duration: float, count: int = 5) -> list[float]:
    if duration <= 0:
        return []
    if duration < 5:
        return [duration / 2]
    if duration <= 30:
        return [duration * ratio for ratio in (0.20, 0.50, 0.80)]
    return [duration * ratio for ratio in (0.10, 0.30, 0.50, 0.70, 0.90)][:count]


def _near_transcript(transcript: TranscriptResult, timestamp: float, radius: float) -> bool:
    return any(
        str(segment.text or "").strip()
        and float(segment.end or segment.start) >= timestamp - radius
        and float(segment.start or 0) <= timestamp + radius
        for segment in transcript.segments
    )


def _near_frame(samples: list[FrameSample], timestamp: float, radius: float) -> bool:
    return any(abs(float(sample.timestamp) - timestamp) <= radius for sample in samples)


def _is_subtitle_source(source: str) -> bool:
    value = str(source or "").strip().lower()
    return "subtitle" in value or value in {"platform-caption", "browser-caption"}


def calculate_evidence_coverage(
    integrity: MediaIntegrity,
    transcript: TranscriptResult,
    frame_samples: list[FrameSample],
    *,
    visual_enabled: bool,
    source_identity_reasons: list[str] | None = None,
) -> EvidenceCoverage:
    duration = float(integrity.duration or 0)
    covered_seconds = _merged_covered_seconds(transcript, duration)
    transcript_ratio = min(1.0, covered_seconds / duration) if duration > 0 else 0.0
    text_chars = len(re.sub(r"\s+", "", transcript.full_text or ""))
    checkpoints = _checkpoint_times(duration)
    radius = min(30.0, max(5.0, duration * 0.05)) if duration else 5.0
    transcript_hits = sum(_near_transcript(transcript, value, radius) for value in checkpoints)
    visual_hits = sum(_near_frame(frame_samples, value, radius) for value in checkpoints)
    checkpoint_ratio = transcript_hits / len(checkpoints) if checkpoints else 0.0
    visual_ratio = visual_hits / len(checkpoints) if checkpoints else 0.0
    subtitle_source = _is_subtitle_source(transcript.source)
    gates: list[EvidenceGate] = []
    blocking_reasons: list[str] = []

    def gate(name: str, passed: bool, detail: str, *, skipped: bool = False) -> None:
        status = "skipped" if skipped else "passed" if passed else "failed"
        gates.append(EvidenceGate(name=name, passed=passed, status=status, detail=detail))
        if not passed and not skipped:
            blocking_reasons.append(name)

    source_reasons = list(source_identity_reasons or [])
    gate("source_identity", not source_reasons, ", ".join(source_reasons) or "Source identity is unchanged.")
    valid_tracks = integrity.has_video and integrity.has_audio
    gate(
        "media_tracks",
        valid_tracks,
        "Both audio and video tracks are present."
        if valid_tracks
        else f"Media status is {integrity.status}; both video and audio tracks are required for a composite video note.",
    )
    gate(
        "transcript_text",
        text_chars >= MIN_TRANSCRIPT_CHARS,
        f"Transcript contains {text_chars} non-whitespace characters.",
    )
    ratio_threshold = 0.15 if duration <= 30 else MIN_TRANSCRIPT_COVERAGE
    gate(
        "transcript_coverage",
        transcript_ratio >= ratio_threshold,
        f"Timed transcript covers {transcript_ratio:.1%} of {duration:.1f}s (minimum {ratio_threshold:.0%}).",
    )
    gate(
        "timeline_consistency",
        checkpoint_ratio >= MIN_TIMELINE_CHECKPOINT_COVERAGE,
        f"Transcript matches {transcript_hits}/{len(checkpoints)} timeline checkpoints.",
    )
    visual_required = bool(visual_enabled and integrity.has_video)
    gate(
        "visual_timeline_consistency",
        visual_ratio >= MIN_VISUAL_CHECKPOINT_COVERAGE if visual_required else True,
        f"Frames match {visual_hits}/{len(checkpoints)} timeline checkpoints."
        if visual_required
        else "Visual understanding is disabled or the source has no video track.",
        skipped=not visual_required,
    )
    can_summarize = not blocking_reasons
    return EvidenceCoverage(
        status="ready" if can_summarize else "blocked",
        can_summarize=can_summarize,
        transcript_source=transcript.source,
        transcript_char_count=text_chars,
        transcript_covered_seconds=round(covered_seconds, 3),
        transcript_coverage_ratio=round(transcript_ratio, 6),
        checkpoint_count=len(checkpoints),
        matched_transcript_checkpoints=transcript_hits,
        matched_visual_checkpoints=visual_hits,
        timeline_consistency_ratio=round(checkpoint_ratio, 6),
        visual_coverage_ratio=round(visual_ratio, 6),
        platform_subtitle_coverage_ratio=round(transcript_ratio, 6) if subtitle_source else 0.0,
        local_transcription_coverage_ratio=0.0 if subtitle_source else round(transcript_ratio, 6),
        visual_frame_count=len(frame_samples),
        gates=gates,
        blocking_reasons=blocking_reasons,
    )


def evidence_coverage_markdown(integrity: MediaIntegrity, coverage: EvidenceCoverage) -> str:
    track_text = (
        f"视频轨 {'有' if integrity.has_video else '无'}，"
        f"音频轨 {'有' if integrity.has_audio else '无'}，"
        f"内嵌字幕轨 {'有' if integrity.has_subtitles else '无'}"
    )
    return "\n".join([
        "## 依据与覆盖",
        "",
        f"- 轨道完整性：{track_text}",
        f"- 文本依据来源：{coverage.transcript_source or '未知'}",
        f"- 带时间文本覆盖：{coverage.transcript_coverage_ratio:.1%}",
        f"- 时间轴抽查：{coverage.matched_transcript_checkpoints}/{coverage.checkpoint_count} 个检查点有文本依据",
        f"- 画面抽查：{coverage.matched_visual_checkpoints}/{coverage.checkpoint_count} 个检查点有画面依据",
        f"- 平台或浏览器字幕覆盖：{coverage.platform_subtitle_coverage_ratio:.1%}",
        f"- 本地转写覆盖：{coverage.local_transcription_coverage_ratio:.1%}",
        f"- 画面证据：{coverage.visual_frame_count} 帧",
    ])
