"""Create an independent learning task for an explicitly selected media range."""
from pathlib import Path
from decimal import Decimal
import math
from fastapi import HTTPException

from .config import DATA_DIR
from .media import extract_video_clip, media_cancellation
from .models import TaskOptions
from .range_media import completed_range_media, has_selected_range
from .storage import get_task, create_task, update_task, task_dir, read_json, atomic_write_text, task_state_transaction, assistant_records
from .task_queue import schedule_processing
from .task_media_guard import available_current_media, require_current_media_provenance, validate_current_media_file
from .task_paths import TaskArtifactUnavailable


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
        with media_cancellation(lambda: check_cancel(task_id)):
            extract_video_clip(source_path, temporary, selected["start"], selected["end"])
        temporary.replace(clip)
    check_cancel(task_id)
    if options.screen_subtitles is not None:
        from .screen_subtitle_tasks import process_screen_subtitle_task
        ocr_options = options.model_copy(update={
            "content_mode": "subtitles" if options.content_mode == "subtitles" else "text",
            "visual_understanding": False, "local_ocr": False})
        update_task(task_id, mode="screen_subtitles", media_path=str(clip), source_media_path=str(clip),
            checkpoint="screen_subtitles_range_ready", options=ocr_options.model_copy(update={"llm_api_key": None}))
        process_screen_subtitle_task(task_id, clip, ocr_options)
        return
    subtitle = source_range_subtitles(task.source_task_id, selected["start"], selected["end"])
    subtitle_path = task_dir(task_id) / "selected-range.srt" if subtitle else None
    if subtitle_path:
        atomic_write_text(subtitle_path, subtitle)
    process_local_video_task(task_id, clip, title, options, subtitle_path=subtitle_path, subtitle_source="selected-range-source-subtitle")


def create_range_task(source_id: str, start: float, end: float, options: TaskOptions, background_tasks):
    # Hold the same deletion/state locks from source validation until its new
    # dependency is durable. Otherwise a reviewed deletion can pass between
    # reading the source and recording the range task's source_task_id.
    with assistant_records.locked(DATA_DIR), task_state_transaction():
        return _create_range_task(source_id, start, end, options, background_tasks)


def _create_range_task(source_id: str, start: float, end: float, options: TaskOptions, background_tasks):
    source = get_task(source_id)
    if source.id != source_id:
        raise ValueError("range_source_identity_conflict")
    if source.mode == "screen_subtitles" and source.options.screen_subtitles is not None:
        options = options.model_copy(update={"screen_subtitles": source.options.screen_subtitles,
            "content_mode": "subtitles" if options.content_mode == "subtitles" else "text",
            "visual_understanding": False, "local_ocr": False})
    duration = source.media_integrity.duration
    selected = source.learning_range
    if any(not math.isfinite(selected[key]) for key in ("start", "end", "original_start", "original_end") if key in selected):
        raise ValueError("invalid_learning_range")
    source_root = DATA_DIR / "tasks" / source.id
    try:
        require_current_media_provenance(source, source_root)
        range_path = completed_range_media(source) if has_selected_range(source) else None
    except TaskArtifactUnavailable as exc:
        raise HTTPException(409, exc.detail()) from exc
    if not all(math.isfinite(value) for value in (start, end, duration)) or start < 0 or end <= start or duration <= 0 or end > duration + .01:
        raise ValueError("invalid_learning_range")
    if "start" in selected and "end" in selected:
        # Encoders can pad a clip beyond its requested evidence interval. The
        # container tolerance above must never expand that logical parent range.
        logical_duration = Decimal(str(selected["end"])) - Decimal(str(selected["start"]))
        if not logical_duration.is_finite() or logical_duration <= 0 or Decimal(str(end)) > logical_duration:
            raise ValueError("invalid_learning_range")
    try:
        path = (validate_current_media_file(source, str(range_path), source_root) if range_path
                else available_current_media(source, source_root))
    except TaskArtifactUnavailable as exc:
        raise HTTPException(409, exc.detail()) from exc
    if path is None or not path.is_relative_to(DATA_DIR.absolute()):
        raise ValueError("range_source_media_missing")
    base = Decimal(str(selected.get("original_start", selected.get("start", 0.0))))
    original_start, original_end = float(base + Decimal(str(start))), float(base + Decimal(str(end)))
    if not all(math.isfinite(value) for value in (original_start, original_end)):
        raise ValueError("invalid_learning_range")
    if "original_end" in selected and original_end > selected["original_end"]:
        raise ValueError("invalid_learning_range")
    title = f"{source.title} · 片段 {original_start:g}–{original_end:g}秒"
    if options.screen_subtitles is not None:
        from .screen_subtitle_media import create_retained_ocr_task
        task, path = create_retained_ocr_task(source, path, options, title=title, range_pending=True)
    else:
        task = create_task("local", title, page_url=source.page_url, options=options, mode="rerun_from_media")
    task = update_task(task.id, source_task_id=source.id, source_media_path=str(path), checkpoint="screen_subtitles_range_pending" if options.screen_subtitles is not None else "", source_identity=source.source_identity.model_copy(update={"media_sha256": "", "resource_fingerprint": ""}), learning_range={"start": start, "end": end, "original_start": original_start, "original_end": original_end})
    schedule_processing(background_tasks, process_range_task, task.id, path, title, options, _queue_kind="range")
    return task
