from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ..config import DATA_DIR, TEMP_DIR
from ..library import (
    MATERIAL_IMPORT_MAX_BYTES,
    backup_library,
    delete_material,
    duplicate_groups,
    get_material,
    import_document_material,
    library_status,
    list_materials,
    material_anchors,
    material_capabilities,
    preview_document_material,
    material_content,
    material_source_path,
    redecode_document_material,
    rebuild_document_material,
    rebuild_index,
    register_task_material,
    restore_library,
    search_library,
)
from ..storage import get_task
from ..catalog_health import catalog_status
from .catalog_recovery import catalog_recovery_router
from ..document_exports import (
    DocumentExportUnavailable,
    build_docx_export,
    build_html_export,
    build_pdf_export,
    build_structured_export,
    normalize_export_options,
    sanitize_export_text,
)


library_router = APIRouter(prefix="/api/library", tags=["library"])
library_router.include_router(catalog_recovery_router)


class MaterialUnifiedExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str = Field(default="html", pattern=r"^(html|docx|pdf|markdown)$")
    options: dict = Field(default_factory=dict)
    annotations: str = Field(default="", max_length=100000)
    practice: list[dict] = Field(default_factory=list, max_length=200)
    space_id: str = Field(default="", max_length=64)


@library_router.get("/status")
def api_library_status() -> dict:
    return library_status()


@library_router.get("/search")
def api_library_search(q: str = "", limit: int = 50) -> dict:
    return {"query": q, "results": search_library(q, limit)}


@library_router.get("/duplicates")
def api_library_duplicates() -> dict:
    return {"groups": duplicate_groups()}


@library_router.get("/materials/capabilities")
def api_library_material_capabilities() -> dict:
    return material_capabilities()


@library_router.get("/materials")
def api_library_materials(limit: int = 100, source_type: str = "") -> dict:
    catalog = catalog_status(DATA_DIR)
    if catalog["state"] in {"missing", "corrupt"} and catalog["recovery_required"]:
        return {"schema_version": 1, "materials": [], "catalog": catalog}
    return {"schema_version": 1, "materials": list_materials(limit, source_type)}


@library_router.post("/materials/preview")
async def api_library_material_preview(file: UploadFile = File(...), encoding: str = Form(default="", max_length=40)) -> dict:
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > MATERIAL_IMPORT_MAX_BYTES:
            raise HTTPException(status_code=413, detail="学习资料不能超过 32 MB。")
    try:
        return preview_document_material(file.filename or "material", bytes(content), file.content_type or "", encoding.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "资料预检未通过，请检查文件格式、PDF 密码或文字编码；尚未保存原文。"}) from exc


@library_router.post("/materials/import")
async def api_library_material_import(file: UploadFile = File(...), encoding: str = Form(default="", max_length=40)) -> dict:
    filename = Path(file.filename or "material").name
    content = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > MATERIAL_IMPORT_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail={"code": "material_file_too_large", "message": "学习资料不能超过 32 MB。"},
            )
    try:
        material = import_document_material(filename, bytes(content), file.content_type or "", encoding=encoding.strip())
    except ValueError as exc:
        code = str(exc)
        messages = {
            "local_video_use_task_upload": "本地视频请使用现有本地视频任务入口，任务建立后再登记到资料库，避免复制媒体。",
            "material_type_unsupported": "仅支持 PDF、Markdown、HTML 和 TXT 学习资料。",
            "material_file_empty": "学习资料文件为空。",
            "material_file_too_large": "学习资料不能超过 32 MB。",
            "material_no_extractable_text": "资料中没有可提取文本；扫描 PDF 需要先完成本地 OCR。",
            "pdf_text_extraction_unavailable": "PDF 文本提取组件不可用，请安装后端完整依赖。",
            "pdf_password_required": "PDF 需要密码。请先在本机解锁并另存为不加密的副本，再导入。",
            "pdf_file_invalid": "PDF 文件损坏或无法读取，请重新导出或选择有效的 PDF 文件。",
            "pdf_page_limit_exceeded": "PDF 页数超过 500 页，请拆分后再导入。",
            "extracted_text_too_large": "资料解压后的文本超过 500 万字，请拆分后再导入。",
            "material_anchor_limit_exceeded": "资料章节过多，请拆分为较小文件后导入。",
            "text_encoding_unsupported": "无法可靠识别资料编码；请选择文字编码后重试。",
            "text_mojibake_detected": "检测到高置信度乱码；请选择原文编码后重试。",
            "material_storage_failed": "无法安全保存本地资料，请检查磁盘空间和数据目录权限。",
        }
        status = 409 if code == "local_video_use_task_upload" else 422
        recovery = None
        if code == "local_video_use_task_upload":
            recovery = {"action": "upload_local_video", "endpoint": "/api/tasks/local"}
        elif code == "pdf_text_extraction_unavailable":
            recovery = {"action": "install_backend_requirements", "command": "python -m pip install -r backend/requirements.txt"}
        raise HTTPException(
            status_code=status,
            detail={"code": code, "message": messages.get(code, "无法导入该学习资料。"), "recovery": recovery},
        ) from exc
    return {"ok": True, "material": material}


