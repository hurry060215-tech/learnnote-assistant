"""Explainable local-first model routing and offline readiness."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .models import TaskOptions
from .model_capabilities import vision_batch_plan


ROUTE_SCHEMA_VERSION = 3
REMOTE_ASR_NAMES = {"openai", "openai-compatible", "openai-compatible-asr", "groq", "groq-asr"}


def plan_route(
    options: TaskOptions | None = None,
    *,
    local_asr_available: bool = False,
    model_configured: bool = False,
    asr_configured: bool | None = None,
    vision_configured: bool = False,
    source_available_offline: bool = False,
    capability_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = options or TaskOptions()
    from .config import LLM_BASE_URL, LLM_MODEL
    batch_plan = vision_batch_plan(selected.llm_base_url or LLM_BASE_URL,
                                  selected.llm_model or LLM_MODEL, selected.vision_batch_size)
    catalog = dict(capability_catalog or {})
    image_limit = dict(batch_plan["image_limit"])
    image_limit["detail"] += f" 设置每批 {batch_plan['requested_size']} 张，实际每批最多 {batch_plan['effective_size']} 张；选中的窗口按原顺序拆分。"
    catalog["image_limit"] = image_limit
    asr_configured = model_configured if asr_configured is None else asr_configured
    local_model = urlparse(selected.llm_base_url or "").hostname in {"localhost", "127.0.0.1", "::1"}
    remote_asr = str(selected.transcriber or "").strip().lower() in REMOTE_ASR_NAMES
    text_routes = [
        {
            "id": "platform_or_embedded_subtitles",
            "label": "平台/内嵌字幕",
            "kind": "local",
            "ready": True,
            "network": "none" if source_available_offline else "source_only",
            "data_types": [],
            "detail": "优先复用可验证的字幕，不下载音频、不调用模型。",
        },
        {
            "id": "remote_asr" if remote_asr else "local_asr",
            "label": "配置的音频转写服务" if remote_asr else "本地语音识别",
            "kind": "remote" if remote_asr and not local_model else "local",
            "ready": bool(asr_configured) if remote_asr else bool(local_asr_available),
            "network": ("none" if local_model else "required") if remote_asr else "offline_after_model_ready",
            "data_types": ["audio"] if remote_asr else [],
            "conditional": "only_when_verified_subtitles_are_unavailable",
            "detail": "没有字幕时向所选转写服务发送音频；由该服务处理。" if remote_asr else "没有字幕时使用本机 Whisper；模型权重需提前准备。",
        },
        {
            "id": "remote_text_model",
            "label": "配置的文字模型",
            "kind": "local" if local_model else "remote",
            "ready": bool(model_configured),
            "network": "none" if local_model else "required",
            "data_types": ["source_title", "source_url", "transcript", "instructions"],
            "optional_data_types": ["approved_page_context", "approved_page_text_fallback"],
            "detail": "发送来源标题、页面链接（若有）、字幕和整理要求；本任务另行同意后才发送最多 4,000 字符页面上下文。失败后的页面全文兜底需单独审阅同意（页面最多 50,000 字符、字幕线索最多 10,000 字符）。",
        },
    ]
    visual_route = {
        "id": "remote_vision_model",
        "label": "配置的视觉模型",
        "kind": "local" if local_model else "remote",
        "ready": bool(vision_configured),
        "network": "none" if local_model else "required",
        "data_types": ["source_title", "source_url", "selected_frames", "transcript", "instructions"],
        "optional_data_types": ["approved_page_context"],
        "detail": "图文模式发送选定画面、对应字幕、来源标题、页面链接（若有）和整理要求；本任务另行同意后才发送最多 4,000 字符页面上下文。",
    }
    if selected.content_mode == "subtitles":
        requested = ["platform_or_embedded_subtitles"]
    elif selected.visual_understanding:
        requested = ["platform_or_embedded_subtitles", "remote_asr" if remote_asr else "local_asr", "remote_text_model", "remote_vision_model"]
    else:
        requested = ["platform_or_embedded_subtitles", "remote_asr" if remote_asr else "local_asr", "remote_text_model"]
    route_by_id = {item["id"]: item for item in text_routes + [visual_route]}
    requested_routes = [route_by_id[item] for item in requested]
    blocking = [
        item["detail"]
        for item in requested_routes
        if not item["ready"] and item["id"] in {"local_asr", "remote_asr", "remote_text_model", "remote_vision_model"}
    ]
    return {
        "schema_version": ROUTE_SCHEMA_VERSION,
        "content_mode": selected.content_mode,
        "selected_route": selected.content_mode,
        "routes": requested_routes,
        "offline_ready": bool(source_available_offline) and all(item["ready"] and item["network"] != "required" for item in requested_routes),
        "offline_source_confirmed": bool(source_available_offline),
        "readiness_scope": "Configuration and cached files only; no network or model probe was performed. A local gateway may itself forward requests.",
        "capability_catalog": catalog,
        "vision_batch_plan": batch_plan,
        "data_leaving_device": sorted({value for item in requested_routes if item["kind"] == "remote" for value in item.get("data_types", [])}),
        "local_fallback": {
            "content_mode": "subtitles",
            "requires_model_key": False,
            "requires_verified_transcript": True,
            "detail": "无 Key 时可保存已取得的字幕原文；没有字幕时需准备本地 ASR 或重新选择资料。",
        },
        "estimates": {
            "cost": None, "duration_seconds": None, "context_limit": None, "image_limit": None,
            "cost_range": None, "duration_seconds_range": None,
            "status": "unknown_until_source_and_provider_limits_are_known",
            "uncertainty": "unmeasured",
            "detail": "费用与耗时区间：未知。尚无当前输入、设备及服务商的可用测量依据，无法给出可靠区间；不代表免费或立即完成。",
        },
        "blocking_reasons": blocking,
        "policy": "local-first; remote calls require explicit configured provider; no account is required",
    }


__all__ = ["ROUTE_SCHEMA_VERSION", "plan_route"]
