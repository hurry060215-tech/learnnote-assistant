"""Consolidate supported non-catalog SQLite families on disposable copies only."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import re
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .data_migration_inventory import DATABASES, checked, fail, fingerprint

from .data_migration_schemas import EXPECTED_SCHEMAS


def _quoted(value):
    return '"' + value.replace('"', '""') + '"'


def _sql_signature(value):
    # Ignore layout between SQL tokens, never case/whitespace inside literals.
    return re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]", value) if value else None


def _proof(db, name):
    db.execute("PRAGMA trusted_schema=OFF")
    if db.execute("PRAGMA user_version").fetchone()[0] != 0 or db.execute("PRAGMA application_id").fetchone()[0] != 0:
        fail("unsupported_database_schema", f"{name} 数据库版本未受支持。")
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        fail("database_integrity", f"{name} 完整性校验失败。")
    schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    result = {}
    actual_schema = {row[1]: (row[0], row[2], _sql_signature(row[3])) for row in schema}
    expected_schema = {key: (value[0], value[1], _sql_signature(value[2])) for key, value in EXPECTED_SCHEMAS[name].items()}
    if actual_schema != expected_schema:
        fail("unsupported_database_schema", f"{name} 数据库结构未受支持，请先检查或恢复原库。")
    for kind, table, _owner, sql in schema:
        if kind in {"view", "trigger"} or (kind == "table" and sql and "VIRTUAL" in sql.upper()):
            fail("unsupported_database_schema", f"{name} 含未支持的数据库对象。")
        if kind != "table":
            continue
        columns = [row[1] for row in db.execute(f"PRAGMA table_info({_quoted(table)})")]
        rows = db.execute(f"SELECT * FROM {_quoted(table)}").fetchall()
        encoded = sorted(json.dumps(row, ensure_ascii=True, separators=(",", ":"),
            default=lambda value: {"blob_hex": value.hex()}) for row in rows)
        result[table] = {"columns": columns, "rows": len(rows),
                         "values_sha256": hashlib.sha256("\n".join(encoded).encode()).hexdigest()}
        if name == "task-queue.sqlite3" and table == "jobs":
            if "state" not in columns or any(row[columns.index("state")] not in {"done", "cancelled", "failed"} for row in rows):
                fail("tasks_running", "任务队列仍有待处理工作，请先完成或停止任务。")
    return {"schema": schema, "tables": result}


def _build(snapshot, inventory):
    receipts, outputs = [], {}
    if any(name.endswith("-journal") for name in inventory):
        fail("pending_recovery", "回滚日志需要在原目录单独恢复，迁移不会打开它。")
    for name in sorted(DATABASES - {"library.sqlite3"}):
        if name not in inventory:
            continue
        family = [name + suffix for suffix in ("", "-wal", "-shm") if name + suffix in inventory]
        for relative in family:
            item = fingerprint(snapshot / relative)
            if any(item[key] != inventory[relative][key] for key in ("size", "sha256")):
                fail("snapshot_changed", "数据库快照发生变化。")
        with tempfile.TemporaryDirectory(prefix=".migration-db-", dir=snapshot.parent) as temporary:
            scratch = Path(temporary)
            for relative in family:
                shutil.copyfile(snapshot / relative, scratch / relative, follow_symlinks=False)
            original = scratch / name
            result = scratch / "consolidated.sqlite3"
            with closing(sqlite3.connect(original, timeout=0)) as db:
                before = _proof(db, name)
                with closing(sqlite3.connect(result, timeout=0)) as out:
                    db.backup(out)
                    after = _proof(out, name)
                    if before != after:
                        fail("database_changed", "数据库行、模式或非路径数据校验失败。")
            raw = result.read_bytes()
        outputs[name] = raw
        receipts.append({"path": name, "family": family, "before": before, "after": after,
            "original_sha256": inventory[name]["sha256"], "result_sha256": hashlib.sha256(raw).hexdigest(),
            "result_size": len(raw), "removed_paths": family[1:]})
    return receipts, outputs


def plan_databases(snapshot: Path, inventory):
    return _build(snapshot, inventory)[0]


def apply_databases(stage: Path, inventory, plan):
    actual, outputs = _build(stage, inventory)
    # JSON roundtrip makes SQLite schema tuples comparable to a persisted plan.
    if json.loads(json.dumps(actual)) != json.loads(json.dumps(plan)):
        fail("database_plan_changed", "数据库快照与已确认预览不一致。")
    for item in actual:
        path = stage / item["path"]
        checked(path)
        path.write_bytes(outputs[item["path"]])
        for relative in item["removed_paths"]:
            checked(stage / relative)
            (stage / relative).unlink()
    return actual
