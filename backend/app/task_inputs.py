"""Shared options and owned-media checks for explicit task actions."""
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

from .config import LLM_BASE_URL, LLM_MODEL
from .models import TaskOptions, TaskRecord
from .storage import get_task
from . import storage
from .range_media import completed_range_media, has_selected_range
from .model_connections import resolve_model_options
from .summarizer import llm_model_supports_vision
from .task_media_guard import require_current_media_provenance, validate_current_media_file
from .task_paths import TaskArtifactUnavailable


def merge_task_options(base: TaskOptions | None, overrides: TaskOptions | None, *, resolve_connection: bool = True) -> TaskOptions:
    merged = (base or TaskOptions()).model_dump(mode="json")
    if overrides is not None:
        explicit_fields = getattr(overrides, "model_fields_set", set()) or set()
        override_values = overrides.model_dump(mode="json")
        for field in explicit_fields:
            if field in override_values:
                merged[field] = override_values[field]
    options = TaskOptions.model_validate(merged)
    return resolve_model_options(options) if resolve_connection else options


def require_ready_note_model(options: TaskOptions) -> None:
    """Explicit AI work must not spend minutes extracting before finding no key."""
    if options.content_mode not in {"text", "visual"}:
        return  # Existing auto-mode integrations keep their source-first behavior.
    from .summarizer import _model_key
    if not _model_key(resolve_model_options(options)):
        raise HTTPException(409, {"code": "model_required", "message": "还没有可用的模型连接。请先配置模型，或选择仅提取字幕；本次尚未下载或转写。"})
    if options.content_mode == "visual" and not llm_model_supports_vision(options.llm_base_url or LLM_BASE_URL, options.llm_model or LLM_MODEL):
        raise HTTPException(409, {"code": "visual_model_required", "message": "当前模型不支持画面理解，请更换视觉模型或选择文字笔记。"})


def task_media_path(task: TaskRecord, *, allow_range_source=False, strict=False) -> Path | None:
    try:
        require_current_media_provenance(task, storage.TASK_DIR / task.id)
    except TaskArtifactUnavailable:
        if strict:
            raise
        return None
    if has_selected_range(task) and not allow_range_source:
        try:
            return completed_range_media(task, verify_duration=False)
        except HTTPException:
            return None
    for raw_path in (task.media_path, task.source_media_path):
        if not raw_path:
            continue
        try:
            return validate_current_media_file(task, raw_path, storage.TASK_DIR / task.id)
        except TaskArtifactUnavailable as exc:
            if exc.reason not in {"missing_destination", "invalid_destination_type"}:
                if strict:
                    raise
                return None
        except OSError:
            continue
    return None


def task_preview_file(task_id: str) -> tuple[TaskRecord, Path]:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    path = task_reuse_media_path(task)
    if not path:
        raise HTTPException(status_code=404, detail="Media not found")
    return task, path


def task_reuse_media_path(task: TaskRecord) -> Path | None:
    require_current_media_provenance(task, storage.TASK_DIR / task.id)
    return completed_range_media(task) if has_selected_range(task) else task_media_path(task, strict=True)


@contextmanager
def media_source_admission(task_id: str, source: TaskRecord):
    """Commit dependencies after probing, under the source deletion lock order."""
    from .storage import assistant_records, task_state_transaction, get_task, DATA_DIR
    with assistant_records.locked(DATA_DIR), task_state_transaction():
        try:
            current = get_task(task_id)
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(409, {"code": "media_source_changed", "message": "来源已改变，请刷新后重试。"}) from exc
        if current.id != task_id or current.model_dump() != source.model_dump():
            raise HTTPException(409, {"code": "media_source_changed", "message": "来源已改变，请刷新后重试。"})
        yield
