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
from .text_cleanup import read_canonical_text


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
    record = get_task(task_id)
    if not record.note_path:
        return ""
    path = Path(record.note_path)
    if not path.is_file():
        return ""
    diagnostics = record.summary_diagnostics or {}
    if (record.summary_source == "transcript-draft"
            and record.error_code == "transcript_review_required"
            and record.status == "failed"
            and diagnostics.get("note_publication") == "review_draft"
            and diagnostics.get("review_required") is True
            and diagnostics.get("summary_generated") is False
            and path.name == "draft.review.md"):
        # These are generated UTF-8 drafts, not an alternate decoder for formal
        # notes. Keep the warning and unresolved words exactly as preserved.
        return path.read_bytes().decode("utf-8")
    return read_canonical_text(path).text


def read_task_transcript(task_id: str) -> dict[str, Any]:
    record = get_task(task_id)
    if not record.transcript_path:
        return TranscriptResult().model_dump(mode="json")
    path = Path(record.transcript_path)
    if not path.is_file():
        return TranscriptResult().model_dump(mode="json")
    value = json.loads(read_canonical_text(path).text)
    return value if isinstance(value, dict) else TranscriptResult().model_dump(mode="json")


__all__ = ["read_task_note", "read_task_transcript", "public_summary_task"]
