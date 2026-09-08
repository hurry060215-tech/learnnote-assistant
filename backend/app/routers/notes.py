"""Evidence-first note document endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
import hashlib
import json
import threading
from pydantic import BaseModel, Field
from ..config import DATA_DIR
from ..storage import atomic_write_text
from ..library import get_material, material_content

from ..knowledge import evidence_for_task
from ..note_document import build_note_document, normalize_note_markdown
from ..storage import get_task
from ..storage import read_json
from ..task_artifacts import read_task_note


notes_router = APIRouter(prefix="/api/tasks", tags=["notes"])


@notes_router.get("/{task_id}/ocr")
def api_ocr(task_id: str):
    try:
        get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return read_json(task_id, "ocr.json", {"status": "not_requested", "frames": []})


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


# User editions are independent of generated task artifacts and source evidence.
# Optimistic revision checks prevent a stale tab from replacing a newer edit.

_edition_lock = threading.RLock()

class EditionRequest(BaseModel):
    text: str = Field(max_length=5_000_000)
    revision: str = Field(max_length=64)

def _edition_source(kind: str, source_id: str):
    if kind == "task":
        get_task(source_id)
        return read_task_note(source_id)
    if kind == "material":
        get_material(source_id)
        return material_content(source_id)
    raise ValueError("Unknown source type")

def _edition_path(kind: str, source_id: str):
    key = hashlib.sha256(f"{kind}:{source_id}".encode()).hexdigest()
    return DATA_DIR / "user-editions" / f"{key}.json"

def _edition_state(kind: str, source_id: str):
    original = _edition_source(kind, source_id)
    path = _edition_path(kind, source_id)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"text": original, "revision": hashlib.sha256(original.encode()).hexdigest(), "edited": False}

@notes_router.get("/editions/{kind}/{source_id}")
def get_edition(kind: str, source_id: str):
    try:
        with _edition_lock:
            return _edition_state(kind, source_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, "Source unavailable") from exc

@notes_router.put("/editions/{kind}/{source_id}")
def put_edition(kind: str, source_id: str, request: EditionRequest):
    try:
        with _edition_lock:
            current = _edition_state(kind, source_id)
            if current["revision"] != request.revision:
                raise HTTPException(409, "笔记已在其他页面更新。请先复制当前修改，再重新打开笔记。")
            state = {"text": request.text, "revision": hashlib.sha256(request.text.encode()).hexdigest(), "edited": True}
            atomic_write_text(_edition_path(kind, source_id), json.dumps(state, ensure_ascii=False))
            return state
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, "Source unavailable") from exc


@notes_router.get("/editions/{kind}/{source_id}/exports/{format}")
def export_edition(kind: str, source_id: str, format: str, include_annotations: bool = False):
    from types import SimpleNamespace
    from fastapi.responses import Response
    from ..personal_notes import annotation_markdown
    from ..document_exports import build_docx_export, build_pdf_export, sanitize_export_text, DocumentExportUnavailable
    if format not in {"markdown", "docx", "pdf"}:
        raise HTTPException(404, "Unsupported export format")
    value = get_edition(kind, source_id)
    text = value["text"]
    if include_annotations:
        text += annotation_markdown(kind, source_id)
    if format == "markdown":
        return Response(sanitize_export_text(text), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="note.md"'})
    task = get_task(source_id) if kind == "task" else SimpleNamespace(id=source_id, title=get_material(source_id)["title"], page_url="")
    try:
        result = build_docx_export(task, text) if format == "docx" else build_pdf_export(task, text)
    except DocumentExportUnavailable as exc:
        raise HTTPException(503, "导出组件不可用，请检查安装包。") from exc
    return Response(result.content, media_type=result.media_type, headers={"Content-Disposition": f'attachment; filename="note.{format}"'})
