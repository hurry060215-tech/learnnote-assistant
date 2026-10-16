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
from .catalog_recovery_errors import recovery_error
from .task_catalog_recovery import task_catalog_recovery_router

catalog_recovery_router = APIRouter(prefix="/catalog", tags=["library"])


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


catalog_recovery_router.include_router(task_catalog_recovery_router)
