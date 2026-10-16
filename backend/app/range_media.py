"""Resolve atomically installed range artifacts without falling back to a full source."""
import math
from pathlib import Path
from fastapi import HTTPException
from .media import probe_duration, MediaProcessingError
from .storage import get_task, task_dir
from . import storage
from .task_media_guard import require_current_media_provenance, same_native_path, validated_caption_source
from .task_paths import TaskArtifactUnavailable


def has_selected_range(task):
    return "start" in task.learning_range and "end" in task.learning_range


def completed_range_media(task, *, verify_duration=True, duration_probe=None):
    require_current_media_provenance(task, storage.TASK_DIR / task.id)
    # Browser tasks record the full download before clipping. These final,
    # task-owned names are installed atomically by the existing slicers.
    owner, seen = task, set()
    while owner.id not in seen and len(seen) < 16:
        seen.add(owner.id)
        if owner.learning_range != task.learning_range:
            break
        root = task_dir(owner.id)
        names = ("selected-range-source.mp4", "selected-range.mp4")
        if owner.mode == "screen_subtitles":
            from .screen_subtitle_media import retained_media_name
            names = (retained_media_name(Path(owner.media_path or "")), "screen-subtitles-source.media", *names)
        for name in names:
            path = root / name
            if root.is_symlink() or path.is_symlink() or not path.is_file():
                continue
            if task.screen_subtitles_media_sha256 and not same_native_path(task.media_path, path.absolute()):
                continue
            if verify_duration:
                try:
                    expected = float(task.learning_range["end"]) - float(task.learning_range["start"])
                    actual = (duration_probe or probe_duration)(path)
                    if not math.isfinite(expected) or expected <= 0 or not math.isfinite(actual) or actual <= 0 or abs(actual - expected) > 1:
                        break
                except (ValueError, OSError, KeyError, TypeError, ImportError, MediaProcessingError):
                    break
            return path
        if not owner.source_task_id:
            break
        if owner.mode not in {"screen_subtitles", "rerun_from_media"}:
            if owner.mode != "subtitle_only":
                break
            validated_caption_source(owner, storage.TASK_DIR / owner.id)
        try:
            owner = get_task(owner.source_task_id)
        except FileNotFoundError:
            break
    raise HTTPException(409, {"code": "range_media_unconfirmed", "message": "无法确认已完成的片段文件；请先恢复来源任务。不会把完整原视频当作片段识别。"})


def range_media_preview_state(task):
    if not has_selected_range(task):
        return {}
    try:
        completed_range_media(task, verify_duration=False)
        return {"range_media_ready": True}
    except (HTTPException, TaskArtifactUnavailable):
        return {"range_media_ready": False}
