"""Read-only access to portable task artifacts.

Routers and integration projections use this module instead of importing the
processing orchestrator.  The task record remains the authority for paths and
all decoding is strict so corrupt artifacts never become silent UI content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import TranscriptResult
from .storage import get_task
from .text_cleanup import read_canonical_text


def read_task_note(task_id: str) -> str:
    record = get_task(task_id)
    if not record.note_path:
        return ""
    path = Path(record.note_path)
    if not path.is_file():
        return ""
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


__all__ = ["read_task_note", "read_task_transcript"]
