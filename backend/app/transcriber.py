from __future__ import annotations

from pathlib import Path
import re

from .config import DEFAULT_WHISPER_COMPUTE_TYPE, DEFAULT_WHISPER_DEVICE, configure_local_caches
from .models import TranscriptResult, TranscriptSegment


TIMESTAMP_RE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{1,3})\s+-->\s+(?P<end>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{1,3})"
)


def _parse_timestamp(value: str) -> float:
    value = value.replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def transcript_from_subtitle(path: Path) -> TranscriptResult:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    normalized = re.sub(r"\r+\n", "\n", text)
    normalized = re.sub(r"\r+", "\n", normalized)
    blocks = re.split(r"\n\s*\n", normalized)
    segments: list[TranscriptSegment] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines or lines[0].upper().startswith("WEBVTT") or lines[0].upper().startswith("NOTE"):
            continue
        time_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
        if time_index < 0:
            continue
        match = TIMESTAMP_RE.search(lines[time_index])
        if not match:
            continue
        cue_text = " ".join(
            re.sub(r"<[^>]+>", "", line).strip()
            for line in lines[time_index + 1:]
            if not line.startswith(("NOTE", "STYLE", "REGION"))
        ).strip()
        if not cue_text:
            continue
        cue_text = re.sub(r"\s+", " ", cue_text)
        if segments and segments[-1].text == cue_text:
            segments[-1].end = _parse_timestamp(match.group("end"))
            continue
        segments.append(
            TranscriptSegment(
                start=_parse_timestamp(match.group("start")),
                end=_parse_timestamp(match.group("end")),
                text=cue_text,
            )
        )
    return TranscriptResult(
        language="unknown",
        source="page-subtitle",
        segments=segments,
        full_text="\n".join(segment.text for segment in segments),
        warning="" if segments else "字幕文件存在，但未解析出有效字幕片段。",
    )


def transcribe_audio(audio_path: Path, model_size: str = "small") -> TranscriptResult:
    configure_local_caches()
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return TranscriptResult(
            language="unknown",
            source="missing-faster-whisper",
            warning="未安装 faster-whisper；请执行 `pip install faster-whisper` 后重试以获得真实转写。",
            segments=[
                TranscriptSegment(
                    start=0,
                    end=0,
                    text="未安装 faster-whisper，当前任务没有生成真实字幕。仍可根据画面帧生成基础笔记。",
                )
            ],
            full_text="未安装 faster-whisper，当前任务没有生成真实字幕。仍可根据画面帧生成基础笔记。",
        )

    try:
        model = WhisperModel(model_size, device=DEFAULT_WHISPER_DEVICE, compute_type=DEFAULT_WHISPER_COMPUTE_TYPE)
        segments_iter, info = model.transcribe(str(audio_path), vad_filter=True)
        segments: list[TranscriptSegment] = []
        for item in segments_iter:
            text = item.text.strip()
            if text:
                segments.append(TranscriptSegment(start=float(item.start), end=float(item.end), text=text))
        return TranscriptResult(
            language=getattr(info, "language", "unknown") or "unknown",
            source="faster-whisper",
            segments=segments,
            full_text="\n".join(seg.text for seg in segments),
        )
    except Exception as exc:
        return TranscriptResult(
            language="unknown",
            source="faster-whisper-error",
            warning=f"faster-whisper 转写失败：{exc}",
            segments=[
                TranscriptSegment(start=0, end=0, text=f"转写失败：{exc}")
            ],
            full_text=f"转写失败：{exc}",
        )
