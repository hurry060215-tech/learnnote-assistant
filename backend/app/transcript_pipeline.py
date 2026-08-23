"""Transcript evidence selection and persistence for video tasks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from .models import BrowserSubtitleCue, TaskOptions, TranscriptResult
from .processor_state import ContentMismatchError, check_cancel
from .storage import task_dir, update_task, write_json


@dataclass
class TranscriptArtifacts:
    transcript: TranscriptResult
    asr_error: str
    audio_path: Path | None
    audio_warning: str
    transcript_path: Path


def prepare_transcript(
    task_id: str,
    input_path: Path,
    normalized_path: Path,
    integrity,
    options: TaskOptions,
    subtitle_path: Path | None,
    browser_subtitles: list[BrowserSubtitleCue] | None,
    subtitle_source: str,
    *,
    parse_subtitle_or_none: Callable,
    browser_subtitles_are_reliable: Callable,
    extract_embedded_subtitle: Callable,
    extract_audio: Callable,
    transcribe_with_task_progress: Callable,
    transcript_from_browser_subtitles: Callable,
    write_browser_subtitles_srt: Callable,
    correct_transcript_terms: Callable,
    use_remote_asr: Callable,
    asr_failure_detail: Callable,
    calculate_evidence_coverage: Callable,
) -> TranscriptArtifacts:
    work_dir = task_dir(task_id)
    audio_warning = ""
    transcript: TranscriptResult | None = None
    browser_fallback_transcript = transcript_from_browser_subtitles(browser_subtitles or [])

    if subtitle_path:
        owned_subtitle_path = subtitle_path
        try:
            if subtitle_path.resolve().parent != work_dir.resolve():
                owned_subtitle_path = work_dir / subtitle_path.name
                if owned_subtitle_path.resolve() != subtitle_path.resolve():
                    from shutil import copy2
                    copy2(subtitle_path, owned_subtitle_path)
        except OSError:
            owned_subtitle_path = subtitle_path
        update_task(task_id, subtitle_path=str(owned_subtitle_path), message="已检测到页面字幕，正在解析字幕")
        transcript = parse_subtitle_or_none(owned_subtitle_path, source=subtitle_source or "page-subtitle")

    if transcript is None and browser_subtitles and browser_subtitles_are_reliable(browser_subtitles, integrity.duration):
        update_task(task_id, message="已读取完整的浏览器播放器字幕，正在生成带时间戳转写")
        transcript = transcript_from_browser_subtitles(browser_subtitles)
        update_task(task_id, subtitle_path=write_browser_subtitles_srt(task_id, transcript))

    if transcript is None:
        embedded_subtitle = extract_embedded_subtitle(input_path, work_dir / "embedded_subtitle.srt")
        if embedded_subtitle:
            update_task(task_id, subtitle_path=str(embedded_subtitle), message="已检测到视频内嵌字幕，正在解析字幕")
            transcript = parse_subtitle_or_none(embedded_subtitle, source="embedded-subtitle")

    if integrity.status in {"video_only", "audio_only"}:
        blocked_coverage = calculate_evidence_coverage(
            integrity,
            transcript or TranscriptResult(source="missing-subtitle"),
            [],
            visual_enabled=options.visual_understanding,
        )
        blocked_path = write_json(task_id, "evidence_coverage.json", blocked_coverage.model_dump(mode="json"))
        update_task(task_id, evidence_coverage=blocked_coverage, evidence_coverage_path=str(blocked_path))
        raise ContentMismatchError(
            f"Single-track media ({integrity.status}) cannot produce a composite video note; both video and audio tracks are required."
        )

    audio_path: Path | None = None
    if transcript is None:
        update_task(task_id, phase="processing_video", progress=38, message="正在提取音频")
        audio_path = work_dir / "audio.wav"
        try:
            extract_audio(normalized_path, audio_path)
            check_cancel(task_id)
            update_task(task_id, audio_path=str(audio_path))
        except Exception as exc:
            audio_path = None
            audio_warning = f"未能提取可转写音轨：{exc}；已继续使用画面切片生成笔记。"

        update_task(
            task_id,
            phase="transcribing",
            progress=52,
            message="正在使用远程 ASR 转写音频" if use_remote_asr(options) else "正在加载本地转写模型并生成字幕，首次使用会稍久",
        )
        if audio_path:
            transcript = transcribe_with_task_progress(task_id, audio_path, options, integrity.duration)
            check_cancel(task_id)
        else:
            transcript = TranscriptResult(source="no-audio", warning=audio_warning)

    if browser_fallback_transcript.segments and (
        transcript is None or not transcript.segments or transcript.source in {"no-audio", "missing-faster-whisper", "faster-whisper-error"}
    ):
        transcript = browser_fallback_transcript.model_copy(update={"warning": "音轨转写不可用，已退回到浏览器当前可见字幕；内容可能不完整。"})
        update_task(task_id, subtitle_path=write_browser_subtitles_srt(task_id, transcript))

    if transcript is None:
        transcript = TranscriptResult(source="no-audio", warning=audio_warning)
    transcript = correct_transcript_terms(transcript)
    asr_error = asr_failure_detail(transcript)
    if asr_error:
        transcript = transcript.model_copy(update={"segments": [], "full_text": ""})
    transcript_path = work_dir / "transcript.json"
    transcript_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    update_task(task_id, transcript_path=str(transcript_path))
    return TranscriptArtifacts(transcript, asr_error, audio_path, audio_warning, transcript_path)


__all__ = ["TranscriptArtifacts", "prepare_transcript"]
