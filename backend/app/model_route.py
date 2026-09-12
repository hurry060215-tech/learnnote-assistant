"""Explainable local-first model routing and offline readiness."""
from __future__ import annotations

from typing import Any

from .models import TaskOptions


ROUTE_SCHEMA_VERSION = 1


def plan_route(
    options: TaskOptions | None = None,
    *,
    local_asr_available: bool = False,
    model_configured: bool = False,
    vision_configured: bool = False,
) -> dict[str, Any]:
    selected = options or TaskOptions()
    text_routes = [
        {
            "id": "platform_or_embedded_subtitles",
            "label": "平台/内嵌字幕",
            "kind": "local",
            "ready": True,
            "network": "source_only",
            "detail": "优先复用可验证的字幕，不下载音频、不调用模型。",
        },
        {
            "id": "local_asr",
            "label": "本地语音识别",
            "kind": "local",
            "ready": bool(local_asr_available),
            "network": "offline_after_model_ready",
            "detail": "没有字幕时使用本机 Whisper；模型权重需提前准备。",
        },
        {
            "id": "remote_text_model",
            "label": "配置的文字模型",
            "kind": "remote",
            "ready": bool(model_configured),
            "network": "required",
            "detail": "仅发送当前任务所需的文字材料和明确要求。",
        },
    ]
    visual_route = {
        "id": "remote_vision_model",
        "label": "配置的视觉模型",
        "kind": "remote",
        "ready": bool(vision_configured),
        "network": "required",
        "detail": "只在图文模式下发送选定画面和对应字幕窗口。",
    }
    if selected.content_mode == "subtitles":
        requested = ["platform_or_embedded_subtitles"]
    elif selected.content_mode == "visual":
        requested = ["platform_or_embedded_subtitles", "local_asr", "remote_vision_model"]
    else:
        requested = ["platform_or_embedded_subtitles", "local_asr", "remote_text_model"]
    route_by_id = {item["id"]: item for item in text_routes + [visual_route]}
    requested_routes = [route_by_id[item] for item in requested]
    blocking = [
        item["detail"]
        for item in requested_routes
        if not item["ready"] and item["id"] in {"local_asr", "remote_text_model", "remote_vision_model"}
    ]
    return {
        "schema_version": ROUTE_SCHEMA_VERSION,
        "content_mode": selected.content_mode,
        "selected_route": selected.content_mode,
        "routes": requested_routes,
        "offline_ready": selected.content_mode != "visual" and all(item["ready"] for item in requested_routes if item["kind"] == "local"),
        "blocking_reasons": blocking,
        "policy": "local-first; remote calls require explicit configured provider; no account is required",
    }


__all__ = ["ROUTE_SCHEMA_VERSION", "plan_route"]
