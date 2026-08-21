"""Durable task-state and evidence guards used by the processing pipeline."""

from __future__ import annotations

import re
import time
from pathlib import Path

from .models import TranscriptResult, now_iso
from .resource_monitor import ResourceMonitor
from .storage import get_task, mark_task_cancelled, task_dir, update_task, write_json


class TaskCancelled(Exception):
    pass


class ContentMismatchError(Exception):
    pass


class ResourceBudgetError(Exception):
    pass


def mark_checkpoint(task_id: str, name: str) -> None:
    """Persist the last durable artifact boundary for restart/recovery UX."""

    update_task(task_id, checkpoint=name, checkpoint_updated_at=now_iso())


def start_task_resource_monitor(task_id: str) -> tuple[ResourceMonitor, float]:
    monitor = ResourceMonitor(task_dir(task_id), interval_seconds=1.0).start()
    return monitor, time.monotonic()


def persist_task_resource_usage(task_id: str, monitor: ResourceMonitor, started_at: float) -> None:
    """Persist local resource evidence without changing the task outcome."""

    try:
        observed = monitor.stop().as_dict()
        try:
            outcome = get_task(task_id).status
        except Exception:
            outcome = "unknown"
        report = {
            "schema_version": 1,
            "task_id": task_id,
            "outcome": outcome,
            "elapsed_seconds": round(max(0.0, time.monotonic() - started_at), 3),
            "observed": observed,
            "privacy": "process counters and local free space only; no task content, URL, cookie, or model payload",
        }
        path = write_json(task_id, "resource_usage.json", report)
        update_task(task_id, resource_usage_path=str(path))
    except Exception:
        try:
            monitor.stop()
        except Exception:
            pass


def validate_summary_evidence(transcript: TranscriptResult, frames: list[Path], media_duration: float) -> None:
    transcript_chars = len(re.sub(r"\s+", "", transcript.full_text or ""))
    distinct_frames = len({path.name for path in frames})
    if transcript_chars > 0 or (media_duration >= 2 and distinct_frames >= 2):
        return
    raise ContentMismatchError(
        "未取得足够的真实视频内容：没有可用转写，且画面或时长证据不足。"
        "已停止生成笔记，避免总结到封面、图标或错误资源。"
    )


def has_visual_summary_evidence(frames: list[Path], media_duration: float) -> bool:
    return media_duration >= 2 and len({path.name for path in frames}) >= 2


def check_cancel(task_id: str) -> None:
    if get_task(task_id).cancel_requested:
        mark_task_cancelled(task_id)
        raise TaskCancelled(task_id)


def fail_task(task_id: str, code: str, detail: str) -> None:
    record = get_task(task_id)
    if record.cancel_requested or record.status == "cancelled":
        mark_task_cancelled(task_id)
        return
    update_task(
        task_id,
        status="failed",
        phase="failed",
        progress=100,
        error_code=code,
        error_detail=detail,
        failed_phase=record.phase,
        message=detail,
    )
