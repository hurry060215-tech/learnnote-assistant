from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR, MODEL_CACHE_DIR, STATIC_DIR, TASK_DIR, TEMP_DIR, UPLOAD_DIR, ensure_dirs
from .library import index_task, remove_task
from .models import SourceIdentity, SubtitleProbe, TaskOptions, TaskRecord, now_iso
from .migrations import migrate_task_record, migrate_task_payload
from .observability import record_task_event
from .source_input import clean_task_title
from .summary_outcome import safe_summary_diagnostics, safe_summary_warning, summary_failure_message
from .activation import record_status
from . import assistant_operation_store as assistant_records
from .worker_lease import worker_lease

_lock = threading.RLock()
_state_depth = threading.local()


@contextmanager
def task_state_transaction():
    """Lock order: task RLock, state lease, then queue SQLite; never wait for workers.

    The separate lease directory cannot consume or deadlock a processing slot.
    Read-only snapshots deliberately do not acquire/create this file lock.
    """
    with _lock:
        depth = getattr(_state_depth, "value", 0)
        if depth:
            yield
            return
        root = TASK_DIR.parent / ".task-state"
        root.mkdir(parents=True, exist_ok=True)
        with worker_lease(root):
            _state_depth.value = 1
            try:
                yield
            finally:
                _state_depth.value = 0


STALE_TASK_AFTER = timedelta(hours=6)
STALE_CANCELLING_AFTER = timedelta(minutes=5)


def new_task_id() -> str:
    return uuid.uuid4().hex[:12]


def task_dir(task_id: str) -> Path:
    path = TASK_DIR / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_file(task_id: str) -> Path:
    return TASK_DIR / task_id / "task.json"


def public_task_options(options: TaskOptions | None) -> TaskOptions:
    public = (options or TaskOptions()).model_copy(deep=True)
    public.llm_api_key = None
    return public


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def default_task_mode(source_type: str) -> str:
    if source_type == "page_text":
        return "page_text"
    if source_type == "local":
        return "local"
    return "video"


