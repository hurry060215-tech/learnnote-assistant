from __future__ import annotations

from pathlib import Path
from urllib.parse import quote
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.responses import Response

from ..community import add_community_context, clear_all_community_context, clear_community_context, community_settings, delete_community_item, list_community_context, sample_community_context, set_community_enabled
from ..document_exports import DocumentExportUnavailable, build_docx_export, build_html_export, build_pdf_export, build_structured_export, normalize_export_options
from ..embeddings import embedding_status
from ..knowledge import add_evidence, answer_from_evidence, evidence_by_ids, evidence_for_task, extract_import_text, preserve_raw_import, remove_evidence, search_evidence
from ..models import SourceEvidence, StudyCard, StudyCardPositionRequest, StudyCardStatusRequest, StudyPlanUpdateRequest, StudyReviewRequest
from ..note_document import normalize_note_markdown
from ..study import activity_summary, clear_study_data, due_cards, export_study_data, get_study_plan, list_cards, propose_cards, record_activity, review_card, review_history, save_cards, set_card_position, set_card_status, study_dashboard, study_summary, update_study_plan
from ..storage import get_task
from ..study import initialize_study_timezone
from ..study import rebuild_study_schedules
from ..courses import course_evidence_ids
from ..task_artifacts import read_task_note, read_task_transcript
from ..learning_spaces import list_space_practice
from ..config import DATA_DIR
from ..storage import atomic_write_text
import json
from pydantic import BaseModel, ConfigDict, Field


knowledge_router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
study_router = APIRouter(prefix="/api/study", tags=["study"])
task_study_router = APIRouter(prefix="/api/tasks", tags=["study"])


class UnifiedExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str = Field(default="html", pattern=r"^(html|docx|pdf|markdown)$")
    options: dict = Field(default_factory=dict)
    annotations: str = Field(default="", max_length=100000)
    practice: list[dict] = Field(default_factory=list, max_length=200)
    space_id: str = Field(default="", max_length=64)


def _export_presets_path():
    return DATA_DIR / "export-presets.json"


@study_router.get("/cards/{card_id}/schedule-preview")
def api_schedule_preview(card_id: str):
    from ..study import review_schedule_preview
    try:
        return review_schedule_preview(card_id)
    except ValueError as exc:
        raise HTTPException(404, "卡片不存在。") from exc


@knowledge_router.post("/evidence")
def api_knowledge_evidence(evidence: SourceEvidence) -> dict:
    try:
        stored = add_evidence(evidence)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "证据文本不能为空。"}) from exc
    return {"ok": True, "evidence": stored.model_dump(mode="json")}


@knowledge_router.post("/import-file")
async def api_knowledge_import_file(file: UploadFile = File(...), encoding: str = "") -> dict:
    filename = Path(file.filename or "evidence.txt").name
    content = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail={"code": "evidence_file_too_large", "message": "导入文件不能超过 20 MB。"})
    try:
        text, source_type = extract_import_text(filename, bytes(content), file.content_type or "", encoding=encoding)
        raw_info = preserve_raw_import(bytes(content), filename)
        stored = add_evidence(SourceEvidence(
            source_type=source_type,
            title=Path(filename).stem[:500],
            source_uri=f"local://{filename}",
            locator="file",
            text=text,
            metadata={"filename": filename, "content_type": file.content_type or "", "raw_sha256": raw_info["sha256"], "raw_byte_count": raw_info["byte_count"], "decoding_hint": encoding.strip()[:40]},
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "无法从该文件提取可检索文本。"}) from exc
    return {"ok": True, "evidence": stored.model_dump(mode="json")}


@knowledge_router.get("/evidence/{evidence_id}")
def api_evidence_source(evidence_id: str) -> dict:
    items = evidence_by_ids([evidence_id], limit=1)
    if not items:
        raise HTTPException(status_code=404, detail={"code": "evidence_missing", "message": "出处已删除或不可用，请重新关联原文。"})
    return {"evidence": items[0]}


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
    raw_ids = body.get("evidence_ids") if isinstance(body.get("evidence_ids"), list) else []
    requested_ids = [str(value)[:128] for value in raw_ids[:100] if str(value).strip()]
    evidence = [SourceEvidence.model_validate(item) for item in evidence_by_ids(requested_ids, limit=100)]
    if not evidence:
        raise HTTPException(status_code=422, detail={"code": "canonical_evidence_required", "message": "请先选择资料库中的可追溯证据。"})
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
    if len(raw) > 100:
        raise HTTPException(status_code=413, detail={"code": "too_many_cards", "message": "单次最多保存 100 张卡片。"})
    for item in raw:
        if not isinstance(item, dict):
            continue
        front = str(item.get("front") or "").strip()[:1000]
        back = str(item.get("back") or "").strip()[:4000]
        evidence_ids = [str(value)[:128] for value in (item.get("source_evidence_ids") or [])[:8] if str(value).strip()]
        canonical = evidence_by_ids(evidence_ids, limit=8)
        canonical_ids = [str(value["evidence_id"]) for value in canonical]
        if not front or not back or not evidence_ids or set(canonical_ids) != set(evidence_ids):
            continue
        cards.append(StudyCard(front=front, back=back, source_evidence_ids=canonical_ids))
    if not cards:
        raise HTTPException(status_code=422, detail={"code": "cards_required", "message": "至少确认一张记忆卡片。"})
    return {"cards": [card.model_dump(mode="json") for card in save_cards(cards)]}


