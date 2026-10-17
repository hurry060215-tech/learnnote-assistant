"""Capture-only validation and errors never reflect raw page input."""
from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from ..community_capture import CommunityPreviewRequest, CommunitySaveRequest, preview_visible_community, save_visible_community


class _CommunityCaptureRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validated_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Default validation errors reflect raw rejected inputs (and
                # cannot serialize NaN). Keep this capture boundary literal.
                raise HTTPException(status_code=422, detail={
                    "code": "community_capture_payload_invalid",
                    "message": "社区观点请求格式或大小无效，请重新预览。",
                }) from None

        return validated_handler


community_capture_router = APIRouter(route_class=_CommunityCaptureRoute)


def _community_capture_error(exc: ValueError) -> HTTPException:
    # Never echo untrusted page text, URL parameters or exception details.
    errors = {
        "task_not_found": (404, "任务不存在，请重新选择任务。"),
        "community_context_disabled": (409, "社区观点层默认关闭，请先显式启用。"),
        "community_source_unsupported": (422, "仅支持已授权的 HTTPS B站视频页面及有效分P。"),
        "community_source_mismatch": (409, "当前页面与任务视频或分P不一致，请重新预览。"),
        "community_preview_unavailable": (409, "预览已过期、已使用或不可用，请重新预览。"),
        "community_preview_changed": (409, "任务来源或预览已改变，请重新预览。"),
        "community_selection_invalid": (422, "请选择本次预览中的有效条目。"),
        "community_preview_capacity_exceeded": (429, "暂存预览已达到上限，请稍后重试。"),
        "community_storage_quota_exceeded": (422, "本地社区观点已达到上限，请先清理旧内容。"),
        "community_items_invalid": (422, "没有可保存的社区观点。"),
    }
    code = str(exc) if str(exc) in errors else "community_capture_unavailable"
    status, message = errors.get(code, (422, "本地社区观点预览不可用，请重新预览。"))
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@community_capture_router.post("/{task_id}/community-context/preview")
def api_preview_task_community_context(task_id: str, request: CommunityPreviewRequest) -> dict:
    try:
        return preview_visible_community(task_id, request)
    except ValueError as exc:
        raise _community_capture_error(exc) from exc


@community_capture_router.post("/{task_id}/community-context/save")
def api_save_task_community_context(task_id: str, request: CommunitySaveRequest) -> dict:
    try:
        return save_visible_community(task_id, request)
    except ValueError as exc:
        raise _community_capture_error(exc) from exc