def _material_ocr_error(exc: Exception) -> HTTPException:
    messages = {
        "material_not_found": "学习资料不存在。",
        "material_ocr_requires_pdf": "扫描 PDF OCR 只支持 PDF 资料。",
        "material_ocr_not_required": "这份 PDF 已有原始文本，无需扫描识别。",
        "material_source_integrity_mismatch": "原始文件校验失败，现有 OCR 内容未改变。",
        "material_ocr_cache_invalid": "OCR 缓存校验失败，已保留现有文字与引用；请从本地备份恢复缓存。",
        "material_ocr_batch_failed": "本次页面识别失败，已保留之前的结果；可以再次继续。",
        "material_ocr_changed_reload_required": "资料已更新，请重新打开后继续。",
        "material_source_missing": "本机原始 PDF 缺失，已保留 OCR 结果；请恢复原文件后继续。",
        "material_ocr_cache_too_large": "OCR 缓存超过安全大小，已保留之前的结果。请拆分 PDF 后导入。",
        "material_ocr_invalid_result": "本次 OCR 结果无效，已保留之前的结果；可以重试。",
        "material_ocr_identity_invalid": "OCR 引用身份不一致，未覆盖现有引用。",
        "pdf_page_limit_exceeded": "PDF 超过支持的 500 页，请拆分后再导入。",
    }
    # Use exception text only as a lookup key. Responses contain public literals,
    # never exception strings that could include local paths or document content.
    public_codes = {known: known for known in messages}
    code = public_codes.get(str(exc), "material_ocr_failed") if isinstance(exc, ValueError) else "material_ocr_failed"
    return HTTPException(status_code=404 if code == "material_not_found" else 422,
                         detail={"code": code, "message": messages.get(code, "本地 OCR 未能完成，已保留之前的结果；请检查可选组件后重试。")})


@library_router.get("/materials/{material_id}/ocr")
def api_library_material_ocr_cache(material_id: str) -> dict:
    from ..material_ocr import get_material_ocr
    try:
        return {"ok": True, "ocr": get_material_ocr(material_id)}
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise _material_ocr_error(exc) from exc


@library_router.post("/materials/{material_id}/ocr")
def api_library_material_ocr(material_id: str) -> dict:
    from ..material_ocr import continue_material_ocr
    try:
        result = continue_material_ocr(material_id)
        if not result["ok"]:
            raise HTTPException(status_code=503, detail={"code": "pdf_ocr_unavailable", "message": result["ocr"].get("warning", "扫描 PDF OCR 组件不可用。")})
        return result
    except HTTPException:
        raise
    except (ValueError, OSError, ImportError, RuntimeError, sqlite3.Error) as exc:
        raise _material_ocr_error(exc) from exc


@library_router.post("/materials/register-task/{task_id}")
def api_library_register_task_material(task_id: str) -> dict:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在。"}) from exc
    if task.source_type != "local" and task.mode != "local":
        raise HTTPException(
            status_code=422,
            detail={"code": "task_not_local_video", "message": "该入口只登记本地视频任务。"},
        )
    return {"ok": True, "material": register_task_material(task)}


@library_router.get("/materials/{material_id}")
def api_library_material(material_id: str) -> dict:
    try:
        return {"material": get_material(material_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc), "message": "学习资料不存在。"}) from exc


@library_router.delete("/materials/{material_id}")
def api_library_delete_material(material_id: str, confirm: str = "") -> dict:
    if confirm != "delete_material":
        raise HTTPException(status_code=400, detail={"code": "confirmation_required", "message": "永久删除学习资料前需要明确确认。"})
    try:
        return delete_material(material_id)
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "material_not_found" else 422
        raise HTTPException(status_code=status, detail={"code": code, "message": "学习资料无法安全删除。"}) from exc


