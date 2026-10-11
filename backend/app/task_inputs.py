"""Shared options and owned-media checks for explicit task actions."""
from pathlib import Path

from fastapi import HTTPException

from .config import LLM_BASE_URL, LLM_MODEL
from .models import TaskOptions, TaskRecord
from .model_connections import resolve_model_options
from .summarizer import llm_model_supports_vision


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


def task_media_path(task: TaskRecord) -> Path | None:
    for raw_path in (task.media_path, task.source_media_path):
        if not raw_path:
            continue
        try:
            path = Path(raw_path)
        except (OSError, ValueError):
            continue
        if path.is_file():
            return path
    return None