@study_router.get("/due")
def api_study_due(limit: int = 50, course_id: str = "") -> dict:
    try:
        ids = course_evidence_ids(course_id) if course_id else None
        return {"cards": [card.model_dump(mode="json") for card in due_cards(limit, ids)], "course_id": course_id}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="课程不可用，请重新选择。") from exc


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


@study_router.get("/activity")
def api_study_activity(days: int = 30) -> dict:
    return activity_summary(days)


@study_router.post("/activity")
def api_record_study_activity(payload: dict | None = Body(default=None)) -> dict:
    body = payload or {}
    try:
        return {"ok": True, "activity": record_activity(str(body.get("kind") or ""), str(body.get("source_id") or ""))}
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": "活动类型必须是 reading、answer、self_assessment 或 review。"},
        ) from exc


@study_router.get("/dashboard")
def api_study_dashboard(limit: int = 12, activity_days: int = 14, course_id: str = "") -> dict:
    result = study_dashboard(limit, activity_days)
    if course_id:
        try:
            ids = course_evidence_ids(course_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=404, detail="课程不可用，请重新选择。") from exc
        for key in ("mistakes", "quiz_queue", "due_cards"):
            result[key] = [item for item in result[key] if ids.intersection(item.get("source_evidence_ids", []))]
    result["course_id"] = course_id
    result["activity_scope"] = "all_sources"
    return result


@study_router.get("/reviews")
def api_study_reviews(card_id: str = "", limit: int = 200) -> dict:
    return {"reviews": review_history(card_id, limit)}


@study_router.post("/rebuild-schedule")
def api_rebuild_study_schedule(confirm: str = ""):
    if confirm != "rebuild_from_history":
        raise HTTPException(status_code=400, detail="请确认按评分历史重建调度。")
    return rebuild_study_schedules()


@study_router.get("/export")
def api_study_export() -> dict:
    return export_study_data()


@study_router.delete("/data")
def api_clear_study_data(confirm: str = "") -> dict:
    if confirm != "delete_all_study_data":
        raise HTTPException(status_code=400, detail={"code": "confirmation_required", "message": "永久删除全部学习记录前需要明确确认。"})
    return {"ok": True, **clear_study_data()}


@study_router.get("/plan")
def api_study_plan() -> dict:
    return {"plan": get_study_plan().model_dump(mode="json")}


@study_router.put("/plan")
def api_update_study_plan(request: StudyPlanUpdateRequest) -> dict:
    try:
        return {"plan": update_study_plan(request.title, request.daily_target, request.paused, request.timezone).model_dump(mode="json")}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "请选择有效的 IANA 时区，例如 Asia/Shanghai。"}) from exc


@study_router.post("/plan/initialize")
def api_initialize_study_plan(request: StudyPlanUpdateRequest) -> dict:
    try:
        return {"plan": initialize_study_timezone(request.timezone or "UTC").model_dump(mode="json")}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "无法识别本地时区，请在学习计划中选择时区。"}) from exc


@study_router.post("/cards/{card_id}/review")
def api_study_review(card_id: str, request: StudyReviewRequest) -> dict:
    try:
        card = review_card(card_id, request.rating, request.idempotency_key)
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "card_not_found" else (409 if code == "study_plan_paused" else 422)
        message = "学习计划已暂停，请恢复计划后再复习。" if code == "study_plan_paused" else "记忆卡片不存在、已暂停或评分无效。"
        raise HTTPException(status_code=status, detail={"code": code, "message": message}) from exc
    return {"card": card.model_dump(mode="json")}


@study_router.get("/community/settings")
def api_community_settings() -> dict:
    return community_settings()


@study_router.put("/community/settings")
def api_update_community_settings(payload: dict | None = Body(default=None)) -> dict:
    body = payload or {}
    if "enabled" not in body or not isinstance(body.get("enabled"), bool):
        raise HTTPException(
            status_code=422,
            detail={"code": "community_enabled_boolean_required", "message": "请明确选择是否启用社区观点层。"},
        )
    return set_community_enabled(bool(body["enabled"]))