@library_router.post("/materials/{material_id}/redecode")
def api_library_material_redecode(material_id: str, payload: dict | None = Body(default=None)) -> dict:
    encoding = str((payload or {}).get("encoding") or "").strip()[:40]
    expected_updated_at = (payload or {}).get("expected_updated_at")
    try:
        return {"ok": True, "material": redecode_document_material(material_id, encoding, expected_updated_at=expected_updated_at)}
    except (ValueError, OSError, sqlite3.Error) as exc:
        messages = {
            "material_not_found": "学习资料不存在。",
            "material_redecode_changed_reload_required": "资料已被另一项操作修改，未覆盖当前版本。请关闭并重新打开编码窗口后再试。",
            "material_rebuild_changed_reload_required": "资料已被另一项操作修改，未覆盖当前版本。请关闭并重新打开编码窗口后再试。",
            "material_rebuild_requires_document": "视频资料请从原视频任务恢复。",
            "material_rebuild_identity_invalid": "资料引用身份不一致，未覆盖当前资料。",
            "material_source_missing": "本机原始文件缺失，无法重解码；现有资料未改变。",
            "material_file_too_large": "原始文件过大，未覆盖当前资料。",
            "material_redecode_encoding_required": "请先选择原文编码。",
            "material_redecode_pdf_unsupported": "PDF 请使用本地 OCR；字符集重解码仅适用于 TXT、Markdown 和 HTML。",
            "material_source_integrity_mismatch": "原始文件校验失败，未覆盖当前资料。",
            "material_redecode_empty": "所选编码没有提取出有效文本，当前资料未改变。",
            "material_no_extractable_text": "所选编码没有提取出有效文本，当前资料未改变。",
            "material_redecode_evidence_missing": "原始出处索引不完整，当前资料未改变。",
            "text_encoding_unsupported": "所选编码无法无损解码原始字节，当前资料未改变。",
            "text_mojibake_detected": "所选编码仍会产生高置信度乱码，当前资料未改变。",
            "material_anchor_limit_exceeded": "解码结果包含过多段落，当前资料未改变。",
            "extracted_text_too_large": "解码结果过大，当前资料未改变。",
        }
        # Return a literal public code from this mapping, never exception text
        # (which can include local paths or document content).
        public_codes = {known: known for known in messages}
        code = public_codes.get(str(exc), "material_redecode_failed") if isinstance(exc, ValueError) else "material_redecode_failed"
        conflict = code in {"material_redecode_changed_reload_required", "material_rebuild_changed_reload_required"}
        status = 404 if code == "material_not_found" else 409 if conflict else 422
        raise HTTPException(status_code=status, detail={"code": code, "message": messages.get(code, "资料重解码失败，当前内容未改变。")}) from exc


@library_router.post("/materials/{material_id}/rebuild")
def api_library_material_rebuild(material_id: str) -> dict:
    try:
        return {"ok": True, "material": rebuild_document_material(material_id)}
    except (ValueError, OSError, sqlite3.Error) as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("material_") else "material_rebuild_failed"
        messages = {
            "material_source_missing": "本机原始文件缺失，无法重建；现有资料未改变。",
            "material_source_integrity_mismatch": "原始文件校验失败，未覆盖当前资料。",
            "material_rebuild_ocr_cache_invalid": "本地 OCR 缓存缺失或校验失败，请重新运行本地 OCR。",
            "material_rebuild_revision_changed": "原文解析结果与保存的版本不同，未覆盖现有引用。",
            "material_rebuild_identity_invalid": "资料引用身份不一致，未覆盖现有索引。",
            "material_rebuild_changed_reload_required": "资料已被另一项操作修改，请刷新后再试。",
            "material_rebuild_requires_document": "视频资料请从原视频任务恢复。",
        }
        raise HTTPException(status_code=404 if code == "material_not_found" else 422,
                            detail={"code": code, "message": messages.get(code, "资料索引未能重建，现有记录未改变。")}) from exc


@library_router.get("/materials/{material_id}/anchors")
def api_library_material_anchors(material_id: str, limit: int = 500) -> dict:
    try:
        material = get_material(material_id)
        anchors = material_anchors(material_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc), "message": "学习资料不存在。"}) from exc
    return {"material_id": material["material_id"], "anchors": anchors}


