"""User-readable summary outcomes, without disclosing provider account details."""

from __future__ import annotations

import re


def has_generated_summary(source: str) -> bool:
    return str(source or "") in {"text-llm", "vision-llm", "page-text-llm", "offline-fixture"}


def safe_summary_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)\b(?:sk|ak|org|proj)-[A-Za-z0-9_-]{6,}", "<redacted>", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<redacted>", text)
    return text


_INTERNAL_WARNING_PARTS = {
    "笔记未发布：输出检查未通过", "缺少可信视频证据",
    "结果仅基于页面文本和未经媒体校验的浏览器字幕线索。",
    "已降级为本地页面文本模板，不能视为视频字幕或完整视频笔记。",
    "已启用画面理解，但未能从完整视频提取任何画面帧",
    "本任务没有视觉切片，请检查视频是否包含可解码的视频轨道。",
    "转写含待核对字符，已保留原始转写和待核对草稿",
    "请核对原音频并重新转写，尚未发布正式笔记。",
    "未配置 OpenAI-compatible API Key，已使用本地画面索引模板生成笔记。",
    "视觉/LLM 总结调用失败或不可用，已降级为本地画面索引模板。",
    "总结中的部分内容未通过来源检查", "模型服务额度不足", "尚未配置可用模型",
    "模型服务的凭据未通过验证", "模型服务暂时限制了请求频率", "模型服务响应超时", "模型服务未能完成总结",
    "字幕已保留，尚未得到可用的 AI 总结。调整模型后可直接重新总结，无需再次下载或转写。",
    "诊断详情已省略",
}


def safe_summary_warning(value: str) -> str:
    """Keep internal warning templates; arbitrary provider prose stays local."""
    result = []
    for part in str(value or "").split("；"):
        part = part.strip()
        if not part:
            continue
        if part in _INTERNAL_WARNING_PARTS or re.fullmatch(r"[0-9]{1,6} 条内容待回源核对，已在正文标记", part):
            safe = part
        elif match := re.fullmatch(r"视频直取失败（([a-z][a-z0-9_]{0,63})）：(.*)", part, re.DOTALL):
            # This internal wrapper used to append arbitrary download errors.
            reason = "signed URL expired" if "signed URL expired" in match[2] else "详情已省略"
            safe = f"视频直取失败（{match[1]}）：{reason}"
        else:
            reason = summary_error_reason(part)
            safe = "诊断详情已省略" if reason == "provider_error" else "模型调用诊断：" + reason
        if safe not in result:
            result.append(safe)
    return "；".join(result)


def summary_failure_message(warning: str, events: list[dict] | None = None) -> str:
    detail = (str(warning or "") + " " + " ".join(str(item.get("message") or item.get("code") or "") for item in (events or []))).lower()
    if "未通过来源检查" in detail or any(item.get("stage") == "grounding_validation" and item.get("code") == "rejected" for item in (events or [])):
        reason = "总结中的部分内容未通过来源检查"
    elif any(word in detail for word in ("insufficient balance", "insufficient_quota", "credit balance", "余额不足", "欠费", "模型服务额度不足")):
        reason = "模型服务额度不足"
    elif any(word in detail for word in ("missing_api_key", "未配置", "no api key", "尚未配置可用模型")):
        reason = "尚未配置可用模型"
    elif any(word in detail for word in ("401", "invalid_api_key", "unauthorized", "authentication", "凭据未通过验证")):
        reason = "模型服务的凭据未通过验证"
    elif any(word in detail for word in ("429", "rate limit", "ratelimit", "限制了请求频率")):
        reason = "模型服务暂时限制了请求频率"
    elif any(word in detail for word in ("timeout", "timed out", "响应超时")):
        reason = "模型服务响应超时"
    else:
        reason = "模型服务未能完成总结"
    return f"{reason}；字幕已保留，尚未得到可用的 AI 总结。调整模型后可直接重新总结，无需再次下载或转写。"


# Provider exceptions can contain echoed prompts, response bodies and private
# endpoints. Retain a category, never a cleaned-up excerpt of that text.
def summary_error_reason(value: object) -> str:
    text = str(value or "").lower()
    if not text:
        return ""
    for status in (400, 401, 403, 404, 408, 413, 422, 429, 500, 502, 503, 504):
        if re.search(rf"\b{status}\b", text):
            return f"HTTP {status}"
    if any(word in text for word in ("rate limit", "ratelimit", "限制了请求频率")):
        return "HTTP 429"
    if any(word in text for word in ("insufficient balance", "insufficient_quota", "credit balance")):
        return "insufficient_quota"
    if any(word in text for word in ("timeout", "timed out", "响应超时")):
        return "timeout"
    if any(word in text for word in ("image", "vision", "multimodal")):
        return "vision_input_rejected"
    if any(word in text for word in ("unauthorized", "authentication", "invalid_api_key")):
        return "authentication_failed"
    return "provider_error"


_EVENT_STAGES = {"configuration", "client_import", "client_init", "grounding_repair", "grounding_validation",
    "vision_batch", "vision_cache", "vision_merge", "text_summary", "summary", "provider_compatibility"}
