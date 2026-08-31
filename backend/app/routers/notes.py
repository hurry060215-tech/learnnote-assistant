"""Evidence-first note document endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..knowledge import evidence_for_task
from ..note_document import build_note_document, normalize_note_markdown
from ..storage import get_task
from ..task_artifacts import read_task_note


notes_router = APIRouter(prefix="/api/tasks", tags=["notes"])


@notes_router.get("/{task_id}/note-document")
def api_note_document(task_id: str) -> dict:
    """Return a rebuildable semantic projection without changing task files."""

    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    note = read_task_note(task.id)
    if not note.strip():
        raise HTTPException(status_code=404, detail="Note not found")
    normalized = normalize_note_markdown(task.title, note)
    document = build_note_document(task.title, normalized.markdown, evidence_for_task(task.id))
    document["task_id"] = task.id
    document["normalization"] = normalized.report
    document["evidence_quality"] = task.evidence_coverage.model_dump(mode="json")
    return document


__all__ = ["notes_router"]
