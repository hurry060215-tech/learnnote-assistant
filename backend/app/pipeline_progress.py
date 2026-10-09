"""Deterministic, privacy-safe progress artifacts for long-running tasks."""

from __future__ import annotations

import re
import time
from pathlib import Path
from uuid import uuid4

from .models import TranscriptResult
from functools import partial

from .pipeline_timing import emit_timing, take_queue_wait
from .draft_sections import draft_sections_document, temporal_outline_markdown
from .observability import read_task_events, record_task_event
from .storage import atomic_write_text, read_json, task_dir, write_json
# Use the same RLock as read_json/write_json for complete metadata transactions.
from .storage import _lock as _task_data_lock
from .text_cleanup import canonicalize_unicode_text, redact_sensitive_url_values


PIPELINE_METRICS_SCHEMA_VERSION = 2
UNSET_ATTEMPT = object()
_STAGES = {"queue", "subtitle_probe", "download", "media", "transcript", "frames", "vision", "merge", "verify", "visual", "summary"}


def _metrics(task_id: str) -> dict:
    value = read_json(task_id, "pipeline_metrics.json", {})
    if isinstance(value, dict) and value.get("schema_version") == 1:
        legacy = {
            "attempt_id": "legacy",
            "started_at": "",
            "status": "completed",
            "stages": value.get("stages") if isinstance(value.get("stages"), dict) else {},
            "draft": value.get("draft") if isinstance(value.get("draft"), dict) else {},
        }
        value = {
            "schema_version": PIPELINE_METRICS_SCHEMA_VERSION,
            "next_sequence": value.get("next_sequence") or 1,
            "current_attempt_id": "legacy",
            "attempts": [legacy],
            "stages": legacy["stages"],
            "draft": legacy["draft"],
        }
    if not isinstance(value, dict) or value.get("schema_version") != PIPELINE_METRICS_SCHEMA_VERSION:
        return {
            "schema_version": PIPELINE_METRICS_SCHEMA_VERSION,
            "next_sequence": 1,
            "current_attempt_id": "",
            "attempts": [],
            "stages": {},
            "draft": {},
        }
    value.setdefault("next_sequence", 1)
    value.setdefault("stages", {})
    value.setdefault("draft", {})
    value.setdefault("current_attempt_id", "")
    value.setdefault("attempts", [])
    return value


def _sync_current_attempt(payload: dict) -> None:
    attempt_id = str(payload.get("current_attempt_id") or "")
    attempts = payload.get("attempts") if isinstance(payload.get("attempts"), list) else []
    for attempt in attempts:
        if isinstance(attempt, dict) and str(attempt.get("attempt_id") or "") == attempt_id:
            attempt["stages"] = dict(payload.get("stages") or {})
            attempt["draft"] = dict(payload.get("draft") or {})
            return


def start_pipeline_attempt(task_id: str) -> str:
    with _task_data_lock:
        payload = _metrics(task_id)
        attempt_id = uuid4().hex[:12]
        attempt = {
            "attempt_id": attempt_id,
            "sequence": _next_sequence(payload),
            "started_at_unix_ms": round(time.time() * 1000),
            "status": "running",
            "stages": {},
            "draft": {},
        }
        attempts = payload.get("attempts") if isinstance(payload.get("attempts"), list) else []
        attempts.append(attempt)
        payload["attempts"] = attempts[-20:]
        payload["current_attempt_id"] = attempt_id
        payload["stages"] = {}
        payload["draft"] = {}
        write_json(task_id, "pipeline_metrics.json", payload)
        record_task_event(
            task_id,
            "pipeline_attempt_started",
            phase="pipeline",
            status="running",
            details={"schema_version": PIPELINE_METRICS_SCHEMA_VERSION, "attempt_id": attempt_id, "sequence": attempt["sequence"]},
        )
        queue_wait = take_queue_wait(task_id)
        if queue_wait is not None:
            emit_timing(stage_duration_recorder(task_id, attempt_id), "queue", queue_wait[0], "completed", ended_at=queue_wait[1])
        return attempt_id


