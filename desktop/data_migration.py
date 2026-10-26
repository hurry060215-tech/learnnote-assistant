"""Explicit preview and stopped-process data migration, with config committed last.

This helper never repairs the active source. Every transformation is confined to
an exclusive stage; the original directory and exact previous config are kept.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import hashlib
import json
import errno
import sys
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .data_migration_inventory import (
    MigrationError, absolute_directory, checked, copy_snapshot, destination_directory,
    fail, fingerprint, inventory, same_snapshot, COORDINATION_ROOTS, queue_owner_files,
)
from .data_migration_paths import plan_reference_changes, apply_reference_changes
from .data_migration_databases import plan_databases, apply_databases


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _config(root):
    path = root / "learnnote-config.json"
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    checked(path)
    raw = path.read_bytes()
    try:
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate config key")
                result[key] = value
            return result
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
        if not isinstance(value, dict):
            raise ValueError("config object")
    except (ValueError, UnicodeError):
        fail("invalid_config", "当前配置无法验证，请保留原配置并先检查。")
    return raw


def _config_identity(raw):
    return {"exists": raw is not None, "sha256": _sha(raw) if raw is not None else ""}


def _target_identity(target):
    info = checked(target, directory=True)
    return {"device": info.st_dev, "inode": info.st_ino}


def preview_migration(source: Path, target: Path, app_root: Path):
    source, app_root = absolute_directory(source), absolute_directory(app_root)
    target = destination_directory(source, target)
    if app_root == target or target in app_root.parents:
        fail("application_overlap", "目标目录不能包含应用安装目录。")
    config = _config(app_root)
    snapshot = inventory(source)
    with tempfile.TemporaryDirectory(prefix=".migration-preview-", dir=app_root) as temporary:
        scratch = Path(temporary)
        copy_snapshot(source, scratch, snapshot)
        for relative in snapshot["files"]:
            if relative.startswith("tasks/") and relative.endswith("/task.json"):
                payload = json.loads((scratch / relative).read_bytes())
                if payload.get("status") not in {"success", "failed", "cancelled"}:
                    fail("tasks_running", "任务清单仍有未停止或无法确认的任务，请先处理。")
        references = plan_reference_changes(source, scratch, target, snapshot["files"])
        databases = plan_databases(scratch, snapshot["files"])
    if not same_snapshot(snapshot, inventory(source)) or _config(app_root) != config:
        fail("source_changed", "预览期间源数据或配置变化，请重新预览。")
    plan = {"version": 1, "token": uuid4().hex, "source": str(source), "destination": str(target),
        "target_identity": _target_identity(target), "source_identity": _target_identity(source), "snapshot": snapshot,
        "references": references, "databases": databases, "config": _config_identity(config)}
    return plan


def public_preview(plan):
    files = plan["snapshot"]["files"]
    return {"ok": True, "preview": True, "token": plan["token"], "source": plan["source"],
        "path": plan["destination"], "file_count": len(files), "byte_count": sum(row["size"] for row in files.values()),
        "changes": [{**item, "field": item.get("column", "") + item.get("json_pointer", "")} for item in plan["references"]["changes"]], "excluded": plan["snapshot"]["excluded"],
        "external_references": plan["references"]["external_references"],
        "message": "请核对预览。确认后客户端会关闭，停止所有写入后再校验复制。激活前复制或校验失败不会切换；激活结果请查看迁移记录。原目录与原配置备份仍保留。"}


def _write_new(path, raw):
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    _write_new(temporary, _json(value))
    temporary.replace(path)


def _request_root(app_root):
    path = app_root / ".data-migrations"
    try:
        path.mkdir()
    except FileExistsError:
        pass
    checked(path, directory=True)
    return path


def prepare_request(app_root: Path, plan):
    """Called only after explicit confirmation, before launching the helper."""
    source, target = Path(plan["source"]), Path(plan["destination"])
    destination_directory(source, target)
    if _target_identity(target) != plan["target_identity"]:
        fail("destination_changed", "目标目录已被替换，请重新预览。")
    if _target_identity(source) != plan["source_identity"] or not same_snapshot(plan["snapshot"], inventory(source)):
        fail("source_changed", "源数据已变化，请重新预览。")
    previous = _config(app_root)
    if _config_identity(previous) != plan["config"]:
        fail("config_changed", "应用配置已变化，请重新预览。")
    token = plan["token"]
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        fail("invalid_preview", "预览已失效。")
    request_dir = _request_root(app_root) / token
    request_dir.mkdir()  # Never reuse a previous request or partial stage.
    if previous is not None:
        _write_new(request_dir / "previous-config.bin", previous)
    raw = _json(plan)
    _write_new(request_dir / "request.json", raw)
    _atomic(request_dir / "receipt.json", {"version": 1, "status": "scheduled", "source": str(source), "path": str(target), "request_sha256": _sha(raw), "previous_config": plan["config"]})
    return {"token": token, "digest": _sha(raw)}


def _load_request(app_root, token, digest):
    if not re.fullmatch(r"[a-f0-9]{32}", token) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        fail("invalid_request", "迁移请求无效，请重新预览。")
    root = app_root / ".data-migrations"
    checked(root, directory=True)
    directory = root / token
    checked(directory, directory=True)
    path = directory / "request.json"
    checked(path)
    raw = path.read_bytes()
    if _sha(raw) != digest:
        fail("request_changed", "已确认请求发生变化。")
    plan = json.loads(raw)
    if plan.get("version") != 1 or plan.get("token") != token:
        fail("invalid_request", "迁移请求版本无效。")
    previous = None
    if plan["config"]["exists"]:
        checked(directory / "previous-config.bin")
        previous = (directory / "previous-config.bin").read_bytes()
    if _config_identity(previous) != plan["config"]:
        fail("previous_config_changed", "原配置备份无法验证。")
    return directory, plan, previous


@contextmanager
def stopped_source_locks(source):
    """Acquire existing locks without creating, truncating or deleting source files.

    The caller has already waited for the whole desktop process to exit. The
    source session lock must exist; standalone/live backend migration is refused.
    """
    checked(source / ".desktop-session.lock")
    with ExitStack() as stack:
        names = [".desktop-session.lock", ".library-access.lock", *queue_owner_files(source)]
        lease_roots = [source]
        for relative in (*COORDINATION_ROOTS, "assistant-operations"):
            candidate = source / relative
            try:
                candidate.lstat()
            except FileNotFoundError:
                continue
            checked(candidate, directory=True)
            lease_roots.append(candidate)
        if os.name != "nt":
            names += ["worker" + lane + slot + ".lock" for lane in ("", "-light", "-download") for slot in ("", "-1", "-2", "-3")]
            names += [root.relative_to(source).as_posix() + "/worker.lock" for root in lease_roots[1:]]
        else:
            # Windows workers coordinate through named mutexes, not files.
            from app.worker_lease import worker_lease
            for root in lease_roots:
                slots = [(lane, slot) for lane in ("heavy", "light", "download") for slot in range(4)] if root == source else [("heavy", 0)]
                for lane, slot in slots:
                    if not stack.enter_context(worker_lease(root, blocking=False, lane=lane, slot=slot)):
                        fail("source_busy", "仍有后台或资料编辑进程使用原数据，请关闭它后重新预览。")
        for name in names:
            path = source / name
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            checked(path.parent, directory=True)
            checked(path)
            handle = stack.enter_context(path.open("r+b"))
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fail("source_busy", "原目录仍被其他进程使用，请关闭它后重新预览。")
        yield


def _expected_stage(plan):
    expected = {path: {key: value[key] for key in ("size", "sha256")} for path, value in plan["snapshot"]["files"].items()}
    for item in plan["references"]["files"]:
        if item["operation"] == "remove_consolidated_sidecar":
            expected.pop(item["path"], None)
        else:
            expected[item["path"]] = {"size": item["result_size"], "sha256": item["result_sha256"]}
    for path in plan["references"]["removed_paths"]:
        expected.pop(path, None)
    for item in plan["databases"]:
        expected[item["path"]] = {"size": item["result_size"], "sha256": item["result_sha256"]}
        for path in item["removed_paths"]:
            expected.pop(path, None)
    return expected


def _publish_stage(stage, target):
    """Atomic no-replace publication, including concurrent empty-directory races."""
    if os.name == "nt":
        os.rename(stage, target)  # Windows rename fails if any target exists.
        return
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(stage), os.fsencode(target), 0x00000004)  # RENAME_EXCL
    else:
        rename = getattr(library, "renameat2", None)
        if rename is None:
            fail("atomic_publish_unavailable", "系统不支持安全的独占目录发布。原配置未切换。")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(stage), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
    if result != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            fail("destination_changed", "目标目录已有新内容，复制不会覆盖它。")
        raise OSError(code, os.strerror(code))


def _verify_tree(root, expected, directories):
    actual = inventory(root, strict_stage=True)
    if actual["directories"] != directories or set(actual["files"]) != set(expected):
        fail("stage_changed", "复制结果的文件集合不一致。")
    for path, value in expected.items():
        if any(actual["files"][path][key] != value[key] for key in ("size", "sha256")):
            fail("stage_changed", "复制结果校验失败。")
    return actual


def apply_request(app_root: Path, token: str, digest: str, *, checkpoint=lambda phase: None):
    """Run before backend startup and only after the old process has exited.

    checkpoint is an internal fault-injection seam used by subprocess tests; it
    is never derived from request/CLI/UI input. No source file is written.
    """
    app_root = absolute_directory(app_root)
    directory, plan, previous = _load_request(app_root, token, digest)
    source, target = Path(plan["source"]), Path(plan["destination"])
    stage = target.parent / (".learnnote-migration-" + token)
    receipt = {"version": 1, "status": "copying", "source": str(source), "path": str(target),
               "stage": str(stage), "request_sha256": digest, "previous_config": plan["config"]}
    committed = False
    try:
        with stopped_source_locks(source):
            destination_directory(source, target)
            if _target_identity(target) != plan["target_identity"] or _config(app_root) != previous:
                fail("selection_changed", "目标目录或配置已变化，请重新预览。")
            if _target_identity(source) != plan["source_identity"] or not same_snapshot(plan["snapshot"], inventory(source)):
                fail("source_changed", "关闭期间源数据已变化，请重新预览。原目录仍在使用。")
            stage.mkdir()
            _atomic(directory / "receipt.json", receipt)
            checkpoint("stage_created")
            copy_snapshot(source, stage, plan["snapshot"])
            checkpoint("copied")
            original_files = {path: {key: value[key] for key in ("size", "sha256")} for path, value in plan["snapshot"]["files"].items()}
            _verify_tree(stage, original_files, plan["snapshot"]["directories"])
            apply_reference_changes(stage, plan["references"])
            apply_databases(stage, plan["snapshot"]["files"], plan["databases"])
            expected = _expected_stage(plan)
            _verify_tree(stage, expected, plan["snapshot"]["directories"])
            if not same_snapshot(plan["snapshot"], inventory(source)) or _config(app_root) != previous:
                fail("source_changed", "源数据或配置已变化，切换已取消。")
            checkpoint("verified")
            destination_directory(source, target)
            if _target_identity(target) != plan["target_identity"]:
                fail("destination_changed", "目标目录已被替换。")
            # An empty-directory rename cannot replace a populated destination.
            # Windows requires removing the empty placeholder first.
            stage_identity = _target_identity(stage)
            _verify_tree(stage, expected, plan["snapshot"]["directories"])
            target.rmdir()
            checkpoint("destination_released")
            _publish_stage(stage, target)
            checkpoint("published")
            new_config = json.loads(previous) if previous is not None else {}
            new_config["data_dir"] = str(target)
            config_bytes = _json(new_config)
            receipt.update(status="ready_to_activate", files=expected, changes=plan["references"]["changes"],
                catalog_proof=plan["references"]["catalog_proof"], databases=plan["databases"],
                next_config_sha256=_sha(config_bytes))
            _atomic(directory / "receipt.json", receipt)
            config_temp = app_root / (".learnnote-config-" + token + ".tmp")
            _write_new(config_temp, config_bytes)
            checkpoint("before_config")
            if _target_identity(target) != stage_identity:
                fail("destination_changed", "已校验的复制目录发生变化。")
            _verify_tree(target, expected, plan["snapshot"]["directories"])
            if _config(app_root) != previous or not same_snapshot(plan["snapshot"], inventory(source)):
                fail("source_changed", "激活前源数据或配置已变化。原配置仍保留。")
            config_temp.replace(app_root / "learnnote-config.json")
            committed = True
            checkpoint("activated")
            receipt["status"] = "complete"
            _atomic(directory / "receipt.json", receipt)
    except Exception as exc:
        if not committed:
            receipt.update(status="failed", code=getattr(exc, "code", "migration_failed"),
                message="复制未激活。原数据目录和配置保留；请检查迁移记录并重新预览。")
            try:
                _atomic(directory / "receipt.json", receipt)
            except OSError:
                pass
            raise
        # Atomic config replacement is the commit point. A later receipt I/O
        # failure is recoverable from the ready receipt. Programming errors are
        # still surfaced; they never trigger an automatic config rollback.
        if not isinstance(exc, OSError):
            raise
    return {"ok": True, "path": str(target), "receipt": str(directory / "receipt.json")}


def migration_status(app_root: Path):
    """Read local receipts/config only; never inspect the recorded data paths."""
    root = app_root / ".data-migrations"
    try:
        root.lstat()
    except FileNotFoundError:
        return {"ok": True, "status": "none", "message": ""}
    checked(root, directory=True)
    candidates = []
    for directory in root.iterdir():
        if not re.fullmatch(r"[a-f0-9]{32}", directory.name):
            continue
        checked(directory, directory=True)
        path = directory / "receipt.json"
        try:
            info = checked(path)
        except MigrationError:
            continue
        candidates.append((info.st_mtime_ns, path))
    if not candidates:
        return {"ok": True, "status": "none", "message": ""}
    path = max(candidates, key=lambda item: (item[0], str(item[1])))[1]
    record = json.loads(path.read_bytes())
    config = _config_identity(_config(app_root))
    committed = bool(record.get("next_config_sha256") and config["exists"] and config["sha256"] == record["next_config_sha256"])
    if committed:
        status = "complete"
        message = "复制已校验，配置已切换到目标目录。原目录和原配置备份仍保留。"
    elif record.get("status") == "failed" and record.get("previous_config") == config:
        status = "failed"
        message = "迁移未激活，仍保留原配置。请查看记录，处理原因后选择新的空目录重新预览。"
    elif record.get("status") == "scheduled":
        status = "scheduled"
        message = "迁移已安排，尚无完成记录。请保留原目录；不要在无法确认结果时重复操作。"
    else:
        status = "incomplete"
        message = "迁移或配置状态尚未确认。请保留新旧目录与原配置备份，查看记录后再决定恢复或重新预览。"
    return {"ok": True, "status": status, "source": str(record.get("source", "")),
            "path": str(record.get("path", "")), "receipt": str(path), "message": message}


def fail_scheduled_request(app_root, request):
    """A helper-launch failure consumes the request without activating it."""
    directory, plan, _previous = _load_request(app_root, request["token"], request["digest"])
    _atomic(directory / "receipt.json", {"version": 1, "status": "failed", "source": plan["source"],
        "path": plan["destination"], "previous_config": plan["config"], "request_sha256": request["digest"],
        "code": "helper_not_started"})
