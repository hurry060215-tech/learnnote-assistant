from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..learning_spaces import (
    delete_learning_space,
    get_learning_space,
    list_learning_spaces,
    list_space_practice,
    migrate_courses_to_learning_spaces,
    propose_space_practice,
    save_learning_space,
    save_space_practice,
    source_refresh_status,
    space_evidence,
    space_summary,
)
from ..models import StudyCard
from ..study import assign_cards_to_space, due_cards, save_cards_unique, unassigned_cards

learning_space_router = APIRouter(prefix="/api/learning-spaces", tags=["learning-spaces"])


class LearningSpaceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["task", "material", "url"]
    id: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_-]*$")
    url: str = Field(default="", max_length=4096)
    title: str = Field(default="", max_length=500)


class LearningSpaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(default="", max_length=1000)
    focus: str = Field(default="", max_length=2000)
    daily_review_limit: int = Field(default=10, ge=1, le=200)
    question_types: list[str] = Field(default_factory=lambda: ["short_answer"], max_length=12)
    sources: list[LearningSpaceSource] = Field(default_factory=list, max_length=200)
    paused: bool = False
    revision: int = Field(default=0, ge=0)


def _space_or_404(space_id: str) -> dict:
    try:
        return get_learning_space(space_id)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(404, {"code": "learning_space_not_found", "message": "学习空间不存在或已删除。"}) from exc


@learning_space_router.get("")
def api_learning_spaces() -> dict:
    return {"spaces": list_learning_spaces(), "migration": migrate_courses_to_learning_spaces()}


@learning_space_router.post("")
def api_create_learning_space(request: LearningSpaceRequest) -> dict:
    try:
        return {"space": save_learning_space(
            request.title,
            [item.model_dump() for item in request.sources],
            goal=request.goal,
            focus=request.focus,
            daily_review_limit=request.daily_review_limit,
            question_types=request.question_types,
            paused=request.paused,
        )}
    except (ValueError, OSError) as exc:
        raise HTTPException(422, {"code": str(exc), "message": "学习空间或来源无效。"}) from exc


@learning_space_router.get("/{space_id}")
def api_learning_space(space_id: str) -> dict:
    return {"space": _space_or_404(space_id)}


@learning_space_router.put("/{space_id}")
def api_save_learning_space(space_id: str, request: LearningSpaceRequest) -> dict:
    try:
        return {"space": save_learning_space(
            request.title,
            [item.model_dump() for item in request.sources],
            goal=request.goal,
            focus=request.focus,
            daily_review_limit=request.daily_review_limit,
            question_types=request.question_types,
            paused=request.paused,
            space_id=space_id,
            revision=request.revision,
        )}
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(409 if "changed" in code else 422, {"code": code, "message": "学习空间已被更新，请重新读取后再保存。" if "changed" in code else "学习空间内容无效。"}) from exc
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(404, {"code": "learning_space_not_found", "message": "学习空间不存在。"}) from exc


@learning_space_router.delete("/{space_id}")
def api_delete_learning_space(space_id: str) -> dict:
    try:
        delete_learning_space(space_id)
        return {"ok": True, "deleted": True, "sources_deleted": False, "cards_deleted": False}
    except ValueError as exc:
        raise HTTPException(422, {"code": str(exc), "message": "已有复习是系统保留入口，不能删除。"}) from exc
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(404, {"code": "learning_space_not_found", "message": "学习空间不存在。"}) from exc


@learning_space_router.get("/{space_id}/summary")
def api_learning_space_summary(space_id: str) -> dict:
    _space_or_404(space_id)
    try:
        return space_summary(space_id)
    except (ValueError, OSError) as exc:
        raise HTTPException(404, {"code": "learning_space_not_found", "message": "学习空间不可用。"}) from exc


@learning_space_router.get("/{space_id}/sources")
def api_learning_space_sources(space_id: str) -> dict:
    _space_or_404(space_id)
    return {"sources": source_refresh_status(space_id), "evidence": space_evidence(space_id, 1000)}


@learning_space_router.get("/{space_id}/due")
def api_learning_space_due(space_id: str, limit: int = 50) -> dict:
    summary = api_learning_space_summary(space_id)
    evidence_ids = {str(item.get("evidence_id")) for item in space_evidence(space_id, 2000) if item.get("evidence_id")}
    cards = due_cards(limit, None if space_id == "existing-review" else evidence_ids)
    if space_id == "existing-review":
        allowed = {card.card_id for card in unassigned_cards(1000)}
        cards = [card for card in cards if card.card_id in allowed]
    unique_cards = {card.card_id: card for card in cards}.values()
    return {"space_id": space_id, "cards": [card.model_dump(mode="json") for card in unique_cards], "summary": summary}


@learning_space_router.post("/{space_id}/practice/proposals")
def api_learning_space_practice_proposals(space_id: str, payload: dict | None = Body(default=None)) -> dict:
    _space_or_404(space_id)
    limit = int((payload or {}).get("limit") or 20)
    try:
        return {"space_id": space_id, "proposals": propose_space_practice(space_id, limit)}
    except (ValueError, OSError) as exc:
        raise HTTPException(422, {"code": str(exc), "message": "当前空间还没有可生成练习的来源证据。"}) from exc


@learning_space_router.get("/{space_id}/practice")
def api_learning_space_practice(space_id: str) -> dict:
    _space_or_404(space_id)
    return {"space_id": space_id, "items": list_space_practice(space_id)}


@learning_space_router.post("/{space_id}/practice")
def api_save_learning_space_practice(space_id: str, payload: dict | None = Body(default=None)) -> dict:
    _space_or_404(space_id)
    body = payload or {}
    items = body.get("items") if isinstance(body.get("items"), list) else body.get("questions")
    if not isinstance(items, list) or not items:
        raise HTTPException(422, {"code": "practice_items_required", "message": "请先预览并选择练习题。"})
    try:
        saved = save_space_practice(space_id, items)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, {"code": str(exc), "message": "练习题必须绑定当前学习空间中的来源。"}) from exc
    return {"space_id": space_id, "items": saved}


@learning_space_router.post("/{space_id}/review-cards")
def api_save_learning_space_cards(space_id: str, payload: dict | None = Body(default=None)) -> dict:
    _space_or_404(space_id)
    raw = (payload or {}).get("cards")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(422, {"code": "cards_required", "message": "请先预览并选择复习卡片。"})
    evidence_ids = {str(item.get("evidence_id")) for item in space_evidence(space_id, 2000) if item.get("evidence_id")}
    cards = []
    for item in raw[:100]:
        if not isinstance(item, dict):
            continue
        ids = [str(value)[:128] for value in (item.get("source_evidence_ids") or []) if str(value) in evidence_ids]
        if not ids:
            continue
        try:
            cards.append(StudyCard(front=str(item.get("front") or item.get("question") or "").strip(), back=str(item.get("back") or item.get("answer") or "").strip(), source_evidence_ids=ids))
        except ValueError:
            continue
    saved = save_cards_unique(cards)
    assign_cards_to_space(space_id, cards=cards)
    return {"space_id": space_id, "cards": [card.model_dump(mode="json") for card in saved], "deduplicated": len(cards) - len(saved)}
