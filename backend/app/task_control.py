"""Generation-aware task controls for native adapters and HTTP retry routes."""
from __future__ import annotations

from .models import TaskRecord
from .storage import cancel_task_generation
from .task_control_state import task_generation, TaskControlConflict, task_control_snapshot as _snapshot


def read_task_control(task_id: str) -> dict:
    """No queue creation, manifest repair, indexing or locking-file writes."""
    from . import storage
    from .task_queue import read_queue_job
    task = storage.get_task(task_id)
    return _snapshot(task, read_queue_job(storage.TASK_DIR.parent, task_id))


def admit_retry(source: TaskRecord, **changes) -> TaskRecord:
    """HTTP admission adapter shared by the three same-ID retry/resume routes."""
    from fastapi import HTTPException
    from .storage import admit_task_retry
    try:
        return admit_task_retry(source.id, expected_generation=task_generation(source), **changes)
    except TaskControlConflict as exc:
        raise HTTPException(409, {"code": exc.code, "message": "任务状态已变化或仍有工作未结束，请刷新后重试。"}) from exc
