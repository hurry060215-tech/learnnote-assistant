"""Lifecycle wrapper for local-video task execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .models import BrowserSubtitleCue, TaskOptions
from .processor_state import (
    ContentMismatchError,
    ResourceBudgetError,
    TaskCancelled,
    check_cancel,
    fail_task,
    persist_task_resource_usage,
    start_task_resource_monitor,
)


def run_local_video_task(
    task_id: str,
    input_path: Path,
    title: str,
    options: TaskOptions,
    *,
    page_url: str = "",
    browser_subtitles: list[BrowserSubtitleCue] | None = None,
    subtitle_path: Path | None = None,
    subtitle_source: str = "page-subtitle",
    process_video_file: Callable[..., None],
) -> None:
    resource_monitor, resource_started_at = start_task_resource_monitor(task_id)
    try:
        check_cancel(task_id)
        process_video_file(
            task_id=task_id,
            input_path=input_path,
            title=title,
            page_url=page_url,
            options=options,
            subtitle_path=subtitle_path,
            browser_subtitles=browser_subtitles,
            subtitle_source=subtitle_source,
            page_context="",
        )
    except TaskCancelled:
        return
    except ContentMismatchError as exc:
        fail_task(task_id, "media_mismatch", str(exc))
    except ResourceBudgetError as exc:
        fail_task(task_id, "resource_budget_exceeded", str(exc))
    except Exception as exc:
        fail_task(task_id, "processing_failed", str(exc))
    finally:
        persist_task_resource_usage(task_id, resource_monitor, resource_started_at)


__all__ = ["run_local_video_task"]
