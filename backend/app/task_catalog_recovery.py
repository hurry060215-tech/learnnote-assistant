"""Explicit, conservative task-only recovery of an unreadable local catalog.

Task manifests and canonical source files are read, never migrated or rewritten.
Readable databases and unresolved transaction logs require separate recovery.
"""
from __future__ import annotations

from contextlib import closing
import json
from itertools import islice
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
from uuid import uuid4

from . import library
from .catalog_guard import catalog_guard
from .catalog_recovery import _digest, _preserve, _sync_directory
from .knowledge import _prepare_evidence, _write_evidence, ensure_evidence_schema
from .models import TASK_SCHEMA_VERSION, TaskRecord
from .text_cleanup import read_canonical_text

SCOPE = "task_catalog_only"
MARKER = "task_catalog_recovery"
WARNING = "仅恢复本机任务目录与任务出处。原数据库中的文档记录、视频资料登记及其他未知记录未恢复，无法确定缺失数量；没有孤立原文件也不表示目录完整。"
RESTORE = "如需撤回：完全退出 LearnNote 及后端；将当前 library.sqlite3 和全部 library.sqlite3-* 侧文件移到另一新文件夹保留，再按本备份 preserved.json 的 files 清单，仅将列出的同名文件复制回数据文件夹（原来缺失的文件保持缺失；不要复制 original- 或 interrupted- 前缀文件）。重新启动后会回到原先损坏/缺失状态，不保证目录可用。请勿在应用运行时替换文件，也不要把损坏文件提交到正常 SQLite 快照恢复入口。"
MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 20000
MAX_SOURCE_BYTES = 16 * 1024 * 1024