def create_task(
    source_type: str,
    title: str,
    page_url: str = "",
    options: TaskOptions | None = None,
    mode: str | None = None,
    *,
    handoff_id: str = "",
    source_identity: SourceIdentity | None = None,
    learning_range: dict[str, float] | None = None,
    subtitle_probe: SubtitleProbe | None = None,
    extension_version: str = "",
) -> TaskRecord:
    ensure_dirs()
    record = TaskRecord(
        id=new_task_id(),
        handoff_id=handoff_id,
        source_type=source_type,  # type: ignore[arg-type]
        mode=mode or default_task_mode(source_type),
        title=clean_task_title(title, page_url),
        page_url=page_url,
        source_identity=source_identity or SourceIdentity(),
        learning_range=learning_range or {},
        subtitle_probe=subtitle_probe,
        extension_version=extension_version,
        options=public_task_options(options),
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    save_task(record)
    record_task_event(record.id, "task_created", phase=record.phase, status=record.status, message="Task created")
    return record


def save_task(record: TaskRecord) -> None:
    with task_state_transaction():
        from .task_control_state import task_generation
        record.control_generation = task_generation(record)
        record.control_retry_count = record.retry_count
        record = migrate_task_record(record)
        record.updated_at = now_iso()
        atomic_write_text(task_file(record.id), record.model_dump_json(indent=2))
        index_task(record)


def get_task(task_id: str) -> TaskRecord:
    with _lock:
        path = task_file(task_id)
        if not path.exists():
            raise FileNotFoundError(task_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TaskRecord.model_validate(migrate_task_payload(payload))


def update_task(task_id: str, **changes: Any) -> TaskRecord:
    with task_state_transaction():
        record = get_task(task_id)
        from .task_control_state import task_generation
        record.control_generation = task_generation(record)
        record.control_retry_count = record.retry_count
        if record.cancel_requested and changes.get("retry_count", record.retry_count) == record.retry_count:
            # Late progress/failure/success writes cannot undo a cancellation.
            changes.pop("cancel_requested", None)
            if changes.get("status") in {"queued", "running", "success", "failed"}:
                changes["status"] = record.status
                changes["phase"] = record.phase
        previous_phase = record.phase
        previous_status = record.status
        previous_checkpoint = record.checkpoint
        if "summary_diagnostics" in changes:
            changes["summary_diagnostics"] = safe_summary_diagnostics(changes["summary_diagnostics"])
        if "summary_warning" in changes:
            changes["summary_warning"] = safe_summary_warning(changes["summary_warning"])
        if changes.get("error_code", record.error_code) == "summary_unavailable":
            for key in ("message", "error_detail"):
                if key in changes:
                    changes[key] = summary_failure_message(changes[key])
        for key, value in changes.items():
            setattr(record, key, value)
        save_task(record)
        if record.status != previous_status:
            record_status(TASK_DIR.parent, record.status, record.error_code)
        if (
            record.phase != previous_phase
            or record.status != previous_status
            or record.checkpoint != previous_checkpoint
            or record.error_code
            or "message" in changes
        ):
            safe_changes = {
                key: value
                for key, value in changes.items()
                if key in {"progress", "checkpoint", "checkpoint_updated_at", "failed_phase", "retry_count"}
            }
            record_task_event(
                task_id,
                "task_updated",
                phase=record.phase,
                status=record.status,
                error_code=record.error_code,
                message=record.message,
                details=safe_changes,
            )
        return record


def cancel_task_generation(task_id: str, *, expected_generation: str, operation_id: str) -> dict:
    """Atomically request cancellation of the reviewed generation (there is no undo).

    The one bounded receipt survives retry. Replaying it proves its historical
    applied_generation but never mutates the replacement generation.
    """
    from .task_control_state import task_generation, TaskControlConflict, task_control_snapshot
    from .models import TaskCancellationReceipt
    from .task_queue import cancel_queued_processing, read_queue_job
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", operation_id):
        raise ValueError("invalid_operation_id")
    with task_state_transaction():
        task = get_task(task_id)
        receipt = task.cancellation_receipt
        if receipt.operation_id == operation_id and receipt.generation == expected_generation and receipt.requested_at:
            row = read_queue_job(TASK_DIR.parent, task_id)
            if task_generation(task) == expected_generation and task.status == "cancelling":
                cancel_queued_processing(TASK_DIR.parent, task_id,
                                         expected_generation=expected_generation, operation_id=operation_id)
                row = read_queue_job(TASK_DIR.parent, task_id)
            # Finish an interrupted second manifest commit using the durable CAS.
            # A historical replay must never finalize a replacement generation.
            if task_generation(task) == expected_generation and task.status == "cancelling" and task_control_snapshot(task, row)["queued_job_cancelled"]:
                receipt = receipt.model_copy(update={"queued_cancelled_at": receipt.queued_cancelled_at or now_iso()})
                task = update_task(task_id, status="cancelled", phase="cancelled",
                                           message="已取消排队，现有文件保留", cancelled_at=now_iso(),
                                           cancellation_receipt=receipt)
            return task_control_snapshot(task, row)
        if task_generation(task) != expected_generation:
            raise TaskControlConflict("stale_generation")
        if task.awaiting_confirmation:
            # The HTTP route also removes ephemeral handoff entries. Native
            # callers must use that exact cleanup before supporting this mode.
            raise TaskControlConflict("deferred_task")
        if task.cancel_requested:
            raise TaskControlConflict("cancellation_pending")
        if task.status in {"success", "failed", "cancelled"}:
            raise TaskControlConflict("task_not_active")
        receipt = TaskCancellationReceipt(generation=expected_generation, operation_id=operation_id,
                                          requested_at=now_iso())
        # Persist the operation before the CAS. If interrupted after either
        # commit, the receipt and row distinguish request from proven dispatch prevention.
        task = update_task(task_id, cancel_requested=True, cancel_requested_at=receipt.requested_at,
                                   status="cancelling", phase="cancelling", message="正在停止任务",
                                   cancellation_receipt=receipt)
        if cancel_queued_processing(TASK_DIR.parent, task_id,
                                    expected_generation=expected_generation, operation_id=operation_id):
            receipt.queued_cancelled_at = now_iso()
            task = update_task(task_id, status="cancelled", phase="cancelled",
                                       message="已取消排队，现有文件保留", cancelled_at=now_iso(),
                                       cancellation_receipt=receipt)
        return task_control_snapshot(task, read_queue_job(TASK_DIR.parent, task_id))


def request_task_cancel(task_id: str) -> TaskRecord:
    from .task_control_state import task_generation
    with task_state_transaction():
        record = get_task(task_id)
        if record.cancel_requested or record.status in {"success", "failed", "cancelled"}:
            return record
        cancel_task_generation(task_id, expected_generation=task_generation(record), operation_id=uuid.uuid4().hex)
        return get_task(task_id)


def mark_task_cancelled(task_id: str, *, expected_generation: str | None = None) -> TaskRecord:
    from .task_control_state import task_generation, TaskControlConflict
    with task_state_transaction():
        record = get_task(task_id)
        generation = task_generation(record)
        if expected_generation is not None and generation != expected_generation:
            raise TaskControlConflict("stale_generation")
        receipt = record.cancellation_receipt.model_copy(deep=True)
        if receipt.generation != generation:
            from .models import TaskCancellationReceipt
            receipt = TaskCancellationReceipt(generation=generation, requested_at=record.cancel_requested_at)
        receipt.acknowledged_at = now_iso()
        return update_task(
            task_id, status="cancelled", phase="cancelled",
            message="任务已停止，已生成的文件仍然保留", cancelled_at=now_iso(),
            cancellation_receipt=receipt,
        )


def mark_task_recovery_stopped(task_id: str) -> TaskRecord:
    """Only startup recovery holding every worker lease may use this marker."""
    from .task_control_state import task_generation
    from .models import TaskCancellationReceipt
    with task_state_transaction():
        record = get_task(task_id)
        generation = task_generation(record)
        receipt = record.cancellation_receipt.model_copy(deep=True)
        if receipt.generation != generation:
            receipt = TaskCancellationReceipt(generation=generation, requested_at=record.cancel_requested_at)
        receipt.recovery_stopped_at = now_iso()
        return update_task(task_id, status="cancelled", phase="cancelled", cancelled_at=now_iso(),
                           message="重启后已停止取消中的任务，现有文件保留", cancellation_receipt=receipt)


def admit_task_retry(task_id: str, *, expected_generation: str, clone: bool = False, **changes: Any) -> TaskRecord:
    """Final compare-and-set admission for same-ID resumes and clone bookkeeping."""
    from .task_control_state import task_generation, TaskControlConflict
    from .task_queue import read_queue_job
    with task_state_transaction():
        record = get_task(task_id)
        if task_generation(record) != expected_generation:
            raise TaskControlConflict("stale_generation")
        if record.status in {"queued", "running", "cancelling"}:
            raise TaskControlConflict("task_still_running")
        row = read_queue_job(TASK_DIR.parent, task_id)
        if row and row.get("state") in {"queued", "running", "recovering", "unknown"}:
            raise TaskControlConflict("task_still_running")
        if clone:
            # /retry creates another task, but its source counter must never be
            # computed from a detached snapshot or regress a newer generation.
            return update_task(task_id, retry_count=record.retry_count + 1)
        changes.update(status="queued", phase="queued", progress=0, retry_count=record.retry_count + 1,
                       cancel_requested=False, cancel_requested_at="", cancelled_at="")
        return update_task(task_id, **changes)


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def storage_summary() -> dict[str, Any]:
    ensure_dirs()
    categories = {
        "tasks": _directory_size(TASK_DIR),
        "uploads": _directory_size(UPLOAD_DIR),
        "temporary": _directory_size(TEMP_DIR),
        "model_cache": _directory_size(MODEL_CACHE_DIR),
        "static": _directory_size(STATIC_DIR),
    }
    return {
        "root": str(DATA_DIR),
        "total_bytes": sum(categories.values()),
        "categories": categories,
        "task_count": len(list_tasks()),
    }


def delete_task(task_id: str) -> dict[str, Any]:
    with assistant_records.source_deletion("task", task_id, DATA_DIR), task_state_transaction():
        record = get_task(task_id)
        if record.status in {"queued", "running", "cancelling"}:
            raise RuntimeError("active_task")
        owned_upload = Path(record.source_media_path) if record.source_media_path else None
        task_path = (TASK_DIR / task_id).resolve()
        if TASK_DIR.resolve() not in task_path.parents:
            raise ValueError("invalid_task_path")
        task_bytes = _directory_size(task_path)
        if not remove_task(record.id):
            raise RuntimeError("task_index_cleanup_failed")
        edition_key = hashlib.sha256(f"task:{task_id}".encode()).hexdigest()
        (DATA_DIR / "user-editions" / f"{edition_key}.json").unlink(missing_ok=True)
        if task_path.exists():
            shutil.rmtree(task_path)
        upload_bytes = 0
        if owned_upload:
            try:
                resolved_upload = owned_upload.resolve()
                shared = any(
                    other.id != task_id and other.source_media_path and Path(other.source_media_path).resolve() == resolved_upload
                    for other in list_tasks_snapshot()
                )
                if UPLOAD_DIR.resolve() in resolved_upload.parents and resolved_upload.is_file() and not shared:
                    upload_bytes = resolved_upload.stat().st_size
                    resolved_upload.unlink()
            except (OSError, ValueError):
                upload_bytes = 0
        return {"task_id": task_id, "reclaimed_bytes": task_bytes + upload_bytes}


def delete_all_tasks() -> dict[str, Any]:
    with assistant_records.locked(DATA_DIR), task_state_transaction():
        records = list_tasks()
        active = [task for task in records if task.status in {"queued", "running", "cancelling"}]
        if active:
            raise RuntimeError("active_tasks")
        deleted = []
        reclaimed = 0
        for record in records:
            result = delete_task(record.id)
            deleted.append(record.id)
            reclaimed += int(result.get("reclaimed_bytes") or 0)
        return {
            "deleted_task_ids": deleted,
            "deleted_count": len(deleted),
            "reclaimed_bytes": reclaimed,
        }


def cleanup_tasks(retention_days: int = 30, keep_recent: int = 10, dry_run: bool = True) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    terminal = [task for task in list_tasks() if task.status in {"success", "failed", "cancelled"}]
    keep_ids = {task.id for task in terminal[:keep_recent]}
    candidates = []
    reclaimable = 0
    for task in terminal:
        created = _parse_iso_datetime(task.created_at)
        if task.id in keep_ids or not created or created >= cutoff:
            continue
        size = _directory_size(TASK_DIR / task.id)
        candidates.append({"task_id": task.id, "title": task.title, "created_at": task.created_at, "bytes": size})
        reclaimable += size
    reclaimed = 0
    deleted = []
    if not dry_run:
        for candidate in candidates:
            result = delete_task(candidate["task_id"])
            reclaimed += int(result["reclaimed_bytes"])
            deleted.append(candidate["task_id"])
    return {
        "dry_run": dry_run,
        "retention_days": retention_days,
        "keep_recent": keep_recent,
        "candidates": candidates,
        "deleted_task_ids": deleted,
        "reclaimable_bytes": reclaimable,
        "reclaimed_bytes": reclaimed,
    }


def write_json(task_id: str, filename: str, data: Any) -> Path:
    with _lock:
        path = task_dir(task_id) / filename
        if filename == "summary_diagnostics.json":
            data = safe_summary_diagnostics(data)
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
        return path


def read_json(task_id: str, filename: str, default: Any = None) -> Any:
    with _lock:
        path = task_dir(task_id) / filename
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))


