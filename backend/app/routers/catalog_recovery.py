"""Separate, explicit material-catalog recovery API; task restore is unchanged."""
from __future__ import annotations

import asyncio
import sqlite3
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import library
from ..catalog_guard import catalog_guard
from ..catalog_health import catalog_status
from ..catalog_recovery import apply_recovery, preview_recovery

catalog_recovery_router = APIRouter(prefix="/catalog", tags=["library"])

MESSAGES = {
    "catalog_snapshot_invalid": "请选择有效的 LearnNote SQLite 备份。",
    "catalog_snapshot_schema_invalid": "备份版本或表结构不兼容，或包含不支持的数据库对象。",
    "catalog_snapshot_metadata_invalid": "备份中的资料或出处字段类型无效；请另选完整快照。",
    "catalog_snapshot_too_large": "所选备份超过恢复条目上限。",
    "catalog_recovery_too_large": "恢复范围超过 512 MB 或 20,000 个文件；请保留完整数据副本后分开处理。",
    "catalog_recovery_unresolved": "仍有无法验证的资料，或没有可恢复内容；未写入资料库。",
    "catalog_changed_preview_again": "资料库、原文件或备份已改变，请重新预览后再确认。",
    "catalog_busy": "另一进程正在使用资料库，请稍后重新预览。",
    "catalog_source_path_unsafe": "检测到资料路径链接或越界，未读取链接目标；请恢复普通本地文件。",
    "catalog_sidecars_unresolved": "损坏或缺失的资料库还保留未确定状态的事务日志；请连同原数据库保存，暂不自动替换。",
    "catalog_partial_corruption_unresolved": "数据库虽损坏但仍有可读记录；为避免丢失备份之外的记录，暂不自动替换。请保留完整数据副本。",
    "catalog_current_schema_invalid": "本机资料表结构无法安全合并，未修改资料库。",
}


def recovery_error(exc: Exception) -> HTTPException:
    code = str(exc) if str(exc) in MESSAGES else "catalog_recovery_failed"
    return HTTPException(status_code=409 if code in {"catalog_changed_preview_again", "catalog_busy"} else 422,
                         detail={"code": code, "message": MESSAGES.get(code, "恢复未完成；原数据库与原文件已保留。请检查可用空间和完整备份后重试。")})


@catalog_recovery_router.get("/status")
def status() -> dict:
    try:
        with library._lock, catalog_guard(library.DATA_DIR):
            return catalog_status(library.DATA_DIR)
    except (OSError, sqlite3.Error) as exc:
        raise recovery_error(exc) from exc


async def _selected_snapshot(file: UploadFile, token: str | None) -> dict:
    folder = library.DATA_DIR / "temp"
    if folder.is_symlink():
        raise recovery_error(ValueError("catalog_source_path_unsafe"))
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f"catalog-selected-{uuid4().hex}.sqlite3"
    try:
        written = 0
        with temporary.open("xb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > library.LIBRARY_BACKUP_MAX_BYTES:
                    raise HTTPException(status_code=413, detail={"code": "catalog_snapshot_too_large", "message": "SQLite 备份不能超过 128 MB。"})
                handle.write(chunk)
        if token is None:
            return await asyncio.to_thread(preview_recovery, temporary)
        return await asyncio.to_thread(apply_recovery, temporary, token)
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise recovery_error(exc) from exc
    finally:
        temporary.unlink(missing_ok=True)


@catalog_recovery_router.post("/recovery/preview")
async def preview(file: UploadFile = File(...)) -> dict:
    return await _selected_snapshot(file, None)


@catalog_recovery_router.post("/recovery/apply")
async def apply(file: UploadFile = File(...), preview_token: str = Form(..., min_length=64, max_length=64)) -> dict:
    return await _selected_snapshot(file, preview_token)
