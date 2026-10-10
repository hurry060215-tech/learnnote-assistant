"""Bounded, resumable read → reviewed edit → verified readback → real export.

Only an explicit HTTP advance can start a model call. A crashed model attempt
stops; interrupted local operations reconcile their existing write marker and
artifact rather than replaying a new operation. Approval time is not charged.
This local slice supports one backend service process. A foreign process owner
fails closed rather than treating process identity as proof a call can replay.
"""
import asyncio
from datetime import datetime, timezone
import time
from uuid import uuid4

from fastapi import HTTPException
from . import assistant_operation_store as journal, assistant_operations as operations
from . import assistant_run_store as store, assistant_run_planner as planner
from .assistant_operation_types import OperationRequest
from .assistant_note_tools import selected_edition
from .routers.notes import edition_transaction, get_edition

MAX_DECISIONS = 8
MAX_ACTIVE_SECONDS = 120
LIMITS = {"runs": store.MAX_RUNS, "model_decisions": MAX_DECISIONS, "edits": 1,
          "active_seconds": MAX_ACTIVE_SECONDS, "model_timeout_seconds": planner.MODEL_TIMEOUT_SECONDS,
          "source_characters": planner.MAX_SOURCE_CHARACTERS, "output_tokens": planner.MAX_OUTPUT_TOKENS,
          "steps": MAX_DECISIONS + 1}
_SESSION = uuid4().hex
_live = set()
_model_calls = {}
_clocks = {}


def _key(run_id):
    return (str(store.root().resolve()), run_id)


def _save(value):
    value["version"] += 1
    store.save(value)


def _elapsed(value):
    if not value.get("active_started_at"):
        return value["active_seconds"]
    origin = _clocks.get(value.get("attempt_id"))
    delta = time.monotonic() - origin if origin is not None else time.time() - value["active_started_at"]
    # Live deadlines cannot be extended by NTP/manual wall-clock changes. The
    # persisted timestamp is only used to account for interrupted local work;
    # interrupted model attempts always stop and are never automatically retried.
    return value["active_seconds"] + max(0, delta)


def _finish(value, status, reason=None):
    value["active_seconds"] = min(100000, _elapsed(value))
    value["active_started_at"] = None
    value.update(status=status, reason=reason)
    _save(value)
    _clocks.pop(value.get("attempt_id"), None)
    return value


def _flag(value):
    path = store.cancellation_path(value["id"])
    if path.exists():
        try:
            reason = path.read_text(encoding="utf-8")
        except OSError:
            reason = "cancel_requested"
        return reason if reason in {"cancel_requested", "active_timeout", "request_interrupted"} else "cancel_requested"
    if _elapsed(value) >= MAX_ACTIVE_SECONDS:
        return "active_timeout"
    return None


def _stop_flag(value):
    reason = _flag(value)
    if reason:
        _finish(value, "cancelled" if reason == "cancel_requested" else "stopped", reason)
        return True
    return False


def _current(value):
    current = selected_edition(value["source"])
    if current.get("write_id") != value.get("expected_write_id"):
        raise HTTPException(409, "笔记有后续保存，请创建新的任务。")
    if len(current["text"]) > planner.MAX_SOURCE_CHARACTERS:
        raise HTTPException(422, "当前正文超出 24000 字符范围，任务已停止。")
    return current


def _operation(step, value, *, recover=False):
    operation = journal.load(step["operation_id"])
    if not operation:
        return None
    if (operation["tool"] != step["tool"] or operation.get("undo_of")
            or any(operation["source"][k] != value["source"][k] for k in ("kind", "id"))):
        raise HTTPException(409, "任务引用的操作记录不匹配。")
    return operations._recover(operation) if recover else operation


def _public(value):
    # Hydrated receipts include the user's goal and saved note text. Keep the
    # availability check and projection under the same source-deletion lease.
    with journal.locked():
        _required(value["id"])
        return _public_available(value)


def _pending_receipt(value, reason):
    # A noninterruptible worker owns the edition lease. Return only control
    # state promptly, without exposing source/goal/body while cleanup may race.
    return {"id": value["id"], "version": value["version"], "status": "executing",
            "reason": reason, "steps": [], "pending_operation": None,
            "edit_operation_id": None, "artifact_operation_id": None, "limits": LIMITS}


