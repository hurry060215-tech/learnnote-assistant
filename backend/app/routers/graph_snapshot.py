"""Read-only export/preview endpoints; preview never consults the catalog."""
import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ..course_graph_export import capture_graph_snapshot
from ..graph_snapshot import MAX_BYTES, verify_snapshot

graph_snapshot_router = APIRouter()


def snapshot_error(exc):
    code = str(exc)
    messages = {
        "graph_snapshot_too_large": "快照超过本地上限（20 MB、200 个来源、10,000 条出处、20,000 条关系或 100 MB 分组文本扫描量）。请缩小课程或关键词范围后重试；未导出截断的图。",
        "graph_snapshot_invalid": "快照格式、出处归属、摘要校验或图关系不一致，未打开。仅支持 LearnNote 当前筛选图快照；本机资料与分组均未修改。",
        "course_changed_reload_required": "课程或分组已变化，请重新打开课程并查找后再导出。",
        "concept_history_invalid": "含义分组记录损坏，未导出；已有文件未修改。",
        "invalid_comparison_filter": "筛选范围无效，请检查来源、起点和终点。",
        "invalid_comparison_query": "请输入 1 至 200 字的对照关键词。",
    }
    if code not in messages:
        code = "graph_snapshot_unavailable"
    return HTTPException(status_code=413 if code == "graph_snapshot_too_large" else 409,
                         detail={"code": code, "message": messages.get(code, "当前图快照不可用，请检查课程及本机资料索引。未修改任何资料。")})


@graph_snapshot_router.get("/{course_id}/graph-snapshot")
def export_graph_snapshot(course_id: str, q: str = Query(min_length=1, max_length=200), revision: int = Query(ge=1),
                          source_id: str = Query(default="", max_length=128), source_kind: Literal["", "task", "material"] = "",
                          start: float | None = Query(default=None, ge=0), end: float | None = Query(default=None, ge=0)):
    try:
        return capture_graph_snapshot(course_id, q, revision, source_id=source_id, source_kind=source_kind, start=start, end=end)
    except (ValueError, OSError, sqlite3.Error, TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise snapshot_error(exc) from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("graph_snapshot_invalid")
        result[key] = value
    return result


@graph_snapshot_router.post("/graph-snapshot/preview")
async def preview_graph_snapshot(request: Request):
    try:
        body = bytearray()
        async for chunk in request.stream():
            # Small wrapper allowance; the snapshot itself has the exact cap.
            if len(body) + len(chunk) > MAX_BYTES + 100:
                raise ValueError("graph_snapshot_too_large")
            body.extend(chunk)
        value = json.loads(body, object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or set(value) != {"snapshot"}:
            raise ValueError("graph_snapshot_invalid")
        return verify_snapshot(value["snapshot"])
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise snapshot_error(exc if str(exc) == "graph_snapshot_too_large" else ValueError("graph_snapshot_invalid")) from exc
