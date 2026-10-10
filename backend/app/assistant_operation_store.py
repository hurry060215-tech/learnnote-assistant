"""Bounded local operation records; no provider credentials or model prompts."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading

from fastapi import HTTPException
from .config import DATA_DIR
from .worker_lease import worker_lease, has_worker_lease
from .assistant_run_persistence import atomic_write_text, digest

_lock = threading.RLock()
_cancelled: dict[str, threading.Event] = {}
MAX_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 3 * 1024 * 1024
HEADROOM = 256 * 1024
MAX_SLOTS = 64


def root(data_dir=None) -> Path:
    path = (DATA_DIR if data_dir is None else data_dir) / "assistant-operations"
    if path.is_symlink():
        raise HTTPException(409, "操作记录目录不可用，请核对实际状态。")
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_for(operation_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", operation_id):
        raise HTTPException(422, "操作 ID 无效。")
    path = root() / (operation_id + ".json")
    if path.is_symlink():
        raise HTTPException(409, "操作记录不可用，请核对实际状态。")
    return path


@contextmanager
def locked(data_dir=None):
    with _lock:
        directory = root(data_dir)
        if has_worker_lease(directory, "heavy"):
            yield
            return
        with worker_lease(directory) as acquired:
            if not acquired:
                raise HTTPException(409, "操作记录正忙，请重试。")
            # No other operation writer is live while this lease is held.
            # Interrupted atomic writes are private copies, not user backups.
            for path in directory.iterdir():
                if re.fullmatch(r"\.[A-Za-z0-9_-]{8,64}\.(json|md|docx|pdf|html)\.[0-9a-f]{32}\.tmp", path.name):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        raise HTTPException(503, "助手暂存副本无法清理，请恢复本机存储后重试。") from None
            yield


def load(operation_id: str):
    path = path_for(operation_id)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            raise ValueError("oversized_record")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or value.get("id") != operation_id:
            raise ValueError("invalid_record")
        from .assistant_operation_types import SourceRef, validated_arguments
        SourceRef.model_validate(value["source"])
        _allocation(value)
        if value["tool"] not in {"read_note", "edit_note", "export_note"} or value["status"] not in {"prepared", "running", "completed", "failed", "cancelled", "conflict"}:
            raise ValueError("invalid_operation")
        if value.get("undo_of"):
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value["undo_of"]):
                raise ValueError("invalid_undo")
            identity = {"undo_of": value["undo_of"]}
        else:
            arguments = validated_arguments(value["tool"], value["arguments"])
            identity = {"source": value["source"], "tool": value["tool"], "arguments": arguments}
        if digest(identity) != value["request_digest"]:
            raise ValueError("changed_request")
        if value["tool"] == "edit_note":
            edit = value["edit"]
            if (digest(edit["before"]) != edit["before_revision"] or digest(edit["after"]) != edit["after_revision"]
                    or edit["before_revision"] != value["source"]["revision"]):
                raise ValueError("changed_edit")
            if "after_write_id" in edit and (edit["after_write_id"] != operation_id
                    or "before_write_id" not in edit
                    or (edit["before_write_id"] is not None and (not isinstance(edit["before_write_id"], str)
                        or re.fullmatch(r"[A-Za-z0-9_-]{8,64}", edit["before_write_id"]) is None))):
                raise ValueError("changed_edit_marker")
        if value.get("artifact"):
            artifact = value["artifact"]
            if (artifact["name"] not in {operation_id + "." + suffix for suffix in ("md", "docx", "pdf", "html")}
                    or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])):
                raise ValueError("invalid_artifact")
        return value
    except (ValueError, OSError, TypeError, AttributeError, KeyError) as exc:
        raise HTTPException(409, "操作记录损坏，已保留原文件；请先恢复备份。") from exc


def _encoded(value):
    return json.dumps(value, ensure_ascii=False)


def _allocation(value):
    capacity = value.get("record_capacity")
    if not isinstance(capacity, int) or not HEADROOM <= capacity <= MAX_RECORD_BYTES:
        raise HTTPException(409, "操作记录配额信息不可用，已保留原文件。")
    return capacity * (2 if value["tool"] == "edit_note" and not value.get("undo_of") else 1)


def save(value):
    path = path_for(value["id"])
    value["updated_at"] = datetime.now(timezone.utc).isoformat()
    if not path.exists():
        if value.get("undo_of"):
            owner = load(value["undo_of"])
            if (not owner or owner.get("undo_of") or owner.get("undone_by") != value["id"]
                    or owner["tool"] != "edit_note"):
                raise HTTPException(409, "撤销预留记录不匹配，未执行撤销。")
            value["record_capacity"] = owner["record_capacity"]
        else:
            capacity = len(_encoded(value).encode("utf-8")) + HEADROOM
            if capacity > MAX_RECORD_BYTES:
                raise HTTPException(422, "本次操作的撤销副本超出单条记录范围；请缩小修改或使用正文编辑器。")
            value["record_capacity"] = capacity
            records = [load(p.stem) for p in root().glob("*.json")]
            owners = [item for item in records if not item.get("undo_of")]
            slots = sum(2 if item["tool"] == "edit_note" else 1 for item in owners)
            needed = 2 if value["tool"] == "edit_note" else 1
            if slots + needed > MAX_SLOTS or sum(_allocation(item) for item in owners) + _allocation(value) > MAX_BYTES:
                raise HTTPException(409, "本机助手记录已达上限，未接受新操作。已接受操作的完成与一次撤销空间仍保留；可删除不再需要的操作记录。")
    text = _encoded(value)
    # Existing records use their reserved capacity even if other operations fill
    # the quota. This applies equally to terminal receipts and crash recovery.
    if len(text.encode("utf-8")) > value["record_capacity"]:
        raise HTTPException(409, "操作记录超出预留空间，请核对实际状态；不会重复执行。")
    try:
        atomic_write_text(path, text)
    except OSError:
        raise HTTPException(503, "操作记录暂时无法保存，请核对状态后重试。原始资料保留。") from None


def _purge_paths(directory, operation_id):
    # Only deterministic app-owned names, never paths taken from stored JSON.
    for suffix in ("md", "docx", "pdf", "html", "cancel", "json"):
        (directory / (operation_id + "." + suffix)).unlink(missing_ok=True)
    _cancelled.pop(operation_id, None)


@contextmanager
def source_deletion(kind, source_id, data_dir):
    """Take the operation lock BEFORE source locks; deletion removes its copies."""
    with locked(data_dir):
        from . import assistant_run_store
        run_ids = assistant_run_store.matching_sources(kind, source_id, data_dir)
        directory = root(data_dir)
        matches = []
        for path in directory.glob("*.json"):
            try:
                if path.is_symlink() or path.stat().st_size > MAX_RECORD_BYTES:
                    raise ValueError("invalid_record")
                value = json.loads(path.read_text(encoding="utf-8"))
                source = value["source"]
                if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", path.stem):
                    raise ValueError("invalid_id")
                if source["kind"] == kind and source["id"] == source_id:
                    matches.append(path.stem)
            except (OSError, ValueError, TypeError, KeyError):
                raise HTTPException(409, "助手记录损坏，无法确认关联副本；请先恢复记录后删除来源。来源尚未删除。") from None
        yield
        try:
            for operation_id in matches:
                _purge_paths(directory, operation_id)
            for run_id in run_ids:
                assistant_run_store.purge(run_id, data_dir)
        except OSError:
            raise HTTPException(503, "来源已删除，但关联助手副本清理未完成；请保留此提示并重试清理。") from None


def cancellation(operation_id: str) -> threading.Event:
    # The maximum count follows the persisted record cap; entries are reused.
    return _cancelled.setdefault(operation_id, threading.Event())


def public(value):
    return {key: value[key] for key in ("id", "tool", "source", "status", "created_at", "updated_at",
            "preview", "result", "error", "undo_of", "undone_by", "receipt_warning") if key in value}
