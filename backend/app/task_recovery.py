"""Restore orphaned processing intents only under the caller's worker leases.

Task JSON owns outcomes; SQLite owns dispatch intent; OS ownership protects
live callbacks including paused jobs with credentials held only in memory.
"""
from pathlib import Path

from .queue_journal import read_queue_job
from .queue_policy import LANES, task_lane
from .queue_ownership import owner_is_alive


def recover_intents(queue, *, lanes=LANES, reconcile_unjournaled=True, process_range_task, waiting_lanes=None):
    root = queue.root
    from .storage import get_task, update_task, mark_task_cancelled, task_state_transaction, mark_task_recovery_stopped, list_tasks_snapshot, TASK_DIR
    from .task_control_state import task_generation
    from .processor import process_local_video_task, process_current_page_task
    from .models import CurrentPageTaskRequest
    from .task_media_guard import validate_current_media_file
    from .task_artifacts import task_artifact_path
    from .task_paths import TaskArtifactUnavailable

    recovered = waiting = 0
    for snapshot in queue.entries():
        if task_lane(snapshot["kind"]) not in lanes:
            continue
        with task_state_transaction():
            row = queue._job_row(snapshot["task_id"])
            if row is None or row.get("generation", "") != snapshot.get("generation", ""):
                if row and waiting_lanes is not None and row["state"] in {"queued", "running", "recovering"}:
                    waiting_lanes.add(task_lane(row["kind"]))
                continue  # A retry admitted after the recovery snapshot owns its new intent.
            if row["task_id"] in queue.jobs:
                continue
            if owner_is_alive(root, row.get("owner_id", "")):
                # Paused callbacks hold no worker slot; continue observing their
                # owner so process death also recovers an otherwise idle queue.
                if waiting_lanes is not None and row["state"] in {"queued", "running", "recovering"}:
                    waiting_lanes.add(task_lane(row["kind"]))
                continue
            if row["state"] == "cancelled" and row.get("cancel_operation_id") and row.get("generation"):
                from .storage import cancel_task_generation
                from .task_control_state import TaskControlConflict
                try:
                    cancel_task_generation(row["task_id"], expected_generation=row["generation"],
                                           operation_id=row["cancel_operation_id"])
                except (FileNotFoundError, TaskControlConflict):
                    pass
                continue
            if row["state"] not in {"queued", "running", "recovering"}:
                continue
            try:
                task = get_task(row["task_id"])
            except FileNotFoundError:
                queue.set_state(row["task_id"], "cancelled", generation=row.get("generation", ""))
                continue
            if row.get("generation") and row["generation"] != task_generation(task):
                queue.set_state(task.id, "cancelled", generation=row["generation"])
                continue
            if task.cancel_requested:
                # Owning every worker lease proves no callback is executing, but
                # recovery is not evidence that the original worker acknowledged.
                mark_task_recovery_stopped(task.id)
                queue.set_state(task.id, "cancelled", generation=row.get("generation", ""))
                continue
            if task.status in {"success", "failed", "cancelled"}:
                queue.set_state(task.id, "done", generation=row.get("generation", ""))
                continue
            if row["requires_context"]:
                queue.set_state(task.id, "waiting_context", generation=row.get("generation", ""))
                update_task(task.id, status="failed", phase="failed", error_code="resume_context_required", message="进度已保存；请重新确认模型或从原网页发送，以恢复需要登录信息的任务。")
                waiting += 1
                continue
            if row["kind"] == "summary":
                from .processor import process_saved_transcript_task
                callback = lambda task=task: process_saved_transcript_task(task.id, task.options)
            elif row["kind"] in {"local", "range", "local_light", "screen_ocr"} or (row["kind"] == "light" and task.source_type == "local"):
                try:
                    path = validate_current_media_file(task, task.source_media_path or task.media_path or "", TASK_DIR / task.id)
                    subtitle = task_artifact_path(task, "subtitle_path")
                except TaskArtifactUnavailable:
                    path, subtitle = None, None
                if path is None or not path.is_relative_to(Path(root).absolute()):
                    queue.set_state(task.id, "waiting_context", generation=row.get("generation", ""))
                    update_task(task.id, status="failed", phase="failed", error_code="resume_source_required", message="原媒体不在当前数据目录，请重新选择原文件恢复。")
                    waiting += 1
                    continue
                if row["kind"] == "screen_ocr":
                    from .screen_subtitle_tasks import process_screen_subtitle_task
                    callback = lambda task=task, path=path: process_screen_subtitle_task(task.id, path, task.options)
                elif row["kind"] == "range":
                    callback = lambda task=task, path=path: process_range_task(task.id, path, task.title, task.options)
                else:
                    callback = lambda task=task, path=path, subtitle=subtitle: process_local_video_task(
                        task.id, path, task.title, task.options, page_url=task.page_url,
                        browser_subtitles=task.browser_subtitles,
                        subtitle_path=subtitle,
                        subtitle_source="browser-subtitle" if task.browser_subtitles else "page-subtitle")
            else:
                request = CurrentPageTaskRequest(page_url=task.page_url, title=task.title, options=task.options,
                    mode=task.mode, browser_subtitles=task.browser_subtitles, active_video=task.active_video,
                    learning_range=task.learning_range, drm_detected=task.drm_detected, drm_signals=task.drm_signals)
                callback = lambda task=task, request=request: process_current_page_task(task.id, request)
            # Reset the orphaned lease before re-enqueueing the original task ID.
            queue.set_state(task.id, "recovering", generation=row.get("generation", ""))
            generation = task_generation(task)
            def recover_work(callback=callback, task_id=task.id, generation=generation):
                latest = get_task(task_id)
                if task_generation(latest) != generation:
                    return
                if latest.cancel_requested:
                    mark_task_cancelled(task_id, expected_generation=generation)
                    return
                callback()
                if get_task(task_id).cancel_requested:
                    mark_task_cancelled(task_id, expected_generation=generation)
            queue.enqueue(task.id, row["kind"], recover_work, generation=generation, recovery=True)
            recovered += 1
    if reconcile_unjournaled and TASK_DIR.parent.resolve() == Path(root).resolve():
        for snapshot in list_tasks_snapshot():
            if snapshot.status != "cancelling" or not snapshot.cancel_requested or snapshot.awaiting_confirmation:
                continue
            with task_state_transaction():
                task = get_task(snapshot.id)
                if task.status == "cancelling" and task.cancel_requested and read_queue_job(root, task.id) is None:
                    # The worker leases prove stopped now; an absent journal row
                    # cannot establish whether an earlier callback ever returned.
                    mark_task_recovery_stopped(task.id)
    return {"recovered": recovered, "waiting_for_context": waiting}
