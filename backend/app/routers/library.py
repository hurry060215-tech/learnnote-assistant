from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..config import DATA_DIR, TEMP_DIR
from ..library import backup_library, duplicate_groups, library_status, rebuild_index, restore_library, search_library


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


@library_router.post("/rebuild")
def api_library_rebuild() -> dict:
    return rebuild_index()


@library_router.post("/backup")
def api_library_backup() -> dict:
    path = backup_library()
    return {
        "status": "pass",
        "path": str(path),
        "name": path.name,
        "download_url": f"/api/library/backup/{path.name}",
        "bytes": path.stat().st_size,
    }


@library_router.get("/backup/{name}")
def api_library_backup_file(name: str) -> FileResponse:
    candidate = (DATA_DIR / "exports" / name).resolve()
    export_root = (DATA_DIR / "exports").resolve()
    if Path(name).name != name or candidate.parent != export_root or candidate.suffix.lower() != ".sqlite3" or not candidate.is_file():
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
