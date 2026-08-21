"""ASR selection and task-progress reporting for processor stages."""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from .models import TaskOptions, TranscriptResult
from .processor_state import TaskCancelled, check_cancel
from .storage import update_task
from .transcriber import transcribe_audio, transcribe_audio_openai_compatible


REMOTE_ASR_TRANSCRIBERS = {"openai", "openai-compatible", "openai-compatible-asr", "groq", "groq-asr"}
ASR_FAILURE_SOURCES = {"missing-faster-whisper", "faster-whisper-error"}


def use_remote_asr(options: TaskOptions) -> bool:
    return str(options.transcriber or "").strip().lower() in REMOTE_ASR_TRANSCRIBERS


def transcribe_extracted_audio(audio_path: Path, options: TaskOptions, progress_callback=None) -> TranscriptResult:
    if use_remote_asr(options):
        return transcribe_audio_openai_compatible(audio_path, options)
    return transcribe_audio(audio_path, options.whisper_model, progress_callback=progress_callback)


def _clock_text(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def transcribe_with_task_progress(
    task_id: str,
    audio_path: Path,
    options: TaskOptions,
    media_duration: float,
    transcribe_fn=None,
) -> TranscriptResult:
    stop_event = threading.Event()
    state_lock = threading.Lock()
    started_at = time.monotonic()
    state = {"processed": 0.0, "stage": "remote" if use_remote_asr(options) else "loading_model", "published": 0.0}

    def publish(processed_seconds: float = 0, stage: str = "", *, force: bool = False) -> None:
        now = time.monotonic()
        with state_lock:
            previous_processed = float(state["processed"])
            previous_stage = str(state["stage"])
            state["processed"] = max(float(state["processed"]), max(0.0, float(processed_seconds or 0)))
            if stage:
                state["stage"] = stage
            processed = float(state["processed"])
            current_stage = str(state["stage"])
            meaningful_change = (
                current_stage != previous_stage
                or processed - previous_processed >= max(5.0, float(media_duration or 0) * 0.02)
                or current_stage == "complete"
            )
            if not force and not meaningful_change and now - float(state["published"]) < 2.0:
                return
            state["published"] = now

        check_cancel(task_id)
        duration = max(0.0, float(media_duration or 0))
        ratio = min(1.0, processed / duration) if duration > 0 else 0.0
        progress = min(66, 52 + int(ratio * 14))
        elapsed = max(1, int(now - started_at))
        if current_stage == "remote":
            message = f"正在使用远程 ASR 转写音频 · 已等待 {_clock_text(elapsed)}"
        elif current_stage == "loading_model":
            message = f"正在加载本地转写模型 · 已等待 {_clock_text(elapsed)}"
        elif processed > 0 and duration > 0:
            message = f"正在生成字幕 · 已处理 {_clock_text(processed)} / {_clock_text(duration)}"
        else:
            message = f"本地模型已加载，正在分析音频 · 已运行 {_clock_text(elapsed)}"
        update_task(task_id, phase="transcribing", progress=progress, message=message)

    def heartbeat() -> None:
        while not stop_event.wait(8):
            try:
                publish(force=True)
            except (FileNotFoundError, TaskCancelled):
                return

    publish(force=True)
    thread = threading.Thread(target=heartbeat, name=f"learnnote-asr-{task_id}", daemon=True)
    thread.start()
    try:
        runner = transcribe_fn or transcribe_extracted_audio
        return runner(audio_path, options, progress_callback=publish)
    finally:
        stop_event.set()
        thread.join(timeout=1)


def asr_failure_detail(transcript: TranscriptResult) -> str:
    source = str(transcript.source or "").strip().lower()
    failed = source in ASR_FAILURE_SOURCES or bool(re.search(r"-(?:missing-key|missing-sdk|error)$", source))
    if not failed:
        return ""
    return transcript.warning or f"ASR failed with source: {transcript.source or 'unknown'}"


__all__ = ["asr_failure_detail", "transcribe_extracted_audio", "transcribe_with_task_progress", "use_remote_asr"]
