"""Native assistant operation API, independent from text-only chat."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, ValidationError
from ..assistant_operation_types import OperationRequest, StrictModel, tool_catalog
from ..assistant_operation_planner import PlanRequest, plan
from .. import assistant_operations as operations

router = APIRouter(prefix="/api/assistant/operations", tags=["assistant-operations"])


class ExecuteRequest(StrictModel):
    confirm: Literal[True]


class UndoRequest(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")


@router.get("/catalog")
def catalog():
    return {"phase": "single_bounded_operation", "tools": tool_catalog(), "shell": False,
            "notice": "正文编辑保存本机撤销副本；阅读外观由当前浏览器执行。"}


@router.post("/plan")
def plan_operation(request: PlanRequest):
    return plan(request)


@router.post("/prepare")
def prepare_operation(request: OperationRequest):
    try:
        return operations.prepare(request)
    except (ValidationError, ValueError):
        raise HTTPException(422, "操作参数不受支持，未执行修改。") from None


@router.get("")
def recent_operations():
    return {"operations": operations.list_operations()}


@router.get("/{operation_id}")
def get_operation(operation_id: str):
    return operations.get_operation(operation_id)


@router.post("/{operation_id}/execute")
def execute_operation(operation_id: str, request: ExecuteRequest):
    return operations.execute(operation_id)


@router.post("/{operation_id}/cancel")
def cancel_operation(operation_id: str):
    return operations.cancel(operation_id)


@router.post("/{operation_id}/undo")
def undo_operation(operation_id: str, request: UndoRequest):
    return operations.undo(request.operation_id, operation_id)


@router.get("/{operation_id}/artifact")
def download_artifact(operation_id: str):
    path, info = operations.artifact_path(operation_id)
    types = {".md": "text/markdown; charset=utf-8", ".pdf": "application/pdf",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".html": "text/html; charset=utf-8"}
    return FileResponse(path, filename=path.name, media_type=types[path.suffix], headers={"X-Content-Type-Options": "nosniff"})


@router.delete("/{operation_id}")
def forget_operation(operation_id: str, request: ExecuteRequest):
    return operations.forget(operation_id)
