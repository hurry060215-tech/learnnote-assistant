"""Privacy-safe diagnostics for summary and visual-understanding stages."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, TASK_DIR
from .models import FrameGrid, TaskOptions, VisualWindow
from .summarizer import (
    MAX_GRIDS_PER_VISION_CALL,
    MAX_VISION_GRIDS,
    llm_base_host,
    llm_model_supports_vision,
    llm_provider_name,
    select_vision_grid_entries,
)


def _warning_field(summary_warning: str, key: str) -> str:
    marker = f"{key}="
    if marker not in (summary_warning or ""):
        return ""
    value = (summary_warning or "").split(marker, 1)[1]
    return value.split("，", 1)[0].split(";", 1)[0].split("；", 1)[0].strip()


def _llm_failure_code(summary_source: str, summary_warning: str, configured: bool) -> str:
    if summary_source != "local-template" and not summary_warning:
        return ""
    if not configured:
        return "missing_api_key"
    code = _warning_field(summary_warning, "code")
    if code:
        return code
    if "missing_openai_sdk" in (summary_warning or ""):
        return "missing_openai_sdk"
    if summary_source == "local-template":
        return "llm_unavailable"
    return "partial_vision_failure"


def _safe_llm_events(events: list[dict] | None, limit: int = 20) -> list[dict]:
    safe_events: list[dict] = []
    for event in (events or [])[:limit]:
        if not isinstance(event, dict):
            continue
        safe_events.append({
            key: value
            for key, value in event.items()
            if key in {"stage", "code", "error_type", "message", "batch", "model", "duration_ms", "cache"}
            and value not in (None, "", [])
        })
    return safe_events


def _llm_event_failure(events: list[dict]) -> dict:
    for event in reversed(events or []):
        code = str(event.get("code") or "").strip()
        if code and code not in {"ok", "success", "cache_hit"}:
            return event
    return {}


def _vision_model_rejected_image(events: list[dict]) -> bool:
    pattern = "image|vision|modal|multimodal|content|unsupported|invalid"
    for event in events or []:
        if event.get("stage") != "vision_batch":
            continue
        text = " ".join(str(event.get(key) or "") for key in ("code", "error_type", "message")).lower()
        if re.search(pattern, text):
            return True
    return False


def build_summary_diagnostics(
    task_id: str,
    title: str,
    page_url: str,
    options: TaskOptions,
    grids: list[FrameGrid],
    visual_windows: list[VisualWindow],
    summary_source: str,
    summary_warning: str,
    llm_events: list[dict] | None = None,
    page_context: str = "",
    extracted_frame_count: int | None = None,
    frame_extraction_warning: str = "",
    frame_anchor_timestamps: list[float] | None = None,
) -> dict:
    eligible_entries = select_vision_grid_entries(grids)
    eligible_grids = [grid for _index, grid in eligible_entries]
    eligible_indices = [index for index, _grid in eligible_entries]
    eligible_index_set = set(eligible_indices)
    effective_llm_base_url = options.llm_base_url or LLM_BASE_URL
    effective_llm_model = options.llm_model or LLM_MODEL
    llm_configured = bool(options.llm_api_key or LLM_API_KEY)
    vision_model_configured = llm_configured and llm_model_supports_vision(effective_llm_base_url, effective_llm_model)

    def window_id(index: int) -> str:
        if index < len(visual_windows) and visual_windows[index].id:
            return visual_windows[index].id
        return f"W{index + 1:03d}"

    eligible_window_ids = [window_id(index) for index in eligible_indices]
    vision_image_window_ids = [window_id(index) for index, grid in eligible_entries if grid.path and Path(grid.path).is_file()]
    missing_vision_image_window_ids = [window_id(index) for index, grid in eligible_entries if not (grid.path and Path(grid.path).is_file())]
    omitted_vision_window_ids = [window_id(index) for index in range(len(grids)) if index not in eligible_index_set]
    total_image_count = sum(1 for grid in grids if grid.path and Path(grid.path).is_file())
    eligible_image_count = sum(1 for grid in eligible_grids if grid.path and Path(grid.path).is_file())
    vision_batch_size = max(1, int(options.vision_batch_size or MAX_GRIDS_PER_VISION_CALL))
    vision_call_plan = []
    for batch_index, start in enumerate(range(0, len(eligible_entries), vision_batch_size), start=1):
        batch_entries = eligible_entries[start: start + vision_batch_size]
        batch_window_ids = [window_id(index) for index, _grid in batch_entries]
        batch_image_window_ids = [window_id(index) for index, grid in batch_entries if grid.path and Path(grid.path).is_file()]
        vision_call_plan.append({
            "batch": batch_index,
            "window_ids": batch_window_ids,
            "image_window_ids": batch_image_window_ids,
            "grid_count": len(batch_entries),
            "image_count": len(batch_image_window_ids),
        })
    if llm_configured and not vision_model_configured:
        vision_call_status = "text_only_model"
    elif summary_source == "vision-llm":
        vision_call_status = "vision_llm_used"
    elif summary_source == "text-llm":
        vision_call_status = "text_llm_fallback"
    elif not bool(options.visual_understanding):
        vision_call_status = "not_enabled"
    elif not eligible_grids:
        vision_call_status = "no_frame_grids"
    elif not eligible_image_count:
        vision_call_status = "no_grid_images"
    elif not llm_configured:
        vision_call_status = "missing_api_key"
    else:
        vision_call_status = "local_template_fallback"
    safe_llm_events = _safe_llm_events(llm_events)
    last_llm_failure = _llm_event_failure(safe_llm_events)
    failed_vision_batch_count = sum(
        1 for event in safe_llm_events
        if event.get("stage") == "vision_batch" and str(event.get("code") or "").lower() not in {"", "ok", "success", "cache_hit"}
    )
    llm_failure_code = _llm_failure_code(summary_source, summary_warning, llm_configured)
    if not llm_failure_code and last_llm_failure and summary_source == "local-template":
        llm_failure_code = str(last_llm_failure.get("code") or "llm_unavailable")
    page_context_text = (page_context or "").strip()
    try:
        pipeline_metrics = json.loads((TASK_DIR / task_id / "pipeline_metrics.json").read_text(encoding="utf-8"))
        if not isinstance(pipeline_metrics, dict):
            pipeline_metrics = {}
    except (OSError, ValueError):
        pipeline_metrics = {}
    return {
        "task_id": task_id,
        "title": title,
        "page_url": page_url,
        "summary_source": summary_source,
        "summary_warning": summary_warning,
        "visual_understanding": bool(options.visual_understanding),
        "llm_model_configured": llm_configured,
        "vision_model_configured": vision_model_configured,
        "llm_model": effective_llm_model,
        "llm_base_url": effective_llm_base_url,
        "llm_base_host": llm_base_host(effective_llm_base_url),
        "llm_provider": llm_provider_name(effective_llm_base_url),
        "llm_failure_code": llm_failure_code,
        "llm_failure_stage": (_warning_field(summary_warning, "stage") or last_llm_failure.get("stage") or "") if llm_failure_code else "",
        "llm_failure_reason": (_warning_field(summary_warning, "reason") or last_llm_failure.get("message") or last_llm_failure.get("error_type") or "") if llm_failure_code else "",
        "llm_event_count": len(safe_llm_events),
        "llm_events": safe_llm_events,
        "llm_last_event": safe_llm_events[-1] if safe_llm_events else {},
        "llm_last_failure": last_llm_failure,
        "note_style": options.note_style,
        "note_template": options.note_template,
        "summary_depth": options.summary_depth,
        "page_text_char_count": len(page_context_text),
        "page_context_used": bool(page_context_text),
        "frame_grid_count": len(grids),
        "extracted_frame_count": extracted_frame_count,
        "frame_extraction_status": "not_enabled" if not options.visual_understanding else "no_frames" if extracted_frame_count == 0 else "no_frame_grids" if not grids else "ready",
        "frame_extraction_warning": frame_extraction_warning,
        "frame_anchor_timestamps": list(frame_anchor_timestamps or []),
        "visual_window_count": len(visual_windows),
        "available_grid_image_count": total_image_count,
        "vision_grid_limit": MAX_VISION_GRIDS,
        "vision_batch_size": vision_batch_size,
        "vision_concurrency": 1 if options.low_resource_mode else options.vision_concurrency,
        "vision_cache_hit_count": sum(
            1 for event in safe_llm_events
            if event.get("stage") == "vision_cache" and event.get("cache") == "hit"
        ),
        "vision_expected_batch_count": len(vision_call_plan),
        "vision_call_status": vision_call_status,
        "vision_call_plan": vision_call_plan,
        "vision_failed_batch_count": failed_vision_batch_count,
        "vision_model_rejected_image": _vision_model_rejected_image(safe_llm_events),
        "vision_grid_count": len(eligible_grids),
        "vision_image_count": eligible_image_count,
        "vision_window_ids": eligible_window_ids,
        "vision_image_window_ids": vision_image_window_ids,
        "missing_vision_image_window_ids": missing_vision_image_window_ids,
        "omitted_vision_window_ids": omitted_vision_window_ids,
        "omitted_frame_grid_count": max(0, len(grids) - len(eligible_grids)),
        "used_vision_llm": summary_source == "vision-llm",
        "used_text_llm": summary_source == "text-llm",
        "used_local_template": summary_source == "local-template",
        "all_sent_grids_had_images": eligible_image_count == len(eligible_grids),
        "all_grids_had_images": total_image_count == len(grids),
        "window_ids": [window.id for window in visual_windows],
        "pipeline_metrics": pipeline_metrics,
    }


__all__ = ["build_summary_diagnostics"]
