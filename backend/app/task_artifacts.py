"""Read-only access to portable task artifacts.

Routers and integration projections use this module instead of importing the
processing orchestrator.  The task record remains the authority for paths and
decoding is strict. Explicit review drafts retain their literal unresolved text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import TaskRecord, TranscriptResult
from .summary_outcome import safe_summary_diagnostics, safe_summary_warning, summary_failure_message
from .storage import get_task
from . import storage
from .task_paths import TaskArtifactUnavailable, artifact_name, resolve_task_artifact, resolve_task_grid, validate_task_id
from .text_cleanup import read_canonical_text, decode_text_bytes


def task_dir(task_id: str) -> Path:
    # Unlike storage.task_dir, a read must never create the selected directory.
    return storage.TASK_DIR / task_id


def task_artifact_path(record: TaskRecord, field: str, *, task_id: str | None = None) -> Path | None:
    task_id = record.id if task_id is None else task_id
    validate_task_id(task_id)
    if record.id != task_id:
        raise TaskArtifactUnavailable("task_identity_mismatch")
    try:
        return resolve_task_artifact(task_dir(task_id), task_id, getattr(record, field), field=field)
    except TaskArtifactUnavailable as exc:
        if field != "subtitle_path" or exc.reason not in {"ownership_requires_preview", "native_mapping_requires_preview"}:
            raise
        from .task_media_guard import historical_source_subtitle
        return historical_source_subtitle(record, task_dir(task_id))


def task_artifact_states(record: TaskRecord, fields: tuple[str, ...]) -> tuple[dict, dict]:
    available, diagnostics = {}, {}
    for field in fields:
        try:
            available[field] = task_artifact_path(record, field) is not None
        except TaskArtifactUnavailable as exc:
            available[field] = False
            diagnostics[field] = exc.detail()
    return available, diagnostics


def public_summary_task(record: TaskRecord) -> TaskRecord:
    """Redact legacy diagnostic projections without rewriting historical files."""
    fields = {
        "summary_diagnostics": safe_summary_diagnostics(record.summary_diagnostics),
        "summary_warning": safe_summary_warning(record.summary_warning),
    }
    if record.error_code == "summary_unavailable":
        fields.update(message=summary_failure_message(record.message),
            error_detail=summary_failure_message(record.error_detail))
    return record.model_copy(update=fields)


def read_task_note(task_id: str) -> str:
    validate_task_id(task_id)
    record = get_task(task_id)
    if not record.note_path:
        return ""
    path = task_artifact_path(record, "note_path", task_id=task_id)
    return decode_task_note(record, path.read_bytes())


def decode_task_note(record: TaskRecord, content: bytes) -> str:
    """Apply the same note rules to bytes already read through a safe descriptor."""
    name = artifact_name(record.note_path)
    diagnostics = record.summary_diagnostics or {}
    if (record.summary_source == "transcript-draft"
            and record.error_code == "transcript_review_required"
            and record.status == "failed"
            and diagnostics.get("note_publication") == "review_draft"
            and diagnostics.get("review_required") is True
            and diagnostics.get("summary_generated") is False
            and name == "draft.review.md"):
        # These are generated UTF-8 drafts, not an alternate decoder for formal
        # notes. Keep the warning and unresolved words exactly as preserved.
        return content.decode("utf-8")
    return decode_text_bytes(content, source=name).text


def read_task_transcript(task_id: str) -> dict[str, Any]:
    validate_task_id(task_id)
    record = get_task(task_id)
    if not record.transcript_path:
        return TranscriptResult().model_dump(mode="json")
    path = task_artifact_path(record, "transcript_path", task_id=task_id)
    value = json.loads(read_canonical_text(path).text)
    return value if isinstance(value, dict) else TranscriptResult().model_dump(mode="json")


def owned_task_artifact(task_id: str, value: str, *, directory: str = "") -> Path | None:
    """Apply the saved-note/asset ownership boundary before inspecting a file."""
    try:
        validate_task_id(task_id)
        return resolve_task_artifact(task_dir(task_id), task_id, value, directory=directory)
    except (OSError, TaskArtifactUnavailable):
        return None


__all__ = ["read_task_note", "read_task_transcript", "public_summary_task", "owned_task_artifact", "task_artifact_path"]


def task_report_path(record: TaskRecord, field: str) -> Path | None:
    names = {"resource_inventory_path": "resource_inventory.json", "page_preflight_report_path": "page_preflight_report.json", "resource_usage_path": "resource_usage.json"}
    value = getattr(record, field)
    try:
        return resolve_task_artifact(task_dir(record.id), record.id, value or str(task_dir(record.id) / names[field]), field=field)
    except TaskArtifactUnavailable as exc:
        if not value and exc.reason == "missing_destination":
            return None
        raise


def read_task_report(record: TaskRecord, field: str) -> dict:
    """Saved report pointers are owned artifacts; absent optional reports stay empty."""
    path = task_report_path(record, field)
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def saved_note_missing(record: TaskRecord) -> bool:
    try:
        return task_artifact_path(record, "note_path") is None
    except TaskArtifactUnavailable as exc:
        if exc.reason == "missing_destination":
            return True
        raise


def saved_task_media_file(record: TaskRecord, value: str) -> Path:
    from .task_media_guard import validate_current_media_file
    return validate_current_media_file(record, value, task_dir(record.id))


def owned_bundle_writer(record: TaskRecord, writer):
    """Keep archive metadata original while validating every file-copy request."""
    def write(archive, value: str, archive_name: str):
        directory = archive_name.partition("/")[0]
        if directory not in {"subtitles", "grids"}:
            raise TaskArtifactUnavailable("unsupported_artifact")
        if directory == "subtitles" and value != record.subtitle_path:
            raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
        path = (resolve_task_grid(task_dir(record.id), record.id, value) if directory == "grids" else
                task_artifact_path(record, "subtitle_path"))
        if path is None:
            raise TaskArtifactUnavailable("missing_destination")
        writer(archive, str(path), f"{directory}/{path.name}")
    return write


def task_media_path_diagnostics(record: TaskRecord) -> dict:
    from .task_media_guard import task_media_path_diagnostics as diagnostics
    return diagnostics(record, task_dir(record.id))