def _public_available(value):
    result = {key: value.get(key) for key in ("id", "version", "status", "source", "question", "edit_operation_id",
              "artifact_operation_id", "reason", "created_at", "updated_at", "active_seconds", "model_attempts")}
    result.update(limits=LIMITS, steps=[], pending_operation=None)
    for step in value["steps"]:
        item = {key: step[key] for key in ("step_id", "operation_id", "tool", "status", "verification", "readback") if key in step}
        operation = _operation(step, value)
        if operation:
            item["status"] = operation["status"]
            if "result" in operation:
                item["result"] = operation["result"]
            if operation.get("receipt_warning"):
                item["receipt_warning"] = operation["receipt_warning"]
            if value["pending_operation_id"] == operation["id"]:
                result["pending_operation"] = journal.public(operation)
        result["steps"].append(item)
    return result


def _required(run_id):
    value = store.load(run_id)
    if not value:
        raise HTTPException(404, "连续任务不存在。")
    # Missing source metadata never exposes saved goals or old result copies.
    try:
        get_edition(value["source"]["kind"], value["source"]["id"])
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(404, "来源缺失，连续任务暂不可读取。") from None
        raise
    return value


def create(request):
    with journal.locked(), edition_transaction():
        selected = planner.connection(request.options)
        identity = {"question": request.question, "initial_source": request.source.model_dump(),
                    "connection_fingerprint": selected["fingerprint"]}
        existing = store.load(request.run_id)
        if existing:
            if existing["request_digest"] != journal.digest(identity):
                raise HTTPException(409, "此任务 ID 已用于其他目标、来源或模型。")
            return _public(_recover(_required(request.run_id)))
        current = selected_edition(identity["initial_source"])
        if len(current["text"]) > planner.MAX_SOURCE_CHARACTERS:
            raise HTTPException(422, "正文超出 24000 字符范围，不会偷偷截断或发送。")
        now = datetime.now(timezone.utc).isoformat()
        value = {"schema_version": 1, "id": request.run_id, **identity, "request_digest": journal.digest(identity),
                 "source": dict(identity["initial_source"]), "expected_write_id": current.get("write_id"),
                 "status": "ready", "version": 1, "created_at": now, "updated_at": now,
                 "active_seconds": 0.0, "active_started_at": None, "model_attempts": 0,
                 "steps": [], "pending_operation_id": None, "edit_operation_id": None,
                 "artifact_operation_id": None, "reason": None, "attempt_id": None, "owner": None}
        store.save(value)
        return _public(value)


def _new_step(value, tool, *, readback=False):
    step = {"step_id": uuid4().hex, "operation_id": uuid4().hex, "tool": tool, "status": "planned"}
    if readback:
        step["readback"] = True
    value["steps"].append(step)
    value["status"] = "executing"
    _save(value)  # Durable identity exists before prepare/execute.
    return step


def _readback(value, edit_operation):
    edit = edit_operation["edit"]
    current = get_edition(value["source"]["kind"], value["source"]["id"])
    if (current["text"] != edit["after"] or current["revision"] != edit["after_revision"]
            or current.get("write_id") != edit_operation["id"]):
        return _finish(value, "stopped", "readback_mismatch")
    value["source"]["revision"] = current["revision"]
    value["expected_write_id"] = current["write_id"]
    value["pending_operation_id"] = None
    if _stop_flag(value):
        return value
    step = next((s for s in value["steps"] if s.get("readback")), None)
    if step is None:
        step = _new_step(value, "read_note", readback=True)
        operations.prepare(OperationRequest(operation_id=step["operation_id"], source=value["source"], tool="read_note",
                                            arguments={"start_line": 1, "line_count": 200}))
    operation = _operation(step, value, recover=True)
    if operation is None:
        return _finish(value, "stopped", "interrupted_readback")
    if operation["status"] == "prepared":
        operations.execute(operation["id"])
        operation = _operation(step, value, recover=True)
    step["status"] = operation["status"]
    current = _current(value)
    if (operation["status"] != "completed" or current["text"] != edit["after"]
            or operation["result"]["revision"] != edit["after_revision"]
            or operation["result"].get("text") != "\n".join(edit["after"].splitlines()[:200])[:24000]):
        return _finish(value, "stopped", "readback_mismatch")
    step["verification"] = {"revision": current["revision"], "write_id": current["write_id"],
                            "text_sha256": journal.digest(current["text"])}
    if _stop_flag(value):
        return value
    return _finish(value, "ready")


