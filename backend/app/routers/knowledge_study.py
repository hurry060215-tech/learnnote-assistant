from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from pydantic import ValidationError

from ..embeddings import embedding_status
from ..knowledge import add_evidence, answer_from_evidence, evidence_for_task, extract_import_text, remove_evidence, search_evidence
from ..models import SourceEvidence, StudyCard, StudyCardPositionRequest, StudyCardStatusRequest, StudyPlanUpdateRequest, StudyReviewRequest
from ..study import due_cards, export_study_data, get_study_plan, list_cards, propose_cards, review_card, review_history, save_cards, set_card_position, set_card_status, study_summary, update_study_plan
from ..storage import get_task


knowledge_router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
study_router = APIRouter(prefix="/api/study", tags=["study"])
task_study_router = APIRouter(prefix="/api/tasks", tags=["study"])


@knowledge_router.post("/evidence")
def api_knowledge_evidence(evidence: SourceEvidence) -> dict:
    try:
        stored = add_evidence(evidence)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "证据文本不能为空。"}) from exc
    return {"ok": True, "evidence": stored.model_dump(mode="json")}


@knowledge_router.post("/import-file")
async def api_knowledge_import_file(file: UploadFile = File(...)) -> dict:
    filename = Path(file.filename or "evidence.txt").name
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"code": "evidence_file_too_large", "message": "导入文件不能超过 20 MB。"})
    try:
        text, source_type = extract_import_text(filename, content, file.content_type or "")
        stored = add_evidence(SourceEvidence(
            source_type=source_type,
            title=Path(filename).stem[:500],
            source_uri=f"local://{filename}",
            locator="file",
            text=text,
            metadata={"filename": filename, "content_type": file.content_type or ""},
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "无法从该文件提取可检索文本。"}) from exc
    return {"ok": True, "evidence": stored.model_dump(mode="json")}


@knowledge_router.get("/search")
def api_knowledge_search(q: str = "", limit: int = 12, mode: str = "lexical") -> dict:
    try:
        results = search_evidence(q, limit, mode)
    except RuntimeError as exc:
        if str(exc) == "local_embedding_unavailable":
            raise HTTPException(status_code=409, detail={"code": str(exc), "message": "可选本地 embedding 尚未安装。"}) from exc
        raise
    return {"query": q, "mode": mode, "results": results}


@knowledge_router.get("/embedding-status")
def api_knowledge_embedding_status() -> dict:
    return embedding_status()


@knowledge_router.delete("/evidence/{evidence_id}")
def api_knowledge_delete_evidence(evidence_id: str) -> dict:
    if not remove_evidence(evidence_id):
        raise HTTPException(status_code=404, detail={"code": "evidence_not_found", "message": "证据不存在。"})
    return {"ok": True, "evidence_id": evidence_id}


@knowledge_router.post("/ask")
def api_knowledge_ask(payload: dict | None = Body(default=None)) -> dict:
    body = payload or {}
    question = str(body.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail={"code": "question_required", "message": "请输入问题。"})
    try:
        return answer_from_evidence(question, int(body.get("limit") or 6), str(body.get("mode") or "lexical"))
    except RuntimeError as exc:
        if str(exc) == "local_embedding_unavailable":
            raise HTTPException(status_code=409, detail={"code": str(exc), "message": "可选本地 embedding 尚未安装。"}) from exc
        raise


@study_router.post("/proposals")
def api_study_proposals(payload: dict | None = Body(default=None)) -> dict:
    body = payload or {}
    raw = body.get("evidence") if isinstance(body.get("evidence"), list) else []
    evidence: list[SourceEvidence] = []
    for item in raw:
        try:
            evidence.append(SourceEvidence.model_validate(item))
        except ValidationError:
            continue
    return {"proposals": [card.model_dump(mode="json") for card in propose_cards(evidence, int(body.get("limit") or 20))]}


@task_study_router.post("/{task_id}/study-proposals")
def api_task_study_proposals(task_id: str, limit: int = 20) -> dict:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    evidence = [SourceEvidence.model_validate(item) for item in evidence_for_task(task.id)]
    return {"task_id": task.id, "proposals": [card.model_dump(mode="json") for card in propose_cards(evidence, limit)]}


@study_router.post("/cards")
def api_study_cards(payload: dict | None = Body(default=None)) -> dict:
    body = payload or {}
    raw = body.get("cards") if isinstance(body.get("cards"), list) else []
    cards: list[StudyCard] = []
    for item in raw:
        try:
            cards.append(StudyCard.model_validate(item))
        except ValidationError:
            continue
    if not cards:
        raise HTTPException(status_code=422, detail={"code": "cards_required", "message": "至少确认一张记忆卡片。"})
    return {"cards": [card.model_dump(mode="json") for card in save_cards(cards)]}


@study_router.get("/due")
def api_study_due(limit: int = 50) -> dict:
    return {"cards": [card.model_dump(mode="json") for card in due_cards(limit)]}


@study_router.get("/cards")
def api_study_list_cards(status: str = "", limit: int = 200) -> dict:
    return {"cards": [card.model_dump(mode="json") for card in list_cards(status, limit)]}


@study_router.patch("/cards/{card_id}")
def api_study_card_status(card_id: str, request: StudyCardStatusRequest) -> dict:
    try:
        card = set_card_status(card_id, request.status)
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "card_not_found" else 422
        raise HTTPException(status_code=status, detail={"code": code, "message": "卡片不存在或状态无效。"}) from exc
    return {"card": card.model_dump(mode="json")}


@study_router.post("/cards/{card_id}/reorder")
def api_study_card_reorder(card_id: str, request: StudyCardPositionRequest) -> dict:
    try:
        card = set_card_position(card_id, request.position)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc), "message": "卡片不存在。"}) from exc
    return {"card": card.model_dump(mode="json")}


@study_router.get("/summary")
def api_study_summary() -> dict:
    return study_summary()


@study_router.get("/reviews")
def api_study_reviews(card_id: str = "", limit: int = 200) -> dict:
    return {"reviews": review_history(card_id, limit)}


@study_router.get("/export")
def api_study_export() -> dict:
    return export_study_data()


@study_router.get("/plan")
def api_study_plan() -> dict:
    return {"plan": get_study_plan().model_dump(mode="json")}


@study_router.put("/plan")
def api_update_study_plan(request: StudyPlanUpdateRequest) -> dict:
    return {"plan": update_study_plan(request.title, request.daily_target, request.paused).model_dump(mode="json")}


@study_router.post("/cards/{card_id}/review")
def api_study_review(card_id: str, request: StudyReviewRequest) -> dict:
    try:
        card = review_card(card_id, request.rating)
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "card_not_found" else 422
        raise HTTPException(status_code=status, detail={"code": code, "message": "记忆卡片不存在或评分无效。"}) from exc
    return {"card": card.model_dump(mode="json")}