def _redirected(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        # Junctions and other Windows reparse points need not be symlinks.
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except FileNotFoundError:
        return False


def _safe(path: Path, root: Path) -> None:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise ValueError("catalog_source_path_unsafe") from exc
    current = root
    if _redirected(current):
        raise ValueError("catalog_source_path_unsafe")
    for part in relative.parts:
        if part in {".", ".."}:
            raise ValueError("catalog_source_path_unsafe")
        current = current / part
        if _redirected(current):
            raise ValueError("catalog_source_path_unsafe")


def _fingerprint(path: Path, root: Path, inventory: dict) -> None:
    _safe(path, root)
    if not path.is_file():
        raise ValueError("task_recovery_source_missing")
    inventory[path.relative_to(root).as_posix()] = library._file_sha256(path)
    if len(inventory) > MAX_FILES:
        raise ValueError("catalog_recovery_too_large")


def _family(root: Path) -> dict:
    inventory = {}
    paths = {root / "library.sqlite3", *islice(root.glob("library.sqlite3-*"), MAX_FILES + 1)}
    if len(paths) > MAX_FILES:
        raise ValueError("catalog_recovery_too_large")
    size = 0
    for path in sorted(paths):
        _safe(path, root)
        if path.exists():
            size += path.stat().st_size
            if size > MAX_BYTES:
                raise ValueError("catalog_recovery_too_large")
            _fingerprint(path, root, inventory)
    return inventory


def _eligibility(root: Path, family: dict) -> str:
    # Only a literal zero-length transaction log is provably inert.
    for name in family:
        if name != "library.sqlite3" and name != "library.sqlite3-shm":
            if name not in {"library.sqlite3-wal", "library.sqlite3-journal"} or (root / name).stat().st_size:
                return "catalog_sidecars_unresolved"
    path = root / "library.sqlite3"
    if not path.exists() or not path.stat().st_size:
        return ""
    # immutable avoids opening, creating, replaying, or deleting live sidecars.
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("SELECT name FROM sqlite_master").fetchall()
    except sqlite3.DatabaseError as exc:
        if getattr(exc, "sqlite_errorcode", None) in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
            return ""
        return "catalog_current_schema_invalid"
    return "catalog_partial_corruption_unresolved"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("task_recovery_manifest_invalid")
        result[key] = value
    return result


def _sources(root: Path) -> tuple[list, dict]:
    tasks = library.TASK_DIR
    _safe(tasks, root)
    inventory, selected, size = {}, [], 0
    manifests = sorted(islice(tasks.glob("*/task.json"), MAX_FILES // 3 + 1))
    if not manifests or len(manifests) > MAX_FILES // 3:
        raise ValueError("task_recovery_no_tasks" if not manifests else "catalog_recovery_too_large")
    for manifest in manifests:
        _safe(manifest, root)
        if manifest.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("catalog_recovery_too_large")
        size += manifest.stat().st_size
        if size > MAX_BYTES:
            raise ValueError("catalog_recovery_too_large")
        _fingerprint(manifest, root, inventory)
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
            record = TaskRecord.model_validate(payload)
        except (ValueError, RecursionError) as exc:
            raise ValueError("task_recovery_manifest_invalid") from exc
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", record.id) or record.id != manifest.parent.name or record.schema_version > TASK_SCHEMA_VERSION:
            raise ValueError("task_recovery_manifest_invalid")
        if record.status in {"queued", "running", "cancelling"}:
            raise ValueError("task_recovery_tasks_active")
        texts = []
        for value in (record.note_path, record.transcript_path):
            if not value:
                texts.append("")
                continue
            path = Path(value)
            _safe(path, manifest.parent)
            if path.stat().st_size > MAX_SOURCE_BYTES:
                raise ValueError("catalog_recovery_too_large")
            size += path.stat().st_size
            if size > MAX_BYTES:
                raise ValueError("catalog_recovery_too_large")
            _fingerprint(path, root, inventory)
            text = read_canonical_text(path).text
            if len(text) > 1_000_000:
                raise ValueError("catalog_recovery_too_large")
            texts.append("" if path.name == "draft.partial.md" else text)
        note, transcript = texts
        try:
            evidence = [library.record_to_evidence(record, note, "note")] if note else []
            if transcript:
                evidence.extend(library.transcript_evidence(record, transcript))
            evidence = [_prepare_evidence(item) for item in evidence]
            if any(not math.isfinite(float(item.metadata[key])) for item in evidence for key in ("start", "end") if key in item.metadata):
                raise ValueError("nonfinite")
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise ValueError("task_recovery_manifest_invalid") from exc
        selected.append((record, note, transcript, evidence))
    if sum((root / name).stat().st_size for name in inventory) > MAX_BYTES:
        raise ValueError("catalog_recovery_too_large")
    return selected, inventory


def _plan() -> tuple[dict, list, dict, dict]:
    root = library.DATA_DIR
    family = _family(root)
    code = _eligibility(root, family)
    selected, sources = [], {}
    if not code:
        try:
            selected, sources = _sources(root)
        except (ValueError, OSError) as exc:
            code = str(exc) if isinstance(exc, ValueError) else "task_recovery_source_missing"
    if family != _family(root):
        raise ValueError("catalog_changed_preview_again")
    if not code:
        current_sources = {}
        for name in sources:
            _fingerprint(root / name, root, current_sources)
        if current_sources != sources:
            raise ValueError("catalog_changed_preview_again")
    token = _digest([SCOPE, family, sources])
    return ({"can_apply": not code and bool(selected), "code": code, "preview_token": token,
             "recovery_scope": SCOPE, "task_count": len(selected), "evidence_count": sum(len(row[3]) for row in selected),
             "document_count": None, "unknown_documents_unrestored": True,
             "message": WARNING, "restore_instructions": RESTORE}, selected, family, sources)


def preview_task_recovery() -> dict:
    from .storage import task_state_transaction
    _check_lock_paths()
    with library.assistant_records.locked(library.DATA_DIR), task_state_transaction(), library._lock, catalog_guard(library.DATA_DIR):
        return _plan()[0]


def _check_lock_paths():
    root = library.DATA_DIR
    for name in (".task-state/worker.lock", "assistant-operations/worker.lock", ".library-access.lock", "exports"):
        _safe(root / name, root)


def _stage(path: Path, selected: list, backup: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        fts = library._ensure_schema(db)
        ensure_evidence_schema(db)
        evidence_fts = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='source_evidence_fts'").fetchone())
        for record, note, transcript, evidence in selected:
            source = library._safe_url(record.page_url)
            content = "\n".join(part for part in (record.title, source, note, transcript) if part)
            values = (record.id, record.title, source, record.source_type, record.mode, record.status, record.checkpoint,
                      record.created_at, record.updated_at, record.note_path, "", record.source_identity.media_sha256, content)
            db.execute("INSERT INTO library_tasks(task_id,title,source,source_type,mode,status,checkpoint,created_at,updated_at,note_path,media_path,fingerprint,content) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
            if fts:
                db.execute("INSERT INTO library_tasks_fts(task_id,title,source,content) VALUES (?,?,?,?)", (record.id, record.title, source, content))
            for item in evidence:
                _write_evidence(db, item, evidence_fts, replace_existing=False)
        marker = {"schema_version": 1, "scope": SCOPE, "unknown_documents_unrestored": True,
                  "backup_directory": backup.name, "message": WARNING, "restore_instructions": RESTORE}
        db.execute("INSERT INTO library_meta VALUES (?,?)", (MARKER, json.dumps(marker, ensure_ascii=False)))
        db.commit()
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("catalog_recovery_validation_failed")
        if db.execute("SELECT COUNT(*) FROM library_tasks").fetchone()[0] != len(selected):
            raise ValueError("catalog_recovery_validation_failed")
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def apply_task_recovery(preview_token: str) -> dict:
    from .storage import task_state_transaction
    root = library.DATA_DIR
    _check_lock_paths()
    with library.assistant_records.locked(root), task_state_transaction(), library._lock, catalog_guard(root):
        preview, selected, family, sources = _plan()
        if preview_token != preview["preview_token"]:
            raise ValueError("catalog_changed_preview_again")
        if not preview["can_apply"]:
            raise ValueError(preview["code"] or "catalog_recovery_unresolved")
        # _preserve copies every catalog byte durably; it never prunes backups.
        shared = (root / "library.sqlite3-shm").read_bytes() if "library.sqlite3-shm" in family else None
        backup = _preserve(root, family, shared)
        if any(library._file_sha256(backup / name) != fingerprint for name, fingerprint in family.items()):
            raise ValueError("catalog_changed_preview_again")
        instructions = backup / "RESTORE.txt"
        with instructions.open("x", encoding="utf-8") as handle:
            handle.write(WARNING + "\n\n" + RESTORE + "\n\nOriginal family: " + ", ".join(sorted(family)))
            handle.flush(); os.fsync(handle.fileno())
        _sync_directory(backup)
        temporary = root / f".task-catalog-{uuid4().hex}.sqlite3"
        moved, published, staged_digest = [], False, None
        target = root / "library.sqlite3"
        try:
            _stage(temporary, selected, backup)
            staged_digest = library._file_sha256(temporary)
            check, _, now_family, now_sources = _plan()
            if check["preview_token"] != preview_token or now_family != family or now_sources != sources:
                raise ValueError("catalog_changed_preview_again")
            # Keep the original sidecars, including SHM, outside the replacement's
            # SQLite family. Nonempty transaction logs were rejected above.
            for name in sorted(family):
                if name != "library.sqlite3":
                    destination = backup / ("original-" + name)
                    moved.append((name, destination))
                    os.replace(root / name, destination)
                    if library._file_sha256(destination) != family[name]:
                        raise ValueError("catalog_changed_preview_again")
            _sync_directory(backup)
            if _family(root) != {k: v for k, v in family.items() if k == "library.sqlite3"}:
                raise ValueError("catalog_changed_preview_again")
            os.replace(temporary, target)
            published = True
            _sync_directory(root)
        except BaseException:
            # An interruption may arrive after replace succeeds but before the
            # Python publication flag is assigned. Recognize the staged bytes.
            installed = published
            if not installed and staged_digest:
                try:
                    _safe(target, root)
                    installed = target.is_file() and library._file_sha256(target) == staged_digest
                except (OSError, ValueError):
                    # A changed/unsafe/unreadable target must not be followed,
                    # and probing it must not prevent sidecar rollback.
                    installed = False
            if installed:
                # Preserve the generated/current family as well during undo.
                os.replace(target, backup / "interrupted-task-catalog.sqlite3")
                if "library.sqlite3" in family:
                    shutil.copy2(backup / "library.sqlite3", temporary)
                    with temporary.open("r+b") as handle:
                        os.fsync(handle.fileno())
                    os.replace(temporary, target)
            for name, original in moved:
                if not original.exists():
                    # The intended move may have failed before publishing its
                    # destination; the original remains in place in that case.
                    continue
                if (root / name).exists():
                    # An unexpected writer must not lose a newly appeared file
                    # even when the original family has to be rolled back.
                    os.replace(root / name, backup / f"interrupted-{uuid4().hex}-{name}")
                os.replace(original, root / name)
            _sync_directory(root)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return {**preview, "status": "partial", "can_apply": False, "preview_token": "",
                "restored_task_count": len(selected), "restored_evidence_count": preview["evidence_count"],
                "rollback_snapshot_created": True, "rollback_directory": backup.name}
