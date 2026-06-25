from __future__ import annotations

from pathlib import Path

from .models import TranscriptResult, TranscriptSegment


def transcribe_audio(audio_path: Path, model_size: str = "small") -> TranscriptResult:
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
        model = WhisperModel(model_size, device="auto", compute_type="auto")
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