def _settle(value, step, operation):
    step["status"] = operation["status"]
    if operation["status"] != "completed":
        if not _stop_flag(value):
            _finish(value, "stopped" if operation["status"] in {"conflict", "cancelled"} else "failed",
                    "operation_" + operation["status"])
        return value
    if step["tool"] == "edit_note":
        return _readback(value, operation)
    _current(value)
    if step["tool"] == "export_note":
        # File bytes, hash and source version must really exist before success.
        operations.artifact_path(operation["id"])
        if operation["result"]["revision"] != value["source"]["revision"]:
            return _finish(value, "stopped", "export_revision_mismatch")
        value["artifact_operation_id"] = operation["id"]
        if not _stop_flag(value):
            _finish(value, "completed")
    elif not _stop_flag(value):
        _finish(value, "ready")
    return value


def _recover(value):
    if value["status"] == "completed":
        try:
            operations.artifact_path(value["artifact_operation_id"])
        except HTTPException:
            return _finish(value, "stopped", "artifact_unavailable")
        return value
    if value["status"] == "planning" and _stop_flag(value):
        _live.discard(value["attempt_id"])
        return value
    if value["status"] not in {"planning", "executing"} or (value["owner"] == _SESSION and value["attempt_id"] in _live):
        return value
    if value["status"] == "planning":
        return _finish(value, "stopped", "interrupted_model_attempt")
    try:
        with edition_transaction():
            step = value["steps"][-1] if value["steps"] else None
            operation = _operation(step, value, recover=True) if step else None
            if not operation or operation["status"] != "completed":
                return _finish(value, "stopped", "interrupted_operation")
            if step.get("readback"):
                edit_step = next(s for s in value["steps"] if s["tool"] == "edit_note")
                return _readback(value, _operation(edit_step, value, recover=True))
            return _settle(value, step, operation)
    except HTTPException:
        return _finish(value, "stopped", "recovery_conflict")


def get(run_id):
    with journal.locked():
        return _public(_recover(_required(run_id)))


def list_runs():
    with journal.locked():
        result = []
        for path in sorted(store.root().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:store.MAX_RUNS]:
            try:
                result.append(_public(_recover(_required(path.stem))))
            except HTTPException:
                result.append({"id": path.stem, "status": "unavailable", "reason": "record_or_source_unavailable"})
        return {"runs": result, "limits": LIMITS}


def _begin(run_id, expected_version, options):
    with journal.locked(), edition_transaction():
        value = _recover(_required(run_id))
        if value["version"] != expected_version or value["status"] != "ready":
            return value, None
        if _stop_flag(value):
            return value, None
        if value["model_attempts"] >= MAX_DECISIONS:
            return _finish(value, "stopped", "decision_limit"), None
        try:
            _current(value)
        except HTTPException:
            return _finish(value, "stopped", "source_changed"), None
        selected = planner.connection(options)
        if selected["fingerprint"] != value["connection_fingerprint"]:
            return _finish(value, "stopped", "connection_changed"), None
        try:
            receipts = [(step, _operation(step, value, recover=True)) for step in value["steps"]]
            if any(operation is None for _, operation in receipts):
                return _finish(value, "stopped", "operation_record_missing"), None
            history = planner.messages(value, receipts)
        except (ValueError, HTTPException):
            return _finish(value, "stopped", "source_output_limit_or_missing_receipt"), None
        value.update(status="planning", attempt_id=uuid4().hex, owner=_SESSION, active_started_at=time.time())
        value["model_attempts"] += 1
        _save(value)  # A retry/restart sees this attempt, never calls twice.
        _live.add(value["attempt_id"])
        _clocks[value["attempt_id"]] = time.monotonic()
        return value, (selected, history)


def _stop_attempt(run_id, attempt_id, reason):
    _live.discard(attempt_id)
    try:
        with journal.locked():
            value = _required(run_id)
            if value["attempt_id"] == attempt_id and value["status"] == "executing":
                return _public(_recover(value))
            if value["attempt_id"] == attempt_id and value["status"] in {"planning", "executing"}:
                if not _stop_flag(value):
                    _finish(value, "stopped" if reason in {"model_timeout", "request_interrupted"} else "failed", reason)
            return _public(value)
    finally:
        _clocks.pop(attempt_id, None)