@study_router.delete("/community/data")
def api_clear_all_community_context(confirm: str = "") -> dict:
    if confirm != "delete_all_community_context":
        raise HTTPException(status_code=400, detail={"code": "confirmation_required", "message": "永久删除全部社区观点前需要明确确认。"})
    return {"ok": True, "deleted_count": clear_all_community_context()}


@task_study_router.get("/{task_id}/community-context")
def api_task_community_context(task_id: str, limit: int = 500) -> dict:
    try:
        get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在。"}) from exc
    return list_community_context(task_id, limit)


@task_study_router.get("/{task_id}/community-context/sample")
def api_sample_task_community_context(task_id: str, limit: int = 20, seed: str = "") -> dict:
    try:
        get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在。"}) from exc
    return sample_community_context(task_id, limit, seed)


@task_study_router.post("/{task_id}/community-context")
def api_add_task_community_context(task_id: str, payload: dict | None = Body(default=None)) -> dict:
    try:
        get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在。"}) from exc
    body = payload or {}
    raw_items = body.get("items") if isinstance(body.get("items"), list) else []
    try:
        return add_community_context(task_id, raw_items)
    except ValueError as exc:
        code = str(exc)
        messages = {
            "community_context_disabled": "社区观点层默认关闭，请先由用户显式启用。",
            "community_items_required": "至少提供一条评论或弹幕。",
            "community_items_too_many": "单次最多导入 500 条社区内容。",
            "community_content_too_large": "单次社区内容总量过大，请分批导入。",
            "community_storage_quota_exceeded": "本地社区观点存储已达到安全上限，请先清理旧内容。",
            "community_items_invalid": "没有可保存的评论或弹幕。",
        }
        status = 409 if code == "community_context_disabled" else 422
        raise HTTPException(status_code=status, detail={"code": code, "message": messages.get(code, "社区内容无法保存。")}) from exc


@task_study_router.delete("/{task_id}/community-context")
def api_clear_task_community_context(task_id: str, confirm: str = "") -> dict:
    try:
        get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在。"}) from exc
    if confirm != "clear_community_context":
        raise HTTPException(
            status_code=400,
            detail={"code": "confirmation_required", "message": "清空社区观点前需要明确确认。"},
        )
    return {"ok": True, "task_id": task_id, "deleted_count": clear_community_context(task_id)}


@task_study_router.delete("/{task_id}/community-context/{item_id}")
def api_delete_task_community_item(task_id: str, item_id: str) -> dict:
    try:
        get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在。"}) from exc
    if not delete_community_item(task_id, item_id):
        raise HTTPException(status_code=404, detail={"code": "community_item_not_found", "message": "这条社区观点不存在。"})
    return {"ok": True, "task_id": task_id, "item_id": item_id, "deleted": True}


def _document_export_response(task_id: str, export_type: str, include_annotations: bool = False) -> Response:
    try:
        task = get_task(task_id)
        note = read_task_note(task_id)
        transcript = read_task_transcript(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在。"}) from exc
    if not note.strip():
        raise HTTPException(status_code=404, detail={"code": "note_not_found", "message": "任务还没有可导出的笔记。"})
    note = normalize_note_markdown(task.title, note).markdown
    if include_annotations:
        from ..personal_notes import annotation_markdown
        note += annotation_markdown("task", task_id)
    try:
        artifact = build_docx_export(task, note, transcript) if export_type == "docx" else build_pdf_export(task, note, transcript)
    except DocumentExportUnavailable as exc:
        code = str(exc)
        raise HTTPException(
            status_code=503,
            detail={
                "code": code,
                "message": "文档导出组件尚未安装。",
                "recovery": {
                    "action": "install_backend_requirements",
                    "command": "python -m pip install -r backend/requirements.txt",
                    "retry_endpoint": f"/api/tasks/{task_id}/exports/{export_type}",
                },
            },
        ) from exc
    filename = f"learnnote-{task.id}.{artifact.suffix}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}',
        "X-LearnNote-Export-Schema": str(artifact.schema_version),
        "X-LearnNote-Font": artifact.font_name,
    }
    if artifact.warnings:
        headers["X-LearnNote-Export-Warning"] = ",".join(artifact.warnings)
    return Response(artifact.content, media_type=artifact.media_type, headers=headers)


@task_study_router.get("/{task_id}/exports/docx")
def api_export_docx(task_id: str, include_annotations: bool = False) -> Response:
    return _document_export_response(task_id, "docx", include_annotations)


@task_study_router.get("/{task_id}/exports/pdf")
def api_export_pdf(task_id: str, include_annotations: bool = False) -> Response:
    return _document_export_response(task_id, "pdf", include_annotations)


