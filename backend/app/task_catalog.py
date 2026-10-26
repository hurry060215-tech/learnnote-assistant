"""The library needs identities and status, not full media/evidence projections.

This explicit read model has no filesystem, queue, model, or network operations.
Details and actions always re-read the selected task through their existing API.
"""
from .models import TaskRecord
from .source_input import clean_task_title
from .task_control_state import task_generation


def task_catalog_entry(task: TaskRecord) -> dict:
    return {
        "id": task.id,
        "source_task_id": task.source_task_id,
        "title": clean_task_title(task.title, task.page_url),
        "source_type": task.source_type,
        "mode": task.mode,
        "status": task.status,
        "summary_source": task.summary_source,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "awaiting_confirmation": task.awaiting_confirmation,
        "control_generation": task_generation(task),
        "catalog": True,
    }