def _apply_decision(run_id, attempt_id, decision):
    try:
        with journal.locked(), edition_transaction():
            value = _required(run_id)
            if value["attempt_id"] != attempt_id or value["status"] != "planning":
                return _public(value)
            if _stop_flag(value):
                return _public(value)
            _current(value)
            if decision is None:
                return _public(_finish(value, "stopped", "no_action"))
            tool = decision["tool"]
            has_read = any(s["tool"] == "read_note" and s["status"] == "completed" for s in value["steps"])
            if tool != "read_note" and not has_read:
                return _public(_finish(value, "stopped", "read_required"))
            if tool == "edit_note" and value["edit_operation_id"]:
                return _public(_finish(value, "stopped", "edit_limit"))
            if tool == "export_note" and value["edit_operation_id"] and not any(s.get("verification") for s in value["steps"]):
                return _public(_finish(value, "stopped", "verified_readback_required"))
            step = _new_step(value, tool)
            prepared = operations.prepare(OperationRequest(operation_id=step["operation_id"], source=value["source"],
                                                           tool=tool, arguments=decision["arguments"]))
            step["status"] = prepared["status"]
            if tool == "edit_note":
                value["edit_operation_id"] = step["operation_id"]
                value["pending_operation_id"] = step["operation_id"]
                raw = _operation(step, value)
                if len(raw["edit"]["after"]) > planner.MAX_SOURCE_CHARACTERS:
                    operations.cancel(step["operation_id"])
                    _finish(value, "stopped", "edited_source_limit")
                elif _stop_flag(value):
                    operations.cancel(step["operation_id"])
                else:
                    _finish(value, "awaiting_approval")
            else:
                if not _stop_flag(value):
                    operations.execute(step["operation_id"])
                    _settle(value, step, _operation(step, value, recover=True))
            return _public(value)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        return _stop_attempt(run_id, attempt_id, "source_or_operation_conflict" if exc.status_code in {409, 422} else "operation_failed")
    except Exception:
        # Leave durable execution identity for recovery; never repeat model work.
        return _stop_attempt(run_id, attempt_id, "operation_unconfirmed")
    finally:
        _live.discard(attempt_id)
        _clocks.pop(attempt_id, None)


def signal_cancel(run_id, reason="cancel_requested"):
    value = store.load(run_id)
    if not value:
        raise HTTPException(404, "连续任务不存在。")
    if value["status"] in store.TERMINAL:
        return value
    journal.atomic_write_text(store.cancellation_path(run_id), reason)
    # No journal/edition lease is needed to interrupt an ongoing provider or
    # signal cancellation during an exporter's noninterruptible local section.
    if value["steps"]:
        journal.cancellation(value["steps"][-1]["operation_id"]).set()
    call = _model_calls.get(_key(run_id))
    if call:
        loop, task = call
        loop.call_soon_threadsafe(task.cancel)
    return value


async def _wait_local(run_id, task, remaining, disconnected=None):
    try:
        deadline = asyncio.get_running_loop().time() + max(0.001, remaining)
        reason = "active_timeout"
        while True:
            left = deadline - asyncio.get_running_loop().time()
            done, _ = await asyncio.wait({task}, timeout=max(0, min(left, 0.05) if disconnected else left))
            if done:
                return task.result()
            if disconnected and await disconnected():
                reason = "request_interrupted"
                break
            if asyncio.get_running_loop().time() >= deadline:
                break
        signal_cancel(run_id, reason)
        # The worker will persist the actual partial outcome when its local
        # section finishes. Do not block the HTTP deadline or claim rollback.
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        value = store.load(run_id)
        if value is None:
            raise HTTPException(404, "连续任务不存在。")
        return _pending_receipt(value, reason + "_pending_receipt")
    except asyncio.CancelledError:
        signal_cancel(run_id, "request_interrupted")
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        raise


