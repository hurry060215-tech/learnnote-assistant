"""Explicit snapshot recovery; never infer identities from orphaned originals."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from . import library
from .catalog_guard import catalog_guard
from .catalog_health import catalog_status
from .catalog_snapshot import EVIDENCE_COLUMNS, MATERIAL_COLUMNS, equivalent, read_snapshot, trusted_schema, validate_material, validate_schema
from .knowledge import ensure_evidence_schema

REASONS = {
    "catalog_metadata_missing": "所选备份不包含这份原文件的资料元数据；无法确定原身份或解码选择。",
    "catalog_metadata_invalid": "资料元数据不完整或类型无效；请另选完整备份。",
    "catalog_identity_invalid": "资料或出处身份不合法，未猜测或重新导入。",
    "catalog_original_missing": "原文件缺失；请先从完整数据备份恢复对应原文件。",
    "catalog_original_changed": "原文件大小或 SHA-256 与所选备份不一致。",
    "catalog_source_path_unsafe": "原文件或资料目录是链接或越出资料目录，未读取其目标。",
    "catalog_source_too_large": "原文件超过 32 MB 的验证上限。",
    "catalog_cache_invalid": "所选 OCR 缓存缺失、越界或版本校验失败。",
    "catalog_revision_changed": "按保存的编码重新解析后，内容版本与备份不一致。",
    "catalog_evidence_missing": "备份缺少原出处记录，无法验证历史引用身份。",
    "catalog_evidence_invalid": "备份出处记录格式无效。",
    "catalog_evidence_conflict": "备份出处与原文件、身份或解码元数据不一致。",
    "catalog_current_conflict": "本机保留的身份、元数据或出处与所选备份冲突，未覆盖当前版本。",
    "catalog_document_required": "此入口仅恢复文档资料；视频登记需要先恢复原视频任务。",
}


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _freshness(inventory: dict) -> dict:
    empty = hashlib.sha256(b"").hexdigest()
    return {k: v for k, v in inventory.items() if k != "library.sqlite3-shm"
            and not (k in {"library.sqlite3-wal", "library.sqlite3-journal"} and v == empty)}


def _inventory(root: Path) -> dict[str, str]:
    paths = [root / f"library.sqlite3{suffix}" for suffix in ("", "-wal", "-shm", "-journal")]
    material_root = root / "materials"
    if material_root.is_symlink():
        raise ValueError("catalog_source_path_unsafe")
    if material_root.exists():
        paths.extend(sorted(material_root.rglob("*")))
    result, size = {}, 0
    if len(paths) > 20000:
        raise ValueError("catalog_recovery_too_large")
    for path in paths:
        if path.is_symlink():
            raise ValueError("catalog_source_path_unsafe")
        if not path.exists():
            continue
        name = path.relative_to(root).as_posix()
        if path.is_dir():
            result[name] = "directory"
            continue
        if not path.is_file():
            raise ValueError("catalog_source_path_unsafe")
        size += path.stat().st_size
        if size > 512 * 1024 * 1024:
            raise ValueError("catalog_recovery_too_large")
        result[name] = library._file_sha256(path)
    return result


def _live_rows(root: Path, state: str) -> tuple[dict, dict]:
    if state == "corrupt":
        # A partially readable database may contain healthy records absent from
        # the selected backup. Do not discard them through a file replacement.
        try:
            with closing(sqlite3.connect((root / "library.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
                db.execute("SELECT name FROM sqlite_master").fetchall()
        except sqlite3.Error:
            return {}, {}
        raise ValueError("catalog_partial_corruption_unresolved")
    if state == "missing":
        return {}, {}
    with closing(sqlite3.connect((root / "library.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        validate_schema(db, "catalog_current_schema_invalid")
        result = []
        for table, identifier, columns in (("library_materials", "material_id", MATERIAL_COLUMNS), ("source_evidence", "evidence_id", EVIDENCE_COLUMNS)):
            if table in tables and not set(columns).issubset(r[1] for r in db.execute(f"PRAGMA table_info({table})")):
                raise ValueError("catalog_current_schema_invalid")
            rows = [dict(r) for r in db.execute(f"SELECT * FROM {table}")] if table in tables else []
            if any(not set(columns).issubset(row) for row in rows):
                raise ValueError("catalog_current_schema_invalid")
            result.append({row[identifier]: row for row in rows})
        return tuple(result)


def _plan(snapshot: Path) -> tuple[dict, list[tuple[dict, list[dict]]], dict]:
    root = library.DATA_DIR
    inventory = _inventory(root)
    catalog = catalog_status(root)
    rows, evidence, digest = read_snapshot(snapshot)
    current, current_evidence = _live_rows(root, catalog["state"])
    summaries, recoverable, unresolved, seen = [], [], [], set()
    for row in rows:
        key = row.get("material_id")
        # Video aliases have a separate task-manifest recovery path.
        if row.get("source_type") == "video" and row.get("linked_task_id"):
            summaries.append({"material_id": key, "title": row.get("title", ""), "status": "excluded", "reason": REASONS["catalog_document_required"]})
            continue
        seen.add(key)
        summary = {"material_id": key, "title": row.get("title", ""), "status": "unresolved"}
        try:
            material, items = validate_material(root, row, evidence)
            if (key in current and not equivalent(current[key], material, MATERIAL_COLUMNS)
                    or any(other != key and value["sha256"] == material["sha256"] for other, value in current.items())
                    or any(item["evidence_id"] in current_evidence and not equivalent(current_evidence[item["evidence_id"]], item, EVIDENCE_COLUMNS) for item in items)):
                raise ValueError("catalog_current_conflict")
            missing = [item for item in items if item["evidence_id"] not in current_evidence]
            summary["status"] = "recoverable" if key not in current or missing else "unchanged"
            summary["reason"] = "已验证原文件、解码版本和出处身份。" if summary["status"] == "recoverable" else "本机已有相同资料与出处，无需修改。"
            if summary["status"] == "recoverable":
                recoverable.append((material, missing))
        except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
            code = str(exc) if str(exc) in REASONS else "catalog_metadata_invalid"
            summary.update(code=code, reason=REASONS[code])
            unresolved.append(summary.copy())
        summaries.append(summary)
    for key in catalog["orphaned_material_ids"]:
        if key not in seen:
            item = {"material_id": key, "title": "", "status": "unresolved", "code": "catalog_metadata_missing", "reason": REASONS["catalog_metadata_missing"]}
            summaries.append(item)
            unresolved.append(item)
    if catalog["state"] in {"missing", "corrupt"} and any(inventory.get(f"library.sqlite3{suffix}") for suffix in ("-wal", "-journal")):
        raise ValueError("catalog_sidecars_unresolved")
    final_inventory = _inventory(root)
    if _freshness(final_inventory) != _freshness(inventory):
        raise ValueError("catalog_changed_preview_again")
    inventory = final_inventory
    if library._file_sha256(snapshot) != digest:
        raise ValueError("catalog_changed_preview_again")
    return ({"snapshot_sha256": digest, "preview_token": _digest([digest, _freshness(inventory)]), "catalog": catalog,
             "can_apply": bool(recoverable) and not unresolved, "materials": summaries, "unresolved": unresolved,
             "recoverable_count": len(recoverable), "excluded_count": sum(s["status"] == "excluded" for s in summaries),
             "recovery_scope": "material_catalog_only",
             "message": "仅恢复所选备份中已验证的文档身份与出处。丢失当前元数据时，无法证明所选备份是最新历史版本。任务、分组、学习记录和个人修改不会被覆盖。"}, recoverable, inventory)


def preview_recovery(snapshot: Path) -> dict:
    with library._lock, catalog_guard(library.DATA_DIR):
        return _plan(snapshot)[0]


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _preserve(root: Path, inventory: dict) -> Path:
    if (root / "exports").is_symlink():
        raise ValueError("catalog_source_path_unsafe")
    folder = root / "exports" / f"catalog-recovery-{uuid4().hex}"
    folder.mkdir(parents=True)
    preserved = inventory.copy()
    for name, digest in inventory.items():
        target = folder / name
        if digest == "directory":
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
        actual = library._file_sha256(target)
        if name == "library.sqlite3-shm":
            preserved[name] = actual  # Reader bookkeeping is not source identity.
        elif actual != digest:
            raise ValueError("catalog_changed_preview_again")
        with target.open("r+b") as handle:
            os.fsync(handle.fileno())
    manifest = folder / "preserved.json"
    with manifest.open("w", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "files": preserved, "catalog_was_missing": "library.sqlite3" not in inventory}, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    for directory in sorted((p for p in folder.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        _sync_directory(directory)
    _sync_directory(folder)
    _sync_directory(folder.parent)
    _sync_directory(root)
    return folder


def _ensure_recovery_tables(db: sqlite3.Connection) -> None:
    # Generate only our trusted schema; execute DDL inside the caller's transaction.
    for name, definition in trusted_schema().items():
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
            db.execute(definition)
    db.execute("INSERT OR IGNORE INTO library_meta VALUES ('schema_version', ?)", (str(library.LIBRARY_SCHEMA_VERSION),))


def _merge(db: sqlite3.Connection, selected: list) -> tuple[int, int]:
    material_count = evidence_count = 0
    fts = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='source_evidence_fts'").fetchone())
    for material, items in selected:
        if not db.execute("SELECT 1 FROM library_materials WHERE material_id=?", (material["material_id"],)).fetchone():
            db.execute(f"INSERT INTO library_materials ({','.join(MATERIAL_COLUMNS)}) VALUES ({','.join('?' for _ in MATERIAL_COLUMNS)})", tuple(material[k] for k in MATERIAL_COLUMNS))
            material_count += 1
        for item in items:
            db.execute(f"INSERT INTO source_evidence ({','.join(EVIDENCE_COLUMNS)}) VALUES ({','.join('?' for _ in EVIDENCE_COLUMNS)})", tuple(item[k] for k in EVIDENCE_COLUMNS))
            evidence_count += 1
            if fts:
                db.execute("DELETE FROM source_evidence_fts WHERE evidence_id=?", (item["evidence_id"],))
                db.execute("INSERT INTO source_evidence_fts(evidence_id,title,source_uri,locator,text) VALUES (?,?,?,?,?)", tuple(item[k] for k in ("evidence_id", "title", "source_uri", "locator", "text")))
    return material_count, evidence_count


def apply_recovery(snapshot: Path, preview_token: str) -> dict:
    root = library.DATA_DIR
    with library._lock, catalog_guard(root):
        preview, selected, inventory = _plan(snapshot)
        if preview_token != preview["preview_token"]:
            raise ValueError("catalog_changed_preview_again")
        if not preview["can_apply"]:
            raise ValueError("catalog_recovery_unresolved")
        replacement = preview["catalog"]["state"] in {"missing", "corrupt"}
        target = root / "library.sqlite3"
        temporary = root / f".catalog-recovery-{uuid4().hex}.sqlite3"
        db = sqlite3.connect(temporary if replacement else target)
        published, backup = False, None
        try:
            db.execute("PRAGMA cache_spill=OFF")
            if replacement:
                library._ensure_schema(db)
                ensure_evidence_schema(db)
                db.commit()
            db.execute("BEGIN IMMEDIATE")
            if _freshness(_inventory(root)) != _freshness(inventory):
                raise ValueError("catalog_changed_preview_again")
            backup = _preserve(root, inventory)
            _ensure_recovery_tables(db)
            counts = _merge(db, selected)
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("catalog_recovery_validation_failed")
            if _freshness(_inventory(root)) != _freshness(inventory):
                # Our transaction may create a rollback journal, but originals
                # and the pre-transaction database must still match the preview.
                now, before = _freshness(_inventory(root)), _freshness(inventory)
                if any(now.get(k) != v for k, v in before.items()) or any(k not in before and k != "library.sqlite3-journal" for k in now):
                    raise ValueError("catalog_changed_preview_again")
            db.commit()
            db.close()
            if replacement:
                with temporary.open("r+b") as handle:
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
                published = True
                _sync_directory(root)
        except BaseException:
            try:
                db.rollback()
            except sqlite3.ProgrammingError:
                pass
            if published:
                if "library.sqlite3" in inventory:
                    shutil.copy2(backup / "library.sqlite3", temporary)
                    os.replace(temporary, target)
                else:
                    target.unlink()
            raise
        finally:
            db.close()
            temporary.unlink(missing_ok=True)
        return {"status": "pass", "restored_material_count": counts[0], "restored_evidence_count": counts[1],
                "unresolved": [], "excluded_count": preview["excluded_count"], "recovery_scope": "material_catalog_only",
                "rollback_snapshot_created": True, "rollback_directory": backup.name,
                "message": "已恢复验证通过的文档目录与原出处身份。原数据库与资料副本保留在 exports 的恢复备份中；任务索引可另行重建。"}
