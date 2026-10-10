"""User-started OCR routes reuse task-owned media, without arbitrary file inputs."""
import json
import math
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .models import ScreenSubtitleSettings, TaskOptions
from .screen_subtitles import preview, read_observations, media_info
from .screen_subtitle_tasks import process_screen_subtitle_task
from .storage import get_task, task_dir, update_task
from .screen_subtitle_media import create_retained_ocr_task
from .task_queue import schedule_processing
from .task_inputs import merge_task_options, require_ready_note_model, task_media_path

router = APIRouter(prefix="/api/tasks", tags=["screen-subtitles"])


class ScreenSubtitleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: ScreenSubtitleSettings = Field(default_factory=ScreenSubtitleSettings)
    generate_note: bool = False
    options: TaskOptions | None = None


class ScreenSubtitlePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    settings: ScreenSubtitleSettings = Field(default_factory=ScreenSubtitleSettings)
    timestamp: float = Field(default=0, ge=0)


def _completed_range_media(task):
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
            if task.screen_subtitles_media_sha256 and path.resolve() != Path(task.media_path).resolve():
                continue
            try:
                expected = float(task.learning_range["end"]) - float(task.learning_range["start"])
                actual = media_info(path)["duration"]
                if not math.isfinite(expected) or expected <= 0 or abs(actual - expected) > 1:
                    break
            except (ValueError, OSError, KeyError, TypeError, ImportError):
                break
            return path
        if owner.mode != "screen_subtitles" or not owner.source_task_id:
            break
        try:
            owner = get_task(owner.source_task_id)
        except FileNotFoundError:
            break
    raise HTTPException(409, {"code": "range_media_unconfirmed", "message": "无法确认已完成的片段文件；请先恢复来源任务。不会把完整原视频当作片段识别。"})


def _source(task_id, *, allow_pending_range=False):
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "任务不存在。") from exc
    if task.status in {"queued", "running", "cancelling"}:
        raise HTTPException(409, "请先等待当前任务停止，再复用已保存的视频。")
    if task.checkpoint == "screen_subtitles_range_pending" and not allow_pending_range:
        raise HTTPException(409, "此片段尚未生成，请先恢复原任务；不能将完整原视频当作所选片段处理。")
    pending = task.checkpoint == "screen_subtitles_range_pending"
    path = _completed_range_media(task) if task.learning_range and not pending else task_media_path(task)
    if not path or not path.is_file() or path.stat().st_size <= 0:
        raise HTTPException(409, {"code": "media_not_found", "message": "没有可复用的已保存视频。"})
    return task, path


@router.post("/{task_id}/screen-subtitles/preview")
def preview_screen_subtitles(task_id: str, request: ScreenSubtitlePreviewRequest):
    _, path = _source(task_id)
    try:
        return preview(path, request.settings, request.timestamp)
    except Exception as exc:
        raise HTTPException(422, {"code": "screen_ocr_preview_failed", "message": "预览失败，请检查本地 OCR 组件、视频、时间点和裁剪范围。"}) from exc


@router.post("/{task_id}/screen-subtitles")
def create_screen_subtitles(task_id: str, request: ScreenSubtitleRequest, background_tasks: BackgroundTasks):
    source, path = _source(task_id)
    options = merge_task_options(source.options, request.options, resolve_connection=request.generate_note)
    options = options.model_copy(update={"screen_subtitles": request.settings,
        "content_mode": "text" if request.generate_note else "subtitles", "visual_understanding": False, "local_ocr": False})
    if request.generate_note:
        require_ready_note_model(options)
    else:
        # OCR-only does not even resolve or retain a provider credential.
        options = options.model_copy(update={"llm_api_key": None, "use_saved_connection": False})
    task, path = create_retained_ocr_task(source, path, options)
    task = update_task(task.id, source_task_id=source.id, source_media_path=str(path), media_path=str(path),
        media_integrity=source.media_integrity, source_identity=source.source_identity,
        learning_range=source.learning_range, message="已创建独立画面字幕任务；原字幕、笔记和个人修订保留。")
    schedule_processing(background_tasks, process_screen_subtitle_task, task.id, path, options, _queue_kind="screen_ocr")
    return {"task_id": task.id, "task": task.model_dump(mode="json"), "source_task_id": source.id}


@router.get("/{task_id}/screen-subtitles")
def screen_subtitle_result(task_id: str):
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "任务不存在。") from exc
    path = task_dir(task_id) / "screen_subtitles.json"
    if not path.is_file():
        return {"status": "not_started", "settings": task.options.screen_subtitles.model_dump() if task.options.screen_subtitles else None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "画面字幕结果不可读；缓存将在恢复时重新校验。") from exc


def resume_screen_subtitles(task_id, background_tasks, overrides=None):
    source, path = _source(task_id, allow_pending_range=True)
    if source.mode != "screen_subtitles" or source.options.screen_subtitles is None:
        raise HTTPException(409, "此任务不是可恢复的画面字幕任务。")
    options = merge_task_options(source.options, overrides, resolve_connection=source.options.content_mode == "text")
    if options.screen_subtitles != source.options.screen_subtitles:
        raise HTTPException(409, "恢复使用原设置；改变裁剪、间隔或语言请创建新的画面字幕任务。")
    options = options.model_copy(update={"content_mode": source.options.content_mode,
        "visual_understanding": False, "local_ocr": False})
    if options.content_mode == "text":
        require_ready_note_model(options)
    else:
        options = options.model_copy(update={"llm_api_key": None, "use_saved_connection": False})
    task = update_task(task_id, status="queued", phase="queued", progress=0, cancel_requested=False,
        cancel_requested_at="", cancelled_at="", error_code="", error_detail="", failed_phase="",
        options=options.model_copy(update={"llm_api_key": None}), retry_count=source.retry_count + 1,
        message="正在校验并恢复画面字幕窗口，不下载或转写音频。")
    if source.checkpoint == "screen_subtitles_range_pending":
        from .range_learning import process_range_task
        schedule_processing(background_tasks, process_range_task, task.id, path, task.title, options, _queue_kind="range")
    else:
        schedule_processing(background_tasks, process_screen_subtitle_task, task.id, path, options, _queue_kind="screen_ocr")
    return {"task_id": task.id, "task": task.model_dump(mode="json"), "resumed": True}


@router.get("/{task_id}/screen-subtitles/windows/{window_index}")
def screen_subtitle_observations(task_id: str, window_index: int):
    report = screen_subtitle_result(task_id)
    try:
        return read_observations(task_dir(task_id) / "screen-subtitles-cache", report.get("fingerprint", ""), window_index)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "此窗口尚未完成或校验失败，请恢复任务后重试。") from exc


@router.post("/{task_id}/screen-subtitles/resume")
def resume_screen_subtitle_route(task_id: str, background_tasks: BackgroundTasks):
    return resume_screen_subtitles(task_id, background_tasks)
