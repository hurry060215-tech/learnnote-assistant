from __future__ import annotations

from typing import Any

from . import TASK_SCHEMA_VERSION
from .models import TaskRecord


def migrate_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply additive task migrations without discarding unknown legacy artifacts."""
    migrated = dict(payload or {})
    version = int(migrated.get("schema_version") or 0)
    if version < 1:
        # v1 introduced durable checkpoint/recovery fields. Pydantic defaults
        # fill them when absent, while preserving every existing task field.
        migrated["schema_version"] = 1
    migrated["schema_version"] = max(int(migrated.get("schema_version") or 1), TASK_SCHEMA_VERSION)
    return migrated


def migrate_task_record(record: TaskRecord) -> TaskRecord:
    if record.schema_version >= TASK_SCHEMA_VERSION:
        return record
    return record.model_copy(update={"schema_version": TASK_SCHEMA_VERSION})
