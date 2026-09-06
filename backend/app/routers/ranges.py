from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from ..models import TaskOptions
from ..range_learning import create_range_task

range_router = APIRouter(prefix="/api/tasks", tags=["learning-range"])


class RangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    options: TaskOptions = Field(default_factory=TaskOptions)


@range_router.post("/{task_id}/learn-range")
def api_learn_range(task_id: str, request: RangeRequest, background_tasks: BackgroundTasks):
    try:
        task = create_range_task(task_id, request.start, request.end, request.options, background_tasks)
        return {"task_id": task.id, "task": task.model_dump(mode="json")}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="原任务不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "请选择原视频时长内的有效起止位置，并确保本地媒体可用。"}) from exc