def _unified_export_inputs(task_id: str, request: UnifiedExportRequest):
    try:
        task = get_task(task_id)
        note = read_task_note(task_id)
        transcript = read_task_transcript(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, {"code": "task_not_found", "message": "任务或笔记不存在。"}) from exc
    if not note.strip() and not request.options.get("include_note"):
        raise HTTPException(404, {"code": "note_not_found", "message": "任务还没有可导出的笔记。"})
    from ..personal_notes import annotation_markdown
    annotations = request.annotations
    if not annotations and request.options.get("include_annotations", True):
        annotations = annotation_markdown("task", task_id)
    practice = list(request.practice or [])
    if request.space_id and not practice and request.options.get("include_practice", False):
        try:
            practice = list_space_practice(request.space_id)
        except (FileNotFoundError, ValueError, OSError) as exc:
            raise HTTPException(404, {"code": "learning_space_not_found", "message": "学习空间不存在。"}) from exc
    return task, note, transcript, annotations, practice, normalize_export_options(request.options)


@task_study_router.post("/{task_id}/exports/preview")
def api_unified_export_preview(task_id: str, request: UnifiedExportRequest) -> dict:
    task, note, transcript, annotations, practice, options = _unified_export_inputs(task_id, request)
    artifact = build_html_export(task, note, transcript, annotations=annotations, practice=practice, export_options=options)
    return {
        "format": request.format,
        "schema_version": artifact.schema_version,
        "html": artifact.content.decode("utf-8"),
        "warnings": artifact.warnings,
        "font": artifact.font_name,
        "options": options,
    }


@task_study_router.post("/{task_id}/exports/{export_format}")
def api_unified_export(task_id: str, export_format: str, request: UnifiedExportRequest) -> Response:
    if export_format not in {"html", "docx", "pdf", "markdown"}:
        raise HTTPException(404, {"code": "unsupported_export_format", "message": "支持 HTML、Word、PDF 或 Markdown。"})
    task, note, transcript, annotations, practice, options = _unified_export_inputs(task_id, request.model_copy(update={"format": export_format}))
    try:
        if export_format == "html":
            artifact = build_html_export(task, note, transcript, annotations=annotations, practice=practice, export_options=options)
        elif export_format == "docx":
            artifact = build_docx_export(task, note, transcript, annotations=annotations, practice=practice, export_options=options)
        elif export_format == "pdf":
            artifact = build_pdf_export(task, note, transcript, annotations=annotations, practice=practice, export_options=options)
        else:
            from ..document_exports import sanitize_export_text
            artifact = type("MarkdownArtifact", (), {
                "content": sanitize_export_text(build_structured_export(task, note, transcript, annotations=annotations, practice=practice, options=options)["markdown"]),
                "media_type": "text/markdown; charset=utf-8",
                "suffix": "md",
                "font_name": "UTF-8",
                "warnings": [],
                "schema_version": 1,
            })()
            artifact.content = str(artifact.content).encode("utf-8")
    except DocumentExportUnavailable as exc:
        raise HTTPException(503, {"code": str(exc), "message": "导出组件不可用，请检查安装包。"}) from exc
    filename = f"learnnote-{task.id}.{artifact.suffix}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}',
        "X-LearnNote-Export-Schema": str(artifact.schema_version),
        "X-LearnNote-Font": artifact.font_name,
    }
    if artifact.warnings:
        headers["X-LearnNote-Export-Warning"] = ",".join(artifact.warnings)
    return Response(artifact.content, media_type=artifact.media_type, headers=headers)


@study_router.get("/export-presets")
def api_export_presets() -> dict:
    path = _export_presets_path()
    if not path.is_file():
        return {"presets": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {"presets": value.get("presets", []) if isinstance(value, dict) else []}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"presets": []}


@study_router.post("/export-presets")
def api_save_export_preset(payload: dict | None = Body(default=None)) -> dict:
    body = payload or {}
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(422, {"code": "preset_name_required", "message": "请填写预设名称。"})
    options = normalize_export_options(body.get("options") if isinstance(body.get("options"), dict) else {})
    current = api_export_presets()["presets"]
    item = {"id": str(body.get("id") or uuid4().hex), "name": name, "options": options, "updated_at": datetime.now(timezone.utc).isoformat()}
    current = [item if str(existing.get("id")) == item["id"] else existing for existing in current if isinstance(existing, dict)]
    if not any(str(existing.get("id")) == item["id"] for existing in current):
        current.append(item)
    atomic_write_text(_export_presets_path(), json.dumps({"schema_version": 1, "presets": current[-30:]}, ensure_ascii=False, indent=2))
    return {"preset": item, "presets": current[-30:]}
