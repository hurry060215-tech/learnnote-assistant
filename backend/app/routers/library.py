from __future__ import annotations

from pathlib import Path
import re
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

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
    rebuild_index,
    register_task_material,
    restore_library,
    search_library,
)
from ..storage import get_task


library_router = APIRouter(prefix="/api/library", tags=["library"])


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
    return {"schema_version": 1, "materials": list_materials(limit, source_type)}


@library_router.post("/materials/import")
async def api_library_material_import(file: UploadFile = File(...)) -> dict:
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
        material = import_document_material(filename, bytes(content), file.content_type or "")
    except ValueError as exc:
        code = str(exc)
        messages = {
            "local_video_use_task_upload": "本地视频请使用现有本地视频任务入口，任务建立后再登记到资料库，避免复制媒体。",
            "material_type_unsupported": "仅支持 PDF、Markdown、HTML 和 TXT 学习资料。",
            "material_file_empty": "学习资料文件为空。",
            "material_file_too_large": "学习资料不能超过 32 MB。",
            "material_no_extractable_text": "资料中没有可提取文本；扫描 PDF 需要先完成本地 OCR。",
            "pdf_text_extraction_unavailable": "PDF 文本提取组件不可用，请安装后端完整依赖。",
            "pdf_page_limit_exceeded": "PDF 页数超过 500 页，请拆分后再导入。",
            "extracted_text_too_large": "资料解压后的文本超过 500 万字，请拆分后再导入。",
            "material_anchor_limit_exceeded": "资料章节过多，请拆分为较小文件后导入。",
            "text_encoding_unsupported": "无法可靠识别资料编码，请转换为 UTF-8 后重试。",
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


@library_router.post("/backup")
def api_library_backup() -> dict:
    path = backup_library()
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
