from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from ..personal_notes import list_annotations, save_annotation, delete_annotation
from ..personal_anchors import annotation_targets

personal_router = APIRouter(prefix="/api/personal", tags=["personal"])
PUBLIC_ERRORS = {
    code: (409 if code in {"annotation_revision_conflict", "annotation_request_conflict", "annotation_anchor_stale"} else 422, code)
    for code in ("annotation_revision_conflict", "annotation_request_conflict", "annotation_anchor_stale",
                 "annotation_text_required", "annotation_quote_invalid", "annotation_request_id_invalid",
                 "annotation_not_found", "annotation_limit_reached", "annotation_anchor_invalid",
                 "annotation_anchor_kind_invalid", "annotation_anchor_range_invalid",
                 "annotation_anchor_target_required", "annotation_anchor_source_invalid")
}


class AnnotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=8000)
    quote: str | None = Field(default=None, max_length=1000)
    id: str = Field(default="", max_length=128, pattern="^[A-Za-z0-9_-]*$")
    anchor: dict = Field(default_factory=dict)
    revision: str = Field(default="", max_length=64)
    request_id: str = Field(default="", max_length=128, pattern="^[A-Za-z0-9_-]*$")


@personal_router.get("/{kind}/{source_id}/targets")
def get_annotation_targets(kind: Literal["task", "material"], source_id: str):
    try:
        return annotation_targets(kind, source_id)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Source unavailable") from exc


@personal_router.get("/{kind}/{source_id}")
def get_annotations(kind: Literal["task", "material"], source_id: str):
    try:
        return {"annotations": list_annotations(kind, source_id)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Source unavailable") from exc


@personal_router.post("/{kind}/{source_id}")
def put_annotation(kind: Literal["task", "material"], source_id: str, request: AnnotationRequest):
    try:
        return {"annotation": save_annotation(kind, source_id, request.text, request.quote, request.id, request.anchor, request.revision, request.request_id)}
    except (ValueError, OSError) as exc:
        status, detail = PUBLIC_ERRORS.get(str(exc), (422, "annotation_save_failed"))
        raise HTTPException(status_code=status, detail=detail) from exc


@personal_router.delete("/{kind}/{source_id}/{annotation_id}")
def remove_annotation(kind: Literal["task", "material"], source_id: str, annotation_id: str):
    try:
        return {"deleted": delete_annotation(kind, source_id, annotation_id)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Source unavailable") from exc