_EVENT_CODES = {"ok", "success", "cache_hit", "api_error", "mojibake_blocked", "missing_api_key",
    "missing_openai_sdk", "client_init_failed", "repair_required", "repaired", "partial_recovery", "rejected", "llm_unavailable", "offline_fixture", "unclassified"}


def safe_summary_events(events: list[dict] | None) -> list[dict]:
    result = []
    for event in (events or [])[:20]:
        if not isinstance(event, dict):
            continue
        safe = {"stage": event.get("stage") if isinstance(event.get("stage"), str) and event["stage"] in _EVENT_STAGES else "unknown",
                "code": event.get("code") if isinstance(event.get("code"), str) and event["code"] in _EVENT_CODES else "unclassified"}
        if event.get("stage") == "provider_compatibility":
            # Compatibility provenance is an allowlisted category only. Never
            # preserve a provider body, raw message, endpoint or arbitrary field.
            if type(event.get("original_status")) is int and event["original_status"] in {400, 422}:
                safe["original_status"] = event["original_status"]
            for key, allowed in {
                "original_code": {"unsupported_parameter"}, "parameter": {"temperature"},
                "retry_outcome": {"success", "failed", "cancelled"},
                "request_stage": {"grounding_repair", "vision_batch", "vision_merge", "text_summary"},
            }.items():
                if isinstance(event.get(key), str) and event[key] in allowed:
                    safe[key] = event[key]
            result.append(safe)
            continue
        if event.get("message"):
            safe["message"] = summary_error_reason(event["message"])
        for key in ("batch", "duration_ms", "omitted_passages", "issue_count"):
            if isinstance(event.get(key), (int, float)):
                safe[key] = event[key]
        if isinstance(event.get("cache"), str) and event["cache"] in {"hit", "miss"}:
            safe["cache"] = event["cache"]
        if isinstance(event.get("issues"), list):
            safe["issue_count"] = len(event["issues"])
        result.append(safe)
    return result


# Summary diagnostics are a count/status projection, not a copy of the source,
# provider response or task paths. Unknown text fields are omitted by default.
_DIAGNOSTIC_IDENTIFIERS = {
    "task_id", "mode", "summary_source", "llm_model", "llm_provider", "llm_failure_code", "llm_failure_stage",
    "note_style", "note_template", "summary_depth", "frame_extraction_status", "vision_call_status",
    "source_kind", "source_quality", "evidence_quality", "video_evidence", "note_publication",
    "status", "issue_kind", "normalization_version", "severity", "code", "probe_backend", "container",
    "video_codec", "audio_codec", "subtitle_codec", "transcript_source", "stage", "cache",
    "attempt_id", "current_attempt_id", "phase", "name", "kind", "algorithm", "sha256",
}
_WINDOW_LISTS = {"window_ids", "image_window_ids", "vision_window_ids", "vision_image_window_ids",
    "missing_vision_image_window_ids", "omitted_vision_window_ids"}


def safe_summary_diagnostics(value: object) -> dict:
    """Project newly written diagnostics; never mutate stored source artifacts."""
    def clean(item, key=""):
        if key in {"llm_events"}:
            return safe_summary_events(item if isinstance(item, list) else [])
        if key in {"llm_last_event", "llm_last_failure"}:
            return safe_summary_events([item])[0] if isinstance(item, dict) and item else {}
        if key == "llm_base_host":
            # Exact public service hosts only; custom/private endpoints are not diagnostics.
            return item if isinstance(item, str) and item in {"api.openai.com", "api.groq.com", "openrouter.ai",
                "generativelanguage.googleapis.com", "api.deepseek.com", "api.moonshot.cn",
                "dashscope.aliyuncs.com", "api.siliconflow.cn", "127.0.0.1", "localhost", "custom-endpoint"} else "custom-endpoint"
        if key == "llm_failure_stage":
            return item if isinstance(item, str) and item in _EVENT_STAGES else ""
        if key == "llm_failure_code":
            return item if isinstance(item, str) and item in _EVENT_CODES | {"llm_unavailable", "partial_vision_failure", "provider_error", ""} else "provider_error"
        if key == "llm_failure_reason":
            return summary_error_reason(item)
        if key == "summary_warning":
            return summary_error_reason(item)
        if key == "frame_extraction_warning":
            return "frame_extraction_failed" if item else ""
        if key in _WINDOW_LISTS:
            return [v for v in item if isinstance(v, str) and re.fullmatch(r"W[0-9]{3,8}", v)] if isinstance(item, list) else []
        if isinstance(item, dict):
            return {k: result for k, v in item.items()
                    if isinstance(k, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", k)
                    and not re.search(r"cookie|token|secret|password|credential|authorization|api_key", k)
                    and (result := clean(v, k)) is not None}
        if isinstance(item, list):
            return [result for v in item if (result := clean(v, key)) is not None]
        if isinstance(item, (bool, int, float)) or item is None:
            return item
        if (key in _DIAGNOSTIC_IDENTIFIERS and isinstance(item, str)
                and re.fullmatch(r"[A-Za-z0-9_.:/+-]{0,128}", item)
                and "://" not in item and safe_summary_text(item) == item):
            return item
        return None
    result = clean(value)
    return result if isinstance(result, dict) else {}
