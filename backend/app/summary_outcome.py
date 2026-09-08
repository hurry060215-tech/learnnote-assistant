"""User-readable summary outcomes, without disclosing provider account details."""

from __future__ import annotations

import re


def has_generated_summary(source: str) -> bool:
    return str(source or "") in {"text-llm", "vision-llm", "page-text-llm"}


def safe_summary_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)\b(?:sk|ak|org|proj)-[A-Za-z0-9_-]{6,}", "<redacted>", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<redacted>", text)
    return text


def summary_failure_message(warning: str, events: list[dict] | None = None) -> str:
    detail = (str(warning or "") + " " + " ".join(str(item.get("message") or item.get("code") or "") for item in (events or []))).lower()
    if any(item.get("stage") == "grounding_validation" and item.get("code") == "rejected" for item in (events or [])):
        reason = "总结中的部分内容未通过来源检查"
    elif any(word in detail for word in ("insufficient balance", "insufficient_quota", "credit balance", "余额不足", "欠费")):
        reason = "模型服务额度不足"
    elif any(word in detail for word in ("missing_api_key", "未配置", "no api key")):
        reason = "尚未配置可用模型"
    elif any(word in detail for word in ("401", "invalid_api_key", "unauthorized", "authentication")):
        reason = "模型服务的凭据未通过验证"
    elif any(word in detail for word in ("429", "rate limit", "ratelimit")):
        reason = "模型服务暂时限制了请求频率"
    elif any(word in detail for word in ("timeout", "timed out")):
        reason = "模型服务响应超时"
    else:
        reason = "模型服务未能完成总结"
    return f"{reason}；字幕已保留，尚未得到可用的 AI 总结。调整模型后可直接重新总结，无需再次下载或转写。"


def safe_summary_events(events: list[dict] | None) -> list[dict]:
    return [{key: safe_summary_text(value) if isinstance(value, str) else value for key, value in event.items()} for event in (events or []) if isinstance(event, dict)]
