"""Local, source-bound task and course controls with observable receipts."""
from collections import Counter
from datetime import datetime, timezone
import sqlite3

from fastapi import HTTPException

from .assistant_operation_types import CONTROL_TOOLS
from . import courses, course_episodes


def is_control(tool):
    return tool in CONTROL_TOOLS


def task_snapshot(value):
    allowed = ("task_id", "generation", "status", "cancel_requested", "cancellation_requested",
               "queued_job_cancelled", "worker_acknowledged", "callback_finished",
               "dispatch_prevented", "recovery_stopped", "applied_generation",
               "cancellation_operation_id", "operation_applied", "queue_state")
    result = {key: value[key] for key in allowed if key in value}
    result["revision"] = result["generation"]
    return result


def snapshot(source):
    try:
        if source["kind"] == "task_control":
            from .task_control import read_task_control
            return task_snapshot(read_task_control(source["id"]))
        course = courses.get_course(source["id"])
        if (course.get("id") != source["id"] or type(course.get("revision")) is not int
                or type(course.get("paused")) is not bool or not isinstance(course.get("sources"), list)
                or len(course["sources"]) > 200):
            raise ValueError("invalid_course")
        counts = Counter(item["status"] for item in course_episodes.course_episodes(course, read_only=True))
        return {"course_id": course["id"], "title": str(course["title"])[:500], "revision": course["revision"],
                "paused": course["paused"], "source_count": len(course["sources"]),
                "episode_count": sum(counts.values()), "status_counts": dict(counts),
                "observed_at": datetime.now(timezone.utc).isoformat()}
    except FileNotFoundError:
        raise HTTPException(404, "选中的任务或课程已不存在；没有执行操作。") from None
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        raise HTTPException(409, "选中的任务或课程记录暂不可读取，请先恢复；没有执行操作。") from None


def selected_snapshot(source):
    value = snapshot(source)
    if value["revision"] != source["revision"]:
        raise HTTPException(409, "所选任务已进入新一轮或课程已修改，请重新读取状态并预览。")
    return value


def targets(kind):
    if kind == "course":
        items = [{"kind": "course", "id": item["id"], "revision": item["revision"], "title": str(item["title"])[:500]}
                 for item in courses.list_courses() if type(item.get("revision")) is int and item["revision"] >= 1]
    else:
        from .storage import list_tasks_snapshot
        from .task_control import task_generation
        items = [{"kind": "task_control", "id": item.id, "revision": task_generation(item), "title": item.title[:500], "status": item.status}
                 for item in list_tasks_snapshot()]
    return {"targets": items[:200], "truncated": len(items) > 200}


def prepare(value):
    before = selected_snapshot(value["source"])
    if value["tool"] == "cancel_task":
        from .storage import get_task
        if get_task(value["source"]["id"]).awaiting_confirmation:
            raise HTTPException(409, "这项任务仍在等待提交确认，请使用任务面板的取消入口。")
        if before.get("cancel_requested"):
            raise HTTPException(409, "本轮已有取消请求，请读取任务状态核对停止进度。")
        if before.get("status") not in {"queued", "running", "cancelling"}:
            raise HTTPException(409, "本轮任务已经结束，无需再次请求取消。")
    value["control_before"] = before
    notices = {
        "inspect_task": "只读取这一个任务的本机状态，不读取正文、路径或模型设置。",
        "inspect_course": "只读取本课程的状态与数量，不读取来源正文或网址。",
        "cancel_task": "仅请求取消这一轮任务。保留现有文件；不能撤销取消，也不会启动替代任务。已请求取消不代表执行已经停止。",
        "set_course_paused": "暂停仅阻止后续分集准备，不停止已有任务。恢复仅允许准备，不会自动启动处理；可再明确设置相反状态。",
    }
    value["preview"] = {"arguments": value["arguments"], "before": before, "notice": notices[value["tool"]]}


def task_receipt(applied):
    return {"historical_request": {"generation": applied.get("applied_generation"),
                                    "operation_id": applied.get("cancellation_operation_id"),
                                    "recorded": applied.get("operation_applied", False)},
            "observation": task_snapshot(applied), "files_preserved": True, "undo_available": False}


def execute(value, check_cancel):
    source, tool = value["source"], value["tool"]
    selected_snapshot(source)
    if tool.startswith("inspect_"):
        result = {"observation": selected_snapshot(source)}
        check_cancel()
        return result
    if tool == "cancel_task":
        from .task_control import cancel_task_generation, TaskControlConflict
        from .storage import task_state_transaction
        try:
            with task_state_transaction():
                check_cancel()
                applied = cancel_task_generation(source["id"], expected_generation=source["revision"], operation_id=value["id"])
        except TaskControlConflict:
            raise HTTPException(409, "任务状态已改变或不支持本次取消，请刷新状态后重新预览。未取消其他轮次。") from None
        # This observation was read under the mutation lease. A later refresh is
        # a separate read and cannot replace attribution or fail this commit.
        return task_receipt(applied)
    try:
        with courses.course_transaction():
            check_cancel()
            course = courses.set_course_paused(source["id"], source["revision"], value["arguments"]["paused"], value["id"])
    except ValueError:
        raise HTTPException(409, "课程已改变，请重新读取并预览；没有覆盖已有修改。") from None
    return {"revision": course["revision"], "paused": course["paused"],
            "changed": course["control_operation"]["before_paused"] != course["paused"],
            "existing_tasks_unchanged": True, "new_tasks_started": 0}


def recover(value):
    """Reconcile a write marker; never replay an uncertain lifecycle mutation."""
    source = value["source"]
    current = snapshot(source)
    if value["tool"] == "cancel_task":
        if (current.get("cancellation_operation_id") == value["id"]
                and current.get("applied_generation") == source["revision"]):
            from .task_control import cancel_task_generation
            applied = cancel_task_generation(source["id"], expected_generation=source["revision"], operation_id=value["id"])
            return "completed", task_receipt(applied)
        keys = ("generation", "status", "cancel_requested", "cancellation_operation_id", "applied_generation")
        before = value.get("control_before") or {}
        if all(current.get(key) == before.get(key) for key in keys):
            return "prepared", None
    elif value["tool"] == "set_course_paused":
        course = courses.get_course(source["id"])
        marker = course.get("control_operation") or {}
        if (marker.get("id") == value["id"] and marker.get("before_revision") == source["revision"]
                and current["revision"] == source["revision"] + 1
                and marker.get("paused") == value["arguments"]["paused"] == current["paused"]):
            return "completed", {"revision": current["revision"], "paused": current["paused"],
                                  "changed": marker["before_paused"] != current["paused"],
                                  "existing_tasks_unchanged": True, "new_tasks_started": 0}
        if current["revision"] == source["revision"]:
            return "prepared", None
    elif current["revision"] == source["revision"]:
        return "prepared", None
    return "conflict", None
