from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR, MODEL_CACHE_DIR, STATIC_DIR, TASK_DIR, TEMP_DIR, UPLOAD_DIR, ensure_dirs
from .models import TaskOptions, TaskRecord, now_iso
from .source_input import clean_task_title

_lock = threading.RLock()
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
) -> TaskRecord:
    ensure_dirs()
    record = TaskRecord(
        id=new_task_id(),
        source_type=source_type,  # type: ignore[arg-type]
        mode=mode or default_task_mode(source_type),
        title=clean_task_title(title, page_url),
        page_url=page_url,
        options=public_task_options(options),
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    save_task(record)
    return record


def save_task(record: TaskRecord) -> None:
    with _lock:
        record.updated_at = now_iso()
        atomic_write_text(task_file(record.id), record.model_dump_json(indent=2))


def get_task(task_id: str) -> TaskRecord:
    with _lock:
        path = task_file(task_id)
        if not path.exists():
            raise FileNotFoundError(task_id)
        return TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))


def update_task(task_id: str, **changes: Any) -> TaskRecord:
    with _lock:
        record = get_task(task_id)
        for key, value in changes.items():
            setattr(record, key, value)
        save_task(record)
        return record


def request_task_cancel(task_id: str) -> TaskRecord:
    with _lock:
        record = get_task(task_id)
        if record.status in {"success", "failed", "cancelled"}:
            return record
        record.cancel_requested = True
        record.cancel_requested_at = now_iso()
        record.status = "cancelling"
        record.phase = "cancelling"
        record.message = "正在停止任务"
        save_task(record)
        return record


def mark_task_cancelled(task_id: str) -> TaskRecord:
    return update_task(
        task_id,
        status="cancelled",
        phase="cancelled",
        message="任务已停止，已生成的文件仍然保留",
        cancelled_at=now_iso(),
    )


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
    with _lock:
        record = get_task(task_id)
        if record.status in {"queued", "running", "cancelling"}:
            raise RuntimeError("active_task")
        owned_upload = Path(record.source_media_path) if record.source_media_path else None
        task_path = (TASK_DIR / task_id).resolve()
        if TASK_DIR.resolve() not in task_path.parents:
            raise ValueError("invalid_task_path")
        task_bytes = _directory_size(task_path)
        if task_path.exists():
            shutil.rmtree(task_path)
        upload_bytes = 0
        if owned_upload:
            try:
                resolved_upload = owned_upload.resolve()
                shared = any(
                    other.id != task_id and other.source_media_path and Path(other.source_media_path).resolve() == resolved_upload
                    for other in list_tasks()
                )
                if UPLOAD_DIR.resolve() in resolved_upload.parents and resolved_upload.is_file() and not shared:
                    upload_bytes = resolved_upload.stat().st_size
                    resolved_upload.unlink()
            except (OSError, ValueError):
                upload_bytes = 0
        return {"task_id": task_id, "reclaimed_bytes": task_bytes + upload_bytes}


def delete_all_tasks() -> dict[str, Any]:
    with _lock:
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
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
        return path


def read_json(task_id: str, filename: str, default: Any = None) -> Any:
    with _lock:
        path = task_dir(task_id) / filename
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))


def list_tasks() -> list[TaskRecord]:
    ensure_dirs()
    records: list[TaskRecord] = []
    for path in TASK_DIR.glob("*/task.json"):
        try:
            record = TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
            records.append(record)
        except Exception:
            continue
    records = reconcile_stale_tasks(records)
    for record in records:
        repaired_title = clean_task_title(record.title, record.page_url)
        if repaired_title != record.title:
            record.title = repaired_title
            save_task(record)
    return sorted(records, key=lambda item: item.created_at, reverse=True)


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
    for record in records:
        updated = _parse_iso_datetime(record.updated_at) or _parse_iso_datetime(record.cancel_requested_at) or _parse_iso_datetime(record.created_at)
        if record.status == "cancelling":
            if updated and current - updated > cancelling_max_age:
                record.status = "cancelled"
                record.phase = "cancelled"
                record.message = "任务已停止，已生成的文件仍然保留"
                record.cancelled_at = now_iso()
                save_task(record)
            continue
        if record.status not in {"queued", "running"}:
            continue
        if not updated or current - updated <= max_age:
            continue
        has_media = any(
            raw_path and Path(raw_path).is_file()
            for raw_path in (record.media_path, record.source_media_path)
        )
        record.status = "failed"
        record.phase = "failed"
        record.error_code = "task_interrupted"
        record.error_detail = (
            "任务长时间没有进度，后端可能已退出。已下载的媒体仍保留，可从媒体继续切片总结。"
            if has_media
            else "任务长时间没有进度，后端可能已退出。请重新创建任务；旧任务记录已保留。"
        )
        record.message = record.error_detail
        save_task(record)
    return records
