"""Separate opt-in synthesis endpoints; /ask remains local excerpt retrieval."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .. import course_synthesis

course_synthesis_router = APIRouter()


class CourseSynthesisPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=1000)
    revision: int = Field(ge=1)
    mode: Literal["question", "summary"] = "question"
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=300)


class CourseSynthesisAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    preview_id: str = Field(min_length=32, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    share_source: StrictBool


_MESSAGES = {
    "course_consent_required": "请先预览发送内容并明确同意分享原文。",
    "course_model_changed": "所选模型地址或模型已变化，请重新预览。",
    "course_model_unavailable": "所选模型连接不可用，请先保存有效的连接。",
    "course_preview_expired": "这次预览已使用或过期，请重新预览并确认。",
    "course_preview_stale": "课程原文或模型连接已变化，本次结果已丢弃，请重新预览。",
    "course_synthesis_running": "这门课程已有一次 AI 请求处理中，请等待完成。",
    "course_preview_busy": "预览请求过多，请稍后重试。",
    "course_changed_reload_required": "课程来源已变化，请刷新课程范围后重新预览。",
    "course_model_timeout": "模型请求已超时，未自动重试；远端仍可能处理或计费。请重新预览后决定是否再次发送。",
    "course_model_result_rejected": "模型请求失败或返回内容未通过引用校验；未自动重试或修补，费用与用量可能未知。",
}


def _error(exc):
    code = str(exc) if str(exc) in _MESSAGES else "course_evidence_unavailable"
    return HTTPException(409, detail={"code": code, "message": _MESSAGES.get(code, "课程或原文暂不可用，请检查来源后重新预览。")})


@course_synthesis_router.post("/{course_id}/synthesis/preview")
def api_course_synthesis_preview(course_id: str, request: CourseSynthesisPreview):
    try:
        return course_synthesis.preview(course_id, request.model_dump())
    except (ValueError, OSError, TypeError, sqlite3.Error) as exc:
        raise _error(exc) from None


@course_synthesis_router.post("/{course_id}/synthesis/answer")
async def api_course_synthesis_answer(course_id: str, request: CourseSynthesisAnswer):
    try:
        return await course_synthesis.answer(course_id, **request.model_dump())
    except (ValueError, OSError, TypeError, sqlite3.Error) as exc:
        raise _error(exc) from None
