"""Explicit caption extraction ends before any model or audio transcription."""
from .storage import get_task, task_dir, update_task, write_json
from .processor_state import ContentMismatchError
from decimal import Decimal, InvalidOperation
import math
from .pipeline_progress import UNSET_ATTEMPT, current_pipeline_attempt, finish_pipeline_attempt, record_stage_duration, stage_duration_recorder
from .pipeline_timing import emit_timing
from .models import now_iso
from .reading_notes import stamp
import time


def selected_caption_context(transcript, selected):
    """Keep clip-local cues; disclose the authoritative requested source interval.

    original_start/end already include parent offsets. Never add start a second
    time or substitute an encoder's padded physical duration for requested end.
    """
    if not selected:
        return transcript, ""
    try:
        values = {key: Decimal(str(selected[key])) for key in
                  ("start", "end", "original_start", "original_end") if key in selected}
        if any(not value.is_finite() for value in values.values()):
            raise ValueError("Nonfinite range")
        start, end = values["start"], values["end"]
        duration = end - start
        original_start = values.get("original_start", start)
        original_end = values.get("original_end", original_start + duration)
        if start < 0 or duration <= 0 or original_start < 0 or original_end <= original_start:
            raise ValueError("Inconsistent range")
        if any(not math.isfinite(float(value)) for value in (original_start, original_end, duration)):
            raise ValueError("Range overflow")
        # create_range_task stores canonical endpoints as floats. Adding a
        # parent offset can round each endpoint independently. Accept only the
        # combined half-ULP representation error; never a fixed time allowance.
        rounding = sum((Decimal.from_float(math.ulp(float(value))) / 2
                        for value in (start, end, original_start, original_end)), Decimal(0))
        if abs((original_end - original_start) - duration) > rounding:
            raise ValueError("Inconsistent range")
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as exc:
        raise ContentMismatchError("字幕片段范围无效，未发布缺少来源边界的字幕笔记。") from exc
    provenance = {**transcript.provenance, "learning_range": dict(selected),
                  "timestamp_origin": "selected_media_start", "original_time_offset": float(original_start)}
    start_text, end_text = (format(value.normalize(), "f") for value in (original_start, original_end))
    notice = (f"> 选定范围：原视频 {start_text}–{end_text} 秒（请求的学习范围，不代表文件编码时长）。"
              f" 本文及导出的 SRT 时间从片段 0 秒起；原视频时间 = 片段时间 + {start_text} 秒。")
    return transcript.model_copy(update={"provenance": provenance}), notice


def finish_caption_extraction(task_id, title, transcript, subtitle_path="", *, attempt_id=UNSET_ATTEMPT):
    if attempt_id is UNSET_ATTEMPT:
        attempt_id = current_pipeline_attempt(task_id)
    timing_callback = stage_duration_recorder(task_id, attempt_id)
    transcript, range_notice = selected_caption_context(transcript, get_task(task_id).learning_range)
    root = task_dir(task_id)
    path = write_json(task_id, "transcript.json", transcript.model_dump(mode="json"))
    lines = [f"# {title}", "", "> 字幕原文 · 按你的选择，仅提取已有字幕，没有下载视频、转写音频或调用模型。", ""]
    if range_notice:
        lines.extend([range_notice, ""])
    lines.extend(f"`{stamp(segment.start)}` {segment.text}\n" for segment in transcript.segments)
    note = root / "captions.md"
    note.write_text("\n".join(lines), encoding="utf-8")
    for stage in ("download", "media", "visual", "summary"):
        record_stage_duration(task_id, stage, time.monotonic(), status="skipped", expected_attempt_id=attempt_id)
    for stage in ("frames", "vision", "merge", "verify"):
        emit_timing(timing_callback, stage, None, "skipped")
    update_task(task_id, mode="subtitle_only", status="success", phase="completed", progress=100,
        message="字幕已提取完成，未调用模型；可以阅读或导出原文。", note_path=str(note),
        transcript_path=str(path), subtitle_path=subtitle_path, summary_source="subtitle-extract",
        summary_warning="", error_code="", error_detail="", checkpoint="transcript_ready", checkpoint_updated_at=now_iso())
    finish_pipeline_attempt(task_id, expected_attempt_id=attempt_id)
