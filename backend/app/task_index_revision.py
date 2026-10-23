"""Task search revisions, independent of progress and execution ownership.

The receipt describes owned artifact identities, not semantic verification. Files
are published atomically by the task pipeline; every call revalidates ownership
and stats, including replacement at the same pathname. No process cache is used.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .task_paths import TaskArtifactUnavailable, artifact_name, resolve_task_artifact


def task_index_revision(record, root: Path, source: str) -> tuple[str, dict[str, Path | None]]:
    artifacts = {}
    identities = {}
    for field in ("note_path", "transcript_path"):
        value = getattr(record, field)
        if field == "note_path" and artifact_name(value) == "draft.partial.md":
            artifacts[field] = None
            identities[field] = "unpublished"
            continue
        try:
            path = resolve_task_artifact(root, record.id, value, field=field)
            node = path.stat() if path else None
            artifacts[field] = path
            identities[field] = (str(path), node.st_dev, node.st_ino, node.st_size,
                                 node.st_mtime_ns, node.st_ctime_ns) if node else None
        except TaskArtifactUnavailable as exc:
            artifacts[field] = None
            identities[field] = ("unavailable", exc.reason)
    payload = [1, record.id, record.title, source, record.checkpoint,
               bool(record.summary_diagnostics.get("review_required")), identities]
    signature = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return signature, artifacts
