"""Retain explicit pipeline subtitle inputs before publishing a task pointer."""
from pathlib import Path
import shutil

from . import storage
from .task_media_guard import validate_current_media_file
from .task_paths import resolve_task_artifact, task_manifest_path


def retain_subtitle_file(task_id: str, source: Path) -> Path:
    """Preserve source bytes; never publish an alias or silently ignore copy failure."""
    task = storage.get_task(task_id)
    root = storage.TASK_DIR / task_id
    task_manifest_path(root, task_id)
    source = validate_current_media_file(task, str(source), root)
    if source.parent in (root, root / "downloads"):
        return source
    target = root / source.name
    try:
        output = target.open("xb")
    except FileExistsError:
        existing = resolve_task_artifact(root, task_id, str(target), field="subtitle_path")
        if existing.read_bytes() != source.read_bytes():
            raise ValueError("已有字幕与本次来源不同；原字幕未改动。")
        return existing
    try:
        with output, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, output)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def retain_legacy_subtitle_for_retry(task) -> dict:
    """An explicit retry may retain a proven alias before changing task semantics."""
    from .task_artifacts import task_artifact_path
    from .task_paths import TaskArtifactUnavailable
    path = task_artifact_path(task, "subtitle_path")
    root = storage.TASK_DIR / task.id
    if path is None or path.is_relative_to(root):
        return {}
    try:
        return {"subtitle_path": str(retain_subtitle_file(task.id, path))}
    except (OSError, ValueError) as exc:
        raise TaskArtifactUnavailable("subtitle_retention_failed") from exc