def current_pipeline_attempt(task_id: str) -> str | None:
    """Capture identity at the work boundary; unavailable metrics stay unknown."""
    try:
        return str(_metrics(task_id).get("current_attempt_id") or "")
    except Exception:
        return None


def stage_duration_recorder(task_id: str, attempt_id: str | None):
    if attempt_id is None:
        return None
    return partial(record_stage_duration, task_id, expected_attempt_id=attempt_id)


def _next_sequence(payload: dict) -> int:
    sequence = max(1, int(payload.get("next_sequence") or 1))
    payload["next_sequence"] = sequence + 1
    return sequence


def _event_exists(task_id: str, event_name: str, phase: str, attempt_id: str = "") -> bool:
    return any(
        event.get("event") == event_name
        and event.get("phase") == phase
        and (not attempt_id or str((event.get("details") or {}).get("attempt_id") or "") == attempt_id)
        for event in read_task_events(task_id, limit=2000)
    )


def record_stage_duration(task_id: str, stage: str, started_at: float | None, status: str = "completed", *, ended_at: float | None = None, expected_attempt_id=UNSET_ATTEMPT, **safe_details) -> dict:
    """Persist one monotonic interval per stage/attempt; absent starts stay unknown."""

    if started_at is not None and ended_at is None:
        ended_at = time.monotonic()
    with _task_data_lock:
        normalized_stage = str(stage or "").strip().lower()
        if normalized_stage not in _STAGES:
            raise ValueError("invalid_pipeline_stage")
        payload = _metrics(task_id)
        attempt_id = str(payload.get("current_attempt_id") or "")
        if expected_attempt_id is None or (expected_attempt_id is not UNSET_ATTEMPT and attempt_id != expected_attempt_id):
            return {}
        stages = payload["stages"]
        entry = stages.get(normalized_stage)
        if not isinstance(entry, dict):
            entry = {
                "sequence": _next_sequence(payload),
                "status": status if status in {"completed", "failed", "cancelled", "skipped"} else "completed",
                "attempt_id": attempt_id,
            }
            if started_at is not None:
                finished = time.monotonic() if ended_at is None else ended_at
                entry["duration_ms"] = round(max(0.0, finished - float(started_at)) * 1000)
            for key, value in safe_details.items():
                if key in {"frame_count", "grid_count", "cache_hit_count", "batch_count"}:
                    entry[key] = max(0, int(value or 0))
            stages[normalized_stage] = entry
            _sync_current_attempt(payload)
            if normalized_stage in {"summary", "verify"} and entry["status"] in {"failed", "cancelled"}:
                for attempt in payload.get("attempts") or []:
                    if isinstance(attempt, dict) and str(attempt.get("attempt_id") or "") == attempt_id:
                        attempt["status"] = entry["status"]
                        attempt["finished_at_unix_ms"] = round(time.time() * 1000)
                        break
            write_json(task_id, "pipeline_metrics.json", payload)
        if not _event_exists(task_id, "stage_timing", normalized_stage, attempt_id):
            record_task_event(
                task_id,
                "stage_timing",
                phase=normalized_stage,
                status=str(entry.get("status") or "completed"),
                details={"schema_version": PIPELINE_METRICS_SCHEMA_VERSION, **entry},
            )
        return entry


def finish_pipeline_attempt(task_id: str, status: str = "completed", *, expected_attempt_id: str | None) -> None:
    """Finish only after final local checks and note persistence have returned."""
    with _task_data_lock:
        if expected_attempt_id is None:
            return
        try:
            payload = _metrics(task_id)
            if payload["current_attempt_id"] != expected_attempt_id:
                return
            for attempt in payload["attempts"]:
                if attempt.get("attempt_id") == payload["current_attempt_id"]:
                    attempt["status"] = status
                    attempt["finished_at_unix_ms"] = round(time.time() * 1000)
                    write_json(task_id, "pipeline_metrics.json", payload)
                    break
        except Exception:
            pass  # Final note publication must not fail because optional metrics failed.


