"""Read-only chapter review with an explicit preview before each model request."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .. import section_reviews
from ..section_review_sources import chapter_list

section_reviews_router = APIRouter()


class SectionReviewPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    section_id: str = Field(min_length=1, max_length=300)
    offset: int = Field(default=0, ge=0, le=100000)
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=300)


class SectionReviewConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    preview_id: str = Field(pattern=r"^[A-Za-z0-9_-]{32,64}$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    share_source: StrictBool


_MESSAGES = {
    "review_source_changed": "笔记、来源或处理状态已变化，请重新打开当前章节预览。",
    "review_model_changed": "所选模型连接已变化或不可用，请重新预览。",
    "review_claims_unavailable": "这一页没有可核对的正文结论，请换一个章节。",
    "review_claims_oversized": "这一章的正文过长，请选择较短章节；未调用模型。",
    "review_ocr_unreviewed": "画面字幕 OCR 尚未人工核对，本次文字核对不支持该来源。",
    "review_consent_required": "请先预览并明确同意本次发送。",
    "review_preview_expired": "本次预览已过期或已使用，请重新预览。",
    "review_busy": "已有核对请求处理中，请稍后重试。",
    "review_model_timeout": "请求超时，未自动重试；远端仍可能处理或计费。",
    "review_model_rejected": "请求失败或回答未通过格式/引句检查，未自动重试；费用可能未知。",
}


def error(exc):
    code = str(exc) if str(exc) in _MESSAGES else "review_source_unavailable"
    return HTTPException(409, {"code": code, "message": _MESSAGES.get(code, "当前生成稿或原文不可用，请刷新后重试。")})


@section_reviews_router.get("/{task_id}/section-review")
def sections(task_id: str, revision: str = Query(pattern=r"^[a-f0-9]{64}$")):
    try:
        return chapter_list(task_id, revision)
    except (ValueError, OSError, TypeError) as exc:
        raise error(exc) from None


@section_reviews_router.post("/{task_id}/section-review/preview")
def preview(task_id: str, request: SectionReviewPreview):
    try:
        return section_reviews.preview(task_id, request.model_dump())
    except (ValueError, OSError, TypeError) as exc:
        raise error(exc) from None


@section_reviews_router.post("/{task_id}/section-review/confirm")
async def confirm(task_id: str, request: SectionReviewConfirm):
    try:
        return await section_reviews.review(task_id, **request.model_dump())
    except (ValueError, OSError, TypeError) as exc:
        raise error(exc) from None
