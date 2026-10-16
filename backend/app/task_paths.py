"""Read-only, fail-closed resolution inside an explicitly selected task root.

Legacy paths remain provenance. Only known task artifacts can be projected onto
an exact copied task directory; this is not a general path repair/migration API.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat

_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_ROOT_FILES = {
    "note.md", "draft.md", "draft.partial.md", "draft.review.md", "captions.md", "screen_subtitles.md",
    "transcript.json", "visual_index.json", "claim_evidence_map.json",
}
_NOTE_FILES = {"note.md", "draft.md", "draft.partial.md", "draft.review.md", "captions.md", "screen_subtitles.md"}
_SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass", ".ssa"}
_REPORT_FILES = {"resource_inventory_path": "resource_inventory.json", "page_preflight_report_path": "page_preflight_report.json", "resource_usage_path": "resource_usage.json"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class TaskArtifactUnavailable(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("任务文件路径暂不可用。请检查当前选择的数据目录。未应用未确认的迁移映射，原文件未修改；请保留原件，并在支持的入口重新选择或导入。")

    def detail(self) -> dict:
        return {"code": "task_artifact_unavailable", "reason": self.reason,
                "message": str(self), "recoverable": True, "requires_preview": True}


def validate_task_id(task_id: str) -> None:
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise TaskArtifactUnavailable("invalid_task_identity")


def artifact_name(value: str) -> str:
    """Inspect metadata names without interpreting foreign paths on this host."""
    return (PureWindowsPath(value) if "\\" in value or re.match(r"^[A-Za-z]:", value) else PurePosixPath(value)).name


def _plain_path(value: str):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise TaskArtifactUnavailable("invalid_path")
    windows = bool("\\" in value or re.match(r"^[A-Za-z]:", value))
    # Mixed separators, drive-relative, UNC/device paths, ADS and URLs are not a
    # portable ownership claim. Do not normalize traversal away before checking.
    if windows:
        if "/" in value or not re.match(r"^[A-Za-z]:\\", value):
            raise TaskArtifactUnavailable("ambiguous_path")
        if ":" in value[2:]:
            raise TaskArtifactUnavailable("invalid_path")
        parsed = PureWindowsPath(value)
    else:
        if ":" in value or value.startswith("//"):
            raise TaskArtifactUnavailable("invalid_path")
        parsed = PurePosixPath(value)
    if any(part in {".", ".."} for part in re.split(r"[\\/]", value)):
        raise TaskArtifactUnavailable("path_traversal")
    # Windows strips trailing dots/spaces and reserves device names. Refuse the
    # ambiguous spellings even when the current host could create those files.
    for part in parsed.parts[1:] if parsed.is_absolute() else parsed.parts:
        if part.endswith((".", " ")) or PureWindowsPath(part).is_reserved():
            raise TaskArtifactUnavailable("ambiguous_path")
    return parsed, windows


def _check_node(path: Path, *, file: bool) -> os.stat_result:
    try:
        node = path.lstat()
    except OSError as exc:
        raise TaskArtifactUnavailable("missing_destination") from exc
    if stat.S_ISLNK(node.st_mode) or getattr(node, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise TaskArtifactUnavailable("linked_destination")
    if not (stat.S_ISREG(node.st_mode) if file else stat.S_ISDIR(node.st_mode)):
        raise TaskArtifactUnavailable("invalid_destination_type")
    return node


def validate_task_directory(path: Path) -> None:
    _check_node(path, file=False)


def task_manifest_path(root: Path, task_id: str) -> Path:
    """Validate the selected manifest before any read, including native records."""
    validate_task_id(task_id)
    root = root.absolute()
    if root.name != task_id:
        raise TaskArtifactUnavailable("task_identity_mismatch")
    _check_node(root.parent, file=False)
    _check_node(root, file=False)
    path = root / "task.json"
    _check_node(path, file=True)
    return path


def _known_relative(relative: tuple[str, ...], field: str) -> bool:
    if len(relative) == 1:
        name = relative[0]
        if field == "note_path":
            return name in _NOTE_FILES
        if field == "transcript_path":
            return name == "transcript.json"
        if field == "visual_index_path":
            return name == "visual_index.json"
        if field in _REPORT_FILES:
            return name == _REPORT_FILES[field]
        if field == "subtitle_path":
            return PurePosixPath(name).suffix.lower() in _SUBTITLE_SUFFIXES
        return name in _ROOT_FILES or PurePosixPath(name).suffix.lower() in _SUBTITLE_SUFFIXES
    if field == "subtitle_path" and len(relative) == 2 and relative[0] == "downloads":
        return PurePosixPath(relative[1]).suffix.lower() in _SUBTITLE_SUFFIXES
    return len(relative) == 2 and relative[0] == "grids" and PurePosixPath(relative[1]).suffix.lower() in _IMAGE_SUFFIXES


def resolve_task_artifact(root: Path, task_id: str, value: str, *, field: str = "", directory: str = "") -> Path | None:
    """Return one existing owned file or an actionable failure; never rewrite.

    The caller chooses the active task root. A relocated legacy path additionally
    requires the destination manifest to identify that exact task. Native paths
    already owned by this root retain their existing permitted filenames.
    """
    validate_task_id(task_id)
    if not value:
        return None
    if field and field not in {"note_path", "transcript_path", "visual_index_path", "subtitle_path", *_REPORT_FILES}:
        raise TaskArtifactUnavailable("unsupported_artifact")
    if directory not in {"", "grids", "frames"}:
        raise TaskArtifactUnavailable("unsupported_artifact")
    root = root.absolute()
    if root.name != task_id:
        raise TaskArtifactUnavailable("task_identity_mismatch")
    parsed, windows = _plain_path(value)
    native = (windows and os.name == "nt") or (not windows and os.name != "nt")
    relative = None
    relocated = False
    if native and parsed.is_absolute():
        try:
            relative = Path(value).relative_to(root).parts
        except ValueError:
            pass
    if relative is None:
        relocated = True
        if parsed.is_absolute():
            owners = [index for index in range(len(parsed.parts) - 1)
                      if parsed.parts[index:index + 2] == ("tasks", task_id)]
            if len(owners) != 1:
                raise TaskArtifactUnavailable("ownership_requires_preview")
            relative = parsed.parts[owners[0] + 2:]
        else:
            relative = parsed.parts
        if not _known_relative(relative, field):
            raise TaskArtifactUnavailable("unsupported_artifact")
        # An outside native path may still exist or refer to another copy.
        # Never stat/read it to decide. Such mappings require explicit preview.
        if native and parsed.is_absolute():
            raise TaskArtifactUnavailable("native_mapping_requires_preview")
    if field == "subtitle_path" and len(relative) == 2 and relative[0] == "downloads":
        directory = "downloads"
    if len(relative) != (2 if directory else 1) or (directory and relative[0] != directory):
        raise TaskArtifactUnavailable("outside_owned_directory")
    _check_node(root.parent, file=False)
    _check_node(root, file=False)
    candidate = root
    for index, part in enumerate(relative):
        candidate = candidate / part
        _check_node(candidate, file=index == len(relative) - 1)
    if relocated:
        manifest = task_manifest_path(root, task_id)
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TaskArtifactUnavailable("invalid_task_manifest") from exc
        if not isinstance(payload, dict) or payload.get("id") != task_id:
            raise TaskArtifactUnavailable("task_identity_mismatch")
    return candidate


def native_path_under(root: Path, value: str) -> Path:
    """Lexical containment only; no resolve/stat of an untrusted old path."""
    parsed, windows = _plain_path(value)
    if windows != (os.name == "nt") or not parsed.is_absolute():
        raise TaskArtifactUnavailable("ownership_requires_preview")
    candidate = Path(str(parsed))
    if not candidate.is_relative_to(root.absolute()):
        raise TaskArtifactUnavailable("native_mapping_requires_preview")
    return candidate


def native_task_artifact(root: Path, task_id: str, value: str, *, directory="") -> Path:
    native_path_under(root, value)
    return resolve_task_artifact(root, task_id, value, directory=directory)


def lexical_task_dependency(tasks_root: Path, value: str) -> str | None:
    parsed, windows = _plain_path(value)
    if windows != (os.name == "nt"):
        raise TaskArtifactUnavailable("ownership_requires_preview")
    if not parsed.is_absolute():
        if len(parsed.parts) == 1:
            return None  # Canonical task-relative artifact, never a sibling owner.
        raise TaskArtifactUnavailable("ownership_requires_preview")
    try:
        relative = Path(str(parsed)).relative_to(tasks_root.absolute())
    except ValueError:
        return None  # An external original is not a selected task dependency.
    if not relative.parts:
        return None
    validate_task_id(relative.parts[0])
    current = tasks_root.absolute()
    _check_node(current, file=False)
    for index, component in enumerate(relative.parts):
        current = current / component
        try:
            _check_node(current, file=index == len(relative.parts) - 1)
        except TaskArtifactUnavailable as exc:
            if exc.reason == "missing_destination":
                break  # Retain even a missing dependency; never follow a link.
            raise
    return relative.parts[0]


def resolve_task_grid(root: Path, task_id: str, value: str) -> Path | None:
    directory = "grids"
    try:
        if native_path_under(root, value).parent == root.absolute():
            directory = ""  # Preserve existing native task-root grid filenames.
    except TaskArtifactUnavailable:
        pass
    return resolve_task_artifact(root, task_id, value, directory=directory)


def validate_cleanup_task_entries(tasks_root: Path) -> None:
    """Optional cleanup needs complete no-follow visibility, unlike normal listing."""
    validate_task_directory(tasks_root)
    for entry in tasks_root.iterdir():
        task_manifest_path(entry, entry.name)