def _format_timestamp(seconds: float) -> str:
    value = max(0, int(seconds or 0))
    return f"{value // 3600:02d}:{(value % 3600) // 60:02d}:{value % 60:02d}"


def _representative_segments(transcript: TranscriptResult, limit: int = 12):
    segments = [segment for segment in transcript.segments if str(segment.text or "").strip()]
    if len(segments) <= limit:
        return segments
    indices = sorted({round(index * (len(segments) - 1) / (limit - 1)) for index in range(limit)})
    return [segments[index] for index in indices]


def write_progressive_draft(task_id: str, title: str, transcript: TranscriptResult, *, expected_attempt_id=UNSET_ATTEMPT) -> Path | None:
    """Write a transcript-only draft; never includes page text, cookies, or URLs."""

    if expected_attempt_id is UNSET_ATTEMPT:
        expected_attempt_id = current_pipeline_attempt(task_id)
    transcript_text = canonicalize_unicode_text(transcript.full_text or "").strip()
    if not transcript_text:
        return None
    clean_title = canonicalize_unicode_text(title or "学习笔记").strip() or "学习笔记"
    clean_title = redact_sensitive_url_values(re.sub(r"\s+", " ", clean_title))[:200]
    lines = [
        f"# {clean_title}",
        "",
        "> 字幕摘录草稿：原始文字已保存。以下提供时间段阅读提纲和原句预览，尚未生成 AI 主题总结或完成事实校验。",
        "",
        "## 原文预览",
        "",
    ]
    for segment in _representative_segments(transcript):
        text = canonicalize_unicode_text(segment.text).strip()
        text = redact_sensitive_url_values(re.sub(r"\s+", " ", text))
        if text:
            lines.append(f"- `{_format_timestamp(segment.start)}` {text[:280]}")
    if len(lines) == 6:
        for line in transcript_text.splitlines()[:12]:
            text = redact_sensitive_url_values(re.sub(r"\s+", " ", line).strip())
            if text:
                lines.append(f"- {text[:280]}")
    section_document = draft_sections_document(transcript)
    write_json(task_id, "draft_sections.json", section_document)
    lines.extend(["", *temporal_outline_markdown(section_document, _format_timestamp)])
    lines.extend([
        "",
        "## 当前状态",
        "",
        "- 完整内容保留在字幕页；AI 总结完成后，正文才会更新为提炼后的笔记。",
        "",
    ])
    target = task_dir(task_id) / "draft.md"
    atomic_write_text(target, "\n".join(lines))

    with _task_data_lock:
        payload = _metrics(task_id)
        if expected_attempt_id is None or payload["current_attempt_id"] != expected_attempt_id:
            return target
        draft = payload.get("draft")
        if not isinstance(draft, dict) or not draft:
            draft = {
                "sequence": _next_sequence(payload),
                "artifact": "draft.md",
                "segment_count": len(transcript.segments),
                "transcript_char_count": len(transcript_text),
                "section_count": len(section_document["sections"]),
                "sections_artifact": "draft_sections.json",
                "summary_generated": False,
            }
            payload["draft"] = draft
            _sync_current_attempt(payload)
            write_json(task_id, "pipeline_metrics.json", payload)
        attempt_id = str(payload.get("current_attempt_id") or "")
        if not _event_exists(task_id, "draft_ready", "transcript", attempt_id):
            record_task_event(
                task_id,
                "draft_ready",
                phase="transcript",
                status="ready",
                message="Transcript draft ready",
                details={"schema_version": PIPELINE_METRICS_SCHEMA_VERSION, "attempt_id": attempt_id, **draft},
            )
    return target


__all__ = ["PIPELINE_METRICS_SCHEMA_VERSION", "record_stage_duration", "start_pipeline_attempt", "write_progressive_draft"]
