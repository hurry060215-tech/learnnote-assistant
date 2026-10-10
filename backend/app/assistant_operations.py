"""Execute one reviewed operation and reconcile interrupted local writes."""
from datetime import datetime, timezone
import hashlib
import sqlite3
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from . import assistant_operation_store as store
from .assistant_operation_types import OperationRequest, validated_arguments
from .assistant_note_tools import selected_edition, prepare_edit, read_note, export_note
from .routers.notes import edition_transaction, get_edition, save_edition_locked


class OperationCancelled(Exception):
    pass


def _check_cancel(value):
    if store.cancellation(value["id"]).is_set() or (store.root() / (value["id"] + ".cancel")).exists():
        raise OperationCancelled()


def _record(request, arguments):
    identity = {"tool": request.tool, "source": request.source.model_dump(), "arguments": arguments}
    now = datetime.now(timezone.utc).isoformat()
    return {"schema_version": 1, "id": request.operation_id, **identity, "request_digest": store.digest(identity),
            "status": "prepared", "created_at": now, "updated_at": now}


def prepare(request: OperationRequest):
    arguments = validated_arguments(request.tool, request.arguments)
    value = _record(request, arguments)
    with store.locked():
        existing = store.load(value["id"])
        if existing:
            if existing["request_digest"] != value["request_digest"]:
                raise HTTPException(409, "这个操作 ID 已用于其他内容，请重新创建操作。")
            return store.public(_recover(existing))
        selected_edition(value["source"])
        if request.tool == "edit_note":
            value["edit"], value["preview"] = prepare_edit(value["source"], arguments)
        else:
            value["preview"] = {"arguments": arguments, "notice": "只处理当前保存版本；不会改动原始资料。"}
        store.save(value)  # Failure here must leave the note untouched.
        return store.public(value)


def _recover(value):
    # Absence blocks access, but it is not proof of an intentional deletion.
    # Preserve recovery copies if source metadata was lost or damaged.
    from .storage import get_task
    from .library import get_material
    source = value["source"]
    try:
        if source["kind"] == "task":
            get_task(source["id"])
        else:
            get_material(source["id"])
    except FileNotFoundError:
        raise HTTPException(404, "来源缺失，助手副本暂不可读取；已保留用于恢复。") from None
    except ValueError as exc:
        if source["kind"] == "material" and str(exc) == "material_not_found":
            raise HTTPException(404, "来源缺失，助手副本暂不可读取；已保留用于恢复。") from None
        raise HTTPException(409, "来源元信息损坏，已保留助手记录与撤销副本，请先恢复来源。") from None
    except (OSError, sqlite3.Error):
        raise HTTPException(409, "来源暂不可读取，已保留助手记录与撤销副本，请先恢复来源。") from None
    if value.get("undone_by") and store.load(value["undone_by"]) is None:
        # The parent link is committed before its reserved child record. A
        # crash in that gap must not hide the only usable Undo button forever.
        value.pop("undone_by")
        _save_receipt(value)
    if value["status"] != "running":
        return value
    if value["tool"] == "edit_note":
        source, edit = value["source"], value["edit"]
        with edition_transaction():
            current = get_edition(source["kind"], source["id"])
            if current["revision"] == edit["after_revision"]:
                value.update(status="completed", result={"revision": edit["after_revision"], "changed": edit["before"] != edit["after"], "recovered": True})
            elif current["revision"] == edit["before_revision"]:
                value["status"] = "prepared"
            else:
                value.update(status="conflict", error="正文已有其他修改，保留现状与撤销副本。")
    elif value.get("artifact"):
        artifact = value["artifact"]
        path = store.root() / artifact["name"]
        if path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]:
            value.update(status="completed", result={**artifact, "revision": value["source"]["revision"], "recovered": True})
        else:
            value["status"] = "prepared"
    else:
        value["status"] = "prepared"
    _save_receipt(value)
    return value


def _save_receipt(value):
    try:
        store.save(value)
    except (HTTPException, OSError):
        # The action may already be committed. Its exact result is known now;
        # retain the running record for revision-based recovery on next read.
        value["receipt_warning"] = "实际状态已核对，但回执暂未写入磁盘；请保留操作 ID，恢复磁盘后刷新，勿创建重复操作。"


def get_operation(operation_id: str):
    with store.locked():
        value = store.load(operation_id)
        if not value:
            raise HTTPException(404, "操作不存在。")
        return store.public(_recover(value))


