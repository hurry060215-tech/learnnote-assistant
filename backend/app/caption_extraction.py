"""Explicit caption extraction ends before any model or audio transcription."""
from .storage import task_dir, update_task, write_json
from .pipeline_progress import record_stage_duration
from .models import now_iso
from .reading_notes import stamp
import time


def finish_caption_extraction(task_id, title, transcript, subtitle_path=""):
    root = task_dir(task_id)
    path = write_json(task_id, "transcript.json", transcript.model_dump(mode="json"))
    lines = [f"# {title}", "", "> 字幕原文 · 按你的选择，仅提取已有字幕，没有下载视频、转写音频或调用模型。", ""]
    lines.extend(f"`{stamp(segment.start)}` {segment.text}\n" for segment in transcript.segments)
    note = root / "captions.md"
    note.write_text("\n".join(lines), encoding="utf-8")
    for stage in ("download", "media", "visual", "summary"):
        record_stage_duration(task_id, stage, time.monotonic(), status="skipped")
    update_task(task_id, mode="subtitle_only", status="success", phase="completed", progress=100,
        message="字幕已提取完成，未调用模型；可以阅读或导出原文。", note_path=str(note),
        transcript_path=str(path), subtitle_path=subtitle_path, summary_source="subtitle-extract",
        summary_warning="", error_code="", error_detail="", checkpoint="transcript_ready", checkpoint_updated_at=now_iso())
