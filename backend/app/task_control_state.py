"""Pure task generation and cancellation-evidence projection helpers."""
from __future__ import annotations

import hashlib
import json

from .models import TaskRecord


class TaskControlConflict(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def task_generation(task: TaskRecord) -> str:
    """Freeze identity at admission; progress and enriched evidence keep the token."""
    if task.control_generation and task.control_retry_count == task.retry_count:
        return task.control_generation
    identity = [task.id, task.created_at, task.retry_count, task.mode,
                task.source_identity.model_dump(mode="json")]
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def task_control_snapshot(task: TaskRecord, row: dict | None) -> dict:
    generation = task_generation(task)
    receipt = task.cancellation_receipt
    same = receipt.generation == generation
    matching = bool(row and row.get("generation") == generation)
    state = row.get("state", "none") if row else "none"
    cas_evidence = bool(same and matching and state == "cancelled" and receipt.operation_id
                        and row.get("cancel_operation_id") == receipt.operation_id)
    dispatch_prevented = bool(same and receipt.dispatch_prevented_at)
    finished = False if dispatch_prevented else None
    if matching:
        if state in {"done", "failed"} and row.get("callback_finished") == 1:
            finished = True
        elif state in {"queued", "running"} or cas_evidence:
            finished = False
    return {
        "task_id": task.id, "generation": generation, "status": task.status,
        "cancel_requested": task.cancel_requested,
        "cancellation_requested": bool(task.cancel_requested or (same and receipt.requested_at)),
        "queued_job_cancelled": bool(same and (receipt.queued_cancelled_at or cas_evidence)),
        "dispatch_prevented": dispatch_prevented,
        "recovery_stopped": bool(same and receipt.recovery_stopped_at),
        "worker_acknowledged": bool(same and receipt.acknowledged_at),
        "callback_finished": finished,
        "cancellation_operation_id": receipt.operation_id,
        "applied_generation": receipt.generation,
        "operation_applied": bool(receipt.operation_id and receipt.requested_at),
        "queue_state": state if matching or state in {"none", "unknown"} else "unknown",
    }
