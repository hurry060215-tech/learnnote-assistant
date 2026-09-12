from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from ..personal_notes import list_annotations, save_annotation, delete_annotation

personal_router = APIRouter(prefix="/api/personal", tags=["personal"])


class AnnotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=8000)
    quote: str = Field(default="", max_length=1000)
    id: str = Field(default="", max_length=40, pattern="^[a-f0-9]*$")
    anchor: dict[str, str] = Field(default_factory=dict)


@personal_router.get("/{kind}/{source_id}")
def get_annotations(kind: Literal["task", "material"], source_id: str):
    try:
        return {"annotations": list_annotations(kind, source_id)}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Source unavailable") from exc


@personal_router.post("/{kind}/{source_id}")
def put_annotation(kind: Literal["task", "material"], source_id: str, request: AnnotationRequest):
    try:
        return {"annotation": save_annotation(kind, source_id, request.text, request.quote, request.id, request.anchor)}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@personal_router.delete("/{kind}/{source_id}/{annotation_id}")
def remove_annotation(kind: Literal["task", "material"], source_id: str, annotation_id: str):
    try:
        return {"deleted": delete_annotation(kind, source_id, annotation_id)}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Source unavailable") from exc
