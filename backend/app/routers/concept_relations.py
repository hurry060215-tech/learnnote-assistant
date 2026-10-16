"""Explicit read-only local generation, export and offline preview."""
import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ..concept_relation_sources import capture_relations
from ..concept_relation_snapshot import MAX_BYTES, verify_relation_snapshot
from .graph_snapshot import _unique_object

concept_relation_router = APIRouter(prefix="/api/concept-relations", tags=["concept-relations"])


def _error(exc):
    messages = {
        "concept_relations_too_large": "本地图谱超过上限（1,000 个来源、10,000 条出处、单条 24,000 字符、总计 200 万字符、10,000 条关系或 20 MB）。请选择较小课程；未返回截断结果。",
        "concept_relation_index_unavailable": "本地出处索引不可用。请先使用资料库索引恢复或从本机任务重建；本次没有修改索引。",
        "concept_relation_snapshot_invalid": "图谱文件格式、出处或关系与重建结果不一致，未打开；本机资料未修改。",
        "concept_relations_changed_reload_required": "来源或索引已变化，请重新生成本地图谱。",
        "course_changed_reload_required": "课程已变化，请刷新后重新生成。",
        "concept_history_invalid": "本课程含义分组记录损坏，已保留原文件；请先核对历史备份。",
        "invalid_comparison_filter": "来源或时间筛选无效，请检查起点和终点。",
        "invalid_comparison_query": "图谱关键词不能超过 200 字符。",
    }
    code = str(exc) if str(exc) in messages else "concept_relation_index_unavailable"
    return HTTPException(status_code=413 if code == "concept_relations_too_large" else 409, detail={"code": code, "message": messages[code]})


@concept_relation_router.get("")
def local_concept_relations(course_id: str = Query(default="", pattern=r"^(?:[a-f0-9]{32})?$"), revision: int | None = Query(default=None, ge=1),
                            q: str = Query(default="", max_length=200), source_id: str = Query(default="", max_length=128),
                            source_kind: Literal["", "task", "material"] = "", start: float | None = Query(default=None, ge=0), end: float | None = Query(default=None, ge=0)):
    try:
        return capture_relations(course_id=course_id, revision=revision, query=q, source_id=source_id, source_kind=source_kind, start=start, end=end)
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, AttributeError) as exc:
        raise _error(exc) from exc


@concept_relation_router.post("/preview")
async def preview_concept_relations(request: Request):
    try:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BYTES + 100:
                raise ValueError("concept_relations_too_large")
            body.extend(chunk)
        value = json.loads(body, object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or set(value) != {"snapshot"}:
            raise ValueError("concept_relation_snapshot_invalid")
        return verify_relation_snapshot(value["snapshot"])
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _error(exc if str(exc) == "concept_relations_too_large" else ValueError("concept_relation_snapshot_invalid")) from exc
