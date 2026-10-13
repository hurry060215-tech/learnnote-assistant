"""Preflight and reversible file writes for a local learning-backup restore.

The recovery directory is deliberately retained after an interrupted process or
failed rollback. We never guess whether a separate SQLite commit completed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from .personal_storage import PersonalRecoveryRequired, personal_transaction, state_root

_MAX_FILE_BYTES = 32_000_000
_MAX_EXISTING_BYTES = 100_000_000


def _read_existing(path: Path) -> bytes | None:
    root = path.parent
    if root.is_symlink() or (root.exists() and not root.is_dir()) or path.is_symlink():
        raise ValueError("personal_restore_target_unsafe")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError("personal_restore_target_invalid")
    with path.open("rb") as stream:
        content = stream.read(_MAX_FILE_BYTES + 1)
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("personal_restore_target_too_large")
    return content


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("personal_restore_target_invalid")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError("personal_restore_target_invalid")


def _object(content: bytes) -> dict:
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("personal_restore_target_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("personal_restore_target_invalid")
    return value


def _annotation_file(content: bytes, key: str, validate) -> dict:
    value = _object(content)
    version = value.get("schema_version", 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("personal_restore_schema_unsupported")
    items = value.get("annotations")
    if not isinstance(items, list) or any(not isinstance(item, dict) or
            ("anchor" in item and not isinstance(item["anchor"], dict)) for item in items):
        raise ValueError("personal_restore_target_invalid")
    validate({"annotations": [{"key": key, "items": items}], "editions": []})
    return value  # Validation must never strip fields from current personal text.


def _edition_file(content: bytes, key: str, validate) -> None:
    value = _object(content)
    if "schema_version" in value:
        raise ValueError("personal_restore_schema_unsupported")
    if type(value.get("edited")) is not bool:
        raise ValueError("personal_restore_target_invalid")
    validate({"annotations": [], "editions": [{"key": key, "value": value}]})


def _atomic_bytes(path: Path, content: bytes) -> None:
    """Preserve exact preimage bytes, including line endings, during rollback."""
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.restore")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class _Change:
    path: Path
    before: bytes | None
    after: str

    @property
    def written_bytes(self) -> bytes:
        # storage.atomic_write_text uses native text-mode newline translation.
        return self.after.replace("\n", os.linesep).encode("utf-8")


class PersonalRestore:
    def __init__(self, data_dir: Path, snapshot: dict, validate, writer):
        self.data_dir = data_dir
        self.writer = writer
        self.changes: list[_Change] = []
        self.attempted: list[_Change] = []
        self.recovery: Path | None = None
        self.recovery_identity: tuple[int, int] | None = None
        self.counts = {"restored_annotations": 0, "restored_editions": 0, "restored_personal_reviews": 0}
        existing_bytes = 0
        for group in snapshot["annotations"]:
            path = data_dir / "personal-notes" / f"{group['key']}.json"
            before = _read_existing(path)
            existing_bytes += len(before or b"")
            value = _annotation_file(before, group["key"], validate) if before is not None else {"annotations": []}
            existing = value["annotations"]
            ids = {item["id"] for item in existing}
            additions = [item for item in group["items"] if item["id"] not in ids]
            if len(existing) + len(additions) > 500:
                raise ValueError("personal_annotation_limit_reached")
            if additions:
                after = json.dumps({**value, "schema_version": 2, "annotations": existing + additions}, ensure_ascii=False, indent=2)
                self.changes.append(_Change(path, before, after))
                self.counts["restored_annotations"] += len(additions)
            if existing_bytes > _MAX_EXISTING_BYTES:
                raise ValueError("personal_restore_targets_too_large")
        for item in snapshot["editions"]:
            path = data_dir / "user-editions" / f"{item['key']}.json"
            before = _read_existing(path)
            existing_bytes += len(before or b"")
            if before is not None:
                _edition_file(before, item["key"], validate)
            else:
                # Restoring is a new local write, even when its text equals the
                # generated note. Never replay a backed-up assistant write ID.
                restored = {**item["value"], "write_id": uuid4().hex}
                self.changes.append(_Change(path, None, json.dumps(restored, ensure_ascii=False)))
                self.counts["restored_editions"] += 1
            if existing_bytes > _MAX_EXISTING_BYTES:
                raise ValueError("personal_restore_targets_too_large")
        from .personal_review_records import validate_review, imported_review
        for item in snapshot.get("personal_reviews", []):
            path = data_dir / "personal-reviews" / f"{item['key']}.json"
            before = _read_existing(path)
            existing_bytes += len(before or b"")
            if before is not None:
                # Every local state wins, including revoked and stale records.
                validate_review(_object(before), item["key"])
            else:
                value = imported_review(validate_review(item["value"], item["key"]))
                self.changes.append(_Change(path, None, json.dumps(value, ensure_ascii=False)))
                self.counts["restored_personal_reviews"] += 1
            if existing_bytes > _MAX_EXISTING_BYTES:
                raise ValueError("personal_restore_targets_too_large")

    def apply(self) -> None:
        if not self.changes:
            return
        if self.recovery is not None:
            raise ValueError("personal_restore_already_applied")
        recovery = state_root(self.data_dir) / "restore-pending"
        try:
            recovery.mkdir()  # Never claim ownership of a prior restore.
        except FileExistsError as exc:
            raise PersonalRecoveryRequired() from exc
        self.recovery = recovery
        stat = recovery.stat()
        self.recovery_identity = (stat.st_dev, stat.st_ino)
        manifest = {"schema_version": 1, "status": "prepared", "files": []}
        for index, change in enumerate(self.changes):
            if _read_existing(change.path) != change.before:
                raise ValueError("personal_restore_target_changed")
            name = f"{index}.original" if change.before is not None else None
            if name:
                _atomic_bytes(self.recovery / name, change.before)
            manifest["files"].append({"path": change.path.relative_to(self.data_dir).as_posix(),
                "original": name, "original_sha256": hashlib.sha256(change.before).hexdigest() if change.before is not None else None,
                "restored_sha256": hashlib.sha256(change.written_bytes).hexdigest()})
        _atomic_bytes(self.recovery / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        for change in self.changes:
            if _read_existing(change.path) != change.before:
                raise ValueError("personal_restore_target_changed")
            self.attempted.append(change)  # Includes a writer that replaces then raises.
            self.writer(change.path, change.after)
            if _read_existing(change.path) != change.written_bytes:
                raise OSError("personal_restore_write_unverified")

    def rollback(self) -> None:
        failed = False
        for change in reversed(self.attempted):
            try:
                current = _read_existing(change.path)
                if current == change.before:
                    continue
                if current != change.written_bytes:
                    raise ValueError("personal_restore_target_changed")
                if change.before is None:
                    change.path.unlink()
                else:
                    _atomic_bytes(change.path, change.before)
            except (OSError, ValueError):
                failed = True
        if failed:
            raise PersonalRecoveryRequired()
        self.cleanup()

    def cleanup(self) -> None:
        if self.recovery is not None:
            try:
                stat = self.recovery.lstat()
                if self.recovery.is_symlink() or (stat.st_dev, stat.st_ino) != self.recovery_identity:
                    raise PersonalRecoveryRequired()
                shutil.rmtree(self.recovery)
            except OSError as exc:
                raise PersonalRecoveryRequired() from exc
            self.recovery = None


@contextmanager
def personal_restore_transaction(data_dir: Path, snapshot: dict, validate, writer):
    with personal_transaction(data_dir):
        plan = PersonalRestore(data_dir, snapshot, validate, writer)
        try:
            yield plan
        except Exception:
            plan.rollback()
            raise
        else:
            plan.cleanup()
