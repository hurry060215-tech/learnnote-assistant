"""Narrow lock-free reading of a witnessed, unedited transcript draft."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import storage
from .migrations import migrate_task_payload
from .models import TaskRecord, TranscriptResult
from .personal_anchors import MAX_ARTIFACT_BYTES, _opened_artifact
from .task_artifacts import decode_task_note, task_artifact_path
from .task_paths import TaskArtifactUnavailable, artifact_name, task_manifest_path, validate_task_directory, validate_task_id


class DraftSnapshotUnavailable(ValueError):
    pass


def draft_source_revision(task: TaskRecord, transcript: TranscriptResult) -> str:
    source = [task.source_type, task.mode, task.source_task_id, task.page_url, task.source_identity.model_dump(mode="json"),
              task.learning_range, task.screen_subtitles_media_sha256, transcript.model_dump(mode="json")]
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read(task_id: str, path: Path) -> bytes:
    with _opened_artifact(task_id, str(path)) as stream:
        if stream is None:
            raise DraftSnapshotUnavailable("artifact_unavailable")
        value = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(value) > MAX_ARTIFACT_BYTES:
        raise DraftSnapshotUnavailable("artifact_unavailable")
    return value


def _task(task_id: str) -> TaskRecord:
    try:
        path = task_manifest_path(storage.TASK_DIR / task_id, task_id)
    except TaskArtifactUnavailable as exc:
        if exc.reason == "missing_destination":
            # The shared resolver also maps denied/unreadable nodes to this
            # reason. Only an actual absent node may clear the user's reader.
            for node in (storage.TASK_DIR, storage.TASK_DIR / task_id, storage.TASK_DIR / task_id / "task.json"):
                node.lstat()
        raise
    task = TaskRecord.model_validate(migrate_task_payload(json.loads(_read(task_id, path))))
    if task.id != task_id:
        raise DraftSnapshotUnavailable("task_identity_mismatch")
    return task


def _personal_absent(data_dir: Path, edition_path: Path) -> None:
    validate_task_directory(data_dir)
    for path in (edition_path, data_dir / "personal-state" / "restore-pending"):
        try:
            path.parent.lstat()
        except FileNotFoundError:
            continue
        validate_task_directory(path.parent)
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        raise DraftSnapshotUnavailable("personal_state_present")


def _publication(task_id: str, generation: str, *, provisional: bool = False) -> tuple[str, dict]:
    metrics = json.loads(_read(task_id, storage.TASK_DIR / task_id / "pipeline_metrics.json"))
    if not isinstance(metrics, dict):
        raise DraftSnapshotUnavailable("publication_unavailable")
    attempt_id = metrics.get("current_attempt_id")
    if (type(metrics.get("schema_version")) is not int or metrics["schema_version"] != 2
            or not isinstance(attempt_id, str) or not re.fullmatch(r"[a-f0-9]{12}", attempt_id)
            or not isinstance(metrics.get("attempts"), list)):
        raise DraftSnapshotUnavailable("publication_unavailable")
    if provisional and len(metrics["attempts"]) != 1:
        raise DraftSnapshotUnavailable("publication_unavailable")
    attempts = [item for item in metrics["attempts"] if isinstance(item, dict) and item.get("attempt_id") == attempt_id]
    draft = metrics.get("draft")
    if (len(attempts) != 1 or attempts[0].get("control_generation") != generation
            or not isinstance(draft, dict) or attempts[0].get("draft") != draft
            or draft.get("artifact") != "draft.md" or draft.get("summary_generated") is not False
            or type(draft.get("sequence")) is not int or draft["sequence"] < 1
            or any(not isinstance(draft.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", draft[key])
                   for key in ("body_revision", "source_revision"))):
        raise DraftSnapshotUnavailable("publication_unavailable")
    return attempt_id, draft


def _identity(task: TaskRecord) -> dict:
    return task.model_dump(include={"id", "created_at", "control_generation", "control_retry_count", "retry_count",
        "status", "title", "note_path", "transcript_path", "summary_source", "source_type", "mode",
        "source_task_id", "page_url", "source_identity", "learning_range", "screen_subtitles_media_sha256"}, mode="json")


def read_generated_draft(task_id: str, expected_generation: str, *, data_dir: Path, edition_path: Path) -> dict:
    """No task/personal locks, writes, projection, repair or fallback are allowed."""
    if not re.fullmatch(r"[a-f0-9]{64}", expected_generation):
        raise DraftSnapshotUnavailable("generation_unavailable")
    validate_task_id(task_id)
    _personal_absent(data_dir, edition_path)
    root = (storage.TASK_DIR / task_id).lstat()
    task = _task(task_id)
    provisional = not task.note_path
    if (task.control_generation != expected_generation or task.control_retry_count != task.retry_count
            or task.status not in {"running", "cancelling", "failed", "cancelled"}
            or (provisional and (task.retry_count != 0 or task.status != "running"
                                 or task.summary_source != ""))
            or (not provisional and (task.summary_source != "transcript-draft" or artifact_name(task.note_path) != "draft.md"))):
        raise DraftSnapshotUnavailable("task_ineligible")
    attempt, publication = _publication(task_id, expected_generation, provisional=provisional)
    note_task = task.model_copy(update={"note_path": str(storage.TASK_DIR / task_id / "draft.md")}) if provisional else task
    note = task_artifact_path(note_task, "note_path")
    transcript = task_artifact_path(task, "transcript_path")
    if note is None or transcript is None:
        raise DraftSnapshotUnavailable("artifact_unavailable")
    note_bytes = _read(task_id, note)
    text = decode_task_note(note_task, note_bytes)
    revision = hashlib.sha256(text.encode()).hexdigest()
    source = TranscriptResult.model_validate(json.loads(_read(task_id, transcript)))
    if revision != publication["body_revision"] or draft_source_revision(task, source) != publication["source_revision"]:
        raise DraftSnapshotUnavailable("publication_mismatch")
    # Replacements after opening must not silently select another source body.
    if (_read(task_id, note) != note_bytes
            or TranscriptResult.model_validate(json.loads(_read(task_id, transcript))) != source):
        raise DraftSnapshotUnavailable("snapshot_changed")
    current = _task(task_id)
    if (_identity(current) != _identity(task)
            or _publication(task_id, expected_generation, provisional=provisional) != (attempt, publication)):
        raise DraftSnapshotUnavailable("snapshot_changed")
    _personal_absent(data_dir, edition_path)
    current_root = (storage.TASK_DIR / task_id).lstat()
    if (root.st_dev, root.st_ino) != (current_root.st_dev, current_root.st_ino):
        raise DraftSnapshotUnavailable("snapshot_changed")
    return {"text": text, "revision": revision, "edited": False, "reader_snapshot": {
        "schema_version": 1, "task_id": task_id, "control_generation": expected_generation,
        "retry_count": task.retry_count, "attempt_id": attempt, "publication_sequence": publication["sequence"],
        "body_revision": revision, "source_revision": publication["source_revision"],
        "task_updated_at": current.updated_at, "title": current.title, "status": current.status,
        "artifact": "draft.md", "summary_source": "transcript-draft", "summary_generated": False,
        "verified": False, "provisional": provisional}}
