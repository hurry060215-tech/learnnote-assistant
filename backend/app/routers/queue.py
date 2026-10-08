from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from ..config import DATA_DIR
from ..queue_controls import queue_is_paused, set_queue_paused, set_task_priority

router = APIRouter(prefix="/api/queue", tags=["local-queue"])


class PauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paused: StrictBool


class PriorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: StrictInt = Field(ge=0, le=5)


@router.get("")
def queue_controls():
    return {"paused": queue_is_paused(DATA_DIR), "running_tasks": "continue"}


@router.put("/pause")
def pause_queue(payload: PauseRequest):
    return set_queue_paused(DATA_DIR, payload.paused)


@router.put("/tasks/{task_id}/priority")
def prioritize(task_id: str, payload: PriorityRequest):
    try:
        return set_task_priority(DATA_DIR, task_id, payload.priority)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
