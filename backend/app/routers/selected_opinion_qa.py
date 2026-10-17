"""One local preview route; execution remains on the existing task-QA routes."""
from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .. import selected_opinion_qa
from ..models import SelectedOpinionPreviewRequest


class _PreviewRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": {
                    "code": "opinion_request_invalid", "message": "请填写问题、有效所选条目和已保存的模型连接。"}})
        return safe


router = APIRouter(prefix="/api/tasks", route_class=_PreviewRoute)
_MESSAGES = {
    "opinion_stream_required": "所选观点问答仅支持当前窗口的可取消回答，请使用流式问答入口。",
    "community_context_disabled": "社区观点层已关闭，请重新启用并预览。",
    "opinion_model_changed": "模型连接或密钥已变化或不可用，请重新预览。",
    "opinion_selection_changed": "所选观点已删除、来源不符或内容已变，请重新预览。",
    "opinion_selection_invalid": "所选观点超过现有内容上限或无效，请减少选择。",
    "opinion_preview_expired": "预览已过期、已使用或已被替代，请重新预览并确认。",
    "opinion_preview_changed": "问题、所选条目或模型与预览不同，请重新预览。",
    "opinion_consent_required": "请先预览，并明确同意本次问题、原文摘录和所选观点发送到所示模型。",
    "opinion_source_changed": "原文或任务来源已变化，本次结果不可用，请重新预览。",
    "opinion_preview_busy": "已有请求处理中或暂存预览已满，请稍后重新预览。",
    "opinion_model_failed": "本次回答未完成，请重新预览；已发送内容仍可能产生费用。",
    "opinion_source_unavailable": "当前没有可用的已完成原始字幕，请先完成提取并核对来源。",
}


def error(exc):
    code = str(exc) if str(exc) in _MESSAGES else "opinion_source_unavailable"
    return HTTPException(409, {"code": code, "message": _MESSAGES[code]})


@router.post("/{task_id}/qa/preview")
def preview(task_id: str, request: SelectedOpinionPreviewRequest):
    try:
        return selected_opinion_qa.preview(task_id, request.model_dump())
    except (ValueError, OSError, TypeError) as exc:
        raise error(exc) from None
