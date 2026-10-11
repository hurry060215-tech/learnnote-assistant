"""Read catalog availability without creating or repairing a database."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .catalog_guard import CatalogUnavailable, orphaned_sidecars, validate_catalog_version


def catalog_status(root: Path) -> dict:
    path = root / "library.sqlite3"
    directories = sorted(p.name for p in (root / "materials").glob("*") if p.is_dir())
    state, ids, task_count, material_count = "missing", set(), None, None
    sidecars = orphaned_sidecars(path)
    if path.is_symlink():
        state = "corrupt"
    elif sidecars:
        state = "corrupt" if path.exists() else "missing"
    elif path.is_file() and path.stat().st_size:
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                db.execute("PRAGMA query_only=ON")
                validate_catalog_version(db)
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise sqlite3.DatabaseError("integrity")
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "library_materials" in tables:
                    ids = {r[0] for r in db.execute("SELECT material_id FROM library_materials")}
                    material_count = len(ids)
                task_count = db.execute("SELECT COUNT(*) FROM library_tasks").fetchone()[0] if "library_tasks" in tables else 0
                state = "healthy" if "library_materials" in tables else "incomplete"
        except CatalogUnavailable:
            state = "incompatible"
        except (sqlite3.Error, OSError):
            state = "corrupt"
    orphaned = [key for key in directories if key not in ids]
    if state == "healthy" and orphaned:
        state = "incomplete"
    required = state in {"corrupt", "incompatible"} or bool(orphaned) or bool(sidecars)
    return {
        "state": state, "orphaned_material_ids": orphaned, "unresolved_sidecars": sidecars,
        "recovery_required": required, "indexed_task_count": task_count,
        "material_count": material_count,
        "message": "资料目录版本不兼容；已保留原数据库，请使用创建该版本的软件或完整备份恢复。" if state == "incompatible" else "请选择包含资料身份与出处元数据的 SQLite 备份预览恢复；仅有原文件无法确定丢失的身份和解码选择。" if required else "资料目录未发现孤立原文件。",
    }


def require_readable_catalog(root: Path) -> None:
    state = catalog_status(root)
    if state["state"] in {"corrupt", "incompatible"} or (state["state"] == "missing" and state["recovery_required"]):
        raise CatalogUnavailable("catalog_recovery_required")
