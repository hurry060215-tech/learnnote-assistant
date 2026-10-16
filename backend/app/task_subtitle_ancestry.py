"""Read-only compatibility for historically published caption rerun aliases.

This is not a cross-task path mapper. Only the exact source relationship written
by rerun admission and caption finalization may use a current source-owned file.
"""
import json
import re
from pathlib import Path

from .migrations import migrate_task_payload
from .models import TaskRecord
from .task_paths import TaskArtifactUnavailable, native_path_under, resolve_task_artifact, task_manifest_path, validate_task_id


def _record(root: Path, task_id: str) -> TaskRecord:
    path = task_manifest_path(root, task_id)
    task = TaskRecord.model_validate(migrate_task_payload(json.loads(path.read_text(encoding="utf-8"))))
    if task.id != task_id:
        raise TaskArtifactUnavailable("task_identity_mismatch")
    return task


def _routes_agree(root: Path, task_id: str, *, allow_summary=False) -> None:
    def check(value):
        if isinstance(value, dict):
            route = value.get("entry_route")
            allowed = {"local_media", "subtitle_only", "rerun_from_media"} | ({"saved_transcript"} if allow_summary else set())
            if route and route not in allowed:
                raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    for name in ("pipeline_metrics.json", "whole_attempt_duration_evidence.json"):
        try:
            path = resolve_task_artifact(root, task_id, str(root / name))
        except TaskArtifactUnavailable as exc:
            if exc.reason == "missing_destination":
                continue  # Old caption-only producers did not persist route metadata.
            raise
        check(json.loads(path.read_text(encoding="utf-8")))


def _validated_link(task, root: Path, validate_media, cache) -> tuple:
    root = root.absolute()
    if root.name != task.id or task.mode != "subtitle_only" or not task.source_task_id or task.source_task_id == task.id:
        raise TaskArtifactUnavailable("historical_subtitle_requires_review")
    validate_task_id(task.source_task_id)
    if _record(root, task.id) != task:
        raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
    source_root = root.parent / task.source_task_id
    source = _record(source_root, task.source_task_id)
    ancestor, seen = source, {task.id}
    while True:
        if ancestor.id in seen or len(seen) > 16:
            raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
        seen.add(ancestor.id)
        if not ancestor.source_task_id:
            break
        validate_task_id(ancestor.source_task_id)
        ancestor = _record(root.parent / ancestor.source_task_id, ancestor.source_task_id)
    if any(getattr(task, field) != getattr(source, field)
           for field in ("page_url", "selected_resource", "active_video", "learning_range")):
        raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
    digest = task.source_identity.media_sha256
    if (not re.fullmatch(r"[a-fA-F0-9]{64}", digest) or task.media_integrity.sha256 != digest
            or task.source_identity.platform != "local" or task.source_identity.platform_id != digest[:16]
            or task.source_identity.resource_fingerprint != digest):
        raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
    # The source input hash can predate normalization; equality with the child's
    # normalized-output hash is not evidence of ancestry.
    for field in ("note_path", "transcript_path"):
        native_path_under(root, getattr(task, field))
        resolve_task_artifact(root, task.id, getattr(task, field), field=field)
    _routes_agree(root, task.id, allow_summary=True)
    selected_data = root.parent.parent
    requested_media = native_path_under(selected_data, task.source_media_path)
    if task.media_path and native_path_under(selected_data, task.media_path) != requested_media:
        raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
    media_source = source
    if source.subtitle_path:
        try:
            native_path_under(source_root, source.subtitle_path)
            resolve_task_artifact(source_root, source.id, source.subtitle_path, field="subtitle_path")
        except TaskArtifactUnavailable as exc:
            if exc.reason != "native_mapping_requires_preview":
                raise
            # Prove the exact inherited pointer first. Only then omit this field
            # from a temporary media-only projection to avoid recursive guards.
            resolve_historical_source_subtitle(source, source_root, validate_media, _cache=cache)
            media_source = source.model_copy(update={"subtitle_path": ""})
    source_media = None
    for value in (source.media_path, source.source_media_path):
        if value:
            native_path_under(selected_data, value)
            try:
                source_media = validate_media(media_source, value, source_root)
                break
            except TaskArtifactUnavailable as exc:
                if exc.reason not in {"missing_destination", "invalid_destination_type"}:
                    raise
    if source_media is None or requested_media != source_media:
        raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
    return source, source_root


def validated_caption_source(task, root: Path, validate_media) -> tuple:
    """One strict rerun identity proof, independent of where its subtitle lives."""
    try:
        return _validated_link(task, root, validate_media, {})
    except TaskArtifactUnavailable:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise TaskArtifactUnavailable("historical_subtitle_requires_review") from exc


def resolve_historical_source_subtitle(task, root: Path, validate_media, *, _cache=None) -> Path:
    """Follow only the exact bounded source chain to one owned subtitle."""
    cache = {} if _cache is None else _cache
    cached = cache.get(task.id)
    if cached is not None and cached[0] == task:
        return cached[1]
    try:
        pointer = native_path_under(root.parent, task.subtitle_path)
        current, current_root, seen = task, root, set()
        for _ in range(16):
            if (current.id in seen or current.summary_source != "subtitle-extract"
                    or current.options.content_mode != "subtitles"):
                raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
            seen.add(current.id)
            _routes_agree(current_root, current.id)
            source, source_root = _validated_link(current, current_root, validate_media, cache)
            if native_path_under(root.parent, source.subtitle_path) != pointer:
                raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
            try:
                native_path_under(source_root, str(pointer))
            except TaskArtifactUnavailable as exc:
                if exc.reason != "native_mapping_requires_preview":
                    raise
                current, current_root = source, source_root
                continue
            result = resolve_task_artifact(source_root, source.id, source.subtitle_path, field="subtitle_path")
            cache[task.id] = (task, result)
            return result
        raise TaskArtifactUnavailable("historical_subtitle_identity_changed")
    except TaskArtifactUnavailable:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise TaskArtifactUnavailable("historical_subtitle_requires_review") from exc