async def advance(run_id, request, disconnected=None):
    try:
        value, context = await asyncio.to_thread(_begin, run_id, request.expected_version, request.options)
    except asyncio.CancelledError:
        signal_cancel(run_id, "request_interrupted")
        raise
    if context is None:
        return await asyncio.to_thread(_public, value)
    attempt = value["attempt_id"]
    remaining = MAX_ACTIVE_SECONDS - _elapsed(value)
    timeout = min(planner.MODEL_TIMEOUT_SECONDS, remaining)
    async def guarded_decision():
        # _begin can wait for another local write. A dropped/cancelled request
        # while it waits must never send the subsequently prepared prompt.
        if disconnected and await disconnected():
            signal_cancel(run_id, "request_interrupted")
        stored = store.load(run_id)
        if (stored is None or stored["status"] != "planning" or stored["attempt_id"] != attempt
                or _flag(stored)):
            raise asyncio.CancelledError()
        return await planner.decide(*context, timeout=max(0.001, timeout))
    call = asyncio.create_task(guarded_decision())
    _model_calls[_key(run_id)] = (asyncio.get_running_loop(), call)
    async def watch_disconnect():
        while not call.done():
            if disconnected and await disconnected():
                signal_cancel(run_id, "request_interrupted")
                return
            if _flag(value):
                call.cancel()
                return
            await asyncio.sleep(0.05)
    watcher = asyncio.create_task(watch_disconnect())
    try:
        decision = await asyncio.wait_for(call, timeout=max(0.001, timeout))
    except asyncio.TimeoutError:
        return await asyncio.to_thread(_stop_attempt, run_id, attempt, "model_timeout")
    except asyncio.CancelledError:
        if not _flag(value):
            signal_cancel(run_id, "request_interrupted")
        return await asyncio.shield(asyncio.to_thread(_stop_attempt, run_id, attempt, "request_interrupted"))
    except Exception:
        return await asyncio.to_thread(_stop_attempt, run_id, attempt, "invalid_model_result")
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        if _model_calls.get(_key(run_id), (None, None))[1] is call:
            _model_calls.pop(_key(run_id), None)
    task = asyncio.create_task(asyncio.to_thread(_apply_decision, run_id, attempt, decision))
    return await _wait_local(run_id, task, MAX_ACTIVE_SECONDS - _elapsed(value), disconnected)


def _approve(run_id, request):
    attempt = None
    try:
        with journal.locked(), edition_transaction():
            value = _recover(_required(run_id))
            if value["version"] != request.expected_version or value["status"] != "awaiting_approval":
                return _public(value)
            if request.operation_id != value["pending_operation_id"]:
                raise HTTPException(409, "批准的操作与当前差异不匹配。")
            if _stop_flag(value):
                return _public(value)
            try:
                _current(value)
            except HTTPException:
                return _public(_finish(value, "stopped", "source_changed"))
            attempt = uuid4().hex
            value.update(status="executing", active_started_at=time.time(), attempt_id=attempt, owner=_SESSION)
            _save(value)
            _live.add(attempt)
            _clocks[attempt] = time.monotonic()
            step = next(s for s in value["steps"] if s["operation_id"] == request.operation_id)
            operations.execute(request.operation_id)
            _settle(value, step, _operation(step, value, recover=True))
            return _public(value)
    except HTTPException:
        if attempt:
            return _stop_attempt(run_id, attempt, "operation_unconfirmed")
        raise
    finally:
        if attempt:
            _live.discard(attempt)
            _clocks.pop(attempt, None)


async def approve(run_id, request, disconnected=None):
    value = await asyncio.to_thread(_required, run_id)
    if disconnected and await disconnected():
        signal_cancel(run_id, "request_interrupted")
    task = asyncio.create_task(asyncio.to_thread(_approve, run_id, request))
    return await _wait_local(run_id, task, MAX_ACTIVE_SECONDS - _elapsed(value), disconnected)


def cancel(run_id):
    value = signal_cancel(run_id)
    if value["status"] in store.TERMINAL:
        return _public(value)
    # A live operation owns the lease. Its worker observes the durable marker
    # and settles truthfully; cancel must remain available meanwhile.
    if value["status"] == "executing" and value["attempt_id"] in _live:
        return _pending_receipt(value, "cancel_requested")
    with journal.locked():
        value = _recover(_required(run_id))
        if value["status"] not in store.TERMINAL:
            if value["pending_operation_id"]:
                operations.cancel(value["pending_operation_id"])
            _finish(value, "cancelled", "cancel_requested")
        return _public(value)


def forget(run_id):
    with journal.locked():
        value = store.load(run_id)
        if not value:
            return {"id": run_id, "deleted": True}
        if operations._source_metadata_missing(value["source"]):
            signal_cancel(run_id)
            store.purge(run_id)
            return {"id": run_id, "deleted": True}
        value = _recover(value)
        if value["status"] not in store.TERMINAL:
            raise HTTPException(409, "请先取消或完成任务，再删除记录。")
        # Operation receipts/undo are explicitly managed by the existing API.
        store.purge(run_id)
        return {"id": run_id, "deleted": True, "notice": "连续任务记录已删除；操作回执、单次编辑撤销与导出缓存仍在操作记录中。"}