@library_router.post("/rebuild")
def api_library_rebuild() -> dict:
    return rebuild_index()


@library_router.get("/materials/{material_id}/content")
def api_material_content(material_id: str) -> dict:
    try:
        return {"text": material_content(material_id), "truncated": False}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc), "message": "原文不可用，请重新导入原文件。"}) from exc


@library_router.get("/materials/{material_id}/source")
def api_material_source(material_id: str) -> FileResponse:
    try:
        path = material_source_path(material_id)
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Original source unavailable") from exc


def _material_unified_export_inputs(material_id: str, request: MaterialUnifiedExportRequest):
    material = get_material(material_id)
    note = material_content(material_id)
    from ..personal_notes import annotation_markdown

    annotations = request.annotations
    options = normalize_export_options(request.options)
    if not annotations and options["include_annotations"]:
        annotations = annotation_markdown("material", material_id)
    practice = list(request.practice or [])
    if request.space_id and not practice and options["include_practice"]:
        from ..learning_spaces import list_space_practice
        practice = list_space_practice(request.space_id)
    source = SimpleNamespace(
        id=material_id,
        title=str(material.get("title") or material_id),
        page_url="",
        frame_grids=[],
    )
    return source, note, {}, annotations, practice, options


def _material_unified_export_response(material_id: str, export_format: str, request: MaterialUnifiedExportRequest) -> Response:
    if export_format not in {"html", "docx", "pdf", "markdown"}:
        raise HTTPException(status_code=404, detail={"code": "unsupported_export_format", "message": "支持 HTML、Word、PDF 或 Markdown。"})
    try:
        source, note, transcript, annotations, practice, options = _material_unified_export_inputs(
            material_id, request.model_copy(update={"format": export_format})
        )
        if export_format == "html":
            artifact = build_html_export(source, note, transcript, annotations=annotations, practice=practice, export_options=options)
        elif export_format == "docx":
            artifact = build_docx_export(source, note, transcript, annotations=annotations, practice=practice, export_options=options)
        elif export_format == "pdf":
            artifact = build_pdf_export(source, note, transcript, annotations=annotations, practice=practice, export_options=options)
        else:
            content = sanitize_export_text(
                build_structured_export(source, note, transcript, annotations=annotations, practice=practice, options=options)["markdown"]
            ).encode("utf-8")
            artifact = SimpleNamespace(
                content=content,
                media_type="text/markdown; charset=utf-8",
                suffix="md",
                font_name="UTF-8",
                warnings=[],
                schema_version=1,
            )
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail={"code": "material_export_unavailable", "message": "学习资料或原文不可用。"}) from exc
    except DocumentExportUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": str(exc), "message": "导出组件不可用，请检查安装包。"}) from exc
    filename = f"learnnote-material-{material_id}.{artifact.suffix}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-LearnNote-Export-Schema": str(artifact.schema_version),
        "X-LearnNote-Font": artifact.font_name,
    }
    if artifact.warnings:
        headers["X-LearnNote-Export-Warning"] = ",".join(artifact.warnings)
    return Response(artifact.content, media_type=artifact.media_type, headers=headers)


@library_router.post("/materials/{material_id}/exports/preview")
def api_material_unified_export_preview(material_id: str, request: MaterialUnifiedExportRequest) -> dict:
    try:
        source, note, transcript, annotations, practice, options = _material_unified_export_inputs(material_id, request)
        artifact = build_html_export(source, note, transcript, annotations=annotations, practice=practice, export_options=options)
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail={"code": "material_export_unavailable", "message": "学习资料或原文不可用。"}) from exc
    return {
        "format": request.format,
        "schema_version": artifact.schema_version,
        "html": artifact.content.decode("utf-8"),
        "warnings": artifact.warnings,
        "font": artifact.font_name,
        "options": options,
    }


@library_router.post("/materials/{material_id}/exports/{export_format}")
def api_material_unified_export(material_id: str, export_format: str, request: MaterialUnifiedExportRequest) -> Response:
    return _material_unified_export_response(material_id, export_format, request)