def list_operations():
    with store.locked():
        values = []
        for path in sorted(store.root().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
            try:
                value = store.load(path.stem)
                if value is not None:
                    values.append(store.public(_recover(value)))
            except HTTPException:
                values.append({"id": path.stem, "status": "unavailable", "error": "记录不可读取，原文件已保留。"})
        return values


def _save_artifact(value, artifact):
    _check_cancel(value)
    content = artifact.content
    used = 0
    for path in store.root().iterdir():
        try:
            if path.is_file():
                used += path.stat().st_size
        except FileNotFoundError:
            # Cancellation markers use atomic temp files outside the lease so
            # they can interrupt a running export; a renamed temp is not an IO failure.
            continue
    if len(content) > 32 * 1024 * 1024 or used + len(content) > 64 * 1024 * 1024:
        raise HTTPException(409, "助手导出缓存已达上限，请使用普通导出并保留需要的文件。")
    name = value["id"] + "." + artifact.suffix
    value["artifact"] = {"name": name, "media_type": artifact.media_type,
                         "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "warnings": artifact.warnings}
    store.save(value)
    path = store.root() / name
    temporary = path.with_name("." + name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(content)
        _check_cancel(value)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {**value["artifact"], "revision": value["source"]["revision"]}


def execute(operation_id: str):
    with store.locked():
        value = store.load(operation_id)
        if not value:
            raise HTTPException(404, "操作不存在。")
        value = _recover(value)
        if value["status"] != "prepared":
            return store.public(value)
        try:
            _check_cancel(value)
            selected_edition(value["source"])
            value["status"] = "running"
            store.save(value)
            source = value["source"]
            if value["tool"] == "edit_note":
                with edition_transaction():
                    _check_cancel(value)
                    edit = value["edit"]
                    saved = save_edition_locked(source["kind"], source["id"], edit["after"], edit["before_revision"])
                    value["result"] = {"revision": saved["revision"], "changed": edit["before"] != edit["after"]}
                # A cancellation after this commit cannot pretend the write vanished.
            elif value["tool"] == "read_note":
                value["result"] = read_note(source, value["arguments"])
                _check_cancel(value)
            else:
                value["result"] = _save_artifact(value, export_note(source, value["arguments"]))
            value["status"] = "completed"
        except OperationCancelled:
            value.update(status="cancelled", error="已在提交前取消，没有修改笔记。")
        except HTTPException as exc:
            value.update(status="conflict" if exc.status_code == 409 else "failed", error=exc.detail)
        except Exception:
            # Keep 'running' after an uncertain write; the next read reconciles
            # exact before/after revisions instead of retrying blindly.
            raise HTTPException(503, "操作未能确认完成。请读取操作记录再重试；原始资料保留。") from None
        _save_receipt(value)
        return store.public(value)


def cancel(operation_id: str):
    value = store.load(operation_id)
    if not value:
        raise HTTPException(404, "操作不存在。")
    store.cancellation(operation_id).set()
    from .storage import atomic_write_text
    atomic_write_text(store.root() / (operation_id + ".cancel"), "cancelled")
    with store.locked():
        stored = store.load(operation_id)
        if not stored:
            (store.root() / (operation_id + ".cancel")).unlink(missing_ok=True)
            raise HTTPException(404, "来源或操作记录已删除。")
        value = _recover(stored)
        if value["status"] == "prepared":
            value.update(status="cancelled", error="操作已取消，未修改笔记。")
            store.save(value)
        return store.public(value)


def undo(operation_id: str, target_id: str):
    store.path_for(operation_id)
    with store.locked():
        target = store.load(target_id)
        if not target or _recover(target)["status"] != "completed" or target["tool"] != "edit_note" or target.get("undo_of"):
            raise HTTPException(409, "只有已完成的正文编辑可以撤销。")
        identity = {"undo_of": target_id}
        if target.get("undone_by") not in (None, operation_id):
            raise HTTPException(409, "这次修改已安排撤销，请读取已有撤销操作的状态。")
        value = store.load(operation_id)
        if value:
            if value.get("request_digest") != store.digest(identity):
                raise HTTPException(409, "此操作 ID 已用于其他操作。")
        else:
            edit = target["edit"]
            source = {**target["source"], "revision": edit["after_revision"]}
            selected_edition(source)
            now = datetime.now(timezone.utc).isoformat()
            value = {"schema_version": 1, "id": operation_id, "tool": "edit_note", "source": source,
                     "status": "prepared", "created_at": now, "updated_at": now,
                     "request_digest": store.digest(identity), "undo_of": target_id,
                     "edit": {"before": edit["after"], "after": edit["before"],
                              "before_revision": edit["after_revision"], "after_revision": edit["before_revision"]}}
            target["undone_by"] = operation_id
            store.save(target)
            store.save(value)
    return execute(operation_id)


def artifact_path(operation_id: str):
    with store.locked():
        value = store.load(operation_id)
        if not value or _recover(value)["status"] != "completed" or not value.get("artifact"):
            raise HTTPException(404, "导出文件尚不可用。")
        info = value["artifact"]
        path = store.root() / info["name"]
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
            raise HTTPException(409, "导出文件缺失或已变化，请创建新的导出操作。")
        return path, info


def forget(operation_id: str):
    """Explicitly discard a completed record pair and its local undo/export copies."""
    with store.locked():
        value = store.load(operation_id)
        if not value:
            return {"id": operation_id, "deleted": True}
        owner = store.load(value["undo_of"]) if value.get("undo_of") else value
        records = [owner] if owner else [value]
        if owner and owner.get("undone_by"):
            child = store.load(owner["undone_by"])
            if child:
                records.append(child)
        for record in records:
            recovered = _recover(record) if record["status"] == "running" else record
            if recovered["status"] in {"running", "prepared"}:
                raise HTTPException(409, "请先完成或取消操作，再删除记录。")
        for record in reversed(records):
            store._purge_paths(store.root(), record["id"])
        return {"id": operation_id, "deleted": True, "notice": "已删除本机回执、撤销副本与导出缓存；当前正文未变化。"}