def list_tasks_snapshot(*, strict: bool = False) -> list[TaskRecord]:
    """Nonmutating manifest snapshots: no mkdir, index, reconciliation or repair."""
    records: list[TaskRecord] = []
    for path in TASK_DIR.glob("*/task.json"):
        try:
            record = TaskRecord.model_validate(migrate_task_payload(json.loads(path.read_text(encoding="utf-8"))))
            if strict and record.id != path.parent.name:
                raise ValueError("course_episode_identity_conflict")
            records.append(record)
        except (OSError, ValueError, TypeError):
            if strict:
                raise
            continue
    return sorted(records, key=lambda item: item.created_at, reverse=True)


def list_tasks() -> list[TaskRecord]:
    ensure_dirs()
    records = reconcile_stale_tasks(list_tasks_snapshot())
    repaired = []
    for snapshot in records:
        with task_state_transaction():
            try:
                record = get_task(snapshot.id)
            except FileNotFoundError:
                continue
            title = clean_task_title(record.title, record.page_url)
            if title != record.title:
                record = update_task(record.id, title=title)
            repaired.append(record)
    return sorted(repaired, key=lambda item: item.created_at, reverse=True)


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def reconcile_stale_tasks(
    records: list[TaskRecord],
    *,
    now: datetime | None = None,
    max_age: timedelta = STALE_TASK_AFTER,
    cancelling_max_age: timedelta = STALE_CANCELLING_AFTER,
) -> list[TaskRecord]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    result = []
    for snapshot in records:
        with task_state_transaction():
            try:
                record = get_task(snapshot.id)
            except FileNotFoundError:
                continue
            updated = _parse_iso_datetime(record.updated_at) or _parse_iso_datetime(record.created_at)
            # Elapsed time cannot prove that a worker observed cancellation.
            if record.status in {"queued", "running"} and not record.cancel_requested and updated and current - updated > max_age:
                has_media = any(raw and Path(raw).is_file() for raw in (record.media_path, record.source_media_path))
                detail = ("任务长时间没有进度，后端可能已退出。已下载的媒体仍保留，可从媒体继续切片总结。"
                          if has_media else "任务长时间没有进度，后端可能已退出。请重新创建任务；旧任务记录已保留。")
                record = update_task(record.id, status="failed", phase="failed", error_code="task_interrupted",
                                     error_detail=detail, message=detail)
            result.append(record)
    return result
