"""Explicit task-only catalog recovery endpoints; no snapshot upload path."""
import sqlite3

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..task_catalog_recovery import apply_task_recovery, preview_task_recovery
from .catalog_recovery_errors import MESSAGES, recovery_error

task_catalog_recovery_router = APIRouter(prefix="/tasks")


class TaskRecoveryApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_scope: str = Field(pattern=r"^task_catalog_only$")


@task_catalog_recovery_router.post("/preview")
def preview_tasks() -> dict:
    try:
        result = preview_task_recovery()
        if result["code"]:
            result["diagnostic"] = MESSAGES.get(result["code"], "无法验证任务来源，恢复未启用。")
        return result
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise recovery_error(exc) from exc


@task_catalog_recovery_router.post("/apply")
def apply_tasks(payload: TaskRecoveryApply) -> dict:
    try:
        return apply_task_recovery(payload.preview_token)
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise recovery_error(exc) from exc