@library_router.get("/materials/{material_id}/exports/{kind}")
def api_material_export(material_id: str, kind: str, include_annotations: bool = False) -> Response:
    if kind not in {"docx", "pdf", "markdown"}:
        raise HTTPException(status_code=404, detail="Export format unavailable")
    try:
        material = get_material(material_id)
        content = material_content(material_id)
        if include_annotations:
            from ..personal_notes import annotation_markdown
            content += annotation_markdown("material", material_id)
        if kind == "markdown":
            return Response(content, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="material-{material_id}.md"'})
        task = SimpleNamespace(title=material["title"], page_url="", id=material_id)
        artifact = build_docx_export(task, content) if kind == "docx" else build_pdf_export(task, content)
        return Response(artifact.content, media_type=artifact.media_type, headers={"Content-Disposition": f'attachment; filename="material-{material_id}.{kind}"'})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Material unavailable") from exc
    except DocumentExportUnavailable as exc:
        raise HTTPException(status_code=503, detail="Document export component unavailable") from exc


@library_router.post("/backup")
def api_library_backup() -> dict:
    try:
        path = backup_library()
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(status_code=409, detail={"code": "catalog_recovery_required", "message": "资料目录缺失或损坏；请先选择已有备份预览资料目录恢复。原文件仍然保留。"}) from exc
    return {
        "status": "pass",
        "name": path.name,
        "download_url": f"/api/library/backup/{path.name}",
        "bytes": path.stat().st_size,
        "scope": "task_index_only",
    }


@library_router.get("/backup/{name}")
def api_library_backup_file(name: str) -> FileResponse:
    candidate = (DATA_DIR / "exports" / name).resolve()
    export_root = (DATA_DIR / "exports").resolve()
    valid_name = bool(re.fullmatch(r"learnnote-library-\d{8}-\d{6}-[0-9a-f]{8}\.sqlite3", name))
    if Path(name).name != name or candidate.parent != export_root or not valid_name or not candidate.is_file():
        raise HTTPException(status_code=404, detail={"code": "library_backup_not_found", "message": "备份文件不存在。"})
    return FileResponse(candidate, media_type="application/vnd.sqlite3", filename=candidate.name)


@library_router.post("/restore")
async def api_library_restore(file: UploadFile = File(...)) -> dict:
    temporary = TEMP_DIR / f"library-upload-{uuid4().hex}.sqlite3"
    try:
        written = 0
        with temporary.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > 128 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail={"code": "library_backup_too_large", "message": "资料库备份超过 128 MB。"})
                handle.write(chunk)
        try:
            return restore_library(temporary)
        except sqlite3.Error as exc:
            raise HTTPException(status_code=409, detail={"code": "catalog_recovery_required", "message": "当前数据库不可安全写入。任务索引恢复不恢复文档；请先单独预览资料目录恢复。"}) from exc
        except ValueError as exc:
            code = str(exc)
            messages = {
                "library_backup_missing": "备份文件不存在。",
                "library_backup_too_large": "资料库备份超过 128 MB。",
                "library_backup_invalid": "资料库备份不是有效的 SQLite 文件。",
                "library_backup_schema_mismatch": "资料库备份版本不兼容或缺少必要表。",
            }
            raise HTTPException(status_code=400, detail={"code": code, "message": messages.get(code, "资料库备份无法恢复。")}) from exc
    finally:
        temporary.unlink(missing_ok=True)


@library_router.post("/materials/{material_id}/ask")
def api_material_ask(material_id: str, payload: dict):
    question = str(payload.get("question") or "").strip()[:1000]
    if not question:
        raise HTTPException(422, "请输入问题。")
    try:
        items = material_anchors(material_id, 1000)
    except ValueError as exc:
        raise HTTPException(404, "资料不存在。") from exc
    terms = set(re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", question.lower()))
    # Chinese phrase bigrams allow local retrieval without a remote model.
    for phrase in list(terms):
        if re.fullmatch(r"[\u4e00-\u9fff]+", phrase):
            terms.update(phrase[i:i+2] for i in range(len(phrase)-1))
    ranked = sorted(((sum(term in str(item.get("text", "")).lower() for term in terms), item) for item in items),key=lambda pair:pair[0],reverse=True)
    matches = [item for score,item in ranked[:6] if score]
    answer = "当前资料中的相关原文（未生成推断）：\n\n" + "\n\n".join(f"{item.get('locator','')}\n{str(item.get('text',''))[:1200]}" for item in matches) if matches else "在当前资料中没有找到相关原文，请换一个更具体的关键词。"
    return {"answer":answer,"mode":"local_source_extract","material_id":material_id,"evidence_ids":[item["evidence_id"] for item in matches]}
