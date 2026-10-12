"""Explicit local steps; no unattended model scheduling or chat-history reuse."""
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field
from ..assistant_operation_types import SourceRef, StrictModel
from ..models import TaskOptions
from .. import assistant_runs as runs

router = APIRouter(prefix="/api/assistant/runs", tags=["assistant-runs"])


class CreateRun(StrictModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    question: str = Field(min_length=1, max_length=1000)
    source: SourceRef
    share_source: Literal[True]
    options: TaskOptions | None = None


class AdvanceRun(StrictModel):
    expected_version: int = Field(ge=1)
    options: TaskOptions | None = None


class ApproveRun(StrictModel):
    expected_version: int = Field(ge=1)
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    confirm: Literal[True]


class CancelRun(StrictModel):
    expected_version: int = Field(ge=1)


class DeleteRun(StrictModel):
    confirm: Literal[True]


@router.post("")
def create_run(request: CreateRun):
    return runs.create(request)


@router.get("")
def list_runs():
    return runs.list_runs()


@router.get("/{run_id}")
def get_run(run_id: str):
    return runs.get(run_id)


@router.post("/{run_id}/advance")
async def advance_run(run_id: str, request: AdvanceRun, http_request: Request):
    return await runs.advance(run_id, request, http_request.is_disconnected)


@router.post("/{run_id}/approve")
async def approve_run(run_id: str, request: ApproveRun, http_request: Request):
    return await runs.approve(run_id, request, http_request.is_disconnected)


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, request: CancelRun):
    return runs.cancel(run_id)


@router.delete("/{run_id}")
def delete_run(run_id: str, request: DeleteRun):
    return runs.forget(run_id)
