from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from .config import TASK_DIR, ensure_dirs
from .models import TaskOptions, TaskRecord, now_iso

_lock = threading.RLock()


def new_task_id() -> str:
    return uuid.uuid4().hex[:12]


def task_dir(task_id: str) -> Path:
    path = TASK_DIR / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_file(task_id: str) -> Path:
    return task_dir(task_id) / "task.json"


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
        title=title or "Untitled",
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
            records.append(TaskRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(records, key=lambda item: item.created_at, reverse=True)
