"""Adapt processing calls to durable task admission and HTTP response lifetime.

The supplied queue owns workers; this adapter retains credential-bearing
arguments only in its callback and guards dispatch against task cancellation.
"""
from .queue_journal import read_queue_job
from .queue_policy import QueueFull


def dispatch_processing(queue, background_tasks, function, task_id: str, *args, **kwargs):
    from .models import CurrentPageTaskRequest, TaskOptions
    from .storage import get_task, update_task, mark_task_cancelled, task_state_transaction
    from .task_control_state import task_generation
    from fastapi import HTTPException
    from .processor_state import TaskCancelled

    source = args[0] if args else None
    explicit_kind = kwargs.pop("_queue_kind", "")
    kind = explicit_kind or ("page" if isinstance(source, CurrentPageTaskRequest) else "local")
    options = source.options if kind == "page" else next((value for value in args if isinstance(value, TaskOptions)), None)
    needs_context = bool(options and options.llm_api_key)
    if kind == "page":
        needs_context = needs_context or bool(source.cookies or source.resources or source.page_text)
    if not explicit_kind:
        if isinstance(source, CurrentPageTaskRequest) and source.mode == "download_only":
            kind = "page_download"
        elif (isinstance(source, CurrentPageTaskRequest) and source.mode == "subtitle_only") or (options and options.content_mode == "subtitles"):
            kind = "page_light" if isinstance(source, CurrentPageTaskRequest) else "local_light"

    generation = task_generation(get_task(task_id))

    def work():
        try:
            task = get_task(task_id)
            if task_generation(task) != generation:
                return
            if task.cancel_requested or task.status == "cancelled":
                mark_task_cancelled(task_id)
                return
            function(task_id, *args, **kwargs)
            if get_task(task_id).cancel_requested:
                mark_task_cancelled(task_id, expected_generation=generation)
        except FileNotFoundError:
            return  # Deleting an unstarted task also cancels its queued work.
        except TaskCancelled:
            mark_task_cancelled(task_id)
            return
        except Exception:
            latest = get_task(task_id)
            if latest.cancel_requested or latest.status == "cancelled":
                mark_task_cancelled(task_id)
                return
            update_task(task_id, status="failed", phase="failed", error_code="queued_task_failed", message="处理失败，已保留本地进度，请查看诊断后恢复。")
            raise

    try:
        with task_state_transaction():
            latest = get_task(task_id)
            if task_generation(latest) != generation:
                return
            if latest.cancel_requested:
                row = read_queue_job(queue.root, task_id)
                if row is None or (row.get("generation") != generation and row.get("state") in {"done", "failed", "cancelled", "waiting_context"}):
                    from .models import TaskCancellationReceipt, now_iso
                    receipt = latest.cancellation_receipt.model_copy(deep=True)
                    if receipt.generation != generation:
                        receipt = TaskCancellationReceipt(generation=generation, requested_at=latest.cancel_requested_at)
                    receipt.dispatch_prevented_at = now_iso()
                    update_task(task_id, status="cancelled", phase="cancelled", cancelled_at=now_iso(),
                                message="已在提交处理前取消，现有文件保留", cancellation_receipt=receipt)
                return
            future = queue.enqueue(task_id, kind, work, requires_context=needs_context, generation=generation)
    except QueueFull as exc:
        update_task(task_id, status="failed", phase="failed", error_code="task_queue_full", message=str(exc))
        raise HTTPException(status_code=429, detail={"code": "task_queue_full", "message": str(exc)}) from exc

    def wait_for_result():
        try:
            future.result()
        except Exception:
            pass  # Failure is persisted on the task and displayed by the UI.
    # The worker owns execution; this preserves response-lifecycle compatibility
    # for existing clients and tests without owning the processing lifetime.
    background_tasks.add_task(wait_for_result)
