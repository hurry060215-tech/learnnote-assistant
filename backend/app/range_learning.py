"""Create an independent learning task for an explicitly selected media range."""
from pathlib import Path
import math

from .config import DATA_DIR
from .media import extract_video_clip
from .models import TaskOptions
from .storage import get_task, create_task, update_task, task_dir, read_json, atomic_write_text
from .task_queue import schedule_processing


def _srt_stamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rest = divmod(millis, 3600000)
    minutes, rest = divmod(rest, 60000)
    sec, ms = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{sec:02},{ms:03}"


def source_range_subtitles(source_id: str, start: float, end: float) -> str:
    payload = read_json(source_id, "transcript.json", {})
    selected = []
    for segment in payload.get("segments", []):
        left, right = float(segment["start"]), float(segment["end"])
        if right <= start or left >= end:
            continue
        # We cannot know which words belong inside a partially cut subtitle.
        # Request transcription of the clip rather than leak out-of-range text.
        if left < start or right > end:
            return ""
        selected.append(f"{len(selected)+1}\n{_srt_stamp(left-start)} --> {_srt_stamp(right-start)}\n{segment['text']}\n")
    return "\n".join(selected)


def process_range_task(task_id: str, source_path: Path, title: str, options: TaskOptions):
    from .processor import process_local_video_task
    from .processor_state import check_cancel
    task = get_task(task_id)
    selected = task.learning_range
    check_cancel(task_id)
    update_task(task_id, status="running", phase="processing_video", message="正在提取选定片段，原视频保持不变")
    clip = task_dir(task_id) / "selected-range.mp4"
    if not clip.is_file():
        temporary = clip.with_name("selected-range.partial.mp4")
        extract_video_clip(source_path, temporary, selected["start"], selected["end"])
        temporary.replace(clip)
    check_cancel(task_id)
    subtitle = source_range_subtitles(task.source_task_id, selected["start"], selected["end"])
    subtitle_path = task_dir(task_id) / "selected-range.srt" if subtitle else None
    if subtitle_path:
        atomic_write_text(subtitle_path, subtitle)
    process_local_video_task(task_id, clip, title, options, subtitle_path=subtitle_path, subtitle_source="selected-range-source-subtitle")


def create_range_task(source_id: str, start: float, end: float, options: TaskOptions, background_tasks):
    source = get_task(source_id)
    duration = source.media_integrity.duration
    if not all(math.isfinite(value) for value in (start, end)) or start < 0 or end <= start or duration <= 0 or end > duration + .01:
        raise ValueError("invalid_learning_range")
    path = Path(source.media_path or source.source_media_path or "").resolve()
    if not path.is_file() or not path.is_relative_to(DATA_DIR.resolve()):
        raise ValueError("range_source_media_missing")
    base = source.learning_range.get("original_start", 0.0)
    original_start, original_end = base + start, base + end
    title = f"{source.title} · 片段 {original_start:g}–{original_end:g}秒"
    task = create_task("local", title, options=options, mode="rerun_from_media")
    task = update_task(task.id, source_task_id=source.id, source_media_path=str(path), learning_range={"start": start, "end": end, "original_start": original_start, "original_end": original_end})
    schedule_processing(background_tasks, process_range_task, task.id, path, title, options, _queue_kind="range")
    return task
