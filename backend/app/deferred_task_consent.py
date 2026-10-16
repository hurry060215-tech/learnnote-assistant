"""Atomic admission of a reviewed browser handoff."""
from fastapi import HTTPException

from .model_data_consent import page_data_fingerprint
from .storage import get_task, update_task


def task_or_404(task_id, lookup, detail="Task not found"):
    try:
        return lookup(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=detail) from exc


def start_reviewed_handoff(task_id, background_tasks, options, *, allow_model_page_context=False,
                          allow_page_text_fallback=False, review_fingerprint="", handoffs, lock,
                          merge_options, require_ready, expire_handoff, schedule, process, payload):
    # The capture endpoint uses this same lock when replacing a deferred source.
    # Compare and admit under one lock: there is no rebind between these steps.
    with lock:
        task = task_or_404(task_id, get_task, {"code": "task_not_found", "message": "Task not found"})
        if not task.awaiting_confirmation and task.status in {"queued", "running", "success"}:
            return {"accepted": True, "already_started": True, "task_id": task.id, "task": payload(task)}
        if task.status != "queued" or not task.awaiting_confirmation:
            raise HTTPException(409, {"code": "not_awaiting_confirmation", "message": "Task is not waiting for confirmation."})
        request = handoffs.get(task_id)
        if request is None:
            expire_handoff(task_id)
            raise HTTPException(410, {"code": "handoff_expired",
                "message": "The browser handoff expired after the backend restarted. Send the current page again."})
        if (review_fingerprint and review_fingerprint != page_data_fingerprint(request)) or (
                not review_fingerprint and (allow_model_page_context or allow_page_text_fallback)):
            raise HTTPException(409, {"code": "model_data_review_changed",
                "message": "采集资料已改变或缺少本次审阅记录；尚未开始发送。请刷新任务并重新审阅发送范围。"})
        merged = merge_options(request.options, options)
        if request.mode != "download_only":
            require_ready(merged)
        approved = request.model_copy(update={"options": merged,
            "allow_model_page_context": allow_model_page_context,
            "allow_page_text_fallback": allow_page_text_fallback}, deep=True)
        task = update_task(task_id, awaiting_confirmation=False,
            options=merged.model_copy(update={"llm_api_key": None}), message="已确认，等待开始处理")
        schedule(background_tasks, process, task.id, approved)
        handoffs.pop(task_id, None)
        return {"task_id": task.id, "task": payload(task)}
