"""Read-only, task-owned snapshots of saved note bodies before processing retries."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .storage import get_task, task_dir

_VERSION_ID = re.compile(r"[a-f0-9]{64}\Z")
_MAX_BYTES = 5 * 1024 * 1024


def _owned_note(task_id: str) -> Path | None:
    task = get_task(task_id)
    if not task.note_path:
        return None
    path = Path(task.note_path)
    if path.is_symlink() or path.resolve().parent != task_dir(task_id).resolve() or not path.is_file():
        return None
    return path


def snapshot_summary(task_id: str) -> str | None:
    """Preserve exact existing bytes; failures must stop a potentially destructive retry."""
    note = _owned_note(task_id)
    if note is None:
        return None
    content = note.read_bytes()
    if not content.strip():
        return None
    if len(content) > _MAX_BYTES:
        raise ValueError("已保存正文过大，无法安全建立历史版本；原文未改动。")
    content.decode("utf-8")
    root = task_dir(task_id).resolve()
    versions = root / "summary_versions"
    if versions.is_symlink() or versions.resolve().parent != root:
        raise ValueError("历史版本目录不可用；原文未改动。")
    versions.mkdir(exist_ok=True)
    version_id = hashlib.sha256(content).hexdigest()
    target = versions / f"{version_id}.md"
    if target.is_symlink():
        raise ValueError("历史版本文件不可用；原文未改动。")
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("历史版本校验失败；原文未改动。")
        return version_id
    # Exclusive creation avoids replacing an existing snapshot from another request.
    try:
        with target.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != content:
            raise ValueError("历史版本校验失败；原文未改动。")
    return version_id


def read_summary_version(task_id: str, version_id: str) -> dict:
    get_task(task_id)
    if not _VERSION_ID.fullmatch(version_id):
        raise FileNotFoundError(version_id)
    root = task_dir(task_id).resolve()
    versions = root / "summary_versions"
    path = versions / f"{version_id}.md"
    if versions.is_symlink() or versions.resolve().parent != root or path.is_symlink() or path.resolve().parent != versions:
        raise FileNotFoundError(version_id)
    if not path.is_file() or path.stat().st_size > _MAX_BYTES:
        raise FileNotFoundError(version_id)
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != version_id:
        raise FileNotFoundError(version_id)
    markdown = content.decode("utf-8")
    title = next((line.lstrip("# ").strip() for line in markdown.splitlines() if line.strip()), "已保存正文")[:160]
    return {"task_id": task_id, "id": version_id, "markdown": markdown, "title": title,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "size_bytes": len(content)}


def list_summary_versions(task_id: str) -> dict:
    get_task(task_id)
    note = _owned_note(task_id)
    current_id = hashlib.sha256(note.read_bytes()).hexdigest() if note and note.stat().st_size <= _MAX_BYTES else ""
    root = task_dir(task_id).resolve() / "summary_versions"
    versions = []
    if root.is_dir() and not root.is_symlink():
        for path in root.glob("*.md"):
            try:
                item = read_summary_version(task_id, path.stem)
            except (OSError, ValueError):
                continue
            item.pop("markdown")
            item["current"] = item["id"] == current_id
            versions.append(item)
    versions.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return {"task_id": task_id, "versions": versions, "current_note_available": note is not None}
