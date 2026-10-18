"""Evidence-first note document endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
import hashlib
import json
import re
from uuid import uuid4
from contextlib import contextmanager
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from ..config import DATA_DIR
from ..storage import atomic_write_text
from ..library import get_material, material_content

from ..knowledge import evidence_for_task
from ..note_document import build_note_document, normalize_note_markdown
from ..storage import get_task
from ..storage import read_json
from ..task_artifacts import read_task_note
from ..task_paths import TaskArtifactUnavailable
from ..partial_note_projection import read_partial_note
from .section_reviews import section_reviews_router
from ..personal_storage import RECOVERY_MESSAGE, PersonalStorageError, PersonalRecoveryRequired, lock as _edition_lock, personal_transaction


notes_router = APIRouter(prefix="/api/tasks", tags=["notes"])
notes_router.include_router(section_reviews_router)



@notes_router.get("/{task_id}/partial-note")
def api_partial_note(task_id: str) -> dict:
    """Read an unverified current-attempt projection; never run the pipeline."""
    try:
        return read_partial_note(task_id)
    except FileNotFoundError:
        pass
    raise HTTPException(status_code=404, detail="Task not found")


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

@contextmanager
def edition_transaction():
    """Serialize manual/assistant saves with annotation and backup writes."""
    try:
        with personal_transaction(DATA_DIR):
            root = DATA_DIR / "user-editions"
            if root.is_symlink():
                raise PersonalStorageError("personal_storage_unavailable")
            root.mkdir(parents=True, exist_ok=True)
            yield
    except PersonalRecoveryRequired as exc:
        raise HTTPException(409, {"code": "personal_restore_recovery_required", "message": RECOVERY_MESSAGE}) from exc
    except PersonalStorageError as exc:
        raise HTTPException(409, "个人资料暂不可写入，请检查本地存储后重试。") from exc

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
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(state, dict) or not isinstance(state.get("text"), str)
                    or not isinstance(state.get("revision"), str)
                    or state["revision"] != hashlib.sha256(state["text"].encode()).hexdigest()
                    or state.get("edited") is not True
                    or ("write_id" in state and (not isinstance(state["write_id"], str)
                        or re.fullmatch(r"[A-Za-z0-9_-]{8,64}", state["write_id"]) is None))):
                raise ValueError("Invalid saved edition")
            return state
        except (OSError, ValueError, TypeError) as exc:
            # Preserve unreadable personal work instead of overwriting it.
            raise HTTPException(409, "已保存的个人修改暂时无法读取，原文件未改动。请先复制当前编辑内容，并从备份恢复后重试。") from exc
    return {"text": original, "revision": hashlib.sha256(original.encode()).hexdigest(), "edited": False}

@notes_router.get("/editions/{kind}/{source_id}")
def get_edition(kind: str, source_id: str, reader_snapshot: bool = False, expected_generation: str = ""):
    if reader_snapshot:
        from ..generated_draft_reader import read_generated_draft, DraftSnapshotUnavailable
        try:
            if kind != "task":
                raise DraftSnapshotUnavailable("task_ineligible")
            return read_generated_draft(source_id, expected_generation, data_dir=DATA_DIR,
                                        edition_path=_edition_path(kind, source_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, "Source unavailable") from exc
        except (OSError, ValueError, TypeError, KeyError) as exc:
            reason = str(exc) if isinstance(exc, DraftSnapshotUnavailable) else "artifact_unavailable"
            raise HTTPException(409, {"code": "reader_snapshot_unavailable", "reason": reason}) from exc
    try:
        with _edition_lock:
            return _edition_state(kind, source_id)
    except TaskArtifactUnavailable as exc:
        raise HTTPException(409, exc.detail()) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, "Source unavailable") from exc

@notes_router.put("/editions/{kind}/{source_id}")
def put_edition(kind: str, source_id: str, request: EditionRequest):
    try:
        with edition_transaction():
            return save_edition_locked(kind, source_id, request.text, request.revision)
    except TaskArtifactUnavailable as exc:
        raise HTTPException(409, exc.detail()) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, "Source unavailable") from exc


def save_edition_locked(kind: str, source_id: str, text: str, revision: str, write_id: str | None = None):
    """Caller holds edition_transaction; preserve the existing revision contract."""
    current = _edition_state(kind, source_id)
    if current["revision"] != revision:
        raise HTTPException(409, "笔记已在其他页面更新。请先复制当前修改，再重新打开笔记。")
    # A content hash alone cannot distinguish a later manual return to old text.
    # This marker is committed atomically with the body, without migrating originals.
    marker = write_id or uuid4().hex
    if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", marker) is None:
        raise ValueError("Invalid edition write marker")
    state = {"text": text, "revision": hashlib.sha256(text.encode()).hexdigest(), "edited": True, "write_id": marker}
    atomic_write_text(_edition_path(kind, source_id), json.dumps(state, ensure_ascii=False))
    return state


class PersonalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["mark", "revoke"]
    expected_context_revision: str = Field(max_length=64)
    expected_review_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


def _personal_review_context(kind: str, source_id: str):
    from ..personal_restore import _read_existing, _edition_file
    from ..personal_notes import validate_personal_data
    from ..personal_review_context import source_context
    content = _read_existing(_edition_path(kind, source_id))
    if content is not None:
        _edition_file(content, _edition_path(kind, source_id).stem, validate_personal_data)
        edition = json.loads(content.decode("utf-8"))
        if edition.get("edited") is not True:
            raise ValueError("personal_review_edition_invalid")
        if "write_id" in edition and (not isinstance(edition["write_id"], str) or re.fullmatch(r"[A-Za-z0-9_-]{8,64}", edition["write_id"]) is None):
            raise ValueError("personal_review_edition_invalid")
    elif kind == "task":
        from ..personal_anchors import _opened_artifact, MAX_ARTIFACT_BYTES
        from ..task_artifacts import decode_task_note
        task = get_task(source_id)
        with _opened_artifact(source_id, task.note_path) as stream:
            if stream is None:
                raise ValueError("personal_review_source_unavailable")
            raw = stream.read(MAX_ARTIFACT_BYTES + 1)
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ValueError("personal_review_source_unavailable")
        text = decode_task_note(task, raw)
        edition = {"text": text, "revision": hashlib.sha256(text.encode()).hexdigest(), "edited": False}
    else:
        text = _edition_source(kind, source_id)
        edition = {"text": text, "revision": hashlib.sha256(text.encode()).hexdigest(), "edited": False}
    try:
        return source_context(kind, source_id, edition)
    except HTTPException as exc:
        raise ValueError("personal_review_source_unavailable") from exc


def _personal_review_call(kind: str, source_id: str, request=None):
    from ..personal_reviews import read_review, change_review, ReviewConflict
    reader = lambda: _personal_review_context(kind, source_id)
    try:
        if request is None:
            return read_review(DATA_DIR, kind, source_id, reader)
        return change_review(DATA_DIR, kind, source_id, reader, **request.model_dump())
    except PersonalRecoveryRequired as exc:
        raise HTTPException(409, {"code": "personal_restore_recovery_required", "message": RECOVERY_MESSAGE}) from exc
    except ReviewConflict as exc:
        raise HTTPException(409, "笔记、来源或核对记录已更新。请刷新后重新核对；本次未覆盖现有记录。") from exc
    except (PersonalStorageError, ValueError, OSError) as exc:
        raise HTTPException(409, "个人核对记录暂时无法安全读取或写入，原记录未改动。请检查本地存储或恢复备份。") from exc


@notes_router.get("/editions/{kind}/{source_id}/personal-review")
def get_personal_review(kind: str, source_id: str):
    return _personal_review_call(kind, source_id)


@notes_router.post("/editions/{kind}/{source_id}/personal-review")
def post_personal_review(kind: str, source_id: str, request: PersonalReviewRequest):
    return _personal_review_call(kind, source_id, request)


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
        from ..review_presentation import project_source_reviews
        return Response(sanitize_export_text(project_source_reviews(text)["markdown"]), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="note.md"'})
    task = get_task(source_id) if kind == "task" else SimpleNamespace(id=source_id, title=get_material(source_id)["title"], page_url="")
    try:
        result = build_docx_export(task, text) if format == "docx" else build_pdf_export(task, text)
    except DocumentExportUnavailable as exc:
        raise HTTPException(503, "导出组件不可用，请检查安装包。") from exc
    return Response(result.content, media_type=result.media_type, headers={"Content-Disposition": f'attachment; filename="note.{format}"'})
