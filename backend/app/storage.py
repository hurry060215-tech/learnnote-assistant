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


def create_task(source_type: str, title: str, page_url: str = "", options: TaskOptions | None = None) -> TaskRecord:
    ensure_dirs()
    record = TaskRecord(
        id=new_task_id(),
        source_type=source_type,  # type: ignore[arg-type]
        title=title or "Untitled",
        page_url=page_url,
        options=options or TaskOptions(),
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    save_task(record)
    return record


def save_task(record: TaskRecord) -> None:
    with _lock:
        record.updated_at = now_iso()
        task_file(record.id).write_text(record.model_dump_json(indent=2), encoding="utf-8")


def get_task(task_id: str) -> TaskRecord:
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
    path = task_dir(task_id) / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(task_id: str, filename: str, default: Any = None) -> Any:
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
