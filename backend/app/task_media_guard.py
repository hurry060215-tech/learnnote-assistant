"""Fail-closed media admission when saved task provenance belongs to another root.

This detects a known copy, not an implicit media migration. Current explicit
uploads/originals and existing source-task dependencies retain their semantics.
"""
import os
from pathlib import Path

from .task_paths import TaskArtifactUnavailable, _plain_path, _known_relative, _check_node, validate_task_id

_OWNED_FIELDS = ("note_path", "transcript_path", "subtitle_path", "visual_index_path",
                 "resource_inventory_path", "page_preflight_report_path", "resource_usage_path",
                 "audio_path", "media_integrity_path", "evidence_coverage_path", "summary_diagnostics_path")


def _native(windows: bool) -> bool:
    return windows == (os.name == "nt")


def _under(path, root: Path) -> bool:
    try:
        Path(str(path)).relative_to(root)
        return True
    except ValueError:
        return False


def require_current_media_provenance(task, task_root: Path) -> None:
    """Reject known copied/uncertain task roots without probing recorded paths."""
    validate_task_id(task.id)
    root = task_root.absolute()
    if root.name != task.id:
        raise TaskArtifactUnavailable("task_identity_mismatch")
    for field in _OWNED_FIELDS:
        value = getattr(task, field)
        if not value:
            continue
        parsed, windows = _plain_path(value)
        current = (_native(windows) and parsed.is_absolute() and _under(parsed, root))
        relative = not parsed.is_absolute() and _known_relative(parsed.parts, field)
        if not (current or relative):
            if field == "subtitle_path":
                historical_source_subtitle(task, root)
            else:
                raise TaskArtifactUnavailable("media_reselection_required")
    for value in (task.media_path, task.source_media_path):
        if not value:
            continue
        parsed, windows = _plain_path(value)
        if not _native(windows):
            raise TaskArtifactUnavailable("media_reselection_required")
        # Exact components avoid confusing sibling IDs or prefix-similar roots.
        parts = tuple(part.casefold() for part in parsed.parts) if windows else parsed.parts
        owner_id = task.id.casefold() if windows else task.id
        old_owner = any(parts[index:index + 2] == ("tasks", owner_id)
                        for index in range(len(parts) - 1))
        if old_owner and not (parsed.is_absolute() and _under(parsed, root)):
            raise TaskArtifactUnavailable("media_reselection_required")


def validate_current_media_file(task, value: str, task_root: Path) -> Path:
    """Validate an already-authorized native input; never substitute a new path."""
    require_current_media_provenance(task, task_root)
    parsed, windows = _plain_path(value)
    if not _native(windows):
        raise TaskArtifactUnavailable("media_reselection_required")
    candidate = Path(str(parsed)).absolute()
    trusted = task_root.parent.parent.absolute()
    try:
        relative = candidate.relative_to(trusted).parts
        current = trusted
    except ValueError:
        # External originals retain their existing authority, but no linked
        # component may redirect the read. This path is never a copied mapping.
        current = Path(candidate.anchor)
        relative = candidate.parts[1:]
    _check_node(current, file=False)
    for index, component in enumerate(relative):
        current = current / component
        _check_node(current, file=index == len(relative) - 1)
    if not relative:
        raise TaskArtifactUnavailable("invalid_destination_type")
    return candidate


def task_media_path_diagnostics(task, task_root: Path) -> dict:
    if not (task.media_path or task.source_media_path):
        return {}
    try:
        require_current_media_provenance(task, task_root)
    except TaskArtifactUnavailable as exc:
        return {"media_path": exc.detail()}
    return {}


def available_current_media(task, task_root: Path) -> Path | None:
    require_current_media_provenance(task, task_root)
    for value in (task.media_path, task.source_media_path):
        if not value:
            continue
        try:
            return validate_current_media_file(task, value, task_root)
        except TaskArtifactUnavailable as exc:
            if exc.reason not in {"missing_destination", "invalid_destination_type"}:
                raise
    return None


def upload_cleanup_candidate(task, task_root: Path, upload_root: Path) -> Path | None:
    """Deletion may inspect only an unambiguous current owned upload, never relocate."""
    from .task_paths import native_path_under
    try:
        require_current_media_provenance(task, task_root)
        path = native_path_under(upload_root, task.source_media_path)
        return validate_current_media_file(task, str(path), task_root)
    except TaskArtifactUnavailable:
        return None


def same_native_path(value: str, path: Path) -> bool:
    try:
        parsed, windows = _plain_path(value)
        return _native(windows) and parsed.is_absolute() and Path(str(parsed)) == path
    except TaskArtifactUnavailable:
        return False


def may_reference_native_path(value: str, path: Path, *, tasks_root: Path, upload_root: Path) -> bool:
    """Only a no-follow regular selected-root file proves an independent reference."""
    from .task_paths import native_path_under
    try:
        for root in (upload_root, tasks_root):
            try:
                candidate = native_path_under(root, value)
            except TaskArtifactUnavailable:
                continue
            if candidate == path:
                return True
            relative = candidate.relative_to(root.absolute()).parts
            if root == tasks_root:
                if len(relative) < 2:
                    return True
                validate_task_id(relative[0])
            current = root.absolute()
            _check_node(current, file=False)
            if not relative:
                return True
            for index, component in enumerate(relative):
                current = current / component
                node = _check_node(current, file=index == len(relative) - 1)
            # Lexical inequality is not file independence (hard links and native
            # Windows short/long names). Compare only validated selected-root
            # files; absent/unknown identities conservatively suppress cleanup.
            target = native_path_under(upload_root, str(path))
            current = upload_root.absolute()
            _check_node(current, file=False)
            target_parts = target.relative_to(current).parts
            if not target_parts:
                return True
            for index, component in enumerate(target_parts):
                current = current / component
                target_node = _check_node(current, file=index == len(target_parts) - 1)
            identities = [(getattr(item, "st_dev", None), getattr(item, "st_ino", None))
                          for item in (node, target_node)]
            if any(not isinstance(device, int) or device < 0 or not isinstance(inode, int) or inode <= 0
                   for device, inode in identities):
                return True
            return identities[0] == identities[1]
        return True  # Never probe an external, foreign, or ambiguous reference.
    except TaskArtifactUnavailable:
        return True


def historical_source_subtitle(task, task_root: Path) -> Path:
    from .task_subtitle_ancestry import resolve_historical_source_subtitle
    return resolve_historical_source_subtitle(task, task_root, validate_current_media_file)


def validated_caption_source(task, task_root: Path) -> tuple:
    from .task_subtitle_ancestry import validated_caption_source as validate
    return validate(task, task_root, validate_current_media_file)
