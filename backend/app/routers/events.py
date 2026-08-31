"""Reconnectable server-sent task progress stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..observability import read_task_events_after
from ..storage import get_task


events_router = APIRouter(prefix="/api/tasks", tags=["events"])
TERMINAL_STATUSES = {"success", "failed", "cancelled"}


def sse_frame(event_id: int, event: str, payload: dict[str, Any]) -> str:
    """Encode one standards-compliant SSE frame using JSON data."""

    safe_event = "".join(character for character in str(event or "task_event") if character.isalnum() or character in {"_", "-"})
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {max(0, int(event_id))}\nevent: {safe_event or 'task_event'}\ndata: {body}\n\n"


async def task_event_stream(task_id: str, cursor: int = 0) -> AsyncIterator[str]:
    next_index = max(0, int(cursor))
    idle_ticks = 0
    while True:
        events = read_task_events_after(task_id, next_index, 2000)
        for event_id, item in events:
            next_index = event_id
            idle_ticks = 0
            yield sse_frame(event_id, str(item.get("event") or "task_event"), item)

        try:
            task = get_task(task_id)
        except FileNotFoundError:
            yield sse_frame(next_index, "task_missing", {"task_id": task_id})
            return
        if task.status in TERMINAL_STATUSES:
            yield sse_frame(next_index, "task_terminal", {
                "task_id": task.id,
                "status": task.status,
                "phase": task.phase,
                "progress": task.progress,
            })
            return

        idle_ticks += 1
        if idle_ticks >= 20:
            idle_ticks = 0
            yield ": heartbeat\n\n"
        await asyncio.sleep(0.75)


@events_router.get("/{task_id}/events/stream")
def api_task_event_stream(
    task_id: str,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    try:
        get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    cursor = after
    if last_event_id and last_event_id.isdigit():
        cursor = max(cursor, int(last_event_id))
    return StreamingResponse(
        task_event_stream(task_id, cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["api_task_event_stream", "events_router", "sse_frame", "task_event_stream"]
